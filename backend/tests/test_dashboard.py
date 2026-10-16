"""报表中心（DashboardService）集成测试：真实 SQLite，覆盖个人视图与组织级聚合。

运行（标准环境）：cd backend && pytest -q tests/test_dashboard.py
沙箱限制：openharmony 未装 sqlalchemy/pytest，仅做 compileall 语法校验。
"""
import os
import sys
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.db import Base
from app.models import (
    Announcement,
    AuditLog,
    Department,
    LeaveRequest,
    Notification,
    Role,
    User,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowTask,
    WorkflowVersion,
)
from app.services import DashboardService


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


async def _seed(session):
    """构造：2 角色 / 1 部门 / 2 用户 / 1 流程实例 + 1 待办 / 通知 / 公告 / 审计 / 请假。"""
    admin = Role(name="admin")
    manager = Role(name="manager")
    session.add_all([admin, manager])
    await session.flush()

    dept = Department(name="研发部")
    session.add(dept)
    await session.flush()

    u_admin = User(
        username="rep_admin", email="a@x", full_name="管理员",
        hashed_password="x", role_id=admin.id, department_id=dept.id,
    )
    u_mgr = User(
        username="rep_mgr", email="m@x", full_name="经理",
        hashed_password="x", role_id=manager.id, department_id=dept.id,
    )
    session.add_all([u_admin, u_mgr])
    await session.flush()

    wfd = WorkflowDefinition(code="rep_wf", name="报表流程", status="published", current_version=1)
    session.add(wfd)
    await session.flush()
    wfv = WorkflowVersion(
        definition_id=wfd.id, version=1,
        graph={"nodes": [{"id": "n1", "type": "approval", "name": "审批"}], "edges": []},
        status="published",
    )
    session.add(wfv)
    await session.flush()

    inst = WorkflowInstance(
        code="REP-001", definition_id=wfd.id, version_id=wfv.id,
        title="报表流程单", initiator_id=u_mgr.id, form_data={},
        current_nodes=["n1"], status="running",
        started_at=datetime.utcnow() - timedelta(days=5),
    )
    session.add(inst)
    await session.flush()
    task = WorkflowTask(
        instance_id=inst.id, node_id="n1", node_name="审批",
        node_type="approval", approver_id=u_admin.id, status="pending", seq=0,
    )
    session.add(task)

    session.add(Notification(user_id=u_admin.id, type="workflow", title="待处理", is_read=False))
    session.add(Announcement(title="公告", content="", author_id=u_admin.id))
    session.add(AuditLog(actor_id=u_admin.id, actor_name="管理员", module="wf",
                         action="approve", status="success", message="审批通过"))
    today = datetime.utcnow().date()
    session.add(LeaveRequest(
        user_id=u_mgr.id, leave_type="annual", start_date=today, end_date=today,
        status="pending",
    ))
    await session.commit()
    return {"admin": u_admin, "mgr": u_mgr, "inst": inst}


async def test_dashboard_personal_only(session):
    """无 report:view 时：个人视图恒返回，组织级为 None。"""
    data = await _seed(session)
    out = await DashboardService(session).overview(data["admin"], has_org_scope=False)

    assert out["has_org_scope"] is False
    assert out["org"] is None
    p = out["personal"]
    # admin：1 条未读通知、1 条待审批任务、0 请假、0 在途（实例由 mgr 发起）
    assert p["my_unread"] == 1
    assert p["my_pending_approvals"] == 1
    assert p["my_leaves"] == 0
    assert p["my_running"] == 0
    assert out["generated_at"] is not None


async def test_dashboard_org_scope(session):
    """持 report:view 时：返回组织级 KPI、状态分布、30 天趋势、部门人数与最近动态。"""
    data = await _seed(session)
    out = await DashboardService(session).overview(data["mgr"], has_org_scope=True)

    assert out["has_org_scope"] is True
    p = out["personal"]
    # mgr 发起了那条在途实例，且有 1 条本月请假
    assert p["my_running"] == 1
    assert p["my_leaves"] == 1

    org = out["org"]
    assert org is not None
    kpi = org["kpi"]
    assert kpi["users_total"] == 2
    assert kpi["departments_total"] == 1
    assert kpi["workflow_instances"] == 1
    assert kpi["workflow_active"] == 1
    assert kpi["workflow_done"] == 0
    assert kpi["leaves_this_month"] == 1
    assert kpi["announcements_total"] == 1
    assert kpi["audit_total"] == 1

    assert org["workflow_status"][0]["status"] == "running"
    # 趋势窗口默认 30 天；5 天前发起的那条计入 started
    assert org["trend_days"] == 30
    assert len(org["workflow_trend"]) == 30
    assert sum(pt["started"] for pt in org["workflow_trend"]) == 1
    assert any(d["department"] == "研发部" for d in org["department_headcount"])
    assert len(org["recent_activities"]) == 1
    assert org["recent_activities"][0]["type"] == "wf"


async def test_dashboard_export_tables(session):
    """export_tables 产出多张二维 CSV 表，覆盖 KPI/状态/趋势/部门/动态。"""
    data = await _seed(session)
    tables = await DashboardService(session).export_tables(30)

    # 五张主题表齐全
    for name in (
        "kpi.csv",
        "workflow_status.csv",
        "workflow_trend.csv",
        "department_headcount.csv",
        "recent_activities.csv",
    ):
        assert name in tables, f"缺失导出表 {name}"

    kpi = tables["kpi.csv"]
    assert kpi[0] == ["指标", "数值"]
    # 用户总数应为 2（admin + mgr）
    user_row = next(r for r in kpi[1:] if r[0] == "用户总数")
    assert user_row[1] == "2"

    status = tables["workflow_status.csv"]
    assert status[0] == ["状态", "数量"]
    # 运行状态已映射为中文「审批中」
    assert any(r[0] == "审批中" for r in status[1:])

    trend = tables["workflow_trend.csv"]
    assert trend[0] == ["日期", "发起", "完成"]
    assert len(trend) == 31  # 表头 + 30 天
    assert sum(int(r[1]) for r in trend[1:]) == 1

    dept = tables["department_headcount.csv"]
    assert dept[0] == ["部门", "人数"]
    assert any(r[0] == "研发部" for r in dept[1:])

    acts = tables["recent_activities.csv"]
    assert acts[0] == ["ID", "摘要", "模块", "结果", "操作人", "时间"]
    assert len(acts) == 2  # 表头 + 1 条动态
