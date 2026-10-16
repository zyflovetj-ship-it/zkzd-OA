"""FastAPI 应用入口：中间件、异常处理、CORS、健康检查、启动初始化。"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routers import api
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.errors import (
    AppError,
    app_error_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.logging import configure_logging, get_logger
from app.core.middleware import (
    ActiveRequestMiddleware,
    AuditMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
)
from app.core.scheduler import Scheduler
from app.seed import seed_initial_data

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger("startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", env=settings.environment)
    # 确保上传目录存在（文档中心文件落盘依赖）
    os.makedirs(settings.upload_dir, exist_ok=True)
    # 表结构由 Alembic 迁移管理，启动前需先执行 `alembic upgrade head`（见 run.sh / Dockerfile）
    async with SessionLocal() as session:
        await seed_initial_data(session)
    # 后台调度：审批超时自动升级提醒（默认关闭，生产按需开启）
    scheduler = Scheduler()
    if settings.scheduler_enabled:
        await scheduler.start()
    yield
    # 优雅停机：等待在途请求自然完成（含 SSE 长连接由服务器在超时后主动关闭），
    # 避免强行中断正在写入的事务或下行推送。超时则记录并放弃等待。
    timeout = settings.graceful_shutdown_timeout_seconds
    waited = 0.0
    while ActiveRequestMiddleware.active_count() > 0 and waited < timeout:
        await asyncio.sleep(0.2)
        waited += 0.2
    if waited >= timeout and ActiveRequestMiddleware.active_count() > 0:
        logger.warning(
            "shutdown_drain_timeout",
            remaining=ActiveRequestMiddleware.active_count(),
            waited=round(waited, 1),
        )
    if settings.scheduler_enabled:
        await scheduler.stop()
    logger.info("shutdown")


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)

# 轻量限流（默认关闭；rate_limit_per_minute>0 时启用，置于最外层先行拦截）
app.add_middleware(RateLimitMiddleware, limit_per_minute=settings.rate_limit_per_minute)
# 请求上下文（request_id / 访问日志 / 安全头）
app.add_middleware(RequestContextMiddleware)
# 审计中间件（自动落审计日志）：置于 RequestContext 之后，可复用其注入的 request_id
app.add_middleware(AuditMiddleware)
# CORS：显式来源，生产禁用通配符
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 在途请求计数（置于最外层，覆盖全部内部中间件，用于优雅停机 drained）
app.add_middleware(ActiveRequestMiddleware)

# 异常处理器（更具体的先注册）
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(api)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def ready():
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "not_ready", "detail": str(e)})
