"""Verification-code strategies for every supported mailbox source."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from app.core.config import settings
from app.services.resource_inventory import parse_mailbox

logger = logging.getLogger(__name__)
_MAX_RESPONSE_BYTES = 256 * 1024


@dataclass(frozen=True)
class MailboxImportEntry:
    email: str
    code_url: str | None = None


def _parse_generic_api_url(raw: str) -> str:
    value = raw.strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("取码地址格式无效") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("取码地址必须是无账号密码、无片段的 HTTPS URL")
    host = parsed.hostname.casefold().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("取码地址不能使用本地主机")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("取码地址不能使用内网或保留地址")
    return value


def parse_mailbox_import_line(raw: str, provider_type: str) -> MailboxImportEntry:
    line = raw.strip()
    if provider_type == "outlook":
        return MailboxImportEntry(parse_mailbox(line))
    if provider_type != "generic_api":
        raise ValueError("不支持的邮箱类型")
    email_raw, separator, code_url_raw = line.partition("----")
    if not separator or not code_url_raw.strip():
        raise ValueError("通用 API 格式必须为：邮箱----取码地址")
    email = parse_mailbox(email_raw)
    return MailboxImportEntry(email=email, code_url=_parse_generic_api_url(code_url_raw))


def _find_key(value: Any, wanted: str) -> Any:
    if isinstance(value, dict):
        if wanted in value:
            return value[wanted]
        for child in value.values():
            found = _find_key(child, wanted)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_key(child, wanted)
            if found is not None:
                return found
    return None


def extract_verification_code(payload: Any, expected_email: str) -> str | None:
    response_email = _find_key(payload, "email")
    if isinstance(response_email, str) and response_email.casefold() != expected_email.casefold():
        return None
    code = _find_key(payload, "verification_code")
    if isinstance(code, (str, int)):
        result = str(code).strip()
        if 1 <= len(result) <= 64 and result.isalnum():
            return result
    return None


async def _validate_public_destination(url: str) -> None:
    parsed = urlsplit(url)
    host = parsed.hostname
    if not host:
        raise ValueError("取码地址缺少主机名")
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(
            host,
            parsed.port or 443,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        raise ValueError("取码地址域名解析失败") from None
    addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
    # Clash/Surge/TUN 的 fake-ip DNS 会把公网域名映射到 RFC 2544 基准网段。
    # URL 解析阶段已经禁止直接填写非公网 IP，因此这里只对“域名解析出的
    # fake-ip”放行，仍然拒绝真实内网、回环和保留地址。
    fake_ip_network = ipaddress.ip_network("198.18.0.0/15")
    invalid = [
        address
        for address in addresses
        if not address.is_global and address not in fake_ip_network
    ]
    if not addresses or invalid:
        raise ValueError("取码地址解析到了内网或保留地址")


class VerificationCodeStrategy(ABC):
    source: str

    @abstractmethod
    async def poll(
        self,
        email: str,
        *,
        code_url: str | None = None,
        timeout: int | None = None,
        exclude_code: str | None = None,
    ) -> str | None:
        raise NotImplementedError


class CloudflareVerificationStrategy(VerificationCodeStrategy):
    source = "cloudflare"

    async def poll(self, email: str, *, code_url: str | None = None, timeout: int | None = None, exclude_code: str | None = None) -> str | None:
        from app.services.cloudflare_kv import cf_kv_client
        return await cf_kv_client.poll_verification_code(email)


class OutlookVerificationStrategy(VerificationCodeStrategy):
    source = "outlook"

    async def poll(self, email: str, *, code_url: str | None = None, timeout: int | None = None, exclude_code: str | None = None) -> str | None:
        from app.services.outlook_client import outlook_client
        return await outlook_client.poll_verification_code(email, timeout=timeout)


class GenericApiVerificationStrategy(VerificationCodeStrategy):
    source = "generic_api"

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        destination_validator: Callable[[str], Awaitable[None]] = _validate_public_destination,
    ) -> None:
        self._transport = transport
        self._destination_validator = destination_validator

    async def poll(self, email: str, *, code_url: str | None = None, timeout: int | None = None, exclude_code: str | None = None) -> str | None:
        if not code_url:
            return None
        normalized_url = _parse_generic_api_url(code_url)
        timeout_seconds = timeout or settings.outlook_poll_timeout
        interval = max(1, settings.outlook_poll_interval)
        deadline = asyncio.get_running_loop().time() + timeout_seconds

        await self._destination_validator(normalized_url)
        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(10.0),
            headers={"Accept": "application/json"},
            transport=self._transport,
        ) as client:
            while asyncio.get_running_loop().time() < deadline:
                try:
                    async with client.stream("GET", normalized_url) as response:
                        if response.status_code == 200:
                            content = bytearray()
                            async for chunk in response.aiter_bytes():
                                content.extend(chunk)
                                if len(content) > _MAX_RESPONSE_BYTES:
                                    raise ValueError("取码响应超过大小限制")
                            try:
                                payload = json.loads(content)
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                payload = None
                            code = extract_verification_code(payload, email)
                            if code and code != exclude_code:
                                return code
                        elif response.status_code in {301, 302, 303, 307, 308}:
                            logger.warning("[GenericMail] 取码接口返回重定向，已拒绝")
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("[GenericMail] 取码请求失败: %s", type(exc).__name__)
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(interval, remaining))
        return None


_STRATEGIES: dict[str, VerificationCodeStrategy] = {
    strategy.source: strategy
    for strategy in (
        CloudflareVerificationStrategy(),
        OutlookVerificationStrategy(),
        GenericApiVerificationStrategy(),
    )
}


def get_verification_strategy(source: str) -> VerificationCodeStrategy:
    try:
        return _STRATEGIES[source]
    except KeyError:
        raise ValueError(f"不支持的邮箱来源: {source}") from None


async def poll_verification_code(
    source: str,
    email: str,
    *,
    code_url: str | None = None,
    timeout: int | None = None,
    exclude_code: str | None = None,
) -> str | None:
    return await get_verification_strategy(source).poll(
        email,
        code_url=code_url,
        timeout=timeout,
        exclude_code=exclude_code,
    )
