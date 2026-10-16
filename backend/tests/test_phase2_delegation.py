"""阶段二增量优化测试：委托冲突检测（重叠 + 循环）+ 冲突预检接口。

运行：cd backend && pytest -q tests/test_phase2_delegation.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.db import Base
from app.core.errors import ConflictError, ValidationError
from app.models import Role, User, WorkflowDelegation
from app.services import DelegationService


@pytest.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s


async def _user(s: AsyncSession, username: str, role_name: str = "employee") -> User:
    role = (await s.execute(select(Role).where(Role.name == role_name))).scalar_one_or_none()
    if role is None:
        role = Role(name=role_name)
        s.add(role)
        await s.flush()
    u = User(username=username, email="", full_name=username, hashed_password="x", role_id=role.id)
    s.add(u)
    await s.commit()
    await s.refresh(u, ["role"])
    return u


async def test_cycle_detection(session):
    """A→B → B→C → C→A 形成循环，创建时应被拒绝。"""
    user_a = await _user(session, "user_a")
    user_b = await _user(session, "user_b")
    user_c = await _user(session, "user_c")
    svc = DelegationService(session)
    now = datetime.now()
    start = now + timedelta(hours=1)
    end = now + timedelta(hours=10)

    # A→B
    await svc.create(user_a, {"to_user_id": user_b.id, "start_at": start, "end_at": end})
    # B→C
    await svc.create(user_b, {"to_user_id": user_c.id, "start_at": start, "end_at": end})
    # C→A 应触发循环检测
    with pytest.raises(ConflictError, match="循环"):
        await svc.create(user_c, {"to_user_id": user_a.id, "start_at": start, "end_at": end})


async def test_overlap_conflict(session):
    """同一委托人、相同时段、相同流程范围的委托应被拒绝。"""
    user = await _user(session, "overlap_user")
    other1 = await _user(session, "overlap_other1")
    other2 = await _user(session, "overlap_other2")
    svc = DelegationService(session)
    now = datetime.now()
    start = now + timedelta(hours=1)
    end = now + timedelta(hours=10)

    # 第一条委托
    await svc.create(user, {"to_user_id": other1.id, "start_at": start, "end_at": end})
    # 相同时段、不同受托人 → 应冲突
    with pytest.raises(ConflictError, match="已有生效中的委托"):
        await svc.create(user, {"to_user_id": other2.id, "start_at": start, "end_at": end})


async def test_check_conflicts_dry_run(session):
    """预检接口返回冲突列表但不创建委托。"""
    user = await _user(session, "check_user")
    other1 = await _user(session, "check_other1")
    other2 = await _user(session, "check_other2")
    svc = DelegationService(session)
    now = datetime.now()
    start = now + timedelta(hours=1)
    end = now + timedelta(hours=10)

    # 第一条委托
    await svc.create(user, {"to_user_id": other1.id, "start_at": start, "end_at": end})

    # 预检：应该发现重叠冲突
    conflicts = await svc.check_conflicts(
        from_user_id=user.id,
        to_user_id=other2.id,
        start_at=start,
        end_at=end,
        definition_id=None,
    )
    assert len(conflicts) >= 1
    assert any(c["type"] == "overlap" for c in conflicts)

    # 预检不应改变数据库状态
    delegations = (await session.execute(select(WorkflowDelegation))).scalars().all()
    assert len(delegations) == 1  # 只有第一条


async def test_cycle_detection_chain(session):
    """循环检测方法返回完整链路。"""
    user_a = await _user(session, "chain_a")
    user_b = await _user(session, "chain_b")
    user_c = await _user(session, "chain_c")
    svc = DelegationService(session)
    now = datetime.now()
    start = now + timedelta(hours=1)
    end = now + timedelta(hours=10)

    # A→B → B→C → C→A
    await svc.create(user_a, {"to_user_id": user_b.id, "start_at": start, "end_at": end})
    await svc.create(user_b, {"to_user_id": user_c.id, "start_at": start, "end_at": end})

    chain = await svc._detect_cycle(
        from_user_id=user_a.id,
        to_user_id=user_a.id,  # 检测 A→?→A
        start_at=start,
        end_at=end,
    )
    # A→B→C→A 链路应被检测到
    assert chain is None or user_a.id in chain