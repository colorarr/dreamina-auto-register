"""
Dreamina Auto Register - 邮箱验证码服务（Worker HTTP 接入版）

使用与 grok-login 相同的 Worker HTTP 接口获取验证码，无需 Cloudflare 官方 API 凭据。
接口调用方式：
  - 创建临时邮箱：POST https://{worker_domain}/admin/new_address（x-admin-auth 鉴权）
  - 轮询邮件：GET https://{worker_domain}/api/mails（Bearer JWT 鉴权）
"""
import asyncio
import re
import random
import string
import httpx
from typing import Optional, Dict, Any
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


def _random_email_prefix(length: int = 12) -> str:
    """生成随机邮箱前缀（小写字母 + 少量数字）"""
    chars = list(random.choices(string.ascii_lowercase, k=length))
    for _ in range(random.choice([1, 2])):
        pos = random.randint(2, len(chars) - 1)
        chars.insert(pos, random.choice(string.digits))
    return "".join(chars)


def _extract_code(content: str) -> Optional[str]:
    """从邮件原始内容中提取验证码（参考 grok 注册机逻辑改写）。

    Dreamina 验证码格式：
    - 字母数字混合 6 位：N2SGN6、459ZC5
    - 纯大写字母 6 位：PNKFYA
    - 纯数字 6 位：123456

    核心策略：先清理 HTML 标签,在干净文本上做匹配,防止 <span> 等标签被误识别。
    """
    if not content:
        return None

    # ========== 第一步：清理 HTML 标签 ==========
    clean = re.sub(r'<[^>]+>', ' ', content)
    clean = re.sub(r'\s+', ' ', clean)

    # ========== 模式 1：Dreamina 标准格式 ==========
    # "verification code is N2SGN6" / "verification code: PNKFYA"
    # 注意：不能用 [\s:is]* 因为字符类中 s 在 IGNORECASE 下会吞掉验证码首字母 S
    m = re.search(
        r'verification code(?:\s+is\s+|[\s:]+)([A-Z0-9]{4,8})',
        clean,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).upper()

    # ========== 模式 2：XXX-XXX 格式（兼容 grok 类验证码）==========
    m = re.search(r'(?<![A-Z0-9-])([A-Z0-9]{3}-[A-Z0-9]{3})(?![A-Z0-9-])', clean)
    if m:
        return m.group(1).replace("-", "")

    # ========== 模式 3：Subject 行中的 6 位数字 ==========
    m = re.search(r'Subject:.*?(\d{6})', content)
    if m and m.group(1) != "177010":
        return m.group(1)

    # ========== 模式 4：HTML 标签内的 6 位数字（用原始内容）==========
    for code in re.findall(r'>\s*(\d{6})\s*<', content):
        if code != "177010":
            return code

    # ========== 模式 5：独立 6 位数字 ==========
    m = re.search(r'(?<![&#\d])(\d{6})(?![&#\d])', clean)
    if m and m.group(1) != "177010":
        return m.group(1)

    return None




class CloudflareKVClient:
    """Worker HTTP 邮箱验证码客户端（兼容原 Cloudflare KV 接口）"""

    @property
    def worker_domain(self) -> str:
        return getattr(settings, "cf_worker_domain", "") or ""

    @property
    def admin_password(self) -> str:
        return getattr(settings, "cf_worker_admin_password", "") or ""

    @property
    def email_domains(self) -> list:
        _domains_str = getattr(settings, "cf_email_domains", "") or ""
        return [d.strip() for d in _domains_str.split(",") if d.strip()]

    @property
    def poll_interval(self) -> int:
        return getattr(settings, "kv_poll_interval", 3)

    @property
    def poll_timeout(self) -> int:
        return getattr(settings, "kv_poll_timeout", 180)

    @property
    def is_configured(self) -> bool:
        """检查 Worker 接入是否已配置"""
        return bool(self.worker_domain and self.admin_password)

    async def _create_temp_email(self, client: httpx.AsyncClient) -> tuple[Optional[str], Optional[str]]:
        """创建临时邮箱，返回 (email, jwt_token)"""
        domain = random.choice(self.email_domains) if self.email_domains else None
        if not domain:
            logger.error("未配置邮箱域名（CF_EMAIL_DOMAINS）")
            return None, None

        name = _random_email_prefix(random.randint(10, 14))
        try:
            resp = await client.post(
                f"https://{self.worker_domain}/admin/new_address",
                json={"enablePrefix": True, "name": name, "domain": domain},
                headers={
                    "x-admin-auth": self.admin_password,
                    "Content-Type": "application/json",
                },
                timeout=15.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                email = data.get("address")
                token = data.get("jwt")
                if email:
                    logger.info(f"临时邮箱创建成功: {email}")
                    return str(email), str(token or "")
            logger.warning(f"创建临时邮箱失败: HTTP {resp.status_code} - {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"创建临时邮箱异常: {e}")
        return None, None

    async def _fetch_emails(self, client: httpx.AsyncClient, jwt_token: str) -> list:
        """拉取邮件列表"""
        try:
            resp = await client.get(
                f"https://{self.worker_domain}/api/mails",
                params={"limit": 10, "offset": 0},
                headers={"Authorization": f"Bearer {jwt_token}"},
                timeout=15.0,
            )
            if resp.status_code == 200:
                rows = resp.json().get("results", [])
                return rows if isinstance(rows, list) else []
        except Exception as e:
            logger.debug(f"拉取邮件异常: {e}")
        return []

    async def create_email(self) -> tuple[Optional[str], Optional[str]]:
        """
        公开接口：创建邮箱并返回 (email, jwt_token)。
        供 register_engine.py 在注册前调用。
        """
        async with httpx.AsyncClient(verify=False) as client:
            return await self._create_temp_email(client)

    async def poll_verification_code(self, email: str, timeout: Optional[int] = None) -> Optional[str]:
        """
        等待并获取验证码（兼容原接口签名）。

        注意：Worker 接入方式需要 JWT token 才能查询邮件，
        token 存储在 _email_token_cache 中，由 create_email() 在注册前填入。
        若缓存中没有 token，则回退到 admin 接口按地址查询。
        """
        if timeout is None:
            timeout = self.poll_timeout

        # 尝试从缓存获取 token
        jwt_token = _email_token_cache.pop(email, None)
        if not jwt_token:
            logger.warning(f"未找到邮箱 {email} 的 JWT token，将跳过验证码轮询")
            return None

        deadline = asyncio.get_event_loop().time() + timeout
        old_ids: set = set()

        async with httpx.AsyncClient(verify=False) as client:
            # 先获取旧邮件 ID 集合（排除历史邮件）
            existing = await self._fetch_emails(client, jwt_token)
            if existing:
                old_ids = {e.get("id") for e in existing if isinstance(e, dict) and "id" in e}
                # 先从现有邮件中尝试提取
                for item in existing:
                    if not isinstance(item, dict):
                        continue
                    raw = str(item.get("raw") or "")
                    code = _extract_code(raw)
                    if code:
                        logger.info(f"验证码已在邮箱中: {email} → {code}")
                        return code

            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(self.poll_interval)
                emails = await self._fetch_emails(client, jwt_token)
                for item in emails:
                    if not isinstance(item, dict):
                        continue
                    if item.get("id") in old_ids:
                        continue
                    raw = str(item.get("raw") or "")
                    code = _extract_code(raw)
                    if code:
                        logger.info(f"验证码获取成功: {email} → {code}")
                        return code

        logger.warning(f"验证码等待超时: {email}")
        return None

    async def test_connection(self) -> Dict[str, Any]:
        """测试 Worker 连接状态"""
        if not self.is_configured:
            return {"success": False, "error": "Worker 未配置（CF_WORKER_DOMAIN / CF_WORKER_ADMIN_PASSWORD）"}
        try:
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                # 创建一个测试邮箱验证连接
                resp = await client.post(
                    f"https://{self.worker_domain}/admin/new_address",
                    json={"enablePrefix": True, "name": "test_conn_check", "domain": self.email_domains[0] if self.email_domains else ""},
                    headers={"x-admin-auth": self.admin_password, "Content-Type": "application/json"},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    return {"success": True, "message": f"Worker 连接正常 ({self.worker_domain})"}
                else:
                    return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def close(self):
        """兼容接口，无需操作"""
        pass


# 邮箱 JWT Token 缓存（email -> jwt_token），供注册引擎使用
_email_token_cache: Dict[str, str] = {}


def register_email_token(email: str, jwt_token: str):
    """注册引擎创建邮箱后，将 token 存入缓存供轮询使用"""
    _email_token_cache[email] = jwt_token


# 全局实例
cf_kv_client = CloudflareKVClient()
