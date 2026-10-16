"""工作流服务层（WorkflowService）集成测试：真实 SQLite，覆盖实例全生命周期与权限边界。

与 test_workflow_engine.py（纯图遍历逻辑，不依赖 DB）互补：本文件验证服务层把图遍历结果
正确落库为实例/任务/日志，以及 RBAC 与转办/撤回/催办等行为。

设计：复用 test_dashboard.py 的「真实内存库 + 异步 fixture」范式（不 mock 服务层，符合
全栈专家 Phase 5 规范「集成测试用真实数据库」）。引擎纯逻辑在 app/workflow_engine.py，
此处聚焦 WorkflowService 对 DB 的读写编排。

运行（标准环境）：cd backend && pytest -q tests/test_workflow_service.py
沙箱限制：openharmony 未装 sqlalchemy/pytest，仅做 compileall 语法校验。
"""
import os
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
from app.core.errors import ConflictError, ForbiddenError
from app.models import Role, User, WorkflowDefinition, WorkflowVersion
from app.schemas import (
    WorkflowDefinitionCreate,
    WorkflowInstanceCreate,
    WorkflowReview,
    WorkflowTransfer,
    WorkflowUrge,
    WorkflowVersionSave,
)
from app.services import WorkflowService


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


async def _get_user(s: AsyncSession, username: str) -> User:
    """取用户并预加载 role（decide/withdraw/urge 内部读 user.role.name 做 RBAC 判定）。"""
    res = await s.execute(
        select(User).options(selectinload(User.role)).where(User.username == username)
    )
    return res.scalar_one()


async def _seed(s: AsyncSession) -> dict:
    """构造：3 角色 / 4 用户 / 2 个已发布流程（单级审批 + 会签），全部落库。"""
    admin, manager, employee = Role(name="admin"), Role(name="manager"), Role(name="employee")
    s.add_all([admin, manager, employee])
    await s.flush()

    u_admin = User(username="wf_admin", email="a@x", full_name="管理员", hashed_password="x", role_id=admin.id)
    u_appr = User(username="wf_appr", email="p@x", full_name="审批人", hashed_password="x", role_id=manager.id)
    u_appr2 = User(username="wf_appr2", email="p2@x", full_name="审批人2", hashed_password="x", role_id=manager.id)
    u_init = User(username="wf_init", email="i@x", full_name="发起人", hashed_password="x", role_id=employee.id)
    s.add_all([u_admin, u_appr, u_appr2, u_init])
    await s.flush()

    single_graph = {
        "nodes": [
            {"id": "start", "type": "start", "name": "发起"},
            {"id": "n1", "type": "approval", "name": "主管审批",
             "assignee": {"type": "user", "value": u_appr.id}},
            {"id": "end", "type": "end", "name": "结束"},
        ],
        "edges": [{"source": "start", "target": "n1"}, {"source": "n1", "target": "end"}],
    }
    cs_graph = {
        "nodes": [
            {"id": "start", "type": "start", "name": "发起"},
            {"id": "n1", "type": "countersign", "name": "会签",
             "assignees": [
                 {"type": "user", "value": u_appr.id},
                 {"type": "user", "value": u_appr2.id},
             ], "strategy": "all", "ratio": None},
            {"id": "end", "type": "end", "name": "结束"},
        ],
        "edges": [{"source": "start", "target": "n1"}, {"source": "n1", "target": "end"}],
    }
    d_single = WorkflowDefinition(code="WF-SINGLE", name="单级审批", status="published", current_version=1)
    d_cs = WorkflowDefinition(code="WF-CS", name="会签流程", status="published", current_version=1)
    s.add_all([d_single, d_cs])
    await s.flush()
    s.add_all([
        WorkflowVersion(definition_id=d_single.id, version=1, graph=single_graph,
                       status="published", published_at=datetime.utcnow()),
        WorkflowVersion(definition_id=d_cs.id, version=1, graph=cs_graph,
                       status="published", published_at=datetime.utcnow()),
    ])
    await s.commit()
    return {"admin": u_admin, "appr": u_appr, "appr2": u_appr2, "init": u_init,
            "d_single": d_single, "d_cs": d_cs}


@pytest.fixture
async def data(session):
    return await _seed(session)


async def test_start_activates_node_and_task(session, data):
    """发起后：实例 running、当前节点 n1、审批人收到 1 条待办、发起人可查到在途实例。"""
    svc = WorkflowService(session)
    init = data["init"]
    inst = await svc.start_instance(
        init.id, WorkflowInstanceCreate(definition_id=data["d_single"].id, title="请假单", form_data={"amount": 100})
    )
    assert inst.status == "running"
    assert inst.current_nodes == ["n1"]

    appr = await _get_user(session, "wf_appr")
    pending = await svc.pending_for(appr)
    assert len(pending) == 1
    assert pending[0].instance_id == inst.id

    mine = await svc.my_instances(init)
    assert any(i.id == inst.id for i in mine)


async def test_approve_completes_instance(session, data):
    """审批通过：实例置 approved、finished_at 非空、当前节点清空、任务状态 approved。"""
    svc = WorkflowService(session)
    init = data["init"]
    inst = await svc.start_instance(init.id, WorkflowInstanceCreate(definition_id=data["d_single"].id, title="t"))
    appr = await _get_user(session, "wf_appr")
    task = (await svc.pending_for(appr))[0]

    updated = await svc.decide_task(task.id, appr, WorkflowReview(approve=True, comment="同意"))
    assert updated.status == "approved"
    assert updated.finished_at is not None
    assert updated.current_nodes == []

    fresh = await svc.repo.get_task(task.id)
    assert fresh.status == "approved"


async def test_reject_completes_instance(session, data):
    """审批驳回：实例置 rejected。"""
    svc = WorkflowService(session)
    init = data["init"]
    inst = await svc.start_instance(init.id, WorkflowInstanceCreate(definition_id=data["d_single"].id, title="t"))
    appr = await _get_user(session, "wf_appr")
    task = (await svc.pending_for(appr))[0]

    updated = await svc.decide_task(task.id, appr, WorkflowReview(approve=False, comment="不同意"))
    assert updated.status == "rejected"


async def test_forbidden_for_non_assignee(session, data):
    """非任务处理人（且非 admin）审批 -> ForbiddenError。"""
    svc = WorkflowService(session)
    init = data["init"]
    inst = await svc.start_instance(init.id, WorkflowInstanceCreate(definition_id=data["d_single"].id, title="t"))
    appr = await _get_user(session, "wf_appr")
    task = (await svc.pending_for(appr))[0]

    intruder = await _get_user(session, "wf_init")  # employee，非 admin、非审批人
    with pytest.raises(ForbiddenError):
        await svc.decide_task(task.id, intruder, WorkflowReview(approve=True))


async def test_transfer_reassigns_task(session, data):
    """转办：任务改派给 target，origin_approver_id 留痕；target 可继续审批。"""
    svc = WorkflowService(session)
    init = data["init"]
    inst = await svc.start_instance(init.id, WorkflowInstanceCreate(definition_id=data["d_single"].id, title="t"))
    appr = await _get_user(session, "wf_appr")
    appr2 = await _get_user(session, "wf_appr2")
    task = (await svc.pending_for(appr))[0]

    await svc.transfer_task(task.id, appr, WorkflowTransfer(to_user_id=appr2.id, comment="转办"))
    fresh = await svc.repo.get_task(task.id)
    assert fresh.approver_id == appr2.id
    assert fresh.origin_approver_id == appr.id

    updated = await svc.decide_task(fresh.id, appr2, WorkflowReview(approve=True))
    assert updated.status == "approved"


async def test_withdraw_by_initiator(session, data):
    """发起人撤回在途流程 -> canceled。"""
    svc = WorkflowService(session)
    init = await _get_user(session, "wf_init")
    inst = await svc.start_instance(init.id, WorkflowInstanceCreate(definition_id=data["d_single"].id, title="t"))
    updated = await svc.withdraw(inst.id, init)
    assert updated.status == "canceled"


async def test_urge_logs_reminder(session, data):
    """催办：为当前所有待办记录提醒，返回待办数量且生成 urge 日志。"""
    svc = WorkflowService(session)
    init = await _get_user(session, "wf_init")
    inst = await svc.start_instance(init.id, WorkflowInstanceCreate(definition_id=data["d_single"].id, title="t"))
    cnt = await svc.urge(inst.id, init, WorkflowUrge(comment="请尽快"))
    assert cnt == 1
    logs = await svc.repo.list_logs(inst.id)
    assert any(l.action == "urge" for l in logs)


async def test_countersign_all_requires_everyone(session, data):
    """会签（strategy=all）：首人通过后仍 running，末人通过才 approved。"""
    svc = WorkflowService(session)
    init = data["init"]
    inst = await svc.start_instance(init.id, WorkflowInstanceCreate(definition_id=data["d_cs"].id, title="会签单"))
    appr = await _get_user(session, "wf_appr")
    appr2 = await _get_user(session, "wf_appr2")

    tasks = await svc.repo.list_tasks(inst.id, "n1")
    assert len(tasks) == 2

    t_a = next(t for t in tasks if t.approver_id == appr.id)
    after1 = await svc.decide_task(t_a.id, appr, WorkflowReview(approve=True))
    assert after1.status == "running"
    pending_now = await svc.repo.list_tasks(inst.id, "n1")
    assert any(t.status == "pending" for t in pending_now)

    t_b = next(t for t in pending_now if t.approver_id == appr2.id)
    after2 = await svc.decide_task(t_b.id, appr2, WorkflowReview(approve=True))
    assert after2.status == "approved"


async def test_definition_lifecycle_create_publish_start(session, data):
    """定义生命周期：create(draft) -> 重复编码 Conflict -> save_version(draft) -> publish -> 可发起。"""
    svc = WorkflowService(session)
    wf = await svc.create_definition(WorkflowDefinitionCreate(code="WF-LIFE", name="生命周期", category="hr"))
    assert wf.status == "draft"

    with pytest.raises(ConflictError):
        await svc.create_definition(WorkflowDefinitionCreate(code="WF-LIFE", name="重复"))

    graph = {
        "nodes": [
            {"id": "start", "type": "start", "name": "发起"},
            {"id": "n1", "type": "approval", "name": "审批", "assignee": {"type": "role", "value": "manager"}},
            {"id": "end", "type": "end", "name": "结束"},
        ],
        "edges": [{"source": "start", "target": "n1"}, {"source": "n1", "target": "end"}],
    }
    ver = await svc.save_version(wf.id, WorkflowVersionSave(graph=graph))
    assert ver.status == "draft"
    pub = await svc.publish_version(ver.id)
    assert pub.status == "published"

    init = data["init"]
    inst = await svc.start_instance(init.id, WorkflowInstanceCreate(definition_id=wf.id, title="生命周期单"))
    assert inst.status == "running"
    # 按角色解析审批人：两名 manager 均收到待办
    appr = await _get_user(session, "wf_appr")
    assert len(await svc.pending_for(appr)) >= 1


async def test_get_stats_structure(session, data):
    """监控看板聚合：返回结构化 dict，发起在途实例后 running 计数 >=1。"""
    svc = WorkflowService(session)
    init = data["init"]
    await svc.start_instance(init.id, WorkflowInstanceCreate(definition_id=data["d_single"].id, title="t"))

    stats = await svc.get_stats()
    assert isinstance(stats, dict)
    # 字段名与 WorkflowStatsOut / 前端 WorkflowMonitor 保持一致（instances / tasks）
    assert "instances" in stats and "tasks" in stats
    assert stats["instances"].get("running", 0) >= 1
    assert "pending" in stats["tasks"]
