"""阶段四增量优化测试：公文编号预览 + 流转时间线 + 全文检索。

运行：cd backend && pytest -q tests/test_phase4_official_doc.py
"""
from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.db import Base
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models import OfficialDocument, Role, User
from app.services import OfficialDocService


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


async def test_preview_doc_no(session):
    """预览文号应返回下一个可用编号。"""
    svc = OfficialDocService(session)
    # 收文
    result = await svc.preview_doc_no("in")
    assert result["prefix"] == "SW" and result["seq"] == 1
    assert result["doc_no"].startswith("SW-")
    # 发文
    result = await svc.preview_doc_no("out")
    assert result["prefix"] == "FW" and result["seq"] == 1
    # 创建一条后，预览序号应递增
    owner = await _user(session, "doc_owner")
    await svc.create(owner, {"title": "测试公文", "direction": "in"})
    result = await svc.preview_doc_no("in")
    assert result["seq"] == 2


async def test_timeline(session):
    """创建、传阅、归档应产生完整时间线。"""
    owner = await _user(session, "timeline_owner")
    svc = OfficialDocService(session)
    doc = await svc.create(owner, {"title": "时间线测试", "direction": "in"})
    # 传阅
    await svc.circulate(owner, doc.id, {"user_ids": [], "remark": "全员传阅"})
    # 归档
    await svc.archive(owner, doc.id)
    # 时间线应有3条记录
    timeline = await svc.get_timeline(doc.id)
    assert len(timeline) == 3
    actions = [e["action"] for e in timeline]
    assert "create" in actions and "circulate" in actions and "archive" in actions


async def test_full_text_search(session):
    """全文检索应跨标题/内容/文号匹配。"""
    owner = await _user(session, "search_owner")
    svc = OfficialDocService(session)
    await svc.create(owner, {"title": "关于项目验收的通知", "content": "请各部门于月底前完成验收"})
    await svc.create(owner, {"title": "关于经费申请的请示", "content": "申请项目经费50万元"})
    await svc.create(owner, {"title": "人事任免决定", "content": "任命张三为部门经理"})

    # 搜索"验收"
    result = await svc.search("验收")
    assert result["total"] >= 1
    assert any("验收" in item["title"] or "验收" in item["snippet"] for item in result["items"])

    # 搜索"经费"
    result = await svc.search("经费")
    assert result["total"] >= 1

    # 搜索不存在的内容
    result = await svc.search("不存在的内容XYZ")
    assert result["total"] == 0


async def test_search_filters(session):
    """全文检索应支持方向/状态筛选。"""
    owner = await _user(session, "filter_owner")
    svc = OfficialDocService(session)
    await svc.create(owner, {"title": "收文测试", "direction": "in"})
    await svc.create(owner, {"title": "发文测试", "direction": "out"})

    # 只搜索收文
    result = await svc.search("测试", direction="in")
    assert all(item["direction"] == "in" for item in result["items"])

    # 只搜索发文
    result = await svc.search("测试", direction="out")
    assert all(item["direction"] == "out" for item in result["items"])