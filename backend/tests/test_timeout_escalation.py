"""审批超时自动升级（④ 调度 / 升级策略）测试套件。

分两层：

1. 单元测试（Fake 注入，零数据库）
   覆盖幂等边界（escalated_at 标记）、死信跳过（exists_dead_letter）、
   notify / escalate 两套策略、异常落死信、返回结构。
   可直接 `python3 tests/test_timeout_escalation.py` 运行（需已安装依赖）。

2. 集成测试（真实 SQLite + aiosqlite）
   覆盖 notify / escalate 全链路 + 二次运行幂等，使用 Base.metadata.create_all 建表，
   不依赖 Alembic。需标准 Python 环境运行：
       pip install -r requirements.txt
       pip install pytest pytest-asyncio
       pytest -q

运行：
    cd backend
    python3 tests/test_timeout_escalation.py          # 仅 Fake 单元测试
    pytest -q                                         # 单元 + 集成
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.db import Base
from app.models import (
    DeadLetter,
    Notification,
    Role,
    User,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowNodeLog,
    WorkflowTask,
    WorkflowVersion,
)
from app.services import WorkflowService


# ===================== 单元测试：Fake 依赖 =====================
class _FakeSession:
    """无副作用的会话替身：add/commit/flush/refresh 全部空操作。"""

    def add(self, obj):
        pass

    async def commit(self):
        pass

    async def flush(self):
        pass

    async def refresh(self, obj):
        pass


class FakeInstance:
    def __init__(self, id, title, started_at):
        self.id = id
        self.title = title
        self.started_at = started_at
        self.escalated_at = None  # 模拟 DB 列，幂等边界


class FakeTask:
    def __init__(self, id, instance_id, node_id, node_name, approver_id):
        self.id = id
        self.instance_id = instance_id
        self.node_id = node_id
        self.node_name = node_name
        self.approver_id = approver_id
        self.origin_approver_id = None
        self.status = "pending"


class FakeWorkflowRepo:
    """模拟 WorkflowRepository：以内存列表模拟超时扫描与升级标记。"""

    def __init__(self, instances, pending_by_instance=None):
        self._instances = list(instances)
        self._pending = pending_by_instance or {}
        self.escalated_calls = []
        self.add_log_calls = []

    async def list_running_overdue(self, sla_days):
        # 与真实仓储一致：仅返回 escalated_at IS NULL 的实例（幂等边界）
        return [i for i in self._instances if i.escalated_at is None]

    async def mark_escalated(self, instance_id):
        self.escalated_calls.append(instance_id)
        inst = next((i for i in self._instances if i.id == instance_id), None)
        if inst is not None:
            inst.escalated_at = datetime.now(timezone.utc)

    async def list_pending_tasks(self, instance_id):
        return list(self._pending.get(instance_id, []))

    async def add_log(self, log):
        self.add_log_calls.append(log)


class FakeUserRepo:
    def __init__(self, by_roles):
        self._by_roles = by_roles  # {"admin": [10], "manager": [20]}
        self.calls = []

    async def list_ids_by_roles(self, role_names):
        self.calls.append(list(role_names))
        ids = []
        for r in role_names:
            ids.extend(self._by_roles.get(r, []))
        return ids


class FakeNotificationService:
    def __init__(self, raise_on_notify=False):
        self.notified = []
        self.raise_on_notify = raise_on_notify

    async def notify_many(self, user_ids, ntype, title, body, link=""):
        if self.raise_on_notify:
            raise RuntimeError("notify failed (simulated)")
        self.notified.append(
            {"user_ids": user_ids, "ntype": ntype, "title": title, "body": body, "link": link}
        )
        return len(user_ids)


class FakeSchedulerRepo:
    def __init__(self, existing_dead=None):
        # 已存在的死信集合：set of (task_name, ref_id)
        self._existing = set(existing_dead or [])
        self.written = []

    async def exists_dead_letter(self, task_name, ref_id):
        return (task_name, ref_id) in self._existing

    async def write_dead_letter(self, task_name, ref_id, payload, error):
        self._existing.add((task_name, ref_id))
        self.written.append(
            {"task_name": task_name, "ref_id": ref_id, "payload": payload, "error": error}
        )


def _make_service(instances, *, pending=None, roles=None, notify_raise=False, existing_dead=None):
    """装配一个用 Fake 注入的 WorkflowService，便于隔离测试。"""
    session = _FakeSession()
    wf = FakeWorkflowRepo(instances, pending)
    users = FakeUserRepo(roles or {})
    notif = FakeNotificationService(raise_on_notify=notify_raise)
    sched = FakeSchedulerRepo(existing_dead)
    svc = WorkflowService(
        session,
        workflow_repo=wf,
        user_repo=users,
        notification_service=notif,
        scheduler_repo=sched,
    )
    return svc, wf, users, notif, sched


def _settings(action="notify", fallback_role="admin", sla_days=3):
    s = Settings()
    s.workflow_timeout_action = action
    s.workflow_timeout_fallback_role = fallback_role
    s.workflow_sla_days = sla_days
    return s


async def test_unit_notify_only():
    """默认 notify 策略：通知 admin/manager，不重分配，标记已升级。"""
    inst = FakeInstance(1, "采购审批", datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc))
    svc, wf, users, notif, sched = _make_service(
        [inst], roles={"admin": [10, 11], "manager": [20]}
    )
    with mock.patch("app.core.config.get_settings", return_value=_settings("notify")):
        res = await svc.timeout_escalate_all(sla_days=3)

    assert res == {"scanned": 1, "escalated": 1, "reassigned": 0, "dead_letters": 0}
    assert notif.notified and notif.notified[0]["ntype"] == "workflow"
    assert notif.notified[0]["link"] == "/workflows/monitor"
    assert wf.escalated_calls == [1]
    assert users.calls[0] == ["admin", "manager"]


async def test_unit_escalate_reassigns():
    """escalate 策略：将待审批任务自动转交兜底角色审批人并留痕。"""
    inst = FakeInstance(1, "采购审批", datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc))
    # 原审批人为 manager(20)，兜底角色 supervisor 的成员为 30
    task = FakeTask(100, 1, "n1", "部门经理", approver_id=20)
    svc, wf, users, notif, sched = _make_service(
        [inst],
        pending={1: [task]},
        roles={"admin": [10, 11], "manager": [20], "supervisor": [30]},
    )
    with mock.patch(
        "app.core.config.get_settings",
        return_value=_settings("escalate", "supervisor"),
    ):
        res = await svc.timeout_escalate_all(sla_days=3)

    assert res["escalated"] == 1
    assert res["reassigned"] == 1
    assert task.approver_id == 30
    assert task.origin_approver_id == 20
    assert len(wf.add_log_calls) == 1
    assert wf.add_log_calls[0].action == "escalate"


async def test_unit_deadletter_skip():
    """已存在死信则跳过，避免重复轰炸通知。"""
    inst = FakeInstance(1, "X", datetime(2026, 1, 1, tzinfo=timezone.utc))
    svc, wf, users, notif, sched = _make_service(
        [inst], roles={"admin": [10]}, existing_dead=[("workflow_timeout", 1)]
    )
    with mock.patch("app.core.config.get_settings", return_value=_settings()):
        res = await svc.timeout_escalate_all(sla_days=3)

    assert res == {"scanned": 1, "escalated": 0, "reassigned": 0, "dead_letters": 0}
    assert notif.notified == []
    assert wf.escalated_calls == []


async def test_unit_deadletter_on_error():
    """通知失败应写入死信并保持未升级，供下一轮重试。"""
    inst = FakeInstance(1, "X", datetime(2026, 1, 1, tzinfo=timezone.utc))
    svc, wf, users, notif, sched = _make_service(
        [inst], roles={"admin": [10]}, notify_raise=True
    )
    with mock.patch("app.core.config.get_settings", return_value=_settings()):
        res = await svc.timeout_escalate_all(sla_days=3)

    assert res["escalated"] == 0
    assert res["dead_letters"] == 1
    assert sched.written and sched.written[0]["ref_id"] == 1
    # 未升级，下一轮扫描仍会命中（除非先存在死信）
    assert wf.escalated_calls == []


async def test_unit_idempotent_on_second_run():
    """幂等：首轮升级并标记，次轮扫描边界（escalated_at 非 NULL）返回 0。"""
    inst = FakeInstance(1, "X", datetime(2026, 1, 1, tzinfo=timezone.utc))
    svc, wf, users, notif, sched = _make_service([inst], roles={"admin": [10, 11]})
    with mock.patch("app.core.config.get_settings", return_value=_settings()):
        r1 = await svc.timeout_escalate_all(sla_days=3)
        r2 = await svc.timeout_escalate_all(sla_days=3)

    assert r1["escalated"] == 1
    assert r2["escalated"] == 0 and r2["scanned"] == 0
    assert len(notif.notified) == 1  # 仅通知一次


# ===================== 集成测试：真实 SQLite =====================
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


@pytest.fixture
def patch_settings():
    def _p(**kw):
        s = Settings()
        for k, v in kw.items():
            setattr(s, k, v)
        return mock.patch("app.core.config.get_settings", return_value=s)

    return _p


async def _seed(session, *, fallback_role="supervisor"):
    """构造 admin / manager / 兜底角色与用户、一个超时的运行中实例 + 一条待审批任务。"""
    admin = Role(name="admin")
    manager = Role(name="manager")
    sup = Role(name=fallback_role)
    session.add_all([admin, manager, sup])
    await session.flush()

    u_admin = User(
        username="admin1", email="a@x", full_name="管理员",
        hashed_password="x", role_id=admin.id,
    )
    u_mgr = User(
        username="mgr1", email="m@x", full_name="经理",
        hashed_password="x", role_id=manager.id,
    )
    u_sup = User(
        username="sup1", email="s@x", full_name="兜底",
        hashed_password="x", role_id=sup.id,
    )
    session.add_all([u_admin, u_mgr, u_sup])
    await session.flush()

    wfd = WorkflowDefinition(code="wf1", name="采购", status="published", current_version=1)
    session.add(wfd)
    await session.flush()
    wfv = WorkflowVersion(
        definition_id=wfd.id, version=1,
        graph={"nodes": [{"id": "n1", "type": "approval", "name": "经理审批"}], "edges": []},
        status="published",
    )
    session.add(wfv)
    await session.flush()

    old = datetime.utcnow() - timedelta(days=10)
    inst = WorkflowInstance(
        code="WF2026010100001", definition_id=wfd.id, version_id=wfv.id,
        title="超时采购单", initiator_id=u_admin.id, form_data={},
        current_nodes=["n1"], status="running", started_at=old,
    )
    session.add(inst)
    await session.flush()
    task = WorkflowTask(
        instance_id=inst.id, node_id="n1", node_name="经理审批",
        node_type="approval", approver_id=u_mgr.id, status="pending", seq=0,
    )
    session.add(task)
    await session.commit()
    return {"admin": u_admin, "mgr": u_mgr, "sup": u_sup, "inst": inst, "task": task}


async def test_integration_notify(session, patch_settings):
    data = await _seed(session)
    with patch_settings(workflow_timeout_action="notify", workflow_timeout_fallback_role="supervisor",
                       workflow_sla_days=3):
        svc = WorkflowService(session)
        res = await svc.timeout_escalate_all(sla_days=3)

    assert res["escalated"] == 1 and res["reassigned"] == 0
    notifs = (await session.execute(select(Notification))).scalars().all()
    assert len(notifs) >= 1
    assert any(n.type == "workflow" for n in notifs)
    await session.refresh(data["inst"])
    assert data["inst"].escalated_at is not None
    # 任务未重分配
    await session.refresh(data["task"])
    assert data["task"].approver_id == data["mgr"].id


async def test_integration_escalate(session, patch_settings):
    data = await _seed(session)
    with patch_settings(workflow_timeout_action="escalate", workflow_timeout_fallback_role="supervisor",
                       workflow_sla_days=3):
        svc = WorkflowService(session)
        res = await svc.timeout_escalate_all(sla_days=3)

    assert res["escalated"] == 1 and res["reassigned"] == 1
    await session.refresh(data["task"])
    assert data["task"].approver_id == data["sup"].id
    assert data["task"].origin_approver_id == data["mgr"].id
    logs = (
        await session.execute(select(WorkflowNodeLog).where(WorkflowNodeLog.action == "escalate"))
    ).scalars().all()
    assert len(logs) == 1


async def test_integration_idempotent(session, patch_settings):
    data = await _seed(session)
    with patch_settings(workflow_timeout_action="notify", workflow_sla_days=3):
        svc = WorkflowService(session)
        r1 = await svc.timeout_escalate_all(sla_days=3)
        r2 = await svc.timeout_escalate_all(sla_days=3)

    assert r1["escalated"] == 1
    assert r2["escalated"] == 0 and r2["scanned"] == 0
    # 确认数据库层面仅有一次升级标记
    await session.refresh(data["inst"])
    assert data["inst"].escalated_at is not None


# ===================== 直接运行入口（仅 Fake 单元测试） =====================
if __name__ == "__main__":
    async def _run():
        FAILED = []
        unit_tests = [
            test_unit_notify_only,
            test_unit_escalate_reassigns,
            test_unit_deadletter_skip,
            test_unit_deadletter_on_error,
            test_unit_idempotent_on_second_run,
        ]
        for t in unit_tests:
            try:
                await t()
                print(f"PASS | {t.__name__}")
            except AssertionError as e:
                print(f"FAIL | {t.__name__}: {e}")
                FAILED.append(t.__name__)
            except Exception as e:  # noqa: BLE001
                print(f"ERROR | {t.__name__}: {type(e).__name__}: {e}")
                FAILED.append(t.__name__)
        print("\n" + "=" * 46)
        if FAILED:
            print(f"失败 {len(FAILED)} 项: {', '.join(FAILED)}")
            sys.exit(1)
        print("全部通过")

    asyncio.run(_run())
