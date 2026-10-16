"""阶段三增量优化测试：报销额度（实时聚合 + 提交拦截）/ 发票验真 / 批量打款。

重点回归：预算用量曾因 used_amount 无人回写而恒为 0（额度形同虚设），
本文件锁定「用量按在途单据实时聚合 + 超额拒绝提交」的行为。

运行：cd backend && pytest -q tests/test_phase3_expense_finance.py
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.db import Base
from app.core.errors import ValidationError
from app.models import Budget, ExpenseClaim, Notification, Role, User
from app.seed import seed_initial_data
from app.services import BatchPaymentService, BudgetService, ExpenseService, InvoiceService


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


async def _budget(session, total: float = 100.0, code: str = "BG-TEST",
                  category: str | None = None) -> Budget:
    return await BudgetService(session).create({
        "name": "测试预算", "code": code, "total_amount": total,
        "start_date": date.today() - timedelta(days=30),
        "end_date": date.today() + timedelta(days=30),
        "category": category,
    })


async def _claim(session, user: User, amount: float, *, with_attachment: bool = True) -> ExpenseClaim:
    return await ExpenseService(session).create(user.id, {
        "amount": amount,
        "occur_date": date.today(),
        "claim_type": "daily",
        "description": "测试报销",
        "attachments": [{"document_id": 1, "title": "发票"}] if with_attachment else [],
    })


# =========================================================================
# 额度
# =========================================================================
async def test_quota_counts_submitted_claims_in_realtime(session):
    """在途单据必须占用额度（回归：used_amount 曾无人回写 → 永远不扣减）。"""
    user = await _user(session, "budget_user")
    await seed_initial_data(session)  # 提供 expense-claim 预置流程
    await _budget(session, total=100.0)

    svc = BudgetService(session)
    # 草稿不占额度（附件仅在提交时才被要求，草稿可先不挂）
    draft = await _claim(session, user, 60.0)
    check = await svc.check_quota(amount=50, category="daily",
                                  department_id=None, occur_date=date.today())
    assert check["remaining"] == 100.0

    # 提交后占用额度：剩余额度 100 - 60 = 40
    exp = ExpenseService(session)
    await exp.submit(draft.id, user)
    check = await svc.check_quota(amount=50, category="daily",
                                  department_id=None, occur_date=date.today())
    assert check["has_budget"] and check["exceeded"] is True
    assert check["remaining"] == 40.0
    assert "超出预算" in check["message"]

    # 额度快照已回写到报销单
    claim = await exp.get(draft.id)
    assert claim.budget_id is not None and claim.remaining_quota == 40.0


async def test_over_quota_blocks_submit(session):
    """超额报销必须在提交阶段被拒绝，且不产生流程实例。"""
    user = await _user(session, "over_user")
    await seed_initial_data(session)
    await _budget(session, total=100.0)

    claim = await _claim(session, user, 150.0)
    with pytest.raises(ValidationError, match="超出预算"):
        await ExpenseService(session).submit(claim.id, user)

    fresh = await ExpenseService(session).get(claim.id)
    assert fresh.status == "draft" and fresh.workflow_instance_id is None


async def test_budget_list_shows_real_usage(session):
    """列表返回的 used_amount/remaining 必须是真实占用，而非缓存列 0。"""
    user = await _user(session, "list_user")
    await seed_initial_data(session)
    await _budget(session, total=200.0, code="BG-LIST")

    claim = await _claim(session, user, 50.0)
    await ExpenseService(session).submit(claim.id, user)

    data = await BudgetService(session).list()
    item = next(b for b in data["items"] if b["code"] == "BG-LIST")
    assert item["used_amount"] == 50.0
    assert item["remaining"] == 150.0


async def test_budget_category_scope(session):
    """类别限定的预算不应被其它类别单据占用。"""
    await _budget(session, total=100.0, code="BG-TRAVEL", category="travel")
    check = await BudgetService(session).check_quota(
        amount=10, category="daily", department_id=None, occur_date=date.today()
    )
    assert check["has_budget"] is False  # daily 无预算 → 不拦截


# =========================================================================
# 发票验真
# =========================================================================
def test_uscc_check_digit():
    """统一社会信用代码校验位（GB 32100-2015）：正确通过、改一位失败。"""
    calc = InvoiceService.verify_uscc
    # 构造 17 位主体，按算法求校验位 → 应通过（自洽性 + 位权/字符集逻辑）
    body = "91110000100000016"
    total = sum(InvoiceService._USCC_CHARS.index(body[i]) * InvoiceService._USCC_WEIGHTS[i]
                for i in range(17))
    check = InvoiceService._USCC_CHARS[(total % 31 + 1) % 31]
    assert calc(body + check)["valid"] is True
    # 篡改校验位 → 失败
    wrong = "0" if check != "0" else "1"
    assert calc(body + wrong)["valid"] is False
    # 长度 / 非法字符
    assert calc("123")["valid"] is False
    assert calc(body + "I")["valid"] is False  # I 不在合法字符集


async def test_invoice_verify_endpoint_shape(session):
    """验真返回逐项 checks：格式 + 唯一性 + 金额。"""
    result = await InvoiceService(session).verify_invoice(
        invoice_no="12345678", amount=99.5
    )
    names = {c["name"] for c in result["checks"]}
    assert {"format", "uniqueness", "amount"} <= names
    assert result["status"] in ("verified", "failed")


# =========================================================================
# 批量打款
# =========================================================================
async def test_batch_pay_success_and_failures(session):
    """已通过 → 打款成功并通知申请人；非已通过 → 记入失败明细不抛异常。"""
    user = await _user(session, "pay_user")
    exp_svc = ExpenseService(session)
    ok_claim = await _claim(session, user, 80.0)
    bad_claim = await _claim(session, user, 30.0)  # 仍为 draft
    # 手动置为已通过（模拟流程回写）
    ok_claim.status = "approved"
    await session.commit()

    result = await BatchPaymentService(session).batch_pay([ok_claim.id, bad_claim.id, 999999], user)
    assert result["total"] == 3 and result["success"] == 1 and result["failed"] == 2
    by_id = {r["id"]: r for r in result["results"]}
    assert by_id[ok_claim.id]["success"] is True
    assert "draft" in by_id[bad_claim.id]["error"]
    assert "不存在" in by_id[999999]["error"]

    paid = await exp_svc.get(ok_claim.id)
    assert paid.status == "paid" and paid.paid_at is not None
    notes = (await session.execute(
        select(Notification).where(Notification.user_id == user.id)
    )).scalars().all()
    assert any("已打款" in n.title for n in notes)
