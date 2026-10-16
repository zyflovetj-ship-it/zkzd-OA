"""后台调度器：审批超时自动升级提醒。

- 独立异步任务循环，按 SCHEDULER_INTERVAL_SECONDS 轮询；
- 每轮调用 WorkflowService.timeout_escalate_all()，单轮异常不中断整个循环；
- 分片 sleep（每 5s 检查一次停止标志），shutdown 时及时退出；
- 由 app/main.py 的 lifespan 按 SCHEDULER_ENABLED 启动/停止；run_once() 供手动触发与测试。
"""
import asyncio

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.services import WorkflowService

logger = get_logger("scheduler")


class Scheduler:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._task: asyncio.Task | None = None
        self._stop = False

    async def run_once(self) -> dict:
        """执行一轮超时升级；开启独立会话，避免与请求会话耦合。"""
        async with SessionLocal() as session:
            return await WorkflowService(session).timeout_escalate_all()

    async def _loop(self) -> None:
        interval = max(1, self.settings.scheduler_interval_seconds)
        while not self._stop:
            try:
                result = await self.run_once()
                logger.info("scheduler_run", **result)
            except Exception as exc:  # noqa: BLE001
                logger.error("scheduler_error", error=str(exc))
            # 分片 sleep，支持优雅停机（每 5s 轮询一次停止标志）
            for _ in range(max(1, interval // 5)):
                if self._stop:
                    return
                await asyncio.sleep(5)

    async def start(self) -> None:
        if self._task is None and not self._stop:
            self._stop = False
            self._task = asyncio.create_task(self._loop())
            logger.info(
                "scheduler_started", interval=self.settings.scheduler_interval_seconds
            )

    async def stop(self) -> None:
        self._stop = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("scheduler_stopped")
