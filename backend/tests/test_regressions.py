"""回归测试：锁定本次实测发现并修复的缺陷（启动阻塞 / 接口 500 / 数据一致性）。

每条用例都对应一次真实故障，防止后续改动把问题改回来：

1. 路由前缀重复（/api/api/** → 前端全部 404）
2. 刷新令牌同秒重复（refresh_tokens.token_hash 唯一冲突 → 登录/刷新随机 500）
3. naive/aware 时间比较（刷新令牌接口 TypeError 500）
4. UserUpdate 缺 username 字段（PATCH /api/users/{id} 恒 500）
5. 异步会话惰性加载（新建用户 / 发起流程时 MissingGreenlet 500）
6. Department↔User 双外键未指定 foreign_keys（映射配置失败，任何查询都炸）
7. SQLite 下 alembic 0001 用 ALTER 补外键（本地部署 migrate 直接失败）

运行：cd backend && pytest -q tests/test_regressions.py
"""
import os
import subprocess
import sys
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.db import Base
from app.core.security import create_refresh_token
from app.models import Department, Role, User, WorkflowDefinition, WorkflowVersion
from app.repositories import WorkflowRepository
from app.schemas import UserUpdate, WorkflowInstanceCreate
from app.services import AuthService, UserService, WorkflowService


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


async def _seed(session: AsyncSession) -> dict:
    admin = Role(name="admin")
    employee = Role(name="employee")
    session.add_all([admin, employee])
    await session.flush()
    u_admin = User(
        username="rg_admin", email="a@x", full_name="管理员",
        hashed_password="x", role_id=admin.id,
    )
    u_emp = User(
        username="rg_emp", email="e@x", full_name="员工",
        hashed_password="x", role_id=employee.id,
    )
    session.add_all([u_admin, u_emp])
    await session.flush()
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "name": "发起"},
            {"id": "n1", "type": "approval", "name": "审批",
             "assignee": {"type": "role", "value": "admin"}},
            {"id": "end", "type": "end", "name": "结束"},
        ],
        "edges": [{"source": "start", "target": "n1"}, {"source": "n1", "target": "end"}],
    }
    d = WorkflowDefinition(code="WF-REG", name="回归流程", status="published", current_version=1)
    session.add(d)
    await session.flush()
    session.add(
        WorkflowVersion(definition_id=d.id, version=1, graph=graph,
                        status="published", published_at=datetime.utcnow())
    )
    await session.commit()
    return {"admin": u_admin, "emp": u_emp, "role_admin": admin, "role_emp": employee, "defn": d}


# ---------- 1. 路由前缀 ----------
def test_api_routes_are_not_double_prefixed():
    """/api/api/** 说明容器路由重复加了前缀，前端所有请求都会 404。"""
    from app.main import app

    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert paths, "应用未注册任何路由"
    bad = [p for p in paths if p.startswith("/api/api/")]
    assert not bad, f"路由前缀重复：{bad[:5]}"
    assert any(p == "/api/auth/login" for p in paths), "缺少 /api/auth/login"
    assert any(p == "/api/events/stream" for p in paths), "缺少 /api/events/stream"


# ---------- 2. 刷新令牌唯一性 ----------
def test_refresh_tokens_unique_within_same_second():
    """JWT 的 iat/exp 精度为秒：不带 jti 时同一秒签发的令牌完全相同，
    会撞 refresh_tokens.token_hash 唯一索引 → 登录/刷新 500。"""
    t1, _ = create_refresh_token()
    t2, _ = create_refresh_token()
    assert t1 != t2, "同一秒内签发的刷新令牌必须不同（需带 jti 随机串）"


# ---------- 3. 刷新令牌过期比较（naive vs aware） ----------
async def _with_role(s: AsyncSession, user: User) -> User:
    """按 id 重新取用户并预加载 role（服务层 RBAC 判定要读 user.role.name）。"""
    res = await s.execute(
        select(User).where(User.id == user.id).options(selectinload(User.role))
    )
    return res.scalar_one()


async def test_auth_login_and_refresh_roundtrip(session):
    """DB 里的 expires_at 是 naive UTC；比较时若直接对 aware now 会抛 TypeError。"""
    from app.core import security

    data = await _seed(session)
    data["admin"].hashed_password = security.hash_password("pass12345")
    await session.commit()

    auth = AuthService(session)
    _, raw_refresh, _user = await auth.login("rg_admin", "pass12345")
    # 轮换：再次 refresh 必须成功（过期判断走 _as_utc 归一）
    access2, raw2 = await auth.refresh(raw_refresh)
    assert access2 and raw2 and raw2 != raw_refresh
    # 旧令牌已被吊销
    from app.core.errors import UnauthorizedError
    with pytest.raises(UnauthorizedError):
        await auth.refresh(raw_refresh)


# ---------- 4. UserUpdate 必须含 username ----------
def test_user_update_schema_has_username():
    """服务层 UserService.update 会读 data.username；缺字段即 AttributeError → 500。"""
    assert "username" in UserUpdate.model_fields
    assert UserUpdate().username is None


# ---------- 5. 异步会话不能惰性加载（新建用户 / 发起流程） ----------
async def test_user_create_exposes_loaded_role(session):
    data = await _seed(session)
    from app.schemas import UserCreate

    created = await UserService(session).create(
        UserCreate(username="newbie", password="pass12345", role_id=data["role_emp"].id)
    )
    # 响应模型要读 user.role.name；惰性访问在异步会话里会抛 MissingGreenlet
    assert created.role is not None
    assert created.role.name == "employee"


async def test_user_update_keeps_role_loadable(session):
    data = await _seed(session)
    from app.schemas import UserUpdate as UU

    svc = UserService(session)
    target = data["emp"]
    actor = await _with_role(session, data["admin"])  # 服务层读 actor.role.name 做 RBAC
    updated = await svc.update(target.id, UU(full_name="改名后", role_id=data["role_admin"].id), actor)
    assert updated.full_name == "改名后"
    assert updated.role.name == "admin"  # 改角色后返回的 role_name 必须是新角色


async def test_start_instance_tasks_are_loaded(session):
    """WorkflowInstanceOut 要序列化 tasks：refresh(instance) 不加载集合会 500。"""
    data = await _seed(session)
    svc = WorkflowService(session)
    inst = await svc.start_instance(
        data["admin"].id, WorkflowInstanceCreate(definition_id=data["defn"].id, title="回归")
    )
    # 直接读集合：惰性加载会抛 MissingGreenlet
    assert len(list(inst.tasks)) >= 1, "发起后应生成审批任务且集合已加载"


async def test_get_task_loads_instance_tasks(session):
    data = await _seed(session)
    svc = WorkflowService(session)
    await svc.start_instance(
        data["admin"].id, WorkflowInstanceCreate(definition_id=data["defn"].id, title="回归2")
    )
    repo = WorkflowRepository(session)
    pending = await repo.list_tasks_status("pending")
    assert pending, "应有待办"
    task = await repo.get_task(pending[0].id)
    assert task is not None
    # decide/transfer 返回的就是 task.instance，序列化同样要读 tasks
    assert task.instance is not None
    assert list(task.instance.tasks) is not None


# ---------- 6. Department↔User 双外键 ----------
async def test_department_members_relationship_loads(session):
    """users.department_id 与 departments.manager_id 两条外键，未指定 foreign_keys 时
    SQLAlchemy 会在配置映射时报 ambiguity，任何涉及该表的查询都会失败。"""
    dept = Department(name="回归部门")
    session.add(dept)
    await session.flush()
    emp_role = Role(name="r1")
    session.add(emp_role)
    await session.flush()
    u = User(username="dept_user", email="", full_name="x", hashed_password="x",
             role_id=emp_role.id, department_id=dept.id)
    session.add(u)
    dept.manager_id = u.id
    await session.commit()

    # 映射配置：若 foreign_keys 未指定，这里配置 Department 映射时就会抛
    # "Could not determine join condition ... multiple foreign key paths"
    res = await session.execute(
        select(Department).options(selectinload(Department.members))
    )
    d = res.scalar_one()
    assert [m.username for m in d.members] == ["dept_user"]

    res2 = await session.execute(
        select(User).where(User.username == "dept_user").options(selectinload(User.department))
    )
    u2 = res2.scalar_one()
    assert u2.department is not None and u2.department.name == d.name


# ---------- 7. SQLite 迁移可执行 ----------
def test_alembic_upgrade_head_on_sqlite():
    """0001 用 op.create_foreign_key 补循环外键；SQLite 不支持 ALTER 约束，
    必须走 batch 路径，否则 run.sh / 本地部署第一条命令就失败。

    注意：不使用 pytest 的 tmp_path——本环境家目录属主不一致会让该 fixture 抛 OSError。
    """
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    workdir = os.path.join(backend_dir, ".alembic_check")
    os.makedirs(workdir, exist_ok=True)
    db_file = os.path.join(workdir, "migrate.db")
    if os.path.exists(db_file):
        os.remove(db_file)
    try:
        env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_file}"}
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=backend_dir, env=env, capture_output=True, text=True, timeout=180,
        )
        assert proc.returncode == 0, f"alembic 失败：\n{proc.stdout}\n{proc.stderr}"
        assert os.path.exists(db_file)
    finally:
        for name in os.listdir(workdir):
            try:
                os.remove(os.path.join(workdir, name))
            except OSError:
                pass
        try:
            os.rmdir(workdir)
        except OSError:
            pass
