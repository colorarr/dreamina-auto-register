
"""
Dreamina Auto Register - 任务管理服务
"""
from typing import List, Optional
import json
import uuid
import random
import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.models import TaskRecord, EmailDomain, ProxyNode, Account
from app.models.outlook_mailbox import OutlookMailbox
from app.schemas import TaskCreate
from app.services.task_scheduler import task_scheduler
from app.services.random_generator import random_generator
from app.api.routers.websocket import send_log

logger = logging.getLogger(__name__)

class TaskService:
    """任务管理服务"""
    
    @staticmethod
    async def create_task(db: AsyncSession, task_data: TaskCreate) -> TaskRecord:
        """
        创建并初始化批量注册任务
        支持两种邮件来源模式:
          - cloudflare: 按域名+前缀自动生成邮箱，通过 CF KV 获取验证码
          - outlook: 从邮箱池分配 Outlook 邮箱，通过 OutlookManager API 获取验证码
          - generic_api: 从邮箱池分配通用 API 邮箱，通过每条邮箱绑定的 URL 获取验证码
        """
        email_source = task_data.email_source or "cloudflare"
        
        # ===== Cloudflare 模式：验证域名 =====
        if email_source == "cloudflare":
            # Worker 模式：从配置读取域名，不需要数据库中的域名记录
            from app.core.config import settings as app_settings
            if app_settings.cf_worker_domain:
                # Worker 模式，域名来自 CF_EMAIL_DOMAINS 配置
                worker_domains = [d.strip() for d in (app_settings.cf_email_domains or "").split(",") if d.strip()]
                if not worker_domains:
                    raise HTTPException(status_code=400, detail="Worker 模式需要在设置中配置邮箱域名 (CF_EMAIL_DOMAINS)")
                domains = []  # 不需要数据库域名
            elif task_data.domain_ids:
                # 传统模式：从数据库读取域名
                stmt = select(EmailDomain).where(EmailDomain.id.in_(task_data.domain_ids))
                result = await db.execute(stmt)
                domains = result.scalars().all()
                
                if len(domains) != len(task_data.domain_ids):
                    raise HTTPException(status_code=400, detail="部分域名不存在")
                
                unavailable_domains = [d.domain for d in domains if not d.is_available]
                if unavailable_domains:
                    raise HTTPException(
                        status_code=400,
                        detail=f"以下域名不可用: {', '.join(unavailable_domains)}"
                    )
            else:
                raise HTTPException(status_code=400, detail="cloudflare 模式必须配置 Worker 或提供 domain_ids")
        else:
            domains = []

        # ===== Outlook 模式：预取可用邮箱 =====
        outlook_mailboxes = []
        if email_source in {"outlook", "generic_api"}:
            stmt = select(OutlookMailbox).where(
                OutlookMailbox.is_enabled == True,
                OutlookMailbox.provider_type == email_source,
            ).order_by(OutlookMailbox.last_used_at.asc().nullsfirst())
            result = await db.execute(stmt)
            outlook_mailboxes = result.scalars().all()
            if len(outlook_mailboxes) < task_data.total_count:
                label = "Outlook" if email_source == "outlook" else "通用 API"
                raise HTTPException(
                    status_code=400,
                    detail=f"可用 {label} 邮箱不足，需要 {task_data.total_count} 个，当前可用 {len(outlook_mailboxes)} 个"
                )

        # ===== 获取代理资源 =====
        requested_region = task_data.proxy_region.strip().upper()
        proxy_stmt = select(ProxyNode).where(
            ProxyNode.is_enabled == True,
            ProxyNode.is_healthy == True,
            func.upper(ProxyNode.region_tag) == requested_region,
        ).order_by(ProxyNode.usage_count.asc())
        proxy_result = await db.execute(proxy_stmt)
        active_proxies = proxy_result.scalars().all()

        if not active_proxies:
            raise HTTPException(status_code=400, detail=f"代理池中没有可用的 {requested_region} 代理")

        # 排除已被进行中任务预占的代理，每个账号分配独立代理。
        busy_result = await db.execute(
            select(TaskRecord.assigned_proxy_name).where(
                TaskRecord.status.in_(["created", "queued", "running", "paused"]),
                TaskRecord.assigned_proxy_name.isnot(None),
            )
        )
        busy_names = {name for name in busy_result.scalars().all() if name}
        all_proxies = [p for p in active_proxies if p.name not in busy_names]

        if len(all_proxies) < task_data.total_count:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"IP 不足，任务已停止：{requested_region} 需要 "
                    f"{task_data.total_count} 个独立 IP，当前仅有 {len(all_proxies)} 个可用"
                ),
            )

        # 预分配不重复的代理；不再在循环中 random.choice 导致重复。
        if task_data.proxy_strategy == "random":
            allocated_proxies = random.sample(all_proxies, task_data.total_count)
        else:
            allocated_proxies = all_proxies[: task_data.total_count]

        effective_concurrency = min(50, max(1, task_data.concurrency), task_data.total_count)

        created_tasks = []
        batch_id = str(uuid.uuid4())
        batch_name = f"注册批次 - {task_data.total_count}个账号"

        # ===== 循环创建任务 =====
        for i in range(task_data.total_count):
            # 3.1 决定邮箱
            assigned_email = None
            if email_source in {"outlook", "generic_api"}:
                mailbox = outlook_mailboxes[i]
                assigned_email = mailbox.email
                # 标记为已使用（后续注册成功后会再次禁用），更新使用时间
                mailbox.last_used_at = datetime.utcnow()
            elif email_source == "cloudflare" and app_settings.cf_worker_domain:
                # Worker 模式：邮箱由 register_engine 动态创建，这里先用占位符
                domain = random.choice(worker_domains)
                pattern = task_data.email_prefix_pattern
                prefix = random_generator.generate_email_local_part(pattern)
                assigned_email = f"{prefix}@{domain}"
            elif domains:
                domain = domains[i % len(domains)].domain
                pattern = task_data.email_prefix_pattern
                prefix = random_generator.generate_email_local_part(pattern)
                assigned_email = f"{prefix}@{domain}"

            # 3.2 分配代理信息
            assigned_proxy_region = requested_region
            assigned_proxy_name = None

            if allocated_proxies:
                proxy = allocated_proxies[i]

                assigned_proxy_name = proxy.name
                assigned_proxy_region = proxy.region_tag
                # Fallback region detection
                if not assigned_proxy_region and proxy.name:
                    name = proxy.name
                    if '🇯🇵' in name or '日本' in name: assigned_proxy_region = '日本'
                    elif '🇺🇸' in name or '美国' in name: assigned_proxy_region = '美国'
                    elif '🇸🇬' in name or '新加坡' in name: assigned_proxy_region = '新加坡'
                    elif '🇭🇰' in name or '香港' in name: assigned_proxy_region = '香港'
                    elif '🇹🇼' in name or '台湾' in name: assigned_proxy_region = '台湾'
                    elif '🇰🇷' in name or '韩国' in name: assigned_proxy_region = '韩国'
                    elif '🇬🇧' in name or '英国' in name: assigned_proxy_region = '英国'
                    elif '🇩🇪' in name or '德国' in name: assigned_proxy_region = '德国'
                    elif '🇫🇷' in name or '法国' in name: assigned_proxy_region = '法国'

            # 3.3 创建记录
            task = TaskRecord(
                task_id=str(uuid.uuid4()),
                batch_id=batch_id,
                batch_name=batch_name,
                total_count=1,
                domain_mode=task_data.domain_mode,
                domain_ids=json.dumps(task_data.domain_ids or []),
                proxy_strategy=task_data.proxy_strategy,
                email_prefix_pattern=task_data.email_prefix_pattern,
                email_source=email_source,
                assigned_email=assigned_email,
                assigned_proxy_region=assigned_proxy_region,
                assigned_proxy_name=assigned_proxy_name,
                status="queued",
                max_retries=task_data.max_retries,
                concurrency=effective_concurrency,
            )

            db.add(task)
            created_tasks.append(task)

        await db.commit()

        # 4. 提交调度
        # 调度器工作线程可动态扩容，全局硬上限 50。
        from app.core.config import settings
        settings.max_concurrency = min(
            50, max(settings.max_concurrency or 1, effective_concurrency)
        )
        if not task_scheduler.running:
            await task_scheduler.start()
        else:
            await task_scheduler.start()

        for task in created_tasks:
            await db.refresh(task)
            await send_log("INFO", f"任务 {task.task_id} ({task.assigned_email}) 已创建并加入队列 [来源: {email_source}]", task_id=task.task_id)
            await task_scheduler.submit_batch(task)

        return created_tasks[-1] if created_tasks else None

    @staticmethod
    async def get_tasks(
        db: AsyncSession, 
        status: Optional[str] = None, 
        page: int = 1, 
        page_size: int = 20
    ) -> List[TaskRecord]:
        """获取任务列表"""
        stmt = select(TaskRecord).order_by(TaskRecord.created_at.desc(), TaskRecord.id.asc())
        
        if status:
            stmt = stmt.where(TaskRecord.status == status)
        
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_task_by_id(db: AsyncSession, task_id: str) -> Optional[TaskRecord]:
        """获取单个任务详情"""
        stmt = select(TaskRecord).where(TaskRecord.task_id == task_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def start_task(db: AsyncSession, task_id: str) -> TaskRecord:
        """启动任务"""
        task = await TaskService.get_task_by_id(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        if task.status == "running":
            raise HTTPException(status_code=400, detail=f"任务状态 {task.status} 无法启动")
        
        task.status = "running"
        await db.commit()
        
        if not task_scheduler.running:
            await task_scheduler.start()
            
        await task_scheduler.submit_batch(task)
        return task

    @staticmethod
    async def pause_task(db: AsyncSession, task_id: str) -> TaskRecord:
        """暂停任务"""
        task = await TaskService.get_task_by_id(db, task_id)
        if not task:
             raise HTTPException(status_code=404, detail="任务不存在")
             
        if task.status != "running":
            raise HTTPException(status_code=400, detail="只能暂停运行中的任务")
            
        task.status = "paused"
        await db.commit()
        return task

    @staticmethod
    async def cancel_task(db: AsyncSession, task_id: str) -> TaskRecord:
        """取消任务"""
        task = await TaskService.get_task_by_id(db, task_id)
        if not task:
             raise HTTPException(status_code=404, detail="任务不存在")
             
        if task.status == "completed":
            raise HTTPException(status_code=400, detail="任务已完成，无法取消")
            
        task.status = "cancelled"
        from app.models import Account
        account_stmt = select(Account).where(Account.task_id == task_id)
        account = (await db.execute(account_stmt)).scalar_one_or_none()
        if account and account.status != "active":
            account.status = "failed"
            account.failure_reason = "注册任务已取消"
            if task.assigned_proxy_region:
                account.region = task.assigned_proxy_region.lower()
        await db.commit()
        from app.api.routers.websocket import send_log
        await send_log("WARNING", "注册任务已由用户取消", task_id=task_id)
        return task
        
    @staticmethod
    async def delete_task(db: AsyncSession, task_id: str):
        """删除任务"""
        task = await TaskService.get_task_by_id(db, task_id)
        if not task:
             raise HTTPException(status_code=404, detail="任务不存在")
             
        if task.status == "running":
            raise HTTPException(status_code=400, detail="运行中的任务无法删除")
            
        await db.delete(task)
        await db.commit()

    @staticmethod
    async def get_batches(db: AsyncSession) -> list:
        """获取所有批次的汇总信息"""
        from sqlalchemy import func, case

        stmt = select(
            TaskRecord.batch_id,
            func.max(TaskRecord.batch_name).label("batch_name"),
            func.count(TaskRecord.id).label("total_tasks"),
            func.sum(TaskRecord.success_count).label("success_count"),
            func.sum(TaskRecord.failure_count).label("failure_count"),
            func.min(TaskRecord.created_at).label("created_at"),
            # 批次状态：有 running -> running; 全 completed -> completed; 有 failed -> failed; 否则 -> created
            case(
                (func.sum(case((TaskRecord.status == "running", 1), else_=0)) > 0, "running"),
                (func.sum(case((TaskRecord.status == "paused", 1), else_=0)) > 0, "paused"),
                (func.sum(case((TaskRecord.status.in_(["created", "queued"]), 1), else_=0)) > 0, "running"),
                (func.count(TaskRecord.id) == func.sum(case((TaskRecord.status == "completed", 1), else_=0)), "completed"),
                (func.sum(case((TaskRecord.status == "failed", 1), else_=0)) > 0, "failed"),
                else_="completed"
            ).label("status"),
        ).where(
            TaskRecord.batch_id.isnot(None)
        ).group_by(
            TaskRecord.batch_id
        ).order_by(
            func.min(TaskRecord.created_at).desc()
        )

        result = await db.execute(stmt)
        rows = result.all()

        batches = []
        for row in rows:
            total = row.total_tasks or 0
            success = row.success_count or 0
            failure = row.failure_count or 0
            done = success + failure
            progress = (done / total * 100) if total > 0 else 0

            batches.append({
                "batch_id": row.batch_id,
                "batch_name": row.batch_name or f"批次 {row.batch_id[:8]}",
                "total_tasks": total,
                "success_count": success,
                "failure_count": failure,
                "progress": min(progress, 100.0),
                "status": row.status,
                "created_at": row.created_at,
            })
        return batches

    @staticmethod
    async def get_batch_tasks(db: AsyncSession, batch_id: str) -> List[TaskRecord]:
        """获取指定批次下的所有子任务"""
        stmt = select(TaskRecord).where(
            TaskRecord.batch_id == batch_id
        ).order_by(TaskRecord.id.asc())
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def delete_batch(db: AsyncSession, batch_id: str):
        """删除整个批次（不删除运行中的任务）"""
        from sqlalchemy import delete as sql_delete
        stmt = sql_delete(TaskRecord).where(
            TaskRecord.batch_id == batch_id,
            TaskRecord.status.notin_(["running"])
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount
