"""Dreamina 邮箱纯 HTTP 协议注册。

TLS/HTTP2 指纹由 curl_cffi impersonate 提供；注册链路不启动浏览器，不加载
Patchright，也不执行 page.goto/page.evaluate。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Awaitable, Callable, Protocol
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import CurlError, ProxyError, Timeout
from sqlalchemy import select

from app.core.config import settings
from app.models.outlook_mailbox import OutlookMailbox
from app.services.mailbox_verification import poll_verification_code
from app.services.random_generator import RandomGenerator

logger = logging.getLogger(__name__)


class ProtocolRegistrationError(RuntimeError):
    """协议注册某一步返回业务错误。"""


@dataclass(frozen=True)
class ProtocolResponse:
    status: int
    url: str
    data: dict[str, Any]


class RegistrationTransport(Protocol):
    async def post_form(
        self,
        base_url: str,
        path: str,
        form: dict[str, Any],
        *,
        extra_query: dict[str, Any] | None = None,
    ) -> ProtocolResponse: ...

    async def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> ProtocolResponse: ...

    async def cookies(self) -> list[dict[str, Any]]: ...


def xor5_hex(value: str) -> str:
    """还原 Passport Web SDK 的 fixed_mix_mode 字段编码。"""
    return "".join(format(byte ^ 5, "x") for byte in value.encode("utf-8"))


def _business_error(payload: dict[str, Any]) -> str | None:
    if payload.get("message") == "error":
        data = payload.get("data") or {}
        return str(data.get("description") or data.get("error_code") or "接口返回错误")
    if payload.get("ret") not in (None, 0, "0"):
        return str(payload.get("errmsg") or payload.get("ret"))
    return None


def _require_success(response: ProtocolResponse, step: str) -> dict[str, Any]:
    if response.status < 200 or response.status >= 300:
        raise ProtocolRegistrationError(f"{step}失败：HTTP {response.status}")
    error = _business_error(response.data)
    if error:
        raise ProtocolRegistrationError(f"{step}失败：{error}")
    return response.data.get("data") or response.data


_REGION_PROFILE = {
    # HAR 注册样本：日本出口 + en 协议语言 + zh-CN 浏览器语言 + 上海时区。
    "JP": ("zh-CN", "en", "Asia/Shanghai"),
    "KR": ("ko-KR", "ko", "Asia/Seoul"),
    "SG": ("en-SG", "en", "Asia/Singapore"),
    "HK": ("zh-HK", "zh", "Asia/Hong_Kong"),
    "TW": ("zh-TW", "zh", "Asia/Taipei"),
    "US": ("en-US", "en", "America/New_York"),
    "GB": ("en-GB", "en", "Europe/London"),
    "DE": ("de-DE", "de", "Europe/Berlin"),
    "FR": ("fr-FR", "fr", "Europe/Paris"),
}


PROTOCOL_BROWSER_PROFILES = [
    {
        "name": "Chrome-152-macOS",
        "impersonate": "chrome152_macos",
        "version": "152.0.0.0",
        "platform": "MacIntel",
        "ua": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/152.0.0.0 Safari/537.36"
        ),
    },
    {
        "name": "Chrome-150-Windows",
        "impersonate": "chrome150",
        "version": "150.0.0.0",
        "platform": "Win32",
        "ua": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/150.0.0.0 Safari/537.36"
        ),
    },
]


class BrowserProfileRotator:
    """Randomized round-robin: every profile is used once per shuffled cycle."""

    def __init__(self, profiles: list[dict[str, str]], rng: random.Random | None = None):
        if not profiles:
            raise ValueError("浏览器画像池不能为空")
        self._profiles = tuple(profiles)
        self._rng = rng or random.SystemRandom()
        self._queue: list[dict[str, str]] = []
        self._last_profile: dict[str, str] | None = None
        self._lock = threading.Lock()

    def next(self) -> dict[str, str]:
        with self._lock:
            if not self._queue:
                self._queue = list(self._profiles)
                self._rng.shuffle(self._queue)
                if (
                    len(self._queue) > 1
                    and self._last_profile is not None
                    and self._queue[-1] is self._last_profile
                ):
                    self._queue[0], self._queue[-1] = self._queue[-1], self._queue[0]
            self._last_profile = self._queue.pop()
            return self._last_profile


PROTOCOL_BROWSER_PROFILE_ROTATOR = BrowserProfileRotator(PROTOCOL_BROWSER_PROFILES)


class PureHttpTransport:
    """curl_cffi 驱动的纯 HTTP 会话与 TLS/HTTP2 指纹容器。"""

    def __init__(self, *, proxy_url: str, region: str):
        locale, language, timezone = _REGION_PROFILE.get(
            region.upper(), _REGION_PROFILE["US"]
        )
        self.region = region.upper()
        self.locale = locale
        self.language = language
        self.timezone = timezone
        self.profile = PROTOCOL_BROWSER_PROFILE_ROTATOR.next()
        self.webid = str(
            secrets.randbelow(9_000_000_000_000_000_000)
            + 1_000_000_000_000_000_000
        )
        self.user_agent = self.profile["ua"]
        self.verify_fp = "verify_" + secrets.token_urlsafe(27).replace("-", "A").replace("_", "B")
        self.fingerprint = {
            "engine": "curl_cffi",
            "profile_name": self.profile["name"],
            "impersonate": self.profile["impersonate"],
            "chrome_version": self.profile["version"],
            "platform": self.profile["platform"],
            "user_agent": self.user_agent,
            "locale": locale,
            "language": language,
            "timezone_id": timezone,
            "viewport": {"width": 1920, "height": 1080},
            "verify_fp": self.verify_fp,
        }
        self.bound_exit_ip: str | None = None
        self.session = AsyncSession(
            proxy=proxy_url,
            impersonate=self.profile["impersonate"],
            headers={
                "user-agent": self.user_agent,
                "accept-language": f"{locale},{language};q=0.9,en-US;q=0.8,en;q=0.7",
            },
            timeout=60,
            verify=False,
        )
        self.session.cookies.set("_v2_spipe_web_id", self.webid, domain=".capcut.com")
        self.session.cookies.set("_tea_web_id", self.webid, domain=".capcut.com")
        self._common_query: dict[str, str] | None = None

    async def start(self, target_url: str) -> None:
        """只取 HTTP 首页以接收服务端 Cookie；不执行任何页面脚本。"""
        await self._request("GET", target_url)

    async def detect_exit_ip(self) -> str:
        """使用同一 HTTP 会话探测实际出口 IP。"""
        response = await self._request(
            "GET", "https://cp.cloudflare.com/cdn-cgi/trace"
        )
        if response.status_code != 200:
            raise ProtocolRegistrationError(
                f"代理出口 IP 探测失败：HTTP {response.status_code}"
            )
        values = dict(
            line.split("=", 1)
            for line in response.text.splitlines()
            if "=" in line
        )
        exit_ip = values.get("ip", "").strip()
        if not exit_ip:
            raise ProtocolRegistrationError("代理出口 IP 探测失败：响应缺少 ip")
        return exit_ip

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return await self.session.request(method, url, **kwargs)
            except (CurlError, ProxyError, Timeout) as exc:
                last_error = exc
                if attempt >= 2:
                    raise
                await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(str(last_error))

    async def _query(self) -> dict[str, str]:
        if self._common_query is not None:
            return dict(self._common_query)
        query = {
            "aid": "513641",
            "account_sdk_source": "web",
            "sdk_version": "2.1.10-tiktok",
            "language": self.language,
            "verifyFp": self.verify_fp,
            "timezone_name": self.timezone,
            "webid": self.webid,
            "browser_language": self.locale,
            "browser_name": "Mozilla",
            "browser_platform": self.profile["platform"],
            "browser_version": self.user_agent.removeprefix("Mozilla/"),
            "cookie_enabled": "true",
            "screen_height": "1080",
            "screen_width": "1920",
        }
        ms_token = next(
            (
                cookie.value
                for cookie in self.session.cookies.jar
                if cookie.name == "msToken" and "capcut.com" in cookie.domain
            ),
            None,
        )
        if ms_token:
            query["msToken"] = ms_token
        self._common_query = {key: str(value) for key, value in query.items()}
        return dict(self._common_query)

    async def post_form(
        self,
        base_url: str,
        path: str,
        form: dict[str, Any],
        *,
        extra_query: dict[str, Any] | None = None,
    ) -> ProtocolResponse:
        query = await self._query()
        if extra_query:
            query.update({key: str(value) for key, value in extra_query.items()})
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        response = await self._request(
            "POST",
            url,
            params=query,
            data={key: str(value) for key, value in form.items()},
            headers={
                "origin": "https://dreamina.capcut.com",
                "referer": "https://dreamina.capcut.com/",
                "content-type": "application/x-www-form-urlencoded",
            },
            allow_redirects=True,
        )
        try:
            data = response.json()
        except Exception:
            data = {
                "message": "error",
                "data": {"description": response.text or "非 JSON 响应"},
            }
        return ProtocolResponse(response.status_code, str(response.url), data)

    async def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> ProtocolResponse:
        query = await self._query()
        headers = {
            "content-type": "application/json",
            "appid": "513641",
            "did": query.get("webid", "0"),
            "pf": "7",
            "device-time": str(int(time.time())),
            "lan": query.get("language", "en"),
        }
        if extra_headers:
            headers.update(extra_headers)
        response = await self._request(
            "POST", url, json=payload, headers=headers, allow_redirects=True
        )
        try:
            data = response.json()
        except Exception:
            data = {
                "message": "error",
                "data": {"description": response.text or "非 JSON 响应"},
            }
        return ProtocolResponse(response.status_code, str(response.url), data)

    async def cookies(self) -> list[dict[str, Any]]:
        result = []
        for cookie in self.session.cookies.jar:
            result.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path or "/",
                    "expires": float(cookie.expires or -1),
                    "httpOnly": bool(cookie.has_nonstandard_attr("HttpOnly")),
                    "secure": bool(cookie.secure),
                    "sameSite": "Lax",
                }
            )
        return result

    async def close(self) -> None:
        await self.session.close()


class DreaminaProtocolFlow:
    """可注入 transport 的协议状态机，便于用固定响应完整回归。"""

    LOGIN_ROW = "https://login-row.www.capcut.com"

    def __init__(
        self,
        transport: RegistrationTransport,
        *,
        code_provider: Callable[[], Awaitable[str | None]],
        step_reporter: Callable[[str], Awaitable[None]],
        interruption_check: Callable[[], Awaitable[None]],
    ) -> None:
        self.transport = transport
        self.code_provider = code_provider
        self.step_reporter = step_reporter
        self.interruption_check = interruption_check

    async def run(
        self,
        *,
        email: str,
        password: str,
        birthday: date,
        requested_region: str,
    ) -> dict[str, Any]:
        encoded_email = xor5_hex(email)
        encoded_password = xor5_hex(password)
        birthday_text = birthday.isoformat()
        fallback_region = requested_region.strip().upper() or "JP"

        await self.step_reporter("protocol_detect_region")
        await self.interruption_check()
        region_response = await self.transport.post_form(
            self.LOGIN_ROW,
            "/passport/web/region/",
            {
                "type": 2,
                "hashed_id": hashlib.sha256(email.casefold().encode()).hexdigest(),
            },
            extra_query={"mix_mode": 1},
        )
        region_data = _require_success(region_response, "识别注册地区")
        region = str(region_data.get("country_code") or fallback_region).upper()
        login_base = str(region_data.get("domain") or self.LOGIN_ROW).rstrip("/")

        await self.step_reporter("protocol_check_email")
        check_data = _require_success(
            await self.transport.post_form(
                login_base,
                "/passport/web/user/check_email_registered",
                {"mix_mode": 1, "email": encoded_email, "fixed_mix_mode": 1},
            ),
            "检查邮箱",
        )
        if int(check_data.get("is_registered") or 0) != 0:
            raise ProtocolRegistrationError("检查邮箱失败：邮箱已注册")

        await self.step_reporter("protocol_send_code")
        send_data = _require_success(
            await self.transport.post_form(
                login_base,
                "/passport/web/email/send_code/",
                {
                    "mix_mode": 1,
                    "email": encoded_email,
                    "password": encoded_password,
                    "type": 34,
                    "fixed_mix_mode": 1,
                },
            ),
            "发送验证码",
        )
        if not send_data.get("email_ticket"):
            raise ProtocolRegistrationError("发送验证码失败：响应缺少 email_ticket")

        await self.step_reporter("protocol_wait_code")
        await self.interruption_check()
        code = await self.code_provider()
        if not code:
            raise ProtocolRegistrationError("获取验证码失败：等待超时")

        await self.step_reporter("protocol_verify_code")
        verified = _require_success(
            await self.transport.post_form(
                login_base,
                "/passport/web/email/register/code_verify/",
                {
                    "mix_mode": 1,
                    "email": encoded_email,
                    "code": xor5_hex(code),
                    "type": 34,
                    "fixed_mix_mode": 1,
                },
            ),
            "校验验证码",
        )
        email_ticket = verified.get("email_ticket")
        if not email_ticket:
            raise ProtocolRegistrationError("校验验证码失败：响应缺少 email_ticket")

        await self.step_reporter("protocol_age_gate")
        age_data = _require_success(
            await self.transport.post_json(
                "https://dreamina.capcut.com/lv/v1/sc/age_gate/check_age_without_uid",
                {"birthday": birthday_text},
                extra_headers={
                    "store-country-code": region,
                    "store-country-code-src": "uid",
                },
            ),
            "年龄校验",
        )
        if age_data.get("passed") is not True:
            raise ProtocolRegistrationError("年龄校验失败：未通过年龄门槛")

        await self.step_reporter("protocol_register")
        await self.interruption_check()
        detect_exit_ip = getattr(self.transport, "detect_exit_ip", None)
        bound_exit_ip = getattr(self.transport, "bound_exit_ip", None)
        if detect_exit_ip and bound_exit_ip:
            current_exit_ip = await detect_exit_ip()
            if current_exit_ip != bound_exit_ip:
                raise ProtocolRegistrationError(
                    f"注册前代理出口发生变化: {bound_exit_ip} -> {current_exit_ip}"
                )
        account = _require_success(
            await self.transport.post_form(
                login_base,
                "/passport/web/email/register_verify_login/",
                {
                    "mix_mode": 1,
                    "email": encoded_email,
                    "code": xor5_hex(code),
                    "password": encoded_password,
                    "type": 34,
                    "email_ticket": email_ticket,
                    "birthday": birthday_text,
                    "force_user_region": region,
                    "biz_param": "{}",
                    "fixed_mix_mode": 1,
                },
            ),
            "提交注册",
        )
        if int(account.get("new_user") or 0) != 1:
            raise ProtocolRegistrationError("提交注册失败：服务端未返回 new_user=1")

        return {
            "account": account,
            "login_base": login_base,
            "region": str(account.get("store_country") or region).lower(),
            "birthday": birthday_text,
        }


async def execute_protocol_registration(
    engine: Any,
    db: Any,
    task_id: str,
    email: str,
    password: str,
    *,
    proxy_config: Any,
    email_source: str,
    birth_date: dict[str, str] | None = None,
) -> dict[str, Any]:
    """接入现有任务/邮箱池/代理池的协议注册入口。"""
    result: dict[str, Any] = {
        "success": False,
        "session_id": None,
        "all_tokens": {},
        "full_cookie": "",
        "screenshot_path": "",
        "browser_state_path": "",
        "fingerprint_json": "",
        "detected_region": None,
        "error": None,
        "step": "protocol_init",
    }
    transport: PureHttpTransport | None = None
    try:
        await engine.report_step(db, task_id, "protocol_bootstrap")
        requested_region = str(getattr(proxy_config, "region_tag", "") or "JP").upper()
        transport = PureHttpTransport(
            proxy_url=proxy_config.url,
            region=requested_region,
        )
        result["fingerprint_json"] = json.dumps(
            transport.fingerprint, ensure_ascii=False
        )
        expected_ip = str(getattr(proxy_config, "exit_ip", "") or "").strip()
        session_exit_ip = await transport.detect_exit_ip()
        if expected_ip and session_exit_ip != expected_ip:
            raise ProtocolRegistrationError(
                f"固定代理出口发生变化: {expected_ip} -> {session_exit_ip}"
            )
        result["registration_ip"] = session_exit_ip
        transport.bound_exit_ip = session_exit_ip
        target_url = settings.dreamina_url.rstrip("/")
        if "/ai-tool/" not in target_url:
            target_url += "/ai-tool/login"
        await transport.start(target_url)

        code_url = None
        if email_source == "generic_api":
            mailbox = (
                await db.execute(
                    select(OutlookMailbox).where(
                        OutlookMailbox.email == email,
                        OutlookMailbox.provider_type == "generic_api",
                    )
                )
            ).scalar_one_or_none()
            code_url = mailbox.code_url if mailbox else None

        previous_code = None
        if email_source == "generic_api" and code_url:
            previous_code = await poll_verification_code(
                email_source,
                email,
                code_url=code_url,
                timeout=1,
            )

        async def get_code() -> str | None:
            return await poll_verification_code(
                email_source,
                email,
                code_url=code_url,
                timeout=settings.verification_timeout,
                exclude_code=previous_code,
            )

        async def report(step: str) -> None:
            result["step"] = step
            await engine.report_step(db, task_id, step)

        async def check() -> None:
            await engine.check_interrupted(db, task_id)

        if birth_date:
            birthday = date(
                int(birth_date["year"]),
                int(birth_date["month"]),
                int(birth_date["day"]),
            )
        else:
            # 注册年龄固定为 19–45 周岁，确保严格大于 18 岁。
            birthday = RandomGenerator.generate_birth_date(min_age=19, max_age=45)

        flow_result = await DreaminaProtocolFlow(
            transport,
            code_provider=get_code,
            step_reporter=report,
            interruption_check=check,
        ).run(
            email=email,
            password=password,
            birthday=birthday,
            requested_region=requested_region,
        )
        result["detected_region"] = flow_result["region"]
        result["birth_date"] = flow_result["birthday"]


        # 注册成功后的资料初始化。接口失败不回滚已创建的 Passport 账号。
        await report("protocol_initialize_account")
        init_calls = [
            (
                f"https://dreamina.capcut.com/lv/v1/sc/age_gate/set_birthday_by_uid?region={flow_result['region'].upper()}",
                {"birthday": flow_result["birthday"]},
                {
                    "appid": "348188",
                    "uid": str(flow_result["account"].get("user_id_str") or flow_result["account"].get("user_id") or ""),
                },
            ),
            (
                "https://dreamina.capcut.com/lv/v1/sc/compliance_popup/submit_consent",
                {
                    "entity_key": "conditions-policy-privacy-policy",
                    "business_flow": "web_login",
                    "consent_status": "approved",
                    "region": flow_result["region"].upper(),
                },
                {},
            ),
            (
                "https://dreamina.capcut.com/lv/v1/sc/compliance_popup/submit_consent",
                {
                    "entity_key": "conditions-policy-terms-of-service",
                    "business_flow": "web_login",
                    "consent_status": "approved",
                    "region": flow_result["region"].upper(),
                },
                {},
            ),
            (
                "https://dreamina.capcut.com/lv/v1/user/web/user_info",
                {
                    "sem_info": {
                        "is_sem": False,
                        "medium": "Direct",
                        "register_source": "direct",
                        "register_second_source": "enter_url",
                    }
                },
                {},
            ),
        ]
        for url, payload, call_headers in init_calls:
            try:
                response = await transport.post_json(
                    url,
                    payload,
                    extra_headers={
                        "store-country-code": flow_result["region"].upper(),
                        "store-country-code-src": "uid",
                        **call_headers,
                    },
                )
                error = _business_error(response.data)
                if response.status >= 300 or error:
                    logger.warning("协议注册资料初始化未通过 [%s]: %s", url, error or response.status)
            except Exception as exc:
                logger.warning("协议注册资料初始化异常 [%s]: %s", url, exc)

        # Cookie 写入有极短延迟；轮询 sessionid，而不是依赖注册响应正文。
        cookies: list[dict[str, Any]] = []
        session_id = None
        for _ in range(20):
            cookies = await transport.cookies()
            session_cookie = next(
                (item for item in cookies if item.get("name", "").lower() == "sessionid"),
                None,
            )
            if session_cookie:
                session_id = session_cookie.get("value")
                break
            await asyncio.sleep(0.5)
        if not session_id:
            raise ProtocolRegistrationError("注册成功但未获取到 sessionid Cookie")

        safe_email = email.replace("@", "_at_").replace(".", "_")
        state_path = settings.browser_states_dir / f"{safe_email}_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"cookies": cookies, "origins": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        tokens = {
            item["name"]: item["value"]
            for item in cookies
            if any(key in item.get("name", "").lower() for key in ("session", "sid", "uid", "token", "ttwid"))
        }
        result.update(
            {
                "success": True,
                "session_id": session_id,
                "all_tokens": tokens,
                "full_cookie": json.dumps(cookies, ensure_ascii=False),
                "browser_state_path": str(state_path),
                "step": "protocol_complete",
            }
        )
        await engine.report_step(db, task_id, "protocol_complete")
    except Exception as exc:
        result["error"] = str(exc)
        logger.error("协议注册失败 [%s/%s]: %s", task_id, result.get("step"), exc)
        proxy_keywords = (
            "proxy",
            "tunnel",
            "socks",
            "ERR_CONNECTION",
            "ERR_TUNNEL",
            "ERR_EMPTY_RESPONSE",
            "ERR_TIMED_OUT",
        )
        result["proxy_error"] = any(word.lower() in str(exc).lower() for word in proxy_keywords)
    finally:
        if transport:
            try:
                await transport.close()
            except Exception:
                pass
    return result
