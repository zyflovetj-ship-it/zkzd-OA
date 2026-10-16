"""新功能测试：考勤 / 审批委托 / 报销（工作流回写）/ 公文 / 文档版本 / 公告回执 / 种子数据。

与既有测试同范式：真实内存 SQLite + 异步 fixture，不 mock 服务层（全栈专家 Phase 5 规范）。
每条用例对应本次新增能力的关键业务规则，防止后续改动回归。

运行：cd backend && pytest -q tests/test_features.py
"""
import os
import sys
from datetime import date, datetime, timedelta

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
from app.core.errors import ConflictError, ForbiddenError, ValidationError
from app.models import (
    Attendance,
    Menu,
    Notification,
    Permission,
    Role,
    User,
    WorkflowDefinition,
    WorkflowVersion,
)
from app.schemas import AnnouncementCreate, WorkflowInstanceCreate, WorkflowReview
from app.seed import EXPENSE_WF_CODE, seed_initial_data
from app.services import (
    AnnouncementService,
    AttendanceService,
    DelegationService,
    ExpenseService,
    OfficialDocService,
    WorkflowService,
)


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
    u = User(
        username=username, email="", full_name=username,
        hashed_password="x", role_id=role.id,
    )
    s.add(u)
    await s.commit()
    await s.refresh(u)
    return u


async def _user_with_role(s: AsyncSession, uid: int) -> User:
    res = await s.execute(
        select(User).where(User.id == uid).options(selectinload(User.role))
    )
    return res.scalar_one()


async def _seed_expense_flow(s: AsyncSession) -> WorkflowDefinition:
    """内置报销流程：start → approval(角色 admin) → end，已发布。"""
    admin_role = (await s.execute(select(Role).where(Role.name == "admin"))).scalar_one_or_none()
    if admin_role is None:
        admin_role = Role(name="admin")
        s.add(admin_role)
        await s.flush()
    admin = User(
        username="flow_admin", email="", full_name="审批管理员",
        hashed_password="x", role_id=admin_role.id,
    )
    s.add(admin)
    await s.flush()
    d = WorkflowDefinition(
        code=EXPENSE_WF_CODE, name="费用报销审批", category="expense",
        status="published", current_version=1,
    )
    s.add(d)
    await s.flush()
    s.add(
        WorkflowVersion(
            definition_id=d.id, version=1, status="published",
            graph={
                "nodes": [
                    {"id": "start", "type": "start", "name": "发起"},
                    {"id": "approve", "type": "approval", "name": "审批",
                     "assignee": {"type": "role", "value": "admin"}},
                    {"id": "end", "type": "end", "name": "结束"},
                ],
                "edges": [
                    {"source": "start", "target": "approve"},
                    {"source": "approve", "target": "end"},
                ],
            },
        )
    )
    await s.commit()
    return d


# =========================================================================
# 考勤
# =========================================================================
async def test_attendance_settings_roundtrip(session):
    svc = AttendanceService(session)
    # 未初始化：返回可用默认值而不是全 None（否则响应模型 500）
    default = await svc.get_settings()
    assert default.work_start == "09:00" and default.workdays == [1, 2, 3, 4, 5]

    saved = await svc.save_settings(1, {"work_start": "08:30", "workdays": [1, 2, 3, 4, 5, 6]})
    assert saved.work_start == "08:30"
    assert (await svc.get_settings()).workdays == [1, 2, 3, 4, 5, 6]

    with pytest.raises(ValidationError):
        await svc.save_settings(1, {"workdays": [1, 1, 2]})


async def test_attendance_clock_late_and_early(session):
    user = await _user(session, "att_user")
    svc = AttendanceService(session)
    day = date(2026, 10, 12)  # 周一，工作日

    # 上班迟到 30 分钟（班次 09:00，无宽限）
    rec, msg = await svc.clock(user, now=datetime(2026, 10, 12, 9, 30))
    assert rec.check_in is not None and rec.late_minutes == 30
    assert rec.status == "late" and "迟到" in msg

    # 下班早退 60 分钟（09:30 打卡 → 17:00 下班 = 7.5 小时）
    rec, msg = await svc.clock(user, now=datetime(2026, 10, 12, 17, 0))
    assert rec.check_out is not None and rec.early_minutes == 60
    assert rec.work_minutes == 7 * 60 + 30 and "早退" in msg

    # 第三次打卡应被拒绝
    with pytest.raises(ValidationError):
        await svc.clock(user, now=datetime(2026, 10, 12, 19, 0))

    summary = (await svc.my_month(user.id, "2026-10"))["summary"]
    assert summary["expected_workdays"] > 0
    assert summary["present_days"] == 1
    assert summary["late_days"] == 1 and summary["early_days"] == 1


async def test_attendance_manual_mark_and_stats(session):
    user = await _user(session, "att_user2")
    svc = AttendanceService(session)
    # 1) 打过卡后被管理员改成请假：记录保留，状态/来源被修正
    rec, _ = await svc.clock(user, now=datetime(2026, 10, 13, 8, 55))
    updated = await svc.update_record(rec.id, {"status": "leave", "note": "调休"})
    assert updated.status == "leave" and updated.source == "manual"
    assert updated.late_minutes == 0  # 08:55 早于 09:00，本就无迟到

    # 2) 预先标记的请假（当天没打卡）：计入「免出勤」，不算缺勤也不算出勤
    session.add(Attendance(user_id=user.id, day=date(2026, 10, 14), status="leave"))
    await session.commit()

    stats = await svc.stats("2026-10")
    row = next(r for r in stats["rows"] if r["user_id"] == user.id)
    assert row["present_days"] == 1  # 只有 13 日有打卡
    assert row["absent_days"] == max(0, stats["expected_workdays"] - 2)


async def test_overtime_review_rules(session):
    user = await _user(session, "ot_user")
    reviewer = await _user(session, "ot_reviewer", role_name="manager")
    svc = AttendanceService(session)
    today = date.today()

    ot = await svc.create_overtime(user.id, {"day": today, "hours": 2, "reason": "上线支持"})
    assert ot.status == "pending"

    # 同一天重复提交被拒
    with pytest.raises(ConflictError):
        await svc.create_overtime(user.id, {"day": today, "hours": 1, "reason": "again"})

    reviewer = await _user_with_role(session, reviewer.id)
    done = await svc.review_overtime(ot.id, reviewer, {"approve": True, "comment": "ok"})
    assert done.status == "approved" and done.approver_id == reviewer.id

    # 已处理的不能重复审批
    with pytest.raises(ValidationError):
        await svc.review_overtime(ot.id, reviewer, {"approve": False, "comment": "no"})


# =========================================================================
# 审批委托
# =========================================================================
async def test_delegation_crud_and_validation(session):
    me = await _user(session, "del_owner")
    other = await _user(session, "del_target")
    actor = await _user_with_role(session, me.id)
    svc = DelegationService(session)

    start = datetime(2026, 10, 1, 9, 0)
    end = datetime(2026, 10, 7, 18, 0)
    row = await svc.create(actor, {
        "to_user_id": other.id, "start_at": start, "end_at": end,
    })
    assert row["from_user_id"] == me.id and row["to_user_id"] == other.id
    assert row["to_user_name"] == "del_target"

    # 不能委托给自己 / 时间倒挂 / 受托人不存在
    with pytest.raises(ValidationError):
        await svc.create(actor, {"to_user_id": me.id, "start_at": start, "end_at": end})
    with pytest.raises(ValidationError):
        await svc.create(actor, {"to_user_id": other.id, "start_at": end, "end_at": start})
    from app.core.errors import NotFoundError
    with pytest.raises(NotFoundError):
        await svc.create(actor, {"to_user_id": 99999, "start_at": start, "end_at": end})

    # 列表只看到自己的；停用后仍在列表
    listed = await svc.list(mine=actor)
    assert len(listed) == 1
    updated = await svc.update(actor, row["id"], {"active": False})
    assert updated["active"] is False

    # 他人不能删自己的委托
    other_actor = await _user_with_role(session, other.id)
    with pytest.raises(ForbiddenError):
        await svc.delete(other_actor, row["id"])
    await svc.delete(actor, row["id"])
    assert await svc.list(mine=actor) == []


async def test_delegation_applies_to_workflow_assignee(session):
    """委托生效：原审批人的待办自动派给受托人（引擎 _resolve_assignees）。"""
    approver = await _user(session, "wf_approver", role_name="manager")
    delegate = await _user(session, "wf_delegate", role_name="employee")
    initiator = await _user(session, "wf_initiator")

    graph = {
        "nodes": [
            {"id": "start", "type": "start", "name": "发起"},
            {"id": "approve", "type": "approval", "name": "审批",
             "assignee": {"type": "user", "value": approver.id}},
            {"id": "end", "type": "end", "name": "结束"},
        ],
        "edges": [{"source": "start", "target": "approve"},
                  {"source": "approve", "target": "end"}],
    }
    d = WorkflowDefinition(code="WF-DELEG", name="委托流程", status="published", current_version=1)
    session.add(d)
    await session.flush()
    session.add(WorkflowVersion(definition_id=d.id, version=1, graph=graph, status="published"))
    await session.commit()

    actor = await _user_with_role(session, approver.id)
    await DelegationService(session).create(actor, {
        "to_user_id": delegate.id,
        "start_at": datetime.now() - timedelta(hours=1),
        "end_at": datetime.now() + timedelta(days=3),
    })

    wf = WorkflowService(session)
    inst = await wf.start_instance(
        initiator.id, WorkflowInstanceCreate(definition_id=d.id, title="委托生效测试")
    )
    tasks = [t for t in inst.tasks if t.status == "pending"]
    assert tasks, "应生成审批待办"
    assert tasks[0].approver_id == delegate.id, "待办应派给受托人"
    assert tasks[0].origin_approver_id is None  # 委托是分派期生效，不是转办


# =========================================================================
# 报销（工作流接入）
# =========================================================================
async def test_expense_lifecycle_with_workflow(session):
    claimant = await _user(session, "exp_user")
    await _seed_expense_flow(session)
    svc = ExpenseService(session)
    actor = await _user_with_role(session, claimant.id)

    # 1) 草稿：单号规则、金额校验
    claim = await svc.create(claimant.id, {
        "claim_type": "travel", "amount": 888.5,
        "occur_date": date(2026, 10, 9), "description": "高铁票",
        "attachments": [{"document_id": 1, "title": "发票", "file_url": "/api/documents/1/file"}],
    })
    assert claim.code.startswith(f"BX{datetime.now():%Y%m%d}") and claim.status == "draft"
    with pytest.raises(ValidationError):
        await svc.create(claimant.id, {"amount": 0, "occur_date": date(2026, 10, 9)})

    # 2) 无附件不可提交
    bare = await svc.create(claimant.id, {
        "amount": 10, "occur_date": date(2026, 10, 9), "attachments": [],
    })
    with pytest.raises(ValidationError):
        await svc.submit(bare.id, actor)

    # 3) 提交 → 发起流程
    submitted = await svc.submit(claim.id, actor)
    assert submitted.status == "submitted" and submitted.workflow_instance_id

    # 4) 审批通过 → 报销单回写为 approved
    res = await session.execute(
        select(WorkflowDefinition).where(WorkflowDefinition.code == EXPENSE_WF_CODE)
    )
    definition = res.scalar_one()
    assert definition.status == "published"

    wf = WorkflowService(session)
    pending = await wf.repo.list_tasks_status("pending")
    expense_tasks = [t for t in pending if t.instance_id == submitted.workflow_instance_id]
    assert expense_tasks, "报销流程应生成待办"
    admin = (
        await session.execute(
            select(User).join(Role, Role.id == User.role_id).where(Role.name == "admin")
        )
    ).scalars().first()
    admin = (
        await session.execute(
            select(User).where(User.id == admin.id).options(selectinload(User.role))
        )
    ).scalar_one()
    await wf.decide_task(
        expense_tasks[0].id, admin,
        WorkflowReview(approve=True, comment="同意"),
    )

    after = await svc.get(claim.id)
    assert after.status == "approved" and after.approver_id == admin.id
    # 5) 打款
    paid = await svc.mark_paid(after.id, admin, {"paid": True})
    assert paid.status == "paid" and paid.paid_at is not None
    # 已打款的不能再删
    with pytest.raises(ValidationError):
        await svc.delete(after.id, admin)


async def test_expense_stats_and_scope(session):
    user = await _user(session, "exp_user2")
    svc = ExpenseService(session)
    await svc.create(user.id, {
        "amount": 100, "occur_date": date(2026, 10, 9), "claim_type": "daily",
    })
    await svc.create(user.id, {
        "amount": 200, "occur_date": date(2026, 10, 10), "claim_type": "travel",
    })
    stats = await svc.stats("2026-10")
    assert stats["total_count"] == 2 and stats["total_amount"] == 300
    by_type = {r["status"]: r["amount"] for r in stats["by_type"]}
    assert by_type["travel"] == 200

    page = await svc.list(user_id=user.id, status=None, month="2026-10", q=None)
    assert page["total"] == 2 and page["sum_amount"] == 300
    other = await svc.list(user_id=99999, status=None, month=None, q=None)
    assert other["total"] == 0


# =========================================================================
# 公文
# =========================================================================
async def test_official_doc_lifecycle(session):
    owner = await _user(session, "od_owner")
    actor = await _user_with_role(session, owner.id)
    svc = OfficialDocService(session)

    doc = await svc.create(actor, {
        "doc_no": "中科办〔2026〕1号", "title": "关于开展安全检查的通知",
        "direction": "in", "from_org": "集团公司", "secrecy": "internal",
        "content": "正文……",
    })
    assert doc.status == "draft"
    # 文号唯一
    with pytest.raises(ConflictError):
        await svc.create(actor, {"doc_no": "中科办〔2026〕1号", "title": "重复文号"})

    # 传阅：通知全员、状态置 circulated、记传阅人数
    circ = await svc.circulate(actor, doc.id, {"user_ids": [], "remark": "请阅"})
    assert circ.status == "circulated" and circ.read_count >= 1
    notifs = (await session.execute(select(Notification))).scalars().all()
    assert notifs, "传阅应产生通知"

    # 归档
    archived = await svc.archive(actor, doc.id)
    assert archived.status == "archived" and archived.archived_at is not None
    # 已归档不可编辑/删除
    with pytest.raises(ValidationError):
        await svc.update(archived.id, actor, {"title": "改"})
    with pytest.raises(ValidationError):
        await svc.delete(archived.id, actor)

    # 他人不可传阅
    other = await _user_with_role(session, (await _user(session, "od_other")).id)
    with pytest.raises(ForbiddenError):
        await svc.circulate(other, doc.id, {"user_ids": []})


# =========================================================================
# 公告阅读回执
# =========================================================================
async def test_announcement_attachments_and_read_receipt(session):
    author = await _user(session, "ann_author", role_name="manager")
    reader = await _user(session, "ann_reader")
    svc = AnnouncementService(session)

    ann = await svc.create(author.id, AnnouncementCreate(
        title="带附件的公告", content="见附件",
        attachments=[{"document_id": 7, "title": "方案.pdf", "file_url": "/api/documents/7/file"}],
    ))
    assert len(ann.attachments) == 1 and ann.read_count == 0

    first = await svc.mark_read(ann.id, reader.id)
    assert first["read"] and first["read_count"] == 1
    # 幂等：重复标记不重复计数
    second = await svc.mark_read(ann.id, reader.id)
    assert second["read_count"] == 1

    detail = await svc.readers(ann.id)
    assert detail["read_count"] == 1 and detail["total_users"] >= 1
    assert detail["readers"][0]["user_name"] == "ann_reader"


# =========================================================================
# 种子数据：新权限 / 新菜单 / 预置报销流程（幂等）
# =========================================================================
async def test_seed_adds_new_permissions_menus_and_expense_flow(session):
    await seed_initial_data(session)
    await seed_initial_data(session)  # 重复执行必须幂等

    perms = {p.code for p in (await session.execute(select(Permission))).scalars()}
    assert {
        "att:view", "att:manage",
        "expense:view", "expense:manage",
        "doc:official:view", "doc:official:manage",
    } <= perms

    menus = (await session.execute(select(Menu))).scalars().all()
    paths = {m.path for m in menus}
    assert {"/attendance", "/expenses", "/official-docs", "/workflows/delegations"} <= paths
    # 考勤分组的可见性权限已从 leave:view 迁到 att:view（旧库由 seed 同步）
    group = next(m for m in menus if m.name == "考勤请假" and not m.path)
    assert group.permission_code == "att:view"
    # 菜单排序已按新版调整（报销管理插在电子签单之后）
    by_path = {m.path: m.order for m in menus if m.path}
    assert by_path["/expenses"] == 1 and by_path["/reports"] == 11

    # 预置的报销审批流程：已发布 + 有已发布版本 + 图结构完整
    d = (
        await session.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.code == EXPENSE_WF_CODE)
        )
    ).scalar_one()
    assert d.status == "published" and d.current_version == 1
    ver = (
        await session.execute(
            select(WorkflowVersion).where(WorkflowVersion.definition_id == d.id)
        )
    ).scalars().first()
    assert ver is not None and ver.status == "published"
    assert [n["type"] for n in ver.graph["nodes"]] == ["start", "approval", "end"]
    assert all("source" in e and "target" in e for e in ver.graph["edges"])
