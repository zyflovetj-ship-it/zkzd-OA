"""HTTP 路由层集成测试：真实走 FastAPI 路由栈（非服务层直调）。

专门用于捕获服务层测试发现不了的问题：
- 路由顺序遮蔽（静态路径注册在 /{id} 之后 → 422/404）；
- 运行时 NameError / AttributeError（函数体内引用未导入的名字）；
- response_model 与 ORM 对象的序列化不兼容（from_attributes 等）。

运行：cd backend && pytest -q tests/test_http_integration.py
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.db import Base, SessionLocal, engine as app_engine
from app.api.deps import get_current_permissions, get_current_user
from app.main import app
from app.models import User
from app.seed import seed_initial_data


@pytest.fixture(autouse=True)
async def _db():
    """每个用例前建表 + 灌种子（幂等），确保审计中间件与业务表都在。"""
    async with app_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        await seed_initial_data(s)
    yield


@pytest.fixture
async def admin():
    async with SessionLocal() as s:
        res = await s.execute(select(User).where(User.username == "admin"))
        user = res.scalar_one()
        await s.refresh(user, ["role"])
        return user  # expire_on_commit=False：detach 后 role 仍可用


@pytest.fixture
async def client(admin):
    """带管理员身份的 HTTP 客户端（覆盖认证与权限依赖，直击路由层）。"""

    def _user() -> User:
        return admin

    async def _perms() -> list[str]:
        return ["*"]

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_current_permissions] = _perms
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# =========================================================================
# 静态通用回归：任何「先注册参数路由、后注册同形静态路由」都算遮蔽
# =========================================================================
def test_no_route_shadowing():
    """按注册顺序扫描：若某路由的路径被更早注册的路由 FULL 匹配，即为遮蔽。

    历史上踩过 3 次（/expenses/budgets、/official-docs/search、/next-doc-no），
    该测试一次性守住全部路由。
    """
    from fastapi.routing import APIRoute
    from starlette.routing import Match

    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path not in ("/health", "/ready")]
    issues: list[str] = []
    for i, route in enumerate(routes):
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            scope = {"type": "http", "method": method, "path": route.path, "headers": []}
            for earlier in routes[:i]:
                if not (route.methods & earlier.methods):
                    continue
                s = {"type": "http", "method": method, "path": route.path, "headers": []}
                match, _ = earlier.matches(s)
                if match == Match.FULL:
                    issues.append(
                        f"{method} {route.path} 被更早注册的 "
                        f"{sorted(earlier.methods & route.methods)[0]} {earlier.path} 遮蔽"
                    )
                    break
    assert not issues, "路由遮蔽：\n" + "\n".join(issues)


# =========================================================================
# 路由遮蔽回归：静态路径必须能被正确匹配（此前有 3 处 422/500 缺陷）
# =========================================================================
async def test_expense_budget_routes_are_not_shadowed(client):
    """GET /expenses/budgets 曾被 /{eid} 抢先匹配 → 422。"""
    code = _unique("BG")
    resp = await client.post("/api/expenses/budgets", json={
        "name": "测试预算", "code": code, "total_amount": 10000,
        "start_date": (date.today() - timedelta(days=30)).isoformat(),
        "end_date": (date.today() + timedelta(days=30)).isoformat(),
    })
    assert resp.status_code == 201, resp.text
    budget_id = resp.json()["id"]
    assert resp.json()["remaining"] == 10000.0  # ORM property 序列化

    resp = await client.get("/api/expenses/budgets")
    assert resp.status_code == 200, resp.text
    assert any(b["code"] == code for b in resp.json()["items"])

    resp = await client.get("/api/expenses/budgets/quota-check", params={
        "amount": 500, "occur_date": date.today().isoformat(),
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_budget"] is True

    resp = await client.patch(f"/api/expenses/budgets/{budget_id}", json={"total_amount": 20000})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_amount"] == 20000


async def test_official_doc_static_routes_are_not_shadowed(client):
    """GET /official-docs/search、/next-doc-no 曾被 /{did} 抢先匹配 → 422。"""
    resp = await client.get("/api/official-docs/next-doc-no", params={"direction": "in"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["doc_no"].startswith("SW-")

    resp = await client.get("/api/official-docs/search", params={"q": "不存在的内容XYZ"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 0


# =========================================================================
# 运行时错误回归：函数体内引用了未导入的名字 → 500
# =========================================================================
async def test_delegation_check_conflicts_route(client):
    """该路由此前引用未导入的 _to_utc_naive → 500。"""
    resp = await client.post("/api/workflows/delegations/check-conflicts", json={
        "to_user_id": 999999,
        "start_at": datetime.now().isoformat(),
        "end_at": (datetime.now() + timedelta(hours=8)).isoformat(),
    })
    # 受托人不存在 → 服务层 404（说明已正确走到业务逻辑，而非 NameError 500）
    assert resp.status_code in (200, 404), resp.text
    if resp.status_code == 200:
        assert "conflicts" in resp.json() and "blocking" in resp.json()


async def test_audit_export_route(client):
    """该路由此前引用未导入的 _now → 500。"""
    resp = await client.get("/api/audit/export")
    assert resp.status_code == 200, resp.text
    assert "content-type" in resp.headers


async def test_next_doc_no_preview_persists(client):
    """文号预览此前传 None 作为 session → AttributeError 500。"""
    first = await client.get("/api/official-docs/next-doc-no")
    assert first.status_code == 200, first.text
    # 创建公文后再预览，序号必须递增（证明 get_max_seq 真的查了库）
    resp = await client.post("/api/official-docs", json={
        "title": "集成测试公文", "direction": "in",
    })
    assert resp.status_code == 201, resp.text
    doc_id = resp.json()["id"]
    second = await client.get("/api/official-docs/next-doc-no")
    assert second.json()["seq"] == first.json()["seq"] + 1

    # 流转时间线：创建后至少有 create 事件
    tl = await client.get(f"/api/official-docs/{doc_id}/timeline")
    assert tl.status_code == 200, tl.text
    assert any(e["action"] == "create" for e in tl.json())

    # 全文检索能命中刚创建的公文
    hit = await client.get("/api/official-docs/search", params={"q": "集成测试公文"})
    assert hit.status_code == 200 and hit.json()["total"] >= 1


# =========================================================================
# 新增报表 / 审计 / 考勤端点冒烟
# =========================================================================
async def test_dashboard_cube_and_trends(client):
    resp = await client.get("/api/dashboard/cube", params={
        "metrics": "expense,workflow",
        "dimension": "month",
    })
    assert resp.status_code == 200, resp.text
    assert "expense" in resp.json()["data"] and "workflow" in resp.json()["data"]

    resp = await client.get("/api/dashboard/trends", params={"days": 14})
    assert resp.status_code == 200, resp.text
    assert resp.json()["days"] == 14


async def test_org_aggregates_require_report_view(admin):
    """cube/trends 是全公司聚合，无 report:view 的用户必须 403（与看板同源授权）。"""
    from httpx import ASGITransport, AsyncClient

    async def _perms() -> list[str]:
        return ["dashboard:view"]  # 普通员工：有工作台，但无报表中心

    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_current_permissions] = _perms
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            assert (await c.get("/api/dashboard/cube")).status_code == 403
            assert (await c.get("/api/dashboard/trends")).status_code == 403
    finally:
        app.dependency_overrides.clear()


async def test_attendance_template_and_alerts(client):
    resp = await client.get("/api/attendance/import/template")
    assert resp.status_code == 200, resp.text
    assert "spreadsheet" in resp.headers["content-type"]

    resp = await client.get("/api/attendance/alerts", params={
        "start": (date.today() - timedelta(days=7)).isoformat(),
        "end": date.today().isoformat(),
    })
    assert resp.status_code == 200, resp.text
    assert "alerts" in resp.json() and "by_type" in resp.json()


async def test_invoice_verify_and_batch_pay(client):
    resp = await client.post("/api/expenses/invoice/verify", json={
        "invoice_no": "12345678",
        "amount": 100,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] in ("verified", "failed") and len(body["checks"]) >= 2

    resp = await client.post("/api/expenses/batch-pay", json={
        "expense_ids": [999999],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["failed"] == 1  # 不存在的单据走失败分支，不抛 500


async def test_attendance_import_dry_run_over_http(client):
    """导入端点 multipart 上传 + dry_run 预检（此前只测过服务层）。"""
    import io
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["用户名", "日期", "上班时间", "下班时间", "状态"])
    ws.append(["admin", date.today().isoformat(), "09:00", "18:00", "normal"])
    buf = io.BytesIO()
    wb.save(buf)
    resp = await client.post(
        "/api/attendance/import",
        params={"dry_run": "true"},
        files={"file": ("t.xlsx", buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["dry_run"] is True
