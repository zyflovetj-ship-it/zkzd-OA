"""阶段一增量优化测试：考勤批量导入（预检/批量查询）+ 外勤关联 + 异常预警。

与既有测试同范式：真实内存 SQLite + 异步 fixture，不 mock 服务层。
运行：cd backend && pytest -q tests/test_phase1_attendance.py
"""
from __future__ import annotations

import io
import os
import sys
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.db import Base
from app.core.errors import ConflictError, ForbiddenError, ValidationError
from app.models import Attendance, FieldWorkOrder, Notification, Role, User
from app.seed import seed_initial_data
from app.services import AttendanceService


class FakeUpload:
    """模拟 starlette UploadFile.read()。"""

    def __init__(self, data: bytes):
        self._data = data

    async def read(self) -> bytes:
        return self._data


def build_xlsx(rows: list[list]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "考勤导入"
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


HEADER = ["用户ID", "用户名", "日期", "上班时间", "下班时间", "状态",
          "迟到分钟", "早退分钟", "工时分钟", "来源", "备注",
          "外勤", "外勤地址", "外勤备注"]


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
    await s.refresh(u, ["role"])  # 预载 role：服务层会读 reviewer.role.name
    return u


# =========================================================================
# 批量导入
# =========================================================================
async def test_import_dry_run_then_commit(session):
    user = await _user(session, "imp_user")
    svc = AttendanceService(session)
    data = build_xlsx([
        HEADER,
        [user.id, "", "2026-10-12", "08:55", "18:05", "normal", 0, 0, 550, "clock", "", "", "", ""],
        ["", user.username, "2026-10-13", "09:12", "18:00", "迟到", 12, 0, 528, "import", "中文状态", "", "", ""],
        ["", user.username, "2026-10-14", "", "", "奇怪状态", 0, 0, 0, "", "", "", "", ""],  # 非法状态
        ["", "no_such_user", "2026-10-15", "", "", "normal", 0, 0, 0, "", "", "", "", ""],  # 未知用户
    ])

    # 1) 预检：只校验不写库
    preview = await svc.import_attendance(FakeUpload(data), actor_id=1, dry_run=True)
    assert preview["dry_run"] is True
    assert preview["total"] == 4 and preview["created"] == 2
    assert len(preview["errors"]) == 2 and any("状态无法识别" in e for e in preview["errors"])
    assert any("未找到用户" in e for e in preview["errors"])
    assert (await session.execute(select(Attendance))).scalars().all() == []

    # 2) 正式导入：落库且状态/来源正确
    result = await svc.import_attendance(FakeUpload(data), actor_id=1, dry_run=False)
    assert result["created"] == 2 and result["errors"]
    recs = (await session.execute(select(Attendance).order_by(Attendance.day))).scalars().all()
    assert len(recs) == 2
    assert recs[1].status == "late" and recs[1].late_minutes == 12
    assert all(r.source == "import" for r in recs)

    # 3) 重复导入走更新而非新建（幂等）
    again = await svc.import_attendance(FakeUpload(data), actor_id=1)
    assert again["created"] == 0 and again["updated"] == 2
    assert len((await session.execute(select(Attendance))).scalars().all()) == 2


async def test_import_is_batched_not_per_row(session, engine):
    """50 行导入的 SQL 次数必须与行数无关（批量解析用户/记录，杜绝 N+1）。"""
    user = await _user(session, "batch_user")
    rows = [HEADER]
    for i in range(50):
        day = date(2026, 11 if i // 25 == 0 else 12, (i % 25) + 1)
        rows.append([user.id, "", day.isoformat(), "09:00", "18:00", "normal",
                     0, 0, 540, "import", "", "", "", ""])
    data = build_xlsx(rows)

    calls: list[str] = []

    def _count(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if statement.strip().upper().startswith("SELECT"):
            calls.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _count)
    try:
        result = await AttendanceService(session).import_attendance(
            FakeUpload(data), actor_id=1
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _count)
    assert result["created"] == 50 and not result["errors"]
    # 逐行实现至少 50 次 SELECT；批量实现应在 10 次以内
    assert len(calls) <= 10, f"导入触发 {len(calls)} 次 SELECT，疑似 N+1"


async def test_import_rejects_bad_time_order(session):
    user = await _user(session, "imp_bad")
    data = build_xlsx([
        HEADER,
        [user.id, "", "2026-10-12", "18:00", "09:00", "normal", 0, 0, 0, "", "", "", "", ""],
    ])
    result = await AttendanceService(session).import_attendance(FakeUpload(data), actor_id=1)
    assert any("下班时间必须晚于上班时间" in e for e in result["errors"])
    assert result["created"] == 0


# =========================================================================
# 外勤关联
# =========================================================================
async def test_field_work_flow_links_clock(session):
    user = await _user(session, "fw_user")
    manager = await _user(session, "fw_mgr", role_name="manager")
    svc = AttendanceService(session)
    day = date(2026, 10, 12)

    order = await svc.create_field_work(user, {
        "start_date": day, "end_date": day,
        "address": "客户现场-中科园区", "purpose": "项目驻场",
    })
    assert order.status == "pending"

    # 重叠申请被拒
    with pytest.raises(ConflictError):
        await svc.create_field_work(user, {
            "start_date": day, "end_date": day, "address": "别处", "purpose": "",
        })

    # 不能审批自己的申请
    with pytest.raises(ForbiddenError):
        await svc.review_field_work(order.id, user, {"approve": True})

    approved = await svc.review_field_work(order.id, manager, {"approve": True, "comment": "同意"})
    assert approved.status == "approved" and approved.approver_id == manager.id

    # 迟到 1 小时打卡 → 外勤日免计迟到并自动挂接审批单
    rec, _ = await svc.clock(user, now=datetime(2026, 10, 12, 10, 0))
    assert rec.field_work_order_id == order.id
    assert rec.is_field_work is True
    assert rec.late_minutes == 0 and rec.status == "normal"
    assert rec.field_work_address == "客户现场-中科园区"

    # 早退 2 小时下班 → 同样免计
    rec, _ = await svc.clock(user, now=datetime(2026, 10, 12, 16, 0))
    assert rec.early_minutes == 0 and rec.check_out is not None

    # 申请人收到审批结果站内信
    notes = (await session.execute(
        select(Notification).where(Notification.user_id == user.id)
    )).scalars().all()
    assert any("外勤申请已通过" in n.title for n in notes)


async def test_field_work_list_and_pagination(session):
    user = await _user(session, "fw_list")
    other = await _user(session, "fw_other")
    svc = AttendanceService(session)
    for i in range(3):
        await svc.create_field_work(user, {
            "start_date": date(2026, 10, i + 1), "end_date": date(2026, 10, i + 1),
            "address": f"地点{i}", "purpose": "",
        })
    await svc.create_field_work(other, {
        "start_date": date(2026, 11, 1), "end_date": date(2026, 11, 1),
        "address": "别处", "purpose": "",
    })

    mine = await svc.list_field_work(user_id=user.id)
    assert mine["total"] == 3 and len(mine["items"]) == 3
    assert all(i["user_name"] == "fw_list" for i in mine["items"])

    filtered = await svc.list_field_work(
        user_id=user.id, status="pending", start=date(2026, 10, 2)
    )
    assert filtered["total"] == 2  # 10-02、10-03（10-01 已被区间过滤）


# =========================================================================
# 异常预警
# =========================================================================
async def test_attendance_alerts_detection(session):
    user = await _user(session, "alert_user")
    svc = AttendanceService(session)
    today = date.today()
    # 取最近 8 天里已经过去的工作日（缺勤/缺下班卡只对过去日期判定）
    past_workdays = sorted(
        d for d in (today - timedelta(days=i) for i in range(1, 9)) if d.isoweekday() <= 5
    )
    d1, d2, d3 = past_workdays[0], past_workdays[1], past_workdays[2]
    # d1：有上班无下班；d2：外勤但无审批单；d3：深夜打卡
    session.add(Attendance(
        user_id=user.id, day=d1,
        check_in=datetime.combine(d1, datetime.min.time()).replace(hour=9),
        check_out=None, status="late", late_minutes=5,
    ))
    session.add(Attendance(
        user_id=user.id, day=d2, status="normal", is_field_work=True,
    ))
    session.add(Attendance(
        user_id=user.id, day=d3,
        check_in=datetime.combine(d3, datetime.min.time()).replace(hour=23, minute=40),
        check_out=datetime.combine(d3 + timedelta(days=1), datetime.min.time()).replace(hour=6),
        status="normal", work_minutes=380,
    ))
    await session.commit()

    data = await svc.alerts(start=d1, end=today, threshold=3)
    types = {a["type"] for a in data["alerts"]}
    assert {"missing_checkout", "field_no_order", "night_clock", "absent"} <= types
    assert data["total"] == len(data["alerts"]) >= 4
    assert data["checked_users"] >= 1
    # 未来日期不判缺勤：只统计到今天为止
    future_absent = [a for a in data["alerts"] if a["type"] == "absent" and a["day"] and a["day"] > today]
    assert future_absent == []
    # level 排序：high 排最前
    assert data["alerts"][0]["level"] == "high"

    # 阈值收紧到 1 → 触发连续缺勤
    strict = await svc.alerts(start=d1, end=today, threshold=1)
    assert any(a["type"] == "long_absent" for a in strict["alerts"])

    # 区间超限被拒
    with pytest.raises(ValidationError):
        await svc.alerts(start=date(2026, 1, 1), end=date(2026, 12, 31))


async def test_attendance_alerts_respect_field_order_and_notify(session):
    user = await _user(session, "excused_user")
    svc = AttendanceService(session)
    await seed_initial_data(session)
    today = date.today()
    past_workdays = sorted(
        d for d in (today - timedelta(days=i) for i in range(1, 9)) if d.isoweekday() <= 5
    )
    covered_day = past_workdays[0]

    # 已通过外勤单覆盖 covered_day → 不算缺勤
    session.add(FieldWorkOrder(
        user_id=user.id, start_date=covered_day, end_date=covered_day,
        address="客户现场", status="approved",
    ))
    await session.commit()

    data = await svc.alerts(start=covered_day, end=covered_day, threshold=1)
    absent_days = [
        a for a in data["alerts"] if a["type"] == "absent" and a["user_id"] == user.id
    ]
    assert absent_days == []

    # 通知管理员（seed 后 admin 持有 att:manage）：该区间 admin 自己无记录 → 有缺勤预警
    res = await svc.notify_alerts(start=covered_day, end=covered_day, threshold=1)
    assert res["alert_count"] > 0 and res["notified_users"] >= 1
    admin_notes = (await session.execute(
        select(Notification).join(User, User.id == Notification.user_id).where(
            User.username == "admin"
        )
    )).scalars().all()
    assert any("考勤异常预警" in n.title for n in admin_notes)
