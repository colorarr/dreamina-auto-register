import sys
import os
import asyncio

# Windows 下使用 Playwright 必须使用 ProactorEventLoop
if sys.platform == "win32":
    try:
        from asyncio import WindowsProactorEventLoopPolicy

        if not isinstance(
            asyncio.get_event_loop_policy(), WindowsProactorEventLoopPolicy
        ):
            asyncio.set_event_loop_policy(WindowsProactorEventLoopPolicy())
    except Exception:
        pass

"""
Dreamina Auto Register - FastAPI 主入口
"""
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pathlib import Path

from app.core import settings, ensure_directories, init_db
from app.middleware.error_handler import global_exception_handler
import app.models  # 确保模型被加载
from app.services.register_engine import register_engine
from app.services.cloudflare_kv import cf_kv_client
from app.services.task_scheduler import task_scheduler
from app.services.db_migration import (
    ensure_proxy_node_columns,
    ensure_accounts_login_status_column,
    ensure_accounts_generation_columns,
    ensure_accounts_offer_columns,
    ensure_accounts_proxy_binding_columns,
    ensure_accounts_browser_profile_columns,
    ensure_content_generation_jobs_table,
)
import logging
from logging.handlers import TimedRotatingFileHandler

# 配置日志
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        TimedRotatingFileHandler(
            filename=settings.logs_dir / "app.log",
            when="midnight",
            interval=1,
            backupCount=2,
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("Dreamina Auto Register 启动中...")

    # 确保目录存在
    ensure_directories()

    # 初始化数据库
    await init_db()
    logger.info("数据库初始化完成")

    # 轻量迁移：确保 proxy_nodes 外部代理字段存在
    await ensure_proxy_node_columns()

    # 轻量迁移：确保 accounts 登录状态字段存在
    await ensure_accounts_login_status_column()

    # 轻量迁移：确保 task_records.email_source 字段存在（Outlook 模式支持）
    from app.services.db_migration import ensure_task_records_email_source_column

    await ensure_task_records_email_source_column()
    from app.services.db_migration import ensure_task_records_concurrency_column
    await ensure_task_records_concurrency_column()
    from app.services.db_migration import ensure_outlook_mailbox_strategy_columns
    await ensure_outlook_mailbox_strategy_columns()

    # 轻量迁移：确保内容生成字段和表存在
    await ensure_accounts_generation_columns()
    await ensure_accounts_offer_columns()
    await ensure_accounts_proxy_binding_columns()
    await ensure_accounts_browser_profile_columns()
    await ensure_content_generation_jobs_table()

    # 初始化 WebSocket 日志转发
    from app.api.routers.websocket import WebSocketLogHandler

    root_logger = logging.getLogger()
    ws_handler = WebSocketLogHandler()
    ws_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    root_logger.addHandler(ws_handler)
    logger.info("WebSocket 日志转发已启用")

    # 初始化注册引擎
    try:
        await register_engine.initialize()
        logger.info("注册引擎初始化完成")
    except Exception as e:
        logger.error(f"注册引擎初始化失败: {e}")
        logger.warning("注册功能暂不可用，但不影响其他模块。")

    # 检查 Cloudflare KV 配置
    if cf_kv_client.is_configured:
        kv_test = await cf_kv_client.test_connection()
        if kv_test["success"]:
            logger.info("Cloudflare KV 连接正常")
        else:
            logger.warning(f"Cloudflare KV 连接失败: {kv_test.get('error')}")
    else:
        logger.warning("Cloudflare KV 未配置")

    # 从数据库加载代理池。注册链路直接连接节点，不经过 Clash/Mihomo。
    from app.services.proxy_pool import proxy_pool
    from app.core.database import async_session_factory

    await proxy_pool.reload_from_database()

    # 启动任务调度器
    await task_scheduler.start()

    # 启动内容生成队列
    from app.services.content_generation import content_generation_service

    await content_generation_service.start()

    # 恢复重启前未完成的任务
    try:
        from sqlalchemy import select
        from app.models import TaskRecord

        async with async_session_factory() as db:
            stmt = select(TaskRecord).where(
                TaskRecord.status.in_(["queued", "running"])
            )
            pending_tasks = (await db.execute(stmt)).scalars().all()
            for task in pending_tasks:
                old_status = task.status
                task.status = "failed"
                task.completed_at = datetime.utcnow()
                task.current_step = f"Interrupted by system restart (was {old_status})"
                logger.info(f"清理残留任务 {task.task_id}: {old_status} -> failed")
            await db.commit()
            if pending_tasks:
                logger.info(f"已清理 {len(pending_tasks)} 个由于系统重启而中断的任务")
    except Exception as e:
        logger.error(f"恢复中断任务失败: {e}")

    # 清理注册失败的账号记录（无 session_id，无保留价值）
    try:
        from app.models import Account as AccountModel

        async with async_session_factory() as db:
            from sqlalchemy import delete as sql_delete

            result = await db.execute(
                sql_delete(AccountModel).where(AccountModel.status == "failed")
            )
            if result.rowcount > 0:
                await db.commit()
                logger.info(f"已清理 {result.rowcount} 个注册失败的账号记录")
    except Exception as e:
        logger.error(f"清理失败账号记录时出错: {e}")

    logger.info("Dreamina Auto Register 启动完成!")

    yield

    # 关闭时
    logger.info("Dreamina Auto Register 关闭中...")
    await task_scheduler.stop()
    from app.services.content_generation import content_generation_service

    await content_generation_service.stop()
    await register_engine.shutdown()
    await cf_kv_client.close()
    logger.info("Dreamina Auto Register 已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title=settings.app_name,
    description="Dreamina 国际版自动注册系统 API",
    version="2.2.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本地开发允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册全局异常处理
app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(StarletteHTTPException, global_exception_handler)
app.add_exception_handler(RequestValidationError, global_exception_handler)

# 静态文件（截图）已停用

# 静态文件（缩略图）
thumbnails_dir = settings.data_dir / "thumbnails"
thumbnails_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/thumbnails",
    StaticFiles(directory=str(thumbnails_dir.absolute())),
    name="thumbnails",
)

# 静态文件（本地输出原图/视频）
outputs_dir = settings.data_dir / "outputs"
outputs_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/outputs", StaticFiles(directory=str(outputs_dir.absolute())), name="outputs"
)


# =========================
# 导入并注册路由
# =========================
from app.api.routers import (
    tasks,
    accounts,
    proxies,
    domains,
    settings as settings_router,
    websocket,
    dashboard,
    content_generation,
)
from app.api.routers import outlook_mailboxes

app.include_router(tasks.router, prefix="/api/tasks", tags=["任务管理"])
app.include_router(accounts.router, prefix="/api/accounts", tags=["账号管理"])
app.include_router(proxies.router, prefix="/api/proxies", tags=["代理管理"])
app.include_router(domains.router, prefix="/api/domains", tags=["域名管理"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["系统设置"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["仪表盘"])
app.include_router(websocket.router, tags=["WebSocket"])
app.include_router(
    outlook_mailboxes.router, prefix="/api/outlook-mailboxes", tags=["Outlook 邮箱"]
)
app.include_router(content_generation.router, prefix="/api/content", tags=["内容生成"])


# HEALTH CHECK REMOVED - SERVED BY SPA


@app.get("/api/health", tags=["健康检查"])
async def health_check():
    """详细健康检查"""
    from app.services.proxy_pool import proxy_pool

    kv_status = cf_kv_client.is_configured
    pool_status = await proxy_pool.get_detailed_status()
    from app.services.jimeng_api import JimengClient

    jimeng_api_status = await JimengClient.service_available()

    return {
        "status": "healthy" if jimeng_api_status else "degraded",
        "services": {
            "proxy_pool": pool_status,
            "jimeng_api": "healthy" if jimeng_api_status else "unavailable",
            "cloudflare_kv": "configured" if kv_status else "not_configured",
        },
    }


# 静态文件服务配置
# 1. 挂载 assets 目录 (JS/CSS)
from app.core import get_resource_path

frontend_dist = get_resource_path("frontend/dist")
assets_path = frontend_dist / "assets"

if assets_path.exists():
    app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")
    logger.info(f"已挂载前端静态资源: {assets_path}")


# 2. 挂载入口 HTML 并支持 SPA 路由
@app.get("/{path:path}")
async def serve_spa(path: str):
    # 排除 API 路由
    if path.startswith("api/"):
        raise StarletteHTTPException(status_code=404)

    index_file = frontend_dist / "index.html"
    if index_file.exists():
        from fastapi.responses import FileResponse

        return FileResponse(index_file)

    return {
        "detail": "Frontend assets not found. Please run 'npm run build' in frontend directory."
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app", host="0.0.0.0", port=8005, reload=settings.debug, loop="asyncio"
    )
