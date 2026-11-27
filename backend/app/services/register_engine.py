"""
Dreamina Auto Register - 注册引擎（核心流程编排）
"""

import asyncio
import json
import random
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path
from patchright.async_api import async_playwright, Page, BrowserContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models import Account, EmailDomain, ProxyNode
from app.services.browser_stealth import BrowserStealth
from app.services.human_behavior import HumanBehavior
from app.services.cloudflare_kv import cf_kv_client, register_email_token
from app.services.clash_manager import clash_manager
from app.services.random_generator import (
    generate_password,
    generate_birth_date,
    generate_birth_date_parts,
)
import httpx
import logging

logger = logging.getLogger(__name__)


class TaskInterruptedError(Exception):
    """任务被用户手动暂停或取消"""

    pass


class SessionIdExtractor:
    """SessionId 多路提取器"""

    # 可能的 Cookie 名称
    SESSION_COOKIE_NAMES = [
        "sessionid",
        "session_id",
        "sid",
        "ttwid",
        "passport_csrf_token",
        "s_v_web_id",
        "msToken",
    ]

    # 可能的 LocalStorage 键名
    STORAGE_KEYS = [
        "sessionId",
        "session_id",
        "token",
        "access_token",
        "auth_token",
        "userToken",
    ]

    def __init__(self, page: Page, context: BrowserContext):
        self.page = page
        self.context = context
        self.captured_headers: Dict[str, str] = {}

    async def extract_all(self) -> Dict[str, Any]:
        """执行所有提取方法"""
        result = {
            "session_id": None,
            "all_tokens": {},
            "full_cookie": [],
        }

        # 1. Cookie 提取
        cookies = await self.context.cookies()
        result["full_cookie"] = cookies

        for cookie in cookies:
            name = cookie.get("name", "").lower()
            if any(sn in name for sn in self.SESSION_COOKIE_NAMES):
                result["all_tokens"][cookie["name"]] = cookie["value"]
                if not result["session_id"] and name == "sessionid":
                    result["session_id"] = cookie["value"]

        # 2. LocalStorage 提取
        try:
            local_storage = await self.page.evaluate("""
                () => {
                    const items = {};
                    for (let i = 0; i < localStorage.length; i++) {
                        const key = localStorage.key(i);
                        items[key] = localStorage.getItem(key);
                    }
                    return items;
                }
            """)
            for key in self.STORAGE_KEYS:
                if key in local_storage:
                    result["all_tokens"][f"ls_{key}"] = local_storage[key]
                    if not result["session_id"] and "session" in key.lower():
                        result["session_id"] = local_storage[key]
        except Exception as e:
            logger.warning(f"LocalStorage 提取失败: {e}")

        # 3. SessionStorage 提取
        try:
            session_storage = await self.page.evaluate("""
                () => {
                    const items = {};
                    for (let i = 0; i < sessionStorage.length; i++) {
                        const key = sessionStorage.key(i);
                        items[key] = sessionStorage.getItem(key);
                    }
                    return items;
                }
            """)
            for key in self.STORAGE_KEYS:
                if key in session_storage:
                    result["all_tokens"][f"ss_{key}"] = session_storage[key]
        except Exception as e:
            logger.warning(f"SessionStorage 提取失败: {e}")

        # 4. JS 全局变量提取
        try:
            initial_state = await self.page.evaluate("""
                () => {
                    if (window.__INITIAL_STATE__) {
                        return JSON.stringify(window.__INITIAL_STATE__);
                    }
                    return null;
                }
            """)
            if initial_state:
                result["all_tokens"]["__INITIAL_STATE__"] = initial_state[
                    :1000
                ]  # 截取前1000字符
        except Exception as e:
            logger.warning(f"JS 全局变量提取失败: {e}")

        # 5. 网络请求 Header（如果已捕获）
        if self.captured_headers:
            result["all_tokens"]["captured_headers"] = self.captured_headers

        return result


class RegisterEngine:
    """注册引擎"""

    # 亚洲核心注册区映射
    ASIA_KEYWORDS = [
        "日本",
        "新加坡",
        "香港",
        "台湾",
        "韩国",
        "JP",
        "SG",
        "HK",
        "TW",
        "KR",
        "Japan",
        "Singapore",
        "Hong Kong",
        "Taiwan",
        "Korea",
    ]

    # 页面选择器 (增强多语言支持：EN/JP/CN/HK)
    SELECTORS = {
        "sign_up_trigger": [
            ':text-is("Sign up")',
            ':text-is("Sign Up")',
            ':text-is("注册")',
            ':text-is("登録")',
            ':text-is("新規登録")',
            'button:has-text("Sign Up")',
            'a:has-text("Sign Up")',
            'a:has-text("登録")',
            'a:has-text("注册")',
            '[role="button"]:has-text("Sign Up")',
            '[data-testid="sign-up-button"]',
        ],
        "login_button": [
            ':text-is("Sign in")',
            ':text-is("登录")',
            ':text-is("ログイン")',
            'button:has-text("Sign in")',
            'button:has-text("ログイン")',
            '[role="button"]:has-text("ログイン")',
            '[data-testid="login-button"]',
            ".login-button-HNWFe4",
        ],
        "email_register_option": [
            ':text-is("Continue with email")',
            ':text-is("邮件")',
            ':text-is("邮箱")',
            ':text-is("メールで続行")',
            'button:has-text("Continue with email")',
            'button:has-text("メールで続行")',
            '[role="button"]:has-text("メールで続行")',
            '[data-testid="email-signup"]',
        ],
        "email_input": [
            'input[type="email"]',
            'input[name="email"]',
            'input[placeholder*="email" i]',
            'input[placeholder*="邮件" i]',
            'input[placeholder*="邮箱" i]',
            'input[placeholder*="メール" i]',
            "#email",
            '[data-testid="email-input"]',
        ],
        "password_input": [
            'input[type="password"]',
            'input[name="password"]',
            'input[placeholder*="password" i]',
            'input[placeholder*="密码" i]',
            'input[placeholder*="パスワード" i]',
            "#password",
            '[data-testid="password-input"]',
        ],
        "submit_button": [
            ':text-is("Continue")',
            ':text-is("继续")',
            ':text-is("续行")',
            ':text-is("次へ")',
            ':text-is("続行")',
            'button[type="submit"]',
            'button:has-text("Continue")',
            'button:has-text("次へ")',
            '[role="button"]:has-text("Continue")',
            '[data-testid="submit-button"]',
        ],
        "verification_code_input": [
            'input[name="code"]',
            'input[placeholder*="code" i]',
            'input[placeholder*="验证码" i]',
            'input[maxlength="6"]',
            ".verification-code-input",
            '[data-testid="code-input"]',
        ],
        "birth_year_select": [
            'input[placeholder="Year"]',
            'input[placeholder="年"]',
            'select[name="year"]',
            '[data-testid="birth-year"]',
        ],
        "birth_month_select": [
            ':text-is("Month")',
            ':text-is("月")',
            'select[name="month"]',
            '[data-testid="birth-month"]',
            '[aria-label*="Month" i]',
        ],
        "birth_day_select": [
            ':text-is("Day")',
            ':text-is("日")',
            'select[name="day"]',
            '[data-testid="birth-day"]',
            '[aria-label*="Day" i]',
        ],
        "birthday_next_button": [
            ':text-is("Next")',
            ':text-is("确定")',
            ':text-is("次へ")',
            ':text-is("续行")',
            ':text-is("続行")',
            'button:has-text("Next")',
            'button:has-text("确定")',
            'button:has-text("次へ")',
            ".lv_new_sign_in_panel_wide-birthday-next",
        ],
        "interests_modal": [
            '[class*="interest"]',
            '[class*="preference"]',
            '[data-testid="interests-modal"]',
            ".close-button-bXf1SB",
            ".close-btn-AiEiG_",
            'div[class*="close"] > svg',
        ],
        "home_sign_in_button": [
            ':text-is("Sign in")',
            ':text-is("登录")',
            ':text-is("ログイン")',
            "#SiderMenuLogin .login-button-HNWFe4",
            "#SiderMenuLogin",
            ".login-button-HNWFe4",
        ],
    }

    def __init__(self):
        self.playwright = None
        self.browser_stealth: Optional[BrowserStealth] = None
        self._browser_runtime_lock = asyncio.Lock()
        self.screenshots_dir = settings.screenshots_dir

    async def initialize(self):
        """初始化纯协议注册引擎；浏览器运行时按需加载。"""
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    async def ensure_browser_runtime(self):
        """仅供账号人工登录等独立功能使用，协议注册不会调用。"""
        if self.browser_stealth:
            return
        async with self._browser_runtime_lock:
            if self.browser_stealth:
                return
            self.playwright = await async_playwright().start()
            self.browser_stealth = BrowserStealth(self.playwright)

    async def shutdown(self):
        """关闭引擎"""
        if self.browser_stealth:
            try:
                await self.browser_stealth.close()
            except Exception as e:
                logger.debug(f"关闭 browser_stealth 时报错: {e}")
            self.browser_stealth = None
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception as e:
                logger.debug(f"关闭 playwright 时报错: {e}")
            self.playwright = None

    def is_asia_region(
        self, region_tag: Optional[str], node_name: Optional[str] = None
    ) -> bool:
        """识别是否为亚洲地区（兼容 tag 和 node_name）"""
        target = f"{region_tag or ''} {node_name or ''}"
        if not target.strip():
            return False
        return any(kw.upper() in target.upper() for kw in self.ASIA_KEYWORDS)

    async def find_element(
        self, page: Page, selector_key: str, timeout: int = 10000
    ) -> Optional[Any]:
        """使用 Locator.or_() 并发匹配多个选择器，超时仅计一次"""
        selectors = self.SELECTORS.get(selector_key, [])
        if not selectors:
            return None
        # 将所有选择器合并为组合 Locator，Playwright 内部并发探测
        combined = page.locator(selectors[0])
        for selector in selectors[1:]:
            combined = combined.or_(page.locator(selector))
        try:
            await combined.first.wait_for(state="visible", timeout=timeout)
            return combined.first
        except Exception:
            return None

    async def check_interrupted(self, db: AsyncSession, task_id: str):
        """检查任务是否被暂停或取消"""
        from sqlalchemy import select
        from app.models import TaskRecord

        stmt = select(TaskRecord.status).where(TaskRecord.task_id == task_id)
        result = await db.execute(stmt)
        status = result.scalar_one_or_none()

        if status in ["paused", "cancelled"]:
            logger.info(f"检测到任务 {task_id} 状态已变更为 {status}，触发中断")
            raise TaskInterruptedError(f"Task is {status}")

    async def report_step(self, db: AsyncSession, task_id: str, step: str):
        """上报当前进度步骤到数据库"""
        from app.models.task_record import TaskRecord
        from sqlalchemy import update

        try:
            await db.execute(
                update(TaskRecord)
                .where(TaskRecord.task_id == task_id)
                .values(current_step=step)
            )
            await db.commit()
            from app.api.routers.websocket import send_log
            step_labels = {
                "create_browser": "正在创建浏览器环境",
                "navigate": "正在打开注册页面",
                "login_page_trigger": "正在进入登录页面",
                "click_continue_email": "正在选择邮箱注册",
                "input_email": "正在填写注册邮箱",
                "submit_email": "正在提交注册邮箱",
                "verify_code": "正在等待并填写验证码",
                "set_password": "正在设置账号密码",
                "complete_profile": "正在完善账号资料",
                "extract_session": "正在提取登录会话",
                "protocol_bootstrap": "正在建立协议注册会话",
                "protocol_detect_region": "正在通过代理识别注册地区",
                "protocol_check_email": "正在检查邮箱注册状态",
                "protocol_send_code": "正在请求发送注册验证码",
                "protocol_wait_code": "正在等待邮箱验证码",
                "protocol_verify_code": "正在校验邮箱验证码",
                "protocol_age_gate": "正在校验生日与年龄门槛",
                "protocol_register": "正在提交协议注册",
                "protocol_initialize_account": "正在初始化账号资料与条款",
                "protocol_complete": "协议注册完成，登录会话已保存",
            }
            await send_log("INFO", step_labels.get(step, f"执行步骤：{step}"), task_id=task_id)
            logger.debug(f"Task {task_id} reported step: {step}")
        except Exception as e:
            logger.error(f"Failed to report step {step} for task {task_id}: {e}")

    async def take_screenshot(self, page: Page, step_name: str, email: str) -> str:
        """截图（已禁用，保留兼容返回）"""
        return ""

    async def execute_registration(
        self,
        db: AsyncSession,
        task_id: str,
        email: str,
        password: str,
        domain: EmailDomain,
        proxy_node: Optional[ProxyNode] = None,
        birth_date: Optional[dict] = None,
        proxy_config: Optional[Any] = None,
        email_source: str = "cloudflare",
    ) -> Dict[str, Any]:
        """
        执行完整注册流程
        """
        await self.ensure_browser_runtime()
        result = {
            "success": False,
            "session_id": None,
            "all_tokens": {},
            "full_cookie": "",
            "screenshot_path": "",
            "browser_state_path": "",
            "fingerprint_json": "",
            "detected_region": None,
            "error": None,
            "step": "init",
        }

        context = None
        page = None

        try:
            # 1. 创建浏览器上下文
            result["step"] = "create_browser"
            await self.report_step(db, task_id, result["step"])

            # 地区标签初始值（后续代理预检时通过真实 IP 覆盖）
            region_tag = proxy_node.region_tag if proxy_node else None
            node_name = proxy_node.name if proxy_node else None
            if not region_tag and proxy_config:
                region_tag = proxy_config.group
                node_name = proxy_config.name

            playwright_proxy = None
            if proxy_config:
                protocol = proxy_config.protocol or "http"
                playwright_proxy = {
                    "server": f"{protocol}://{proxy_config.host}:{proxy_config.port}",
                }
                if proxy_config.username:
                    playwright_proxy["username"] = proxy_config.username
                if proxy_config.password:
                    playwright_proxy["password"] = proxy_config.password

                # 代理预检 + 真实 IP 区域检测
                preflight_proxy = proxy_config.url
                try:
                    client_kwargs = {"timeout": 10.0, "verify": False}
                    if preflight_proxy.startswith("socks"):
                        from httpx_socks import AsyncProxyTransport

                        client_kwargs["transport"] = AsyncProxyTransport.from_url(
                            preflight_proxy
                        )
                    else:
                        client_kwargs["proxy"] = preflight_proxy
                    async with httpx.AsyncClient(**client_kwargs) as client:
                        # 连通性检查 (增加重试机制对抗偶尔的 502/断流)
                        max_preflight_retries = 3
                        preflight_success = False
                        last_preflight_error = ""

                        real_country = "UN"
                        real_ip = "Unknown"

                        endpoints = [
                            {
                                "type": "cf",
                                "url": "https://cp.cloudflare.com/cdn-cgi/trace",
                            },
                            {
                                "type": "ipapi",
                                "url": "http://ip-api.com/json/?fields=status,countryCode,query",
                            },
                            {"type": "ipinfo", "url": "https://ipinfo.io/json"},
                            # 新增：业务域名连通性探测 (针对连接重置问题)
                            {
                                "type": "dreamina",
                                "url": "https://dreamina.capcut.com/ai-tool/login",
                            },
                            {
                                "type": "static",
                                "url": "https://sf16-web-login-neutral.capcutstatic.com/obj/capcut-web-login-static/ies/ccweb/dreamina/static/css/async/CanvasAssets.665ef35c.css",
                            },
                        ]

                        for attempt in range(max_preflight_retries):
                            for ep in endpoints:
                                try:
                                    req_url = ep["url"]
                                    if (
                                        ep["type"] == "ipinfo"
                                        and hasattr(settings, "ipinfo_token")
                                        and settings.ipinfo_token
                                    ):
                                        req_url += f"?token={settings.ipinfo_token}"

                                    resp = await client.get(
                                        req_url, timeout=10.0, follow_redirects=True
                                    )
                                    if resp.status_code == 200:
                                        if ep["type"] == "cf":
                                            text = resp.text
                                            for line in text.split("\n"):
                                                if line.startswith("ip="):
                                                    real_ip = line.split("=")[1].strip()
                                                elif line.startswith("loc="):
                                                    real_country = (
                                                        line.split("=")[1]
                                                        .strip()
                                                        .upper()
                                                    )
                                            if real_country and real_ip:
                                                preflight_success = True
                                                break
                                        elif ep["type"] == "ipapi":
                                            data = resp.json()
                                            if data.get("status") == "success":
                                                preflight_success = True
                                                real_country = data.get(
                                                    "countryCode", ""
                                                ).upper()
                                                real_ip = data.get("query", "")
                                                break
                                        elif ep["type"] == "ipinfo":
                                            data = resp.json()
                                            real_country = data.get(
                                                "country", ""
                                            ).upper()
                                            real_ip = data.get("ip", "")
                                            if real_country and real_ip:
                                                preflight_success = True
                                                break
                                        elif ep["type"] in ["dreamina", "static"]:
                                            # 只要能成功拿到 200 或 300+ 响应，说明连接未被重置
                                            if resp.status_code < 400:
                                                preflight_success = True
                                                logger.debug(
                                                    f"业务域名探测成功: {ep['type']}"
                                                )
                                                # 继续探测下一个环节检查，不 break
                                            else:
                                                last_preflight_error = f"业务端点 {ep['type']} 访问异常 (HTTP {resp.status_code})"
                                                preflight_success = False
                                                break
                                    last_preflight_error = f"端点 {ep['type']} 检测失败(HTTP {resp.status_code})"
                                except Exception as req_err:
                                    last_preflight_error = (
                                        f"端点 {ep['type']} 异常: {req_err}"
                                    )

                            if preflight_success:
                                break

                            if attempt < max_preflight_retries - 1:
                                logger.warning(
                                    f"代理预检(所有端点)失败 (尝试 {attempt + 1}/{max_preflight_retries}): {last_preflight_error}，等待重试..."
                                )
                                await asyncio.sleep(2.0)

                        if not preflight_success:
                            raise Exception(
                                f"代理预检(API)异常(多次重试失败): {last_preflight_error}"
                            )

                        # 国家代码映射到 jimeng 区域
                        country_region_map = {
                            "US": "us",
                            "HK": "hk",
                            "JP": "jp",
                            "SG": "sg",
                            "CN": "cn",
                            "TW": "tw",
                            "KR": "kr",
                            "GB": "uk",
                            "DE": "de",
                            "FR": "fr",
                            "NL": "nl",
                        }
                        region_tag = country_region_map.get(
                            real_country, real_country.lower() if real_country else "hk"
                        )
                        logger.info(
                            f"真实 IP 区域检测: {real_ip} → {real_country} → region={region_tag}"
                        )

                    logger.info(
                        f"代理预检通过: {proxy_config.name} via {preflight_proxy}"
                    )
                except Exception as e:
                    if "代理预检异常" in str(e) or "代理预检失败" in str(e):
                        raise
                    raise Exception(f"代理预检失败 [{proxy_config.name}]: {e}")

            # 保存真实检测到的区域
            result["detected_region"] = region_tag

            # 使用最终确定的 region_tag 生成指纹
            fingerprint = self.browser_stealth.get_random_fingerprint(region_tag)
            result["fingerprint_json"] = json.dumps(fingerprint)

            context = await self.browser_stealth.create_context(
                region_tag=region_tag, fingerprint=fingerprint, proxy=playwright_proxy
            )
            page = await self.browser_stealth.create_page(context)
            human = HumanBehavior(page)
            extractor = SessionIdExtractor(page, context)

            async def capture_headers(route, request):
                for key, value in request.headers.items():
                    key_lower = key.lower()
                    if any(s in key_lower for s in ["session", "token", "auth"]):
                        extractor.captured_headers[key] = value
                await route.continue_()

            await page.route("**/api/**", capture_headers)

            # 2. 导航并验证页面加载
            result["step"] = "navigate"
            await self.report_step(db, task_id, result["step"])

            target_url = settings.dreamina_url.rstrip("/")
            if "/ai-tool/" not in target_url:
                target_url = target_url + "/ai-tool/login"

            logger.info(f"导航到: {target_url}")
            await self.check_interrupted(db, task_id)

            max_nav_retries = 3
            for nav_attempt in range(max_nav_retries):
                try:
                    await page.goto(
                        target_url,
                        wait_until="load",
                        timeout=settings.page_load_timeout * 1000,
                    )
                except Exception as e:
                    logger.warning(
                        f"导航至 {target_url} 超时 (尝试 {nav_attempt + 1}/{max_nav_retries}): {e}"
                    )

                await human.wait_for_navigation_stable()

                # 检测页面错误内容
                page_content = ""
                try:
                    page_content = await page.text_content("body") or ""
                except Exception:
                    pass

                error_keywords = [
                    "Gateway Timeout",
                    "502 Bad Gateway",
                    "503 Service",
                    "504 Gateway",
                ]
                if any(kw.lower() in page_content.lower() for kw in error_keywords):
                    logger.warning(
                        f"检测到网关错误 (尝试 {nav_attempt + 1}/{max_nav_retries})"
                    )
                    if nav_attempt < max_nav_retries - 1:
                        await page.wait_for_timeout(3000)
                        continue
                    else:
                        raise Exception(f"连续 {max_nav_retries} 次加载返回网关错误")

                await BrowserStealth.dismiss_error_modal(page, max_retries=1)
                break

            # 3. 触发登录/注册界面
            current_url = page.url
            if "/ai-tool/login" in current_url:
                result["step"] = "login_page_trigger"
                await self.report_step(db, task_id, result["step"])

                # 隐私勾选：增加状态检测，避免重复点击失能
                privacy_selector = ".lv-checkbox-mask, .lv-v-checkbox"
                checkbox_loc = page.locator(privacy_selector).first
                if await checkbox_loc.count() > 0:
                    # 获取 class 列表，检测是否已包含 checked 相关类名
                    classes = await checkbox_loc.get_attribute("class") or ""
                    is_already_checked = any(
                        c in classes for c in ["--checked", "is-checked", "active"]
                    )

                    if not is_already_checked:
                        await human.scroll_randomly(distance=100)
                        await human.click_like_human(privacy_selector)
                        await page.wait_for_timeout(500)
                    else:
                        logger.debug("隐私协议已处于勾选状态，跳过点击")

                # 点击主 Login 按钮 (此时触发邮箱/第三方登录弹窗)
                await human.reading_pause(0.5, 1.2)
                login_btn_selector = ", ".join(self.SELECTORS["login_button"])
                await human.hover_like_human(login_btn_selector)
                await page.locator(login_btn_selector).first.click()
                await human.wait_for_navigation_stable()

            elif "/ai-tool/home" in current_url:
                # 侧边栏登录
                result["step"] = "home_page_trigger"
                await self.report_step(db, task_id, result["step"])
                await human.scroll_randomly(distance=300)
                await human.reading_pause(1.0, 2.5)
                # 侧边栏通常也含有 login class
                login_sidebar_selector = ", ".join(self.SELECTORS["login_button"])
                await human.hover_like_human(login_sidebar_selector)
                await page.locator(login_sidebar_selector).first.click()
                await human.wait_for_navigation_stable()

            # 4. 选择邮箱路径
            result["step"] = "click_continue_email"
            await self.report_step(db, task_id, result["step"])
            await human.reading_pause(1.0, 2.0)
            email_opt_selector = ", ".join(self.SELECTORS["email_register_option"])
            await human.hover_like_human(email_opt_selector)
            await page.locator(email_opt_selector).first.click()

            # 5. 切换到注册 (Sign Up) 界面
            result["step"] = "switch_to_signup"
            await self.report_step(db, task_id, result["step"])
            await human.reading_pause(0.8, 1.5)
            signup_selector = ", ".join(self.SELECTORS["sign_up_trigger"])
            try:
                # 尝试点击注册切换按钮（如果当前显示的是登录界面）
                loc = page.locator(signup_selector).first
                if await loc.count() > 0:
                    await human.hover_like_human(signup_selector)
                    await loc.click()
                    logger.debug("已点击 Sign up / 新規登録 切换至注册界面")
            except Exception as e:
                logger.debug(f"切换注册界面跳过或失败 (可能已处于注册页): {e}")

            # 6. 表单填写
            result["step"] = "fill_register_form"
            await self.report_step(db, task_id, result["step"])
            await human.reading_pause(1.0, 2.0)

            # 邮箱
            email_input_found = False
            for sel in self.SELECTORS["email_input"]:
                if await page.locator(sel).first.count() > 0:
                    await human.fill_form_field(sel, email)
                    email_input_found = True
                    break
            if not email_input_found:
                await page.get_by_role("textbox").first.fill(email)

            await human.reading_pause(0.4, 0.9)

            # 密码
            password_input_found = False
            for sel in self.SELECTORS["password_input"]:
                if await page.locator(sel).first.count() > 0:
                    await human.fill_form_field(sel, password)
                    password_input_found = True
                    break
            if not password_input_found:
                await page.get_by_role("textbox").nth(1).fill(password)

            # 7. 提交注册 (Continue 按钮)
            await human.reading_pause(1.5, 3.0)  # 模拟思考时间
            submit_selector = ", ".join(self.SELECTORS["submit_button"])
            await human.hover_like_human(submit_selector)
            await page.locator(submit_selector).first.click()
            await human.wait_for_navigation_stable()

            # 8. 验证码交互
            result["step"] = "wait_verification_code"
            await self.report_step(db, task_id, result["step"])
            await self.check_interrupted(db, task_id)

            code_url = None
            if email_source == "generic_api":
                from app.models.outlook_mailbox import OutlookMailbox
                mailbox_stmt = select(OutlookMailbox).where(
                    OutlookMailbox.email == email,
                    OutlookMailbox.provider_type == "generic_api",
                )
                mailbox = (await db.execute(mailbox_stmt)).scalar_one_or_none()
                code_url = mailbox.code_url if mailbox else None

            from app.services.mailbox_verification import poll_verification_code
            code = await poll_verification_code(
                email_source,
                email,
                code_url=code_url,
                timeout=settings.verification_timeout,
            )

            if not code:
                raise Exception("注册验证码获取超时")

            result["step"] = "input_verification_code"
            await self.report_step(db, task_id, result["step"])
            code_input_sel = 'input[placeholder*="code" i], input[placeholder*="验证码" i], input[maxlength="6"]'
            await page.locator(code_input_sel).first.wait_for(
                state="visible", timeout=5000
            )
            await human.fill_form_field(code_input_sel, code)
            await human.wait_for_navigation_stable()

            # 9. 填写生日
            result["step"] = "fill_birth_date"
            await self.report_step(db, task_id, result["step"])
            if birth_date is None:
                bd = generate_birth_date()
                birth_date = {
                    "year": str(bd.year),
                    "month": str(bd.month),
                    "day": str(bd.day),
                }

            logger.info(f"填写出生日期: {birth_date}")
            try:
                # 填写年份
                year_filled = False
                for sel in self.SELECTORS["birth_year_select"]:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        await loc.fill(birth_date["year"])
                        year_filled = True
                        break
                if not year_filled:
                    await page.get_by_role("textbox", name="Year").fill(
                        birth_date["year"]
                    )
                await human.reading_pause(0.3, 0.6)

                # 2. 选择月份
                month_names = {
                    "1": "January",
                    "2": "February",
                    "3": "March",
                    "4": "April",
                    "5": "May",
                    "6": "June",
                    "7": "July",
                    "8": "August",
                    "9": "September",
                    "10": "October",
                    "11": "November",
                    "12": "December",
                }
                m_name = month_names.get(birth_date["month"], "January")

                month_clicked = False
                for sel in self.SELECTORS["birth_month_select"]:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        await loc.click()
                        month_clicked = True
                        break
                if not month_clicked:
                    try:
                        await page.get_by_text("Month").first.click(timeout=3000)
                        month_clicked = True
                    except:
                        pass

                if month_clicked:
                    await human.reading_pause(0.5, 1.0)
                    try:
                        # 尝试通过月名点击
                        await page.get_by_role("option", name=m_name).first.click(
                            timeout=2000
                        )
                    except:
                        # 兜底通过 index 点击
                        month_idx = int(birth_date["month"] or 1)
                        await page.get_by_role("option").nth(month_idx - 1).click()

                # 3. 选择日期
                await human.reading_pause(0.3, 0.6)
                day_clicked = False
                for sel in self.SELECTORS["birth_day_select"]:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        await loc.click()
                        day_clicked = True
                        break
                if not day_clicked:
                    try:
                        day_loc = (
                            page.get_by_role("combobox").filter(has_text="Day").first
                        )
                        try:
                            # 尝试录制中的针对性点击方式
                            await day_loc.locator("svg").first.click(timeout=1500)
                        except:
                            await day_loc.click(timeout=1500)
                        day_clicked = True
                    except:
                        pass

                if day_clicked:
                    await human.reading_pause(0.5, 1.0)
                    await page.get_by_role(
                        "option", name=str(int(birth_date["day"])), exact=True
                    ).first.click()

                # 提交生日信息
                await human.reading_pause(1.0, 2.0)
                next_btn_selector = ", ".join(self.SELECTORS["birthday_next_button"])
                await human.hover_like_human(next_btn_selector)
                await page.locator(next_btn_selector).first.click()
                logger.info("生日信息已提交")
            except Exception as e:
                logger.warning(f"生日信息填写流程遇到异常 (可能非必须/已跳过): {e}")

            await human.wait_for_navigation_stable()

            # 10. 提取 Session
            result["step"] = "extract_session"
            await self.report_step(db, task_id, result["step"])

            logger.info("开始提取 Session，最多等待 15 秒...")
            max_wait_time = 15.0
            total_waited = 0.0
            extracted = {"session_id": None, "all_tokens": {}, "full_cookie": []}

            while total_waited < max_wait_time:
                extracted = await extractor.extract_all()
                if extracted.get("session_id"):
                    logger.info(f"成功获取到 session_id (耗时: {total_waited}s)")
                    break
                await asyncio.sleep(1.0)
                total_waited += 1.0

            if not extracted.get("session_id"):
                logger.warning("提取 Session 超时，未获取到 session_id")

            result.update(
                {
                    "session_id": extracted["session_id"],
                    "all_tokens": extracted["all_tokens"],
                    "full_cookie": json.dumps(extracted["full_cookie"]),
                    "success": True if extracted.get("session_id") else False,
                }
            )
            result["screenshot_path"] = ""

            # 11. 保存浏览器状态 (指纹核心)
            safe_email = email.replace("@", "_at_").replace(".", "_")
            state_path = settings.browser_states_dir / f"{safe_email}_state.json"
            await self.browser_stealth.save_state(context, str(state_path))
            result["browser_state_path"] = str(state_path)

            # 12. 模拟浏览欢迎页 (增加权重)
            await human.scroll_randomly(distance=random.randint(200, 500))
            await human.reading_pause(2.0, 5.0)

        except TaskInterruptedError as e:
            logger.warning(f"任务 {task_id} 已由用户中断: {e}")
            result["success"] = False
            result["error"] = str(e)
            # 中断的任务不计入 failure_count，由 scheduler 层处理
        except TaskInterruptedError as e:
            logger.info(f"任务 {task_id} 在步骤 {result.get('step')} 被用户中断")
            result["success"] = False
            result["error"] = str(e)
            result["interrupted"] = True
            # 不重抛，让 execute_with_proxy 处理状态
        except Exception as e:
            error_msg = str(e)
            error_step = result.get("step", "unknown")
            # 已禁用异常截图
            result["success"] = False
            result["error"] = error_msg

            # 识别是否为代理导致的任务失败
            proxy_error_keywords = [
                "代理预检异常",
                "代理预检失败",
                "ERR_PROXY_CONNECTION_FAILED",
                "ERR_NO_SUPPORTED_PROXIES",
                "ERR_TUNNEL_CONNECTION_FAILED",
                "ERR_SOCKS_CONNECTION_FAILED",
            ]
            if any(keyword in error_msg for keyword in proxy_error_keywords):
                result["proxy_error"] = True

            logger.error(f"注册失败 [{error_step}]: {e}")
        finally:
            # 如果开启了 pause_on_fail 且注册失败，保留浏览器方便调试
            should_keep_browser = (
                settings.pause_on_fail
                and not result.get("success", False)
                and context
            )
            if should_keep_browser:
                logger.warning(
                    "⚠️ [调试模式] 注册失败，浏览器保持打开。"
                    "请手动检查后关闭浏览器窗口。"
                )
            elif context:
                browser_to_close = context.browser
                try:
                    await context.close()
                except Exception as e:
                    logger.debug(f"Closing context exception: {e}")

                if browser_to_close:
                    try:
                        await browser_to_close.close()
                    except Exception as e:
                        logger.debug(f"Closing browser exception: {e}")
        return result

    async def execute_with_proxy(
        self, db: AsyncSession, task_id: str, proxy_config: Any
    ) -> Dict[str, Any]:
        from app.models import TaskRecord, EmailDomain, ProxyNode, Account
        from app.services.random_generator import (
            generate_email_prefix,
            generate_password,
        )
        from sqlalchemy import select
        import random
        import hashlib

        stmt = select(TaskRecord).where(TaskRecord.task_id == task_id)
        task = (await db.execute(stmt)).scalar_one_or_none()
        if not task:
            return {"success": False, "error": "Task not found"}

        email_source = task.email_source or "cloudflare"
        domain_ids = json.loads(task.domain_ids) if task.domain_ids else []

        # 确定 邮箱地址
        email = task.assigned_email
        domain = None

        if email_source == "cloudflare":
            from app.core.config import settings as app_settings
            from app.services.cloudflare_kv import _email_token_cache
            if app_settings.cf_worker_domain:
                # Worker 模式：检查是否有可复用的真实邮箱（重试场景）
                if email and email in _email_token_cache:
                    # 重试：上次 Worker 创建的真实邮箱且 JWT token 还在，直接复用
                    logger.info(f"复用 Worker 邮箱: {email}")
                else:
                    # 首次 或 token 丢失：调 Worker 创建新邮箱
                    worker_email, worker_jwt = await cf_kv_client.create_email()
                    if not worker_email:
                        return {"success": False, "error": "Worker 创建临时邮箱失败，请检查 CF_WORKER_DOMAIN / CF_EMAIL_DOMAINS 配置"}
                    email = worker_email
                    if worker_jwt:
                        register_email_token(email, worker_jwt)
                    # 用真实邮箱替换占位符
                    try:
                        from sqlalchemy import update as sa_update
                        await db.execute(
                            sa_update(TaskRecord)
                            .where(TaskRecord.task_id == task_id)
                            .values(assigned_email=email)
                        )
                        await db.commit()
                    except Exception as _sync_err:
                        logger.warning(f"同步任务邮箱失败（不影响注册）: {_sync_err}")
            elif email:
                logger.info(f"复用已分配邮箱: {email}")
            else:
                return {"success": False, "error": "未配置 Worker 且无可用邮箱"}
        elif email_source in {"outlook", "generic_api"}:
            # 邮箱池模式：邮箱已在 create_task 时分配，直接使用
            if not email:
                return {"success": False, "error": "No mailbox assigned"}

        password = generate_password()

        from app.services.jimeng_api import JimengClient

        # region 将在 execute_registration 中通过真实 IP 检测覆盖
        configured_region = str(getattr(proxy_config, "region_tag", "") or "").strip().lower()
        region = configured_region if configured_region and configured_region != "un" else JimengClient.resolve_region(proxy_config.name, proxy_config.group)

        account_stmt = select(Account).where(Account.email == email)
        account = (await db.execute(account_stmt)).scalar_one_or_none()

        if account:
            account.status = "pending"
            account.task_id = task_id
            account.password = password
            account.proxy_node_name = proxy_config.name
            account.registration_ip = getattr(proxy_config, "exit_ip", None)
            account.registration_asn = getattr(proxy_config, "exit_asn", None)
            account.registration_proxy_key = hashlib.sha256(
                proxy_config.unique_id.encode()
            ).hexdigest()
            account.region = region
            account.failure_reason = None
            account.session_id = None
        else:
            account = Account(
                email=email,
                password=password,
                domain_id=domain.id if domain else None,
                task_id=task_id,
                status="pending",
                proxy_node_name=proxy_config.name,
                registration_ip=getattr(proxy_config, "exit_ip", None),
                registration_asn=getattr(proxy_config, "exit_asn", None),
                registration_proxy_key=hashlib.sha256(
                    proxy_config.unique_id.encode()
                ).hexdigest(),
                region=region,
            )
            db.add(account)

        try:
            await db.flush()
            await db.refresh(account)
        except Exception as e:
            logger.error(f"Failed to create/update account record: {e}")
            return {"success": False, "error": f"Database integrity error: {e}"}

        from app.services.protocol_register import execute_protocol_registration

        reg_result = await execute_protocol_registration(
            self,
            db,
            task_id,
            email,
            password,
            proxy_config=proxy_config,
            email_source=email_source,
        )

        detected_region = str(reg_result.get("detected_region") or "").strip().lower()
        if detected_region and detected_region != "un":
            account.region = detected_region
            region = detected_region

        if reg_result["success"]:
            account.status = "active"
            if reg_result.get("registration_ip"):
                account.registration_ip = reg_result["registration_ip"]
            if getattr(proxy_config, "exit_asn", None):
                account.registration_asn = proxy_config.exit_asn
            if reg_result.get("birth_date"):
                try:
                    account.birth_date = datetime.strptime(
                        reg_result["birth_date"], "%Y-%m-%d"
                    ).date()
                except (TypeError, ValueError):
                    logger.warning("协议注册生日格式无效，未写入账号记录")
            raw_session = reg_result.get("session_id")
            account.full_cookie = reg_result.get("full_cookie")
            account.screenshot_path = reg_result.get("screenshot_path")
            account.browser_state_path = reg_result.get("browser_state_path")
            account.fingerprint_json = reg_result.get("fingerprint_json")
            try:
                registration_fp = json.loads(account.fingerprint_json or "{}")
            except (TypeError, ValueError):
                registration_fp = {}
            account.registration_browser_profile = registration_fp.get(
                "profile_name"
            ) or registration_fp.get("archetype_name")
            account.registration_browser_version = registration_fp.get(
                "chrome_version"
            )
            account.all_tokens = json.dumps(reg_result.get("all_tokens", {}))

            # 使用真实 IP 检测到的区域更新 account
            # 在保存 session_id 时拼接地区前缀（如 jp-xxxtoken）
            if raw_session and region:
                account.session_id = f"{region}-{raw_session}"
            else:
                account.session_id = raw_session

            # 注册成功 → 自动标记健康并启用生成池
            if account.session_id:
                account.health_status = "healthy"
                account.gen_enabled = True
                account.gen_enabled_at = datetime.utcnow()
                logger.info(f"注册成功，自动启用生成池: {email}")

            # 邮箱池模式：注册成功后禁用该邮箱，避免重复注册
            if email_source in {"outlook", "generic_api"}:
                from app.models.outlook_mailbox import OutlookMailbox

                mailbox_stmt = select(OutlookMailbox).where(
                    OutlookMailbox.email == email
                )
                mailbox = (await db.execute(mailbox_stmt)).scalar_one_or_none()
                if mailbox:
                    mailbox.is_enabled = False
                    mailbox.usage_count = (mailbox.usage_count or 0) + 1
                    mailbox.last_used_at = datetime.utcnow()
                    logger.info("[MailboxPool] 邮箱注册成功，已禁用")

            # 自动签到领取积分（利用当前代理）
            if account.session_id:
                try:
                    # 构造代理 URL
                    proxy_url = None
                    if proxy_config:
                        proxy_url = proxy_config.url

                    client = JimengClient(
                        account.session_id, region=region, proxy_url=proxy_url
                    )
                    logger.info(
                        "注册成功后自动签到: %s (代理节点: %s, 区域: %s)",
                        email,
                        getattr(proxy_config, "name", "unknown"),
                        region,
                    )

                    received = await client.daily_checkin()
                    if received and received.get("success"):
                        credits = received.get("credits", {})
                        account.credits_gift = credits.get("gift", 0)
                        account.credits_purchase = credits.get("purchase", 0)
                        account.credits_vip = credits.get("vip", 0)
                        account.credits_total = credits.get("total", 0)
                        account.last_checkin_at = datetime.utcnow()
                        logger.info(
                            f"自动签到成功: {email} → 积分 {account.credits_total}"
                        )
                    else:
                        # 签到无积分时，尝试获取当前积分
                        credits = await client.get_credits()
                        if credits:
                            account.credits_gift = credits.get("gift", 0)
                            account.credits_purchase = credits.get("purchase", 0)
                            account.credits_vip = credits.get("vip", 0)
                            account.credits_total = credits.get("total", 0)
                        account.last_checkin_at = datetime.utcnow()
                        logger.info(
                            f"自动签到完成（无新增积分），当前积分: {account.credits_total}"
                        )
                except Exception as e:
                    logger.warning(f"自动签到失败 ({email}): {e}，不影响注册结果")

            # 注册成功后立即用纯 HTTP 协议检测订阅优惠资格
            if account.session_id and account.full_cookie:
                try:
                    from app.services.account_offer import check_account_offer

                    await check_account_offer(
                        account,
                        proxy_url=proxy_config.url if proxy_config else None,
                    )
                    logger.info(
                        "注册后优惠检测完成: %s -> %s",
                        email,
                        account.offer_status,
                    )
                except Exception as e:
                    logger.warning("注册后优惠检测异常 (%s): %s", email, e)
        elif reg_result.get("interrupted"):
            account.status = "cancelled"
            account.failure_reason = "Manual stop/pause"
        else:
            # 注册失败 → 直接删除账号记录，不保留无用数据
            await db.delete(account)

        await db.commit()
        return reg_result


# 全局实例
register_engine = RegisterEngine()
