"""依赖注入：数据库会话、当前用户、RBAC 角色与细粒度权限校验。"""
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.db import get_db
from app.core.errors import ForbiddenError, UnauthorizedError
from app.models import User
from app.services import AuthService, PermissionService

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if not creds or not creds.credentials:
        raise UnauthorizedError("缺少访问令牌")
    try:
        payload = security.decode_token(creds.credentials, "access")
        user_id = int(payload["sub"])
    except Exception:
        raise UnauthorizedError("访问令牌无效")
    return await AuthService(session).get_current_user(user_id)


def require_roles(*allowed: str):
    """生成依赖：当前用户角色需在 allowed 列表内，否则 403。"""

    async def checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if allowed and user.role.name not in allowed:
            raise ForbiddenError("权限不足")
        return user

    return checker


async def get_current_permissions(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[str]:
    """返回当前用户角色拥有的权限码；管理员恒为 ["*"]（通配）。"""
    if user.role.name == "admin":
        return ["*"]
    return await PermissionService(session).role_permission_codes(user.role_id)


def require_permissions(*required: str):
    """生成依赖：当前用户需具备 required 中每一项权限（管理员通配放行），否则 403。"""

    async def checker(perms: Annotated[list[str], Depends(get_current_permissions)]) -> None:
        if "*" in perms:
            return
        missing = [p for p in required if p not in perms]
        if missing:
            raise ForbiddenError("权限不足")

    return checker
