"""请求上下文中间件 + 审计中间件：注入 request_id、访问日志、安全头、落审计日志。"""
import json
import threading
import time
import uuid
from collections import defaultdict, deque

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core import security
from app.core.db import SessionLocal
from app.core.logging import get_logger, request_id_var
from app.models import AuditLog, User

logger = get_logger("access")

# 生产加固基础安全头（不依赖外部库）
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        token = request_id_var.set(rid)
        start = time.time()
        response = None
        try:
            response = await call_next(request)
        finally:
            elapsed = round((time.time() - start) * 1000, 2)
            logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code if response is not None else 0,
                ms=elapsed,
                request_id=rid,
            )
            request_id_var.reset(token)
        # 主流程之外的安全头补充
        if response is not None:
            response.headers["x-request-id"] = rid
            for k, v in SECURITY_HEADERS.items():
                response.headers.setdefault(k, v)
        return response


class ActiveRequestMiddleware(BaseHTTPMiddleware):
    """在途请求计数：用于优雅停机时 drained 等待在途请求完成，避免强行中断。"""

    _count: int = 0
    _lock = threading.Lock()

    @classmethod
    def active_count(cls) -> int:
        with cls._lock:
            return cls._count

    async def dispatch(self, request: Request, call_next):
        with self._lock:
            ActiveRequestMiddleware._count += 1
        try:
            return await call_next(request)
        finally:
            with self._lock:
                ActiveRequestMiddleware._count -= 1


class AuditMiddleware(BaseHTTPMiddleware):
    """审计中间件：对变更类请求与关键认证动作自动落审计日志。

    设计要点：
    - 仅审计 POST/PUT/PATCH/DELETE 与 登录/登出/刷新，避免把海量只读请求写入审计表；
    - 按请求路径识别 module/action/target，对审批通过/驳回、建模删除等语义动作做精准标注；
    - 不记录密码/令牌等敏感数据（detail 仅保留脱敏上下文）；
    - 审计写入独立事务，任何失败只告警不影响主响应。
    """

    SKIP_PREFIXES = ("/health", "/ready", "/docs", "/redoc", "/openapi.json", "/static")
    MUTATIONS = {"POST", "PUT", "PATCH", "DELETE"}

    async def dispatch(self, request: Request, call_next):
        method = request.method
        path = request.url.path
        classified = None
        if self._should_audit(method, path):
            classified = await self._classify(request, method, path)
        response = await call_next(request)
        if classified is None:
            return response
        module, action, target_type, target_id, detail = classified
        status = "success" if response.status_code < 400 else "failed"
        try:
            await self._write(request, response, module, action, target_type, target_id, detail, status)
        except Exception:  # noqa: BLE001
            logger.warning("audit_write_failed", path=path)
        return response

    # ---- 判定 ----
    def _should_audit(self, method: str, path: str) -> bool:
        if path.startswith(self.SKIP_PREFIXES):
            return False
        if method in self.MUTATIONS:
            return True
        # 关键认证动作始终审计
        if path.endswith("/api/auth/login") or path.endswith("/api/auth/logout") \
           or path.endswith("/api/auth/refresh"):
            return True
        return False

    async def _classify(self, request: Request, method: str, path: str):
        """按路径识别语义动作；需要判定通过/驳回时读取 JSON body（Starlette 会缓存，端点仍可读取）。"""
        parts = [p for p in path.split("/") if p]
        body = await self._read_json(request)

        # 认证
        if path.endswith("/api/auth/login"):
            return ("auth", "login", "session", "", {})
        if path.endswith("/api/auth/logout"):
            return ("auth", "logout", "session", "", {})
        if path.endswith("/api/auth/refresh"):
            return ("auth", "refresh", "session", "", {})

        # 审批工作流
        if len(parts) >= 5 and parts[0] == "api" and parts[1] == "workflows" \
           and parts[2] == "tasks" and parts[4] == "decide":
            approve = bool(body.get("approve")) if isinstance(body, dict) else False
            comment = (body.get("comment") or "")[:200] if isinstance(body, dict) else ""
            return ("workflow", "approve" if approve else "reject", "workflow_task", parts[3], {"comment": comment})
        if len(parts) >= 5 and parts[0] == "api" and parts[1] == "workflows" \
           and parts[2] == "tasks" and parts[4] == "transfer":
            return ("workflow", "transfer", "workflow_task", parts[3], {})
        if len(parts) >= 7 and parts[0] == "api" and parts[1] == "workflows" \
           and parts[2] == "instances" and parts[5] == "addsign":
            user_ids = (body.get("user_ids") or []) if isinstance(body, dict) else []
            return ("workflow", "addsign", "workflow_instance", parts[3], {"user_ids": user_ids})
        if len(parts) >= 5 and parts[0] == "api" and parts[1] == "workflows" \
           and parts[2] == "instances" and parts[4] in ("withdraw", "urge"):
            return ("workflow", parts[4], "workflow_instance", parts[3], {})
        if path.endswith("/api/workflows/instances") and method == "POST":
            return ("workflow", "start", "workflow_instance", "", {})
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "workflows" \
           and parts[2] == "definitions" and parts[3].isdigit() \
           and path.endswith("/status") and method == "PATCH":
            return ("workflow", "def_status", "workflow_definition", parts[3], {})
        if path.endswith("/api/workflows/definitions") and method == "POST":
            return ("workflow", "def_create", "workflow_definition", "", {})
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "workflows" \
           and parts[2] == "versions" and parts[4] == "publish" and method == "POST":
            return ("workflow", "version_publish", "workflow_version", parts[3], {})

        # 建模引擎
        if path.endswith("/api/models/entities") and method == "POST":
            return ("model", "entity_create", "model_entity", "", {})
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "models" \
           and parts[2] == "entities" and parts[3].isdigit():
            if method == "PATCH":
                return ("model", "entity_update", "model_entity", parts[3], {})
            if method == "DELETE":
                return ("model", "entity_delete", "model_entity", parts[3], {})
        if len(parts) >= 5 and parts[0] == "api" and parts[1] == "models" \
           and parts[2] == "entities" and parts[4] == "records" and method == "POST":
            return ("model", "record_create", "model_record", "", {})
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "models" \
           and parts[2] == "records" and parts[3].isdigit():
            if method == "PATCH":
                return ("model", "record_update", "model_record", parts[3], {})
            if method == "DELETE":
                return ("model", "record_delete", "model_record", parts[3], {})

        # 组织权限中心
        if path.endswith("/api/permissions") and method == "POST":
            return ("org", "perm_create", "permission", "", {})
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "permissions" \
           and parts[2] == "roles" and parts[3].isdigit() and method == "POST":
            return ("org", "perm_assign", "role", parts[3], {})
        if len(parts) >= 5 and parts[0] == "api" and parts[1] == "permissions" \
           and parts[2] == "roles" and parts[3].isdigit() and parts[4].isdigit() and method == "DELETE":
            return ("org", "perm_revoke", "role", parts[3], {})
        if path.endswith("/api/roles") and method == "POST":
            return ("org", "role_create", "role", "", {})
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "roles" \
           and parts[2].isdigit() and method == "DELETE":
            return ("org", "role_delete", "role", parts[2], {})
        if path.endswith("/api/departments") and method == "POST":
            return ("org", "dept_create", "department", "", {})
        if path.endswith("/api/menus") and method == "POST":
            return ("org", "menu_create", "menu", "", {})
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "menus" \
           and parts[2].isdigit() and method == "PATCH":
            return ("org", "menu_update", "menu", parts[2], {})

        # 用户 / 请假 / 公告 / 签单
        if path.endswith("/api/users") and method == "POST":
            return ("user", "user_create", "user", "", {})
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "users" \
           and parts[2].isdigit() and method == "PATCH":
            return ("user", "user_update", "user", parts[2], {})
        if path.endswith("/api/leave") and method == "POST":
            return ("leave", "leave_create", "leave_request", "", {})
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "leave" \
           and parts[2].isdigit() and parts[3] == "review" and method == "POST":
            return ("leave", "leave_review", "leave_request", parts[2], {})
        if path.endswith("/api/announcements") and method == "POST":
            return ("ann", "ann_create", "announcement", "", {})
        if path.endswith("/api/signatures") and method == "POST":
            return ("sig", "sign", "signature", "", {})

        # 内容引擎：文档中心
        if parts[0:2] == ["api", "documents"]:
            if method == "GET" and len(parts) == 2:
                return ("doc", "doc_list", "document", "", {})
            if method == "POST" and len(parts) == 2:
                return ("doc", "doc_upload", "document", "", {})
            if len(parts) >= 3 and parts[2].isdigit():
                tid = parts[2]
                if method == "GET" and parts[3:4] == ["file"]:
                    return ("doc", "doc_download", "document", tid, {})
                if method == "PATCH":
                    return ("doc", "doc_update", "document", tid, {})
                if method == "DELETE":
                    return ("doc", "doc_delete", "document", tid, {})

        # 兜底：通用变更
        last = parts[-1] if parts else "request"
        return ("other", f"{method.lower()}_{last}", "", "", {})

    async def _read_json(self, request: Request) -> dict:
        ct = request.headers.get("content-type", "")
        if not ct.startswith("application/json"):
            return {}
        try:
            raw = await request.body()
            if not raw:
                return {}
            return json.loads(raw)
        except Exception:
            return {}

    # ---- 写入 ----
    async def _write(self, request: Request, response, module, action, target_type, target_id, detail, status):
        actor_id, actor_name = await self._resolve_actor(request)
        ip = request.client.host if request.client else ""
        rid = getattr(request.state, "request_id", "") or request.headers.get("x-request-id") or ""
        async with SessionLocal() as session:
            if actor_id and not actor_name:
                u = await session.get(User, actor_id)
                if u:
                    actor_name = u.full_name or u.username
            log = AuditLog(
                actor_id=actor_id,
                actor_name=actor_name or "",
                module=module,
                action=action,
                target_type=target_type,
                target_id=target_id or "",
                method=request.method,
                path=request.url.path,
                status=status,
                status_code=response.status_code,
                message="",
                detail=detail or {},
                ip=ip,
                request_id=rid,
            )
            session.add(log)
            await session.commit()

    async def _resolve_actor(self, request: Request):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None, ""
        token = auth[len("Bearer "):].strip()
        try:
            payload = security.decode_token(token, "access")
            uid = int(payload["sub"])
        except Exception:
            return None, ""
        return uid, ""


class RateLimitMiddleware(BaseHTTPMiddleware):
    """轻量限流：固定窗口（每分钟每客户端 IP 上限），纯标准库实现，无外部依赖。

    通过 settings.rate_limit_per_minute 控制，0 表示关闭；默认关闭。
    健康检查与就绪探针不受限，避免误伤探测流量。
    """

    # 不受限的路径（探针 / 文档）
    EXEMPT_PATHS = {"/health", "/ready", "/docs", "/openapi.json", "/redoc"}

    def __init__(self, app, limit_per_minute: int = 0):
        super().__init__(app)
        self.limit = limit_per_minute
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    async def dispatch(self, request: Request, call_next):
        if self.limit <= 0:
            return await call_next(request)
        path = request.url.path
        if path in self.EXEMPT_PATHS:
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = time.time()
        window_start = now - 60.0
        with self._lock:
            dq = self._hits[ip]
            while dq and dq[0] < window_start:
                dq.popleft()
            if len(dq) >= self.limit:
                retry_after = max(1, int(dq[0] + 60.0 - now))
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                    content={
                        "error": "too_many_requests",
                        "detail": "请求过于频繁，请稍后再试",
                    },
                )
            dq.append(now)
        return await call_next(request)
