"""Strict parser for registration proxy pool imports."""
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit
import ipaddress
import re

_SCHEMES = {"http", "https", "socks5", "socks5h"}
_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")


@dataclass(frozen=True)
class ImportedProxy:
    protocol: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None


def _host(value: str) -> str:
    host = value.strip().casefold()
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        if not _HOST.fullmatch(host) or ".." in host:
            raise ValueError("无效代理主机") from None
        return host


def _decode(value: str | None) -> str | None:
    if value is None:
        return None
    if re.search(r"%(?![0-9A-Fa-f]{2})", value):
        raise ValueError("代理凭据编码无效")
    try:
        decoded = unquote(value, errors="strict")
    except UnicodeError:
        raise ValueError("代理凭据编码无效") from None
    if not decoded or any(ord(ch) < 32 or ord(ch) == 127 for ch in decoded):
        raise ValueError("代理凭据无效")
    return decoded


def parse_proxy_line(raw: str) -> ImportedProxy:
    line = raw.strip()
    if not line or len(line) > 2048 or any(ch.isspace() or ord(ch) < 32 for ch in line):
        raise ValueError("无效代理格式")

    if "://" in line:
        if any(ch in line for ch in ("?", "#", "\\")):
            raise ValueError("代理 URL 不能包含路径参数或片段")
        try:
            parsed = urlsplit(line)
            port = parsed.port
        except ValueError:
            raise ValueError("代理 URL 或端口无效") from None
        if parsed.scheme not in _SCHEMES or not parsed.hostname or parsed.path:
            raise ValueError("不支持的代理 URL")
        if parsed.netloc.count("@") > 1:
            raise ValueError("代理 URL 凭据格式无效")
        username = _decode(parsed.username)
        password = _decode(parsed.password)
        if (username is None) != (password is None):
            raise ValueError("代理用户名和密码必须同时提供")
        protocol = "socks5" if parsed.scheme == "socks5h" else parsed.scheme
        host = _host(parsed.hostname)
    else:
        match = re.fullmatch(r"(\[[^\]]+\]|[^:\[\]]+):([0-9]{1,5})(?::([^:]+):(.+))?", line)
        if not match:
            raise ValueError("无效代理格式")
        host_raw, port_raw, username, password = match.groups()
        host = _host(host_raw.removeprefix("[").removesuffix("]"))
        port = int(port_raw)
        protocol = "http"
        if (username is None) != (password is None):
            raise ValueError("代理用户名和密码必须同时提供")

    if port is None or not 1 <= port <= 65535:
        raise ValueError("代理端口无效")
    return ImportedProxy(protocol, host, port, username, password)
