"""
Dreamina Auto Register - 任务调度并发管理器
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from uuid import uuid4

from app.models import TaskRecord
from app.services.proxy_pool import proxy_pool, ProxyConfig
from app.services.register_engine import register_engine
from app.services.clash_manager import clash_manager, ClashNode
from app.core.database import async_session_factory
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """内部工作任务"""
    job_id: str
    parent_task_id: str
    email_params: Optional[Dict] = None  # 指定邮箱参数，用于重新入队
    proxy_strategy: str = "least_used"
    proxy_region: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    bound_exit_ip: Optional[str] = None
    batch_id: Optional[str] = None
    concurrency: int = 1
    preferred_proxy_name: Optional[str] = None


from app.core.config import settings

class TaskScheduler:
    """并发调度器"""
    
    def __init__(self, max_concurrency: Optional[int] = None):
        self.max_concurrency = max_concurrency or settings.max_concurrency
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.workers: List[asyncio.Task] = []
        self.running = False
        
        # 统计数据
        self.active_workers = 0
        self.completed_jobs = 0
        self.failed_jobs = 0

        # FlClash 节点轮换
        self._clash_nodes: List[ClashNode] = []  # 可用节点列表
        self._clash_node_index: int = 0  # 当前节点索引
        self._round_counter: int = 0  # 本轮已完成的任务数
        self._rotation_lock = asyncio.Lock()  # 轮换锁
        self._current_node_name: Optional[str] = None  # 当前使用的节点名
        self._batch_semaphores: Dict[str, asyncio.Semaphore] = {}

    async def _probe_proxy_exit(self, proxy: ProxyConfig) -> tuple[str, str, str]:
        """通过当前代理获取出口 IP/国家，用于一号一 IP 强绑定。"""
        import httpx

        client_kwargs: Dict[str, Any] = {
            "timeout": 20.0,
            "verify": False,
            "trust_env": False,
        }
        if proxy.protocol.lower().startswith("socks"):
            from httpx_socks import AsyncProxyTransport

            client_kwargs["transport"] = AsyncProxyTransport.from_url(proxy.url)
        else:
            client_kwargs["proxy"] = proxy.url

        last_error = ""
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(**client_kwargs) as client:
                    response = await client.get(
                        "https://cp.cloudflare.com/cdn-cgi/trace",
                        follow_redirects=True,
                    )
                if response.status_code == 200:
                    values = dict(
                        line.split("=", 1)
                        for line in response.text.splitlines()
                        if "=" in line
                    )
                    exit_ip = values.get("ip", "").strip()
                    country = values.get("loc", "").strip().upper()
                    if exit_ip and country:
                        asn = ""
                        try:
                            async with httpx.AsyncClient(
                                timeout=15.0, verify=False, trust_env=False
                            ) as asn_client:
                                asn_response = await asn_client.get(
                                    f"http://ip-api.com/json/{exit_ip}",
                                    params={
                                        "fields": "status,as,asname,isp,org,query"
                                    },
                                )
                            if asn_response.status_code == 200:
                                asn_data = asn_response.json()
                                if asn_data.get("status") == "success":
                                    asn = str(
                                        asn_data.get("as")
                                        or asn_data.get("asname")
                                        or asn_data.get("isp")
                                        or ""
                                    ).strip()
                        except Exception as asn_exc:
                            logger.warning("ASN 查询失败 [%s]: %s", exit_ip, asn_exc)
                        return exit_ip, country, asn
                last_error = f"HTTP {response.status_code}"
            except Exception as exc:
                last_error = str(exc)
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"代理出口 IP 探测失败: {last_error}")
    
    async def start(self):
        """启动调度器"""
        # 每次启动/提交任务时重新读取最新并发设置
        self.max_concurrency = min(50, max(1, settings.max_concurrency or 1))

        if self.running:
            # 已运行但并发数变了：动态增加 Worker
            current_workers = len([w for w in self.workers if not w.done()])
            if current_workers < self.max_concurrency:
                for i in range(current_workers, self.max_concurrency):
                    t = asyncio.create_task(self._worker_loop(i))
                    self.workers.append(t)
                logger.info(f"动态扩展 Worker: {current_workers} -> {self.max_concurrency}")
            return
            
        self.running = True
        logger.info(f"启动任务调度器 (并发数: {self.max_concurrency})")
        
        # 启动 Worker
        for i in range(self.max_concurrency):
            t = asyncio.create_task(self._worker_loop(i))
            self.workers.append(t)


    async def _init_clash_nodes(self):
        """从 FlClash 9090 API 拉取可用节点并同步到数据库"""
        try:
            connected = await clash_manager.check_connection()
            if not connected:
                logger.warning("FlClash 外部控制器未连接，将使用当前节点不轮换")
                return

            nodes = await clash_manager.get_proxy_group_nodes()
            # 过滤掉信息节点
            skip_keywords = ["流量", "Traffic", "Expire", "到期", "官网", "频道",
                             "群", "重置", "本次", "剩余", "套餐", "网站"]
            filtered_nodes = [n for n in nodes if not any(kw in n.name for kw in skip_keywords)]

            # 即梦国际站支持的地区白名单（基于 jimeng-free-api README 的官方前缀表）
            # 注意：US 不支持国际版视频接口，但支持国内版图片生成，按需决定是否纳入
            SUPPORTED_REGION_CODES = [
                "SG", "HK", "JP", "IT", "AL", "AZ", "BH", "CA",
                "CL", "DE", "GB", "GY", "IL", "IQ", "JO", "KG",
                "OM", "PK", "PT", "SA", "SE", "TR", "TZ", "UZ",
                "VE", "XK", "KR", "TW",
            ]
            # 节点名称中常见的地区关键词映射
            SUPPORTED_REGION_KEYWORDS = [
                # 中文名称
                "新加坡", "香港", "日本", "意大利", "德国", "英国", "加拿大",
                "土耳其", "瑞典", "葡萄牙", "沙特", "韩国", "台湾",
                "智利", "以色列", "巴林", "约旦", "巴基斯坦",
                # 英文名称
                "Singapore", "Hong Kong", "Japan", "Italy", "Germany",
                "United Kingdom", "Canada", "Turkey", "Sweden", "Portugal",
                "Korea", "Taiwan",
            ]
            # 合并：国家代码 + 关键词，统一大写匹配
            ALL_SUPPORTED = [c.upper() for c in SUPPORTED_REGION_CODES] + \
                            [kw.upper() for kw in SUPPORTED_REGION_KEYWORDS]

            def _is_supported_region(node_name: str) -> bool:
                """检查节点名称是否属于即梦支持的地区"""
                name_upper = node_name.upper()
                for kw in ALL_SUPPORTED:
                    if kw in name_upper:
                        return True
                return False

            before_count = len(filtered_nodes)
            filtered_nodes = [n for n in filtered_nodes if _is_supported_region(n.name)]
            skipped_region = before_count - len(filtered_nodes)
            if skipped_region > 0:
                logger.info(f"已排除 {skipped_region} 个不支持地区的节点（仅保留 US/JP/HK/SG/TW/KR）")

            if not filtered_nodes:
                logger.warning("FlClash 没有可用节点，将使用当前节点不轮换")
                return

            # 同步到 proxy_nodes 表（新增/更新）
            from app.models.proxy_node import ProxyNode
            from sqlalchemy import select as sql_select

            async with async_session_factory() as db:
                # 获取数据库中已有的节点
                result = await db.execute(sql_select(ProxyNode).where(ProxyNode.source == "clash"))
                existing_nodes = {n.name: n for n in result.scalars().all()}

                for n in filtered_nodes:
                    last_delay = n.history[-1].get("delay", 0) if n.history else None
                    is_timeout = (last_delay == 0) if last_delay is not None else True

                    if n.name in existing_nodes:
                        # 更新延迟和健康状态
                        node = existing_nodes[n.name]
                        node.latency = last_delay
                        node.is_healthy = not is_timeout
                        node.node_type = n.node_type
                    else:
                        # 新节点 → 插入（默认启用，Timeout的自动禁用）
                        new_node = ProxyNode(
                            name=n.name,
                            node_type=n.node_type,
                            source="clash",
                            is_enabled=not is_timeout,  # Timeout 节点默认禁用
                            is_healthy=not is_timeout,
                            latency=last_delay,
                        )
                        db.add(new_node)

                # 清理：删除数据库中不在过滤列表中的旧 clash 节点（信息节点、不支持地区等）
                valid_names = {n.name for n in filtered_nodes}
                removed_count = 0
                for name, node in existing_nodes.items():
                    if name not in valid_names:
                        await db.delete(node)
                        removed_count += 1
                if removed_count > 0:
                    logger.info(f"已清理 {removed_count} 个无效/不支持的旧节点")

                await db.commit()

                # 重新查询：只取 is_enabled=True 且 is_healthy 的节点
                result = await db.execute(
                    sql_select(ProxyNode).where(
                        ProxyNode.source == "clash",
                        ProxyNode.is_enabled == True,
                    )
                )
                enabled_nodes = result.scalars().all()

            # 构建可用节点列表（按数据库 is_enabled 过滤）
            enabled_names = {n.name for n in enabled_nodes}
            available = [n for n in filtered_nodes if n.name in enabled_names]

            # 对所有启用的节点进行实时延迟测试
            MAX_LATENCY = 300  # 毫秒
            logger.info(f"开始对 {len(available)} 个启用节点进行延迟测试（阈值: {MAX_LATENCY}ms）...")

            async def _test_one(node):
                """测试单个节点延迟"""
                try:
                    latency = await clash_manager.test_node_delay(node.name)
                    return node, latency
                except Exception:
                    return node, None

            # 并发测试所有节点
            tasks = [_test_one(n) for n in available]
            results = await asyncio.gather(*tasks)

            # 过滤：只保留延迟 <= 300ms 的节点
            tested_available = []
            skipped_nodes = []
            for node, latency in results:
                if latency is not None and 0 < latency <= MAX_LATENCY:
                    tested_available.append(node)
                    logger.info(f"  ✓ {node.name} - {latency}ms")
                else:
                    latency_str = f"{latency}ms" if latency else "Timeout"
                    skipped_nodes.append((node.name, latency_str))
                    logger.info(f"  ✗ {node.name} - {latency_str} (跳过)")

            if skipped_nodes:
                logger.info(f"延迟测试完成: {len(tested_available)} 个通过, {len(skipped_nodes)} 个跳过")

            # 更新数据库中的延迟数据
            async with async_session_factory() as db2:
                from sqlalchemy import update as sql_update
                for node, latency in results:
                    is_healthy = latency is not None and 0 < latency <= MAX_LATENCY
                    await db2.execute(
                        sql_update(ProxyNode)
                        .where(ProxyNode.name == node.name, ProxyNode.source == "clash")
                        .values(latency=latency, is_healthy=is_healthy)
                    )
                await db2.commit()

            available = tested_available

            self._clash_nodes = available
            self._clash_node_index = 0
            self._round_counter = 0

            if available:
                first_node = available[0].name
                switched = await clash_manager.switch_node(first_node)
                if switched:
                    self._current_node_name = first_node
                logger.info(
                    f"FlClash 节点轮换已启用: {len(available)} 个可用节点 "
                    f"(总共 {len(filtered_nodes)} 个, "
                    f"{len(filtered_nodes) - len(available)} 个已禁用/Timeout), "
                    f"每 {self.max_concurrency} 个任务轮换一次, "
                    f"当前节点: {first_node}"
                )
                for i, n in enumerate(available):
                    delay = n.history[-1].get("delay", "?") if n.history else "?"
                    logger.info(f"  [{i}] {n.name} ({n.node_type}, {delay}ms)")
            else:
                logger.warning("FlClash 所有节点都被禁用或 Timeout，将使用当前节点不轮换")
        except Exception as e:
            logger.warning(f"FlClash 节点初始化失败: {e}，将使用当前节点不轮换")

    async def _maybe_rotate_node(self):
        """检查是否需要轮换节点（每完成 max_concurrency 个任务后切换）"""
        if not self._clash_nodes:
            return  # 没有节点列表，不轮换

        async with self._rotation_lock:
            self._round_counter += 1
            if self._round_counter >= self.max_concurrency:
                self._round_counter = 0
                self._clash_node_index = (self._clash_node_index + 1) % len(self._clash_nodes)
                next_node = self._clash_nodes[self._clash_node_index]
                logger.info(f"节点轮换: 切换到 [{self._clash_node_index}/{len(self._clash_nodes)}] {next_node.name}")
                switched = await clash_manager.switch_node(next_node.name)
                if switched:
                    self._current_node_name = next_node.name
                else:
                    logger.warning(f"节点切换失败: {next_node.name}，继续使用当前节点")
            
    async def stop(self):
        """停止调度器"""
        self.running = False
        # 发送停止信号
        for _ in self.workers:
            await self.queue.put(None)
        
        # 等待所有 Worker 完成当前任务
        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        logger.info("任务调度器已停止")
    
    async def submit_batch(self, task_record: TaskRecord):
        """提交批次任务"""
        total = task_record.total_count
        logger.info(f"提交批次任务 {task_record.task_id}, 总数: {total}")
        
        # 为该任务生成 N 个 Job
        # 这里其实是一个简化，我们假设 DB 里已经有一个 TaskRecord
        # 但我们需要追踪 100 个具体的注册动作
        # 实际情况可能是：TaskRecord 是一个“批次”，具体的“注册”动作在内存中生成 Job
        
        for _ in range(total):
            job = Job(
                job_id=str(uuid4()),
                parent_task_id=task_record.task_id,
                proxy_strategy=task_record.proxy_strategy or "least_used",
                proxy_region=task_record.assigned_proxy_region,
                max_retries=task_record.max_retries,
                batch_id=task_record.batch_id,
                concurrency=min(50, max(1, task_record.concurrency or 1)),
                preferred_proxy_name=task_record.assigned_proxy_name,
            )
            await self.queue.put(job)
            
    async def _worker_loop(self, worker_id: int):
        """工作线程循环"""
        import random
        from app.core.config import settings
        logger.debug(f"Worker {worker_id} started")
        
        while self.running:
            try:
                # 获取任务 (带超时，以便响应停止信号)
                try:
                    job = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                # 停止信号
                if job is None:
                    break

                batch_key = job.batch_id or job.parent_task_id
                batch_semaphore = self._batch_semaphores.setdefault(
                    batch_key,
                    asyncio.Semaphore(min(50, max(1, job.concurrency))),
                )
                await batch_semaphore.acquire()
                self.active_workers += 1
                logger.info(f"Worker {worker_id} 开始处理 Job {job.job_id} (Task {job.parent_task_id})")
                from app.api.routers.websocket import send_log
                await send_log("INFO", f"开始注册，目标地区 {job.proxy_region or '自动'}，尝试 {job.retry_count + 1}/{job.max_retries + 1}", task_id=job.parent_task_id)
                
                proxy = None
                retry_scheduled = False
                try:
                    # 开启数据库会话
                    async with async_session_factory() as db:
                    # 1. 申请代理
                        pool_status = await proxy_pool.get_detailed_status()
                        proxy = await proxy_pool.acquire_proxy(
                            usage_id=job.job_id,
                            strategy=job.proxy_strategy,
                            region=job.proxy_region,
                            preferred_name=job.preferred_proxy_name,
                        )
                        if not proxy:
                            message = (
                                f"IP 不足：地区 {job.proxy_region} 没有可用的独立 IP，"
                                f"批次已暂停 (pool={pool_status})"
                            )
                            logger.error(message)
                            async with async_session_factory() as stop_db:
                                stmt = update(TaskRecord).where(
                                    TaskRecord.batch_id == job.batch_id,
                                    TaskRecord.status.in_(["queued", "running", "created"]),
                                ).values(status="paused", current_step=message[:500])
                                await stop_db.execute(stmt)
                                await stop_db.commit()
                            await send_log("ERROR", message, task_id=job.parent_task_id)
                            raise Exception("IP_POOL_EXHAUSTED")

                        # 2. 检查任务是否已被暂停或取消
                        stmt = select(TaskRecord.status).where(TaskRecord.task_id == job.parent_task_id)
                        res = await db.execute(stmt)
                        current_status = res.scalar_one_or_none()
                        
                        if current_status in ["paused", "cancelled"]:
                            logger.info(f"Job {job.job_id} 对应的任务已 {current_status}，跳过执行")
                            continue

                        # 一个账号从首次请求到所有重试均锁定同一出口 IP。
                        exit_ip, exit_country, exit_asn = await self._probe_proxy_exit(proxy)
                        if job.bound_exit_ip is None:
                            job.bound_exit_ip = exit_ip
                        elif job.bound_exit_ip != exit_ip:
                            raise RuntimeError(
                                f"固定代理出口发生变化: {job.bound_exit_ip} -> {exit_ip}"
                            )
                        proxy.exit_ip = exit_ip
                        proxy.exit_asn = exit_asn

                        # 地区必须以当前代理的真实出口为准，不能继续沿用导入时、
                        # 上一次会话或凭据文本中的旧标签。
                        detected_country = (exit_country or "UN").strip().upper()
                        proxy.region_tag = detected_country
                        if proxy.node_id:
                            from app.models import ProxyNode

                            await db.execute(
                                update(ProxyNode)
                                .where(ProxyNode.id == proxy.node_id)
                                .values(region_tag=detected_country)
                            )
                            await db.commit()

                        requested_country = (job.proxy_region or "").strip().upper()
                        if (
                            requested_country
                            and requested_country != "UN"
                            and detected_country != requested_country
                        ):
                            message = (
                                f"代理出口地区不匹配：任务要求 {requested_country}，"
                                f"实际检测为 {detected_country} ({exit_ip})；任务已暂停"
                            )
                            logger.error(message)
                            await db.execute(
                                update(TaskRecord)
                                .where(TaskRecord.task_id == job.parent_task_id)
                                .values(status="paused", current_step=message[:500])
                            )
                            await db.commit()
                            await send_log(
                                "ERROR", message, task_id=job.parent_task_id
                            )
                            continue

                        from app.models import Account

                        occupied = (
                            await db.execute(
                                select(Account).where(Account.registration_ip == exit_ip)
                            )
                        ).scalar_one_or_none()
                        if occupied:
                            assigned_email = (
                                await db.execute(
                                    select(TaskRecord.assigned_email).where(
                                        TaskRecord.task_id == job.parent_task_id
                                    )
                                )
                            ).scalar_one_or_none()
                            if occupied.email != assigned_email:
                                raise RuntimeError(
                                    f"出口 IP {exit_ip} 已绑定账号 {occupied.email}"
                                )
                        logger.info(
                            "Job %s 锁定出口 IP: %s (%s, %s)",
                            job.job_id,
                            exit_ip,
                            exit_country,
                            exit_asn or "ASN unknown",
                        )

                        # 3. 更新任务状态为处理中并记录代理信息
                        await self._update_task_start(db, job.parent_task_id, proxy)

                        # 4. 执行注册
                        try:
                            result = await register_engine.execute_with_proxy(
                                 db=db,
                                 task_id=job.parent_task_id,
                                 proxy_config=proxy
                            )
                        except Exception as e:
                            # 识别并处理注册引擎抛出的中断异常 (如果是嵌套异常)
                            from app.services.register_engine import TaskInterruptedError
                            if isinstance(e, TaskInterruptedError) or "Task is cancelled" in str(e) or "Task is paused" in str(e):
                                logger.warning(f"Worker {worker_id}: 检测到任务 {job.parent_task_id} 中断信号，退出 Job")
                                continue
                            raise # 抛出其他异常按原有流程处理
                          
                        if result["success"]:
                            self.completed_jobs += 1
                            # 一号一代理：注册成功即永久退役该代理。
                            proxy.is_enabled = False
                            if proxy.node_id:
                                from app.models import ProxyNode

                                await db.execute(
                                    update(ProxyNode)
                                    .where(ProxyNode.id == proxy.node_id)
                                    .values(
                                        is_enabled=False,
                                        usage_count=proxy.usage_count,
                                    )
                                )
                                await db.commit()
                            detected_region = result.get("detected_region")
                            if detected_region:
                                await db.execute(
                                    update(TaskRecord)
                                    .where(TaskRecord.task_id == job.parent_task_id)
                                    .values(assigned_proxy_region=str(detected_region).upper())
                                )
                                await db.commit()
                            await send_log("SUCCESS", "注册成功，账号与会话已保存", task_id=job.parent_task_id)
                            await self._update_task_progress(db, job.parent_task_id, success=True)
                        elif result.get("proxy_error"):
                            # 代理故障也不换 IP；只允许原代理原 IP 重试。
                            if job.retry_count < job.max_retries:
                                job.retry_count += 1
                                retry_scheduled = True
                                await send_log(
                                    "WARNING",
                                    f"代理连接异常，保持原 IP {job.bound_exit_ip} 重试（{job.retry_count}/{job.max_retries}）",
                                    task_id=job.parent_task_id,
                                )
                                await self.queue.put(job)
                            else:
                                await send_log(
                                    "ERROR",
                                    f"固定 IP {job.bound_exit_ip} 连接失败，已终止该账号注册",
                                    task_id=job.parent_task_id,
                                )
                                await self._update_task_progress(db, job.parent_task_id, success=False)
                        else:
                            error_detail = result.get("error", "Unknown error")
                            
                            # 处理中断导致的 failure
                            if "Task is" in error_detail:
                                logger.info(f"Job {job.job_id} 由于任务状态改变而提前终止")
                                continue

                            self.failed_jobs += 1
                            if job.retry_count < job.max_retries:
                                # 重试前检查任务状态，防止用户已停止任务但系统仍在重试
                                stmt = select(TaskRecord.status).where(TaskRecord.task_id == job.parent_task_id)
                                res_status = await db.execute(stmt)
                                task_current_status = res_status.scalar_one_or_none()
                                
                                if task_current_status in ["paused", "cancelled"]:
                                    logger.info(f"Job {job.job_id} 失败且任务处于 {task_current_status} 状态，放弃重试")
                                    await self._update_task_progress(db, job.parent_task_id, success=False)
                                    continue

                                # 还有重试机会 → 撤回失败计数，重新入队
                                self.failed_jobs -= 1
                                job.retry_count += 1
                                logger.info(f"Job {job.job_id} 失败 [{error_detail}]，尝试重试 ({job.retry_count}/{job.max_retries})")
                                await send_log("WARNING", f"本次注册失败：{str(error_detail)[:500]}；准备第 {job.retry_count + 1} 次尝试", task_id=job.parent_task_id)

                                # Update TaskRecord retry_count in DB
                                try:
                                    stmt = (
                                        update(TaskRecord)
                                        .where(TaskRecord.task_id == job.parent_task_id)
                                        .values(
                                            retry_count=job.retry_count,
                                            current_step=f"Retrying ({job.retry_count}/{job.max_retries})...",
                                            status="running" # Ensure status is running
                                        )
                                    )
                                    await db.execute(stmt)
                                    await db.commit()
                                except Exception as e:
                                    logger.error(f"Failed to update retry count for task {job.parent_task_id}: {e}")

                                await self.queue.put(job)
                                retry_scheduled = True
                            else:
                                logger.error(f"Job {job.job_id} 彻底失败: {error_detail}")
                                await send_log("ERROR", f"注册最终失败：{str(error_detail)[:1000]}", task_id=job.parent_task_id)
                                # 保存失败原因到 current_step，供前端展示
                                try:
                                    stmt = (
                                        update(TaskRecord)
                                        .where(TaskRecord.task_id == job.parent_task_id)
                                        .values(current_step=str(error_detail)[:500])
                                    )
                                    await db.execute(stmt)
                                    await db.commit()
                                except Exception as e:
                                    logger.error(f"保存失败原因到 current_step 出错: {e}")
                                await self._update_task_progress(db, job.parent_task_id, success=False)

                except Exception as e:
                    if str(e) == "No proxy available":
                        pass # Valid case, already handled logging
                    else:
                        logger.error(f"Worker {worker_id} 执行异常: {e}")
                        self.failed_jobs += 1

                finally:
                    # 4. 释放代理
                    if proxy:
                        await proxy_pool.release_proxy(proxy)
                    if not retry_scheduled:
                        await proxy_pool.release_reservation(job.job_id)
                    
                    self.active_workers -= 1
                    batch_semaphore.release()
                    self.queue.task_done()

                    # 5. 冷却时间 (Cool-down)
                    interval = random.uniform(
                        settings.register_interval_min, 
                        settings.register_interval_max
                    )
                    logger.debug(f"Worker {worker_id} 进入冷却: {interval:.2f}s")
                    await asyncio.sleep(interval)
                    
            except Exception as e:
                 logger.error(f"Worker {worker_id} loop error: {e}")
                 await asyncio.sleep(1.0)

    async def _update_task_start(self, db: AsyncSession, task_id: str, proxy: Optional[ProxyConfig]):
        """任务开始时的状态更新"""
        try:
            stmt = select(TaskRecord).where(TaskRecord.task_id == task_id)
            result = await db.execute(stmt)
            task = result.scalar_one_or_none()
            
            if task:
                task.status = "running"
                task.current_step = "Initializing browser..."
                if proxy:
                    task.assigned_proxy_name = proxy.name
                    # 直接使用 ProxyConfig 上经 IP 检测得到的 region_tag
                    if proxy.region_tag and proxy.region_tag != "UN":
                        task.assigned_proxy_region = proxy.region_tag
                    elif proxy.group and proxy.group not in ("default", "external"):
                        task.assigned_proxy_region = proxy.group
                else:
                    task.assigned_proxy_name = "Direct / No Proxy"
                await db.commit()
        except Exception as e:
            logger.error(f"更新任务开始状态失败: {e}")

    async def _update_task_progress(self, db: AsyncSession, task_id: str, success: bool):
        """原子更新数据库进度"""
        try:
            # 1. Atomic Increment via SQL
            if success:
                stmt = (
                    update(TaskRecord)
                    .where(TaskRecord.task_id == task_id)
                    .values(success_count=TaskRecord.success_count + 1)
                    .execution_options(synchronize_session="fetch")
                )
            else:
                stmt = (
                    update(TaskRecord)
                    .where(TaskRecord.task_id == task_id)
                    .values(failure_count=TaskRecord.failure_count + 1)
                    .execution_options(synchronize_session="fetch")
                )
            await db.execute(stmt)
            
            # 2. Check Status (in same transaction)
            q = select(TaskRecord).where(TaskRecord.task_id == task_id)
            result = await db.execute(q)
            task = result.scalar_one_or_none()
            
            if task:
                total = task.total_count
                current = task.success_count + task.failure_count
                
                # Update status if finished
                if current >= total:
                    if bool(task.success_count >= total):
                        if str(getattr(task, "status", "")) != "completed":
                            task.status = "completed"
                            task.completed_at = datetime.utcnow()
                            logger.info(f"Task {task_id} completed (Total: {total})")
                    else:
                        task.status = "failed"
                        task.completed_at = datetime.utcnow()
                        logger.info(f"Task {task_id} failed (Total: {total})")
                elif task.status == "created":
                    task.status = "running"
                
                await db.commit()
                
                # 发送 WebSocket 通知 (可选)
                
        except Exception as e:
            logger.error(f"更新进度失败: {e}")

# 全局实例
task_scheduler = TaskScheduler()
