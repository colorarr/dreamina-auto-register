"""Standalone inventory parsing; never retains a proxy password."""
import ipaddress
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

_LABEL = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?")
_LOCAL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}")
_SCHEMES = {"http", "https", "socks5", "socks5h"}


def _host(value, *, require_domain=False):
    value = value.casefold()
    if not require_domain:
        try:
            if "%" not in value:
                return str(ipaddress.ip_address(value))
        except ValueError:
            pass
    labels = value.split(".")
    if len(value) > 253 or not all(_LABEL.fullmatch(x) for x in labels):
        raise ValueError("无效主机名")
    if require_domain and (len(labels) < 2 or labels[-1].isdigit()):
        raise ValueError("无效邮箱域名")
    return value


def parse_mailbox(raw):
    address = raw.strip()
    local, _, domain = address.partition("@")
    if (len(address) > 254 or not _LOCAL.fullmatch(local) or local.startswith(".")
            or local.endswith(".") or ".." in local):
        raise ValueError("无效邮箱地址")
    _host(domain, require_domain=True)
    return address


@dataclass(frozen=True)
class ProxyEntry:
    protocol: str
    host: str
    port: int
    username: str | None = field(default=None, repr=False)


def _credential(encoded):
    if re.search(r"%(?![0-9a-fA-F]{2})", encoded):
        raise ValueError("代理凭据编码无效")
    try:
        result = unquote(encoded, errors="strict")
    except UnicodeError:
        raise ValueError("代理凭据编码无效") from None
    if not result or any(ord(c) < 32 or ord(c) == 127 for c in result):
        raise ValueError("代理凭据无效")
    return result


def parse_proxy(raw):
    line = raw.strip()
    if not line or len(line) > 2048 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in line):
        raise ValueError("无效代理格式")
    username = None
    if "://" in line:
        if any(char in line for char in ("?", "#", "\\")):
            raise ValueError("代理 URL 不得包含查询参数、片段或反斜杠")
        try:
            url = urlsplit(line)
            protocol, host, port = url.scheme, url.hostname, url.port
        except ValueError:
            raise ValueError("代理 URL 或端口无效") from None
        if protocol not in _SCHEMES:
            raise ValueError("不支持的代理协议")
        authority = url.netloc.rsplit("@", 1)[-1]
        if not re.fullmatch(r"(\[[^\]]+\]|[^:\[\]]+):[0-9]{1,5}", authority):
            raise ValueError("代理主机或端口无效")
        if url.path or url.netloc.count("@") > 1:
            raise ValueError("代理 URL 必须只包含主机、端口和可选凭据")
        if url.username is not None:
            username = _credential(url.username)
            _credential(url.password or "")
    else:
        protocol = "http"
        match = re.fullmatch(r"(\[[^\]]+\]|[^:\[\]]+):([0-9]{1,5})(?::([^:]+):(.+))?", line)
        if not match:
            raise ValueError("无效代理格式")
        host, port_text, username, _password = match.groups()
        host = host.removeprefix("[").removesuffix("]")
        port = int(port_text)
    if not host or port is None or not 1 <= port <= 65535:
        raise ValueError("代理主机或端口无效")
    return ProxyEntry(protocol, _host(host), port, username)


def plan_import(lines, parse, identity, existing):
    seen = set(existing)
    rows, errors, duplicates = [], [], 0
    for index, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            item = parse(raw)
        except ValueError as exc:
            errors.append({"line": index, "reason": str(exc)})
            continue
        key = identity(item)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        rows.append(item)
    return rows, {"new": len(rows), "duplicates": duplicates, "errors": errors}
