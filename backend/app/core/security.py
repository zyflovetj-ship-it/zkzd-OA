"""密码哈希与 JWT（短时效访问令牌 + 刷新令牌）。

说明：密码哈希采用标准库 hashlib.pbkdf2_hmac，零原生依赖、跨平台可移植，
避免在部分架构（如 arm64/openharmony）因缺少 Rust 工具链导致 bcrypt 编译失败。
"""
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import get_settings

settings = get_settings()

_PBKDF2_ALGO = "sha256"
# 迭代次数对齐 OWASP 现行建议（PBKDF2-HMAC-SHA256 建议 60 万）。
# 向后兼容：哈希串自带迭代次数（pbkdf2$sha256$<iters>$...），verify_password 按串内次数校验，
# 因此提升该值只影响此后新设/改密的哈希，存量账号无需重置密码。
# 代价：单次登录的 CPU 开销上升（hashlib 为 C 实现，实测仍远低于 1 秒）。
_PBKDF2_ITERS = 600_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password.encode(), salt, _PBKDF2_ITERS)
    return f"pbkdf2${_PBKDF2_ALGO}${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _, algo, iters, salt_hex, dk_hex = hashed.split("$")
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac(algo, plain.encode(), salt, int(iters))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def _create_token(subject: str, expires_delta: timedelta, token_type: str, **extra: Any) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        **extra,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int, role: str) -> str:
    return _create_token(
        str(user_id),
        timedelta(minutes=settings.access_token_expire_minutes),
        "access",
        role=role,
    )


def create_refresh_token() -> tuple[str, timedelta]:
    """签发刷新令牌。

    必须带唯一 `jti`：JWT 只按秒取 iat/exp，同一秒内签发的令牌会**完全相同**，
    而 `refresh_tokens.token_hash` 是唯一索引——否则同一秒登录/刷新会抛
    `IntegrityError: UNIQUE constraint failed`，表现为登录或刷新随机 500。
    """
    expire = timedelta(days=settings.refresh_token_expire_days)
    token = _create_token("refresh", expire, "refresh", jti=uuid.uuid4().hex)
    return token, expire


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    payload = jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
    if payload.get("type") != expected_type:
        raise ValueError("token type mismatch")
    return payload
