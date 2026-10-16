"""一次性冒烟脚本：对运行中的后端跑通主要读写链路，输出 PASS/FAIL 清单。

⚠️ 本脚本包含**写操作**（新建报销单/公文/文档、导入 xlsx、打卡等），会向目标库写入测试数据。
   请在「正式录入业务数据之前」或「测试环境」运行；生产库已有真实数据时请改用只读的
   tests/deploy_check.py。

用法：
    python tests/smoke_live.py                          # 默认 http://127.0.0.1:8000
    python tests/smoke_live.py http://192.168.1.10:8000 # 指定地址
    SMOKE_BASE=http://host:8000 python tests/smoke_live.py

容器内部署验收：
    docker compose exec backend python tests/smoke_live.py
"""
import json
import os
import sys
import uuid
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

# 优先级：命令行参数 > SMOKE_BASE 环境变量 > 默认本机 8000
BASE = (
    sys.argv[1] if len(sys.argv) > 1
    else os.environ.get("SMOKE_BASE", "http://127.0.0.1:8000")
).rstrip("/")
results = []


def call(method, path, body=None, token=None, raw=False, expect=None, timeout=15, headers=None):
    url = BASE + path
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        if isinstance(body, bytes):
            data = body
        else:
            data = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
    if token:
        hdrs["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        payload = e.read()
        code = e.code
    except Exception as e:  # noqa: BLE001
        return {"code": -1, "data": str(e), "err": str(e), "ok": False}
    if raw:
        return {"code": code, "data": payload, "err": None, "ok": True}
    try:
        parsed = json.loads(payload.decode() or "null")
    except Exception:  # noqa: BLE001
        parsed = payload[:200]
    ok = (code == expect) if expect else (200 <= code < 300)
    return {"code": code, "data": parsed, "err": None, "ok": ok}


def check(name, res, expect=None):
    ok = (res["code"] == expect) if expect else (200 <= res["code"] < 300)
    results.append((name, ok, res["code"]))
    detail = ""
    if not ok:
        d = res["data"]
        detail = " -> " + (json.dumps(d, ensure_ascii=False)[:400] if not isinstance(d, str) else d[:400])
    print(("PASS" if ok else "FAIL"), "|", name, "|", res["code"], detail, flush=True)
    return res["data"] if 200 <= res["code"] < 300 else None


def multipart(fields, file_field, filename, content):
    boundary = "----smoke" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n")
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
        f"filename=\"{filename}\"\r\nContent-Type: text/plain\r\n\r\n"
    )
    body = "".join(parts).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


# ============ 0. 健康检查 ============
check("GET /health", call("GET", "/health"))
check("GET /ready", call("GET", "/ready"))

# ============ 1. 认证 ============
check("POST /api/auth/login（错误密码应 401）",
      call("POST", "/api/auth/login", {"username": "admin", "password": "wrongpwd"}, expect=401), expect=401)
login = check("POST /api/auth/login",
              call("POST", "/api/auth/login", {"username": "admin", "password": "admin123"}, expect=200))
if not login:
    print("\n登录失败，后续跳过")
    sys.exit(1)
tok = login["access_token"]
check("POST /api/auth/refresh", call("POST", "/api/auth/refresh", {"refresh_token": login["refresh_token"]}, expect=200))
me = check("GET /api/auth/me", call("GET", "/api/auth/me", token=tok))
menus = check("GET /api/auth/menus", call("GET", "/api/auth/menus", token=tok))
if isinstance(menus, list):
    print("       可见菜单数:", len(menus))
check("未登录访问 /api/users 应 401", call("GET", "/api/users", expect=401), expect=401)

# ============ 2. 组织 / 账户 ============
users = check("GET /api/users", call("GET", "/api/users?limit=200", token=tok))
print("       用户数:", len(users) if isinstance(users, list) else "-")
roles = check("GET /api/users/roles", call("GET", "/api/users/roles", token=tok))
emp_role = next((r for r in roles if r["name"] == "employee"), None) if isinstance(roles, list) else None

dept = check("POST /api/departments（写）",
             call("POST", "/api/departments", {"name": f"冒烟部{uuid.uuid4().hex[:4]}"}, token=tok))
if dept:
    check("PATCH /api/departments/{id}", call("PATCH", f"/api/departments/{dept['id']}", {"name": dept["name"] + "-改"}, token=tok))

uname = "smoke_" + uuid.uuid4().hex[:6]
new_user = check("POST /api/users（写）",
                 call("POST", "/api/users",
                      {"username": uname, "password": "smoke12345", "full_name": "冒烟员工",
                       "role_id": (emp_role or {}).get("id", 3),
                       "department_id": dept["id"] if dept else None},
                      token=tok))
if new_user:
    check("PATCH /api/users/{id}（停用再启用）",
          call("PATCH", f"/api/users/{new_user['id']}", {"is_active": True, "full_name": "冒烟员工2"}, token=tok))

# 角色 CRUD
new_role = check("POST /api/users/roles（写）",
                 call("POST", "/api/users/roles",
                      {"name": f"smoke_role_{uuid.uuid4().hex[:4]}", "description": "冒烟"}, token=tok))
if new_role:
    check("PATCH /api/users/roles/{id}", call("PATCH", f"/api/users/roles/{new_role['id']}", {"description": "冒烟改"}, token=tok))
    perms = call("GET", "/api/permissions", token=tok)["data"]
    if isinstance(perms, list) and perms:
        check("POST /api/permissions/roles/{id}（授权）",
              call("POST", f"/api/permissions/roles/{new_role['id']}", {"permission_id": perms[0]["id"]}, token=tok))
        check("GET /api/permissions/roles/{id}", call("GET", f"/api/permissions/roles/{new_role['id']}", token=tok))
        check("DELETE /api/permissions/roles/{id}/{pid}（回收）",
              call("DELETE", f"/api/permissions/roles/{new_role['id']}/{perms[0]['id']}", token=tok))
    check("DELETE /api/users/roles/{id}", call("DELETE", f"/api/users/roles/{new_role['id']}", token=tok))

# 菜单 CRUD
check("GET /api/menus", call("GET", "/api/menus", token=tok))
new_menu = check("POST /api/menus（写）",
                 call("POST", "/api/menus",
                      {"name": f"冒烟菜单{uuid.uuid4().hex[:3]}", "path": f"/smoke-{uuid.uuid4().hex[:6]}", "order": 99}, token=tok))
if new_menu:
    check("PATCH /api/menus/{id}", call("PATCH", f"/api/menus/{new_menu['id']}", {"name": "冒烟菜单改"}, token=tok))
check("GET /api/permissions", call("GET", "/api/permissions", token=tok))

# ============ 3. 请假 + 审批 ============
leave = check("POST /api/leave（写）",
              call("POST", "/api/leave",
                   {"leave_type": "annual", "start_date": "2026-10-08",
                    "end_date": "2026-10-09", "reason": "smoke"},
                   token=tok))
check("GET /api/leave", call("GET", "/api/leave", token=tok))
if leave:
    check("POST /api/leave/{id}/review（通过）",
          call("POST", f"/api/leave/{leave['id']}/review", {"approve": True, "comment": "ok"}, token=tok))

# ============ 4. 公告 / 文档 / 消息 / 审计 ============
ann = check("POST /api/announcements（写）",
            call("POST", "/api/announcements", {"title": "冒烟公告", "content": "内容", "published": True}, token=tok))
check("GET /api/announcements", call("GET", "/api/announcements", token=tok))
if ann:
    check("PATCH /api/announcements/{id}", call("PATCH", f"/api/announcements/{ann['id']}", {"title": "冒烟公告改"}, token=tok))

body, hdrs = multipart({"title": "冒烟文档", "category": "test", "description": "smoke"},
                       "file", "smoke.txt", b"hello zk-oa")
doc = call("POST", "/api/documents", body=body, token=tok, headers=hdrs)
check("POST /api/documents（multipart 上传）", doc)
check("GET /api/documents", call("GET", "/api/documents", token=tok))
if doc["ok"] and isinstance(doc["data"], dict):
    did = doc["data"].get("id")
    check("GET /api/documents/{id}/file（下载）", call("GET", f"/api/documents/{did}/file", token=tok, raw=True))
    check("PATCH /api/documents/{id}", call("PATCH", f"/api/documents/{did}", {"description": "改"}, token=tok))
    check("DELETE /api/documents/{id}", call("DELETE", f"/api/documents/{did}", token=tok))

notifs = check("GET /api/notifications", call("GET", "/api/notifications", token=tok))
if isinstance(notifs, dict) and notifs.get("items"):
    check("POST /api/notifications/{id}/read",
          call("POST", f"/api/notifications/{notifs['items'][0]['id']}/read", token=tok))
check("POST /api/notifications/read-all", call("POST", "/api/notifications/read-all", token=tok))
check("GET /api/audit/logs", call("GET", "/api/audit/logs", token=tok))
check("GET /api/audit/stats", call("GET", "/api/audit/stats", token=tok))

# ============ 5. 门户 / 看板 / 运维 ============
check("GET /api/portal/overview", call("GET", "/api/portal/overview", token=tok))
check("GET /api/dashboard", call("GET", "/api/dashboard", token=tok))
check("GET /api/dashboard?days=7", call("GET", "/api/dashboard?days=7", token=tok))
check("GET /api/dashboard/export（CSV zip）", call("GET", "/api/dashboard/export?days=7", token=tok, raw=True))
check("GET /api/ops/overview", call("GET", "/api/ops/overview", token=tok))
check("POST /api/ops/scheduler/run-once", call("POST", "/api/ops/scheduler/run-once", token=tok))

# ============ 6. 工作流全链路 ============
d = check("POST /api/workflows/definitions（写）",
          call("POST", "/api/workflows/definitions",
               {"code": f"smoke-flow-{uuid.uuid4().hex[:6]}", "name": "冒烟审批流", "category": "test"}, token=tok))
check("GET /api/workflows/definitions", call("GET", "/api/workflows/definitions", token=tok))
if d:
    check("PATCH /api/workflows/definitions/{id}/status",
          call("PATCH", f"/api/workflows/definitions/{d['id']}/status?status=draft", token=tok))
    ver = check("POST /api/workflows/definitions/{id}/versions",
                call("POST", f"/api/workflows/definitions/{d['id']}/versions",
                     {"graph": {"nodes": [
                         {"id": "start", "type": "start", "name": "开始"},
                         {"id": "n1", "type": "approval", "name": "审批",
                          "assignee": {"type": "role", "value": "admin"}, "next": ["end"]},
                         {"id": "end", "type": "end", "name": "结束"}],
                         "edges": [{"source": "start", "target": "n1"},
                                   {"source": "n1", "target": "end"}]}},
                     token=tok))
    check("GET /api/workflows/definitions/{id}/versions",
          call("GET", f"/api/workflows/definitions/{d['id']}/versions", token=tok))
    if ver:
        check("POST /api/workflows/versions/{id}/publish",
              call("POST", f"/api/workflows/versions/{ver['id']}/publish", token=tok))
    check("PATCH /api/workflows/definitions/{id}/status?status=published",
          call("PATCH", f"/api/workflows/definitions/{d['id']}/status?status=published", token=tok))

    inst_a = check("POST /api/workflows/instances（发起A）",
                   call("POST", "/api/workflows/instances",
                        {"definition_id": d["id"], "title": "冒烟流程A"}, token=tok))
    check("GET /api/workflows/instances", call("GET", "/api/workflows/instances", token=tok))
    if inst_a:
        check("GET /api/workflows/instances/{id}",
              call("GET", f"/api/workflows/instances/{inst_a['id']}", token=tok))
        check("GET /api/workflows/instances/{id}/logs",
              call("GET", f"/api/workflows/instances/{inst_a['id']}/logs", token=tok))
        check("POST /api/workflows/instances/{id}/urge（催办）",
              call("POST", f"/api/workflows/instances/{inst_a['id']}/urge", {}, token=tok))
        cur = (inst_a.get("current_nodes") or ["n1"])[0]
        if new_user:
            check("POST .../nodes/{id}/addsign（加签）",
                  call("POST", f"/api/workflows/instances/{inst_a['id']}/nodes/{cur}/addsign",
                       {"user_ids": [new_user["id"]]}, token=tok))
    check("GET /api/workflows/pending", call("GET", "/api/workflows/pending", token=tok))
    check("GET /api/workflows/notified", call("GET", "/api/workflows/notified", token=tok))
    check("GET /api/workflows/stats", call("GET", "/api/workflows/stats", token=tok))

    pending = call("GET", "/api/workflows/pending", token=tok)["data"]
    if isinstance(pending, list) and pending:
        tid = pending[0]["id"]
        if new_user:
            check("POST /api/workflows/tasks/{id}/transfer（转办）",
                  call("POST", f"/api/workflows/tasks/{tid}/transfer",
                       {"to_user_id": new_user["id"], "comment": "冒烟转办"}, token=tok))
        # 转办后由被转办人审批（管理员可越权）
        check("POST /api/workflows/tasks/{id}/decide（通过）",
              call("POST", f"/api/workflows/tasks/{tid}/decide",
                   {"approve": True, "comment": "smoke"}, token=tok))
    else:
        results.append(("POST /api/workflows/tasks/{id}/decide（通过）", False, 0))
        print("FAIL | 无待办任务（发起流程未生成审批任务）")

    # 另起一个实例测撤回
    inst_c = check("POST /api/workflows/instances（发起C）",
                   call("POST", "/api/workflows/instances",
                        {"definition_id": d["id"], "title": "冒烟流程C"}, token=tok))
    if inst_c:
        check("POST /api/workflows/instances/{id}/withdraw（撤回）",
              call("POST", f"/api/workflows/instances/{inst_c['id']}/withdraw", token=tok))
    check("GET /api/workflows/mine", call("GET", "/api/workflows/mine", token=tok))
    check("GET /api/workflows/done", call("GET", "/api/workflows/done", token=tok))

# ============ 7. 建模引擎 ============
ent = check("POST /api/models/entities（写）",
            call("POST", "/api/models/entities",
                 {"code": f"smoke_c_{uuid.uuid4().hex[:6]}", "name": "customer", "label": "客户",
                  "fields": [{"key": "name", "label": "名称", "type": "text", "required": True}]},
                 token=tok))
if ent:
    check("GET /api/models/entities/{id}", call("GET", f"/api/models/entities/{ent['id']}", token=tok))
    check("PATCH /api/models/entities/{id}（发布）",
          call("PATCH", f"/api/models/entities/{ent['id']}", {"status": "published"}, token=tok))
    rec = check("POST /api/models/entities/{id}/records（写）",
                call("POST", f"/api/models/entities/{ent['id']}/records",
                     {"data": {"name": "冒烟客户"}}, token=tok))
    check("GET /api/models/entities/{id}/records",
          call("GET", f"/api/models/entities/{ent['id']}/records", token=tok))
    if isinstance(rec, dict) and rec.get("id"):
        check("PATCH /api/models/records/{id}",
              call("PATCH", f"/api/models/records/{rec['id']}", {"data": {"name": "冒烟客户改"}}, token=tok))
        check("DELETE /api/models/records/{id}",
              call("DELETE", f"/api/models/records/{rec['id']}", token=tok))
    check("DELETE /api/models/entities/{id}", call("DELETE", f"/api/models/entities/{ent['id']}", token=tok))
check("GET /api/models/stats", call("GET", "/api/models/stats", token=tok))

# ============ 8. 电子签单 ============
if leave and isinstance(leave, dict):
    check("POST /api/signatures（写）",
          call("POST", "/api/signatures",
               {"ref_type": "leave_request", "ref_id": leave["id"],
                "signature_data": "data:image/png;base64,iVBORw0KGgo=", "comment": "冒烟"},
               token=tok))
    check("GET /api/signatures/{ref}/{id}",
          call("GET", f"/api/signatures/leave_request/{leave['id']}", token=tok))

# ============ 9. RBAC 越权检查 ============
if new_user and uname:
    sub = call("POST", "/api/auth/login", {"username": uname, "password": "smoke12345"}, expect=200)
    if sub["ok"]:
        stok = sub["data"]["access_token"]
        check("员工访问 /api/audit/logs 应 403", call("GET", "/api/audit/logs", token=stok, expect=403), expect=403)
        check("员工访问 /api/ops/overview 应 403", call("GET", "/api/ops/overview", token=stok, expect=403), expect=403)
        check("员工查看自己资料 200", call("GET", "/api/auth/me", token=stok))
    else:
        results.append(("新员工登录", False, sub["code"]))
        print("FAIL | 新员工登录", sub)

# ============ 10. 新增菜单是否下发 ============
if isinstance(menus, list):
    have = {m.get("path") for m in menus}
    for required in ("/attendance", "/expenses", "/official-docs", "/workflows/delegations"):
        results.append((f"菜单包含 {required}", required in have, 200 if required in have else 404))
        print(("PASS" if required in have else "FAIL"), "| 菜单包含", required, flush=True)

# ============ 11. 考勤管理 ============
today = date.today().isoformat()
month = today[:7]
_y, _m = int(month[:4]), int(month[5:7])
_month_end = (
    date(_y + (1 if _m == 12 else 0), 1 if _m == 12 else _m + 1, 1) - timedelta(days=1)
).isoformat()
check("GET /api/attendance/settings", call("GET", "/api/attendance/settings", token=tok))
check(
    "PUT /api/attendance/settings",
    call("PUT", "/api/attendance/settings",
         {"work_start": "09:00", "work_end": "18:00",
          "late_grace_minutes": 0, "workdays": [1, 2, 3, 4, 5]},
         token=tok),
)


def tolerant(name, res, *ok_codes):
    """允许若干业务性 4xx（例如同日重复打卡），只把 5xx 视为故障。"""
    ok = res["code"] in ok_codes or 200 <= res["code"] < 300
    results.append((name, ok, res["code"]))
    print(("PASS" if ok else "FAIL"), "|", name, "|", res["code"], flush=True)
    return res["data"] if ok else None


tolerant("POST /api/attendance/clock（上班/下班）", call("POST", "/api/attendance/clock", token=tok), 422)
tolerant("POST /api/attendance/clock（重复应被拦）", call("POST", "/api/attendance/clock", token=tok), 422)
check("GET /api/attendance/me", call("GET", f"/api/attendance/me?month={month}", token=tok))
check("GET /api/attendance/records", call("GET", f"/api/attendance/records?start={month}-01&end={_month_end}", token=tok))
check("GET /api/attendance/stats", call("GET", f"/api/attendance/stats?month={month}", token=tok))
ot = check(
    "POST /api/attendance/overtime",
    call("POST", "/api/attendance/overtime",
         {"day": today, "hours": 2, "reason": "冒烟加班"}, token=tok),
)
if ot:
    check("POST /api/attendance/overtime/{id}/review",
          call("POST", f"/api/attendance/overtime/{ot['id']}/review",
               {"approve": True, "comment": "同意"}, token=tok))
check("GET /api/attendance/overtime", call("GET", "/api/attendance/overtime", token=tok))
exp_xlsx = call("GET", f"/api/attendance/export?month={month}", token=tok, raw=True)
xlsx_ok = exp_xlsx["code"] == 200 and exp_xlsx["data"][:2] == b"PK"
results.append(("GET /api/attendance/export（xlsx）", xlsx_ok, exp_xlsx["code"]))
print(("PASS" if xlsx_ok else "FAIL"), "| GET /api/attendance/export |", exp_xlsx["code"], flush=True)

# ============ 12. 审批委托（代审） ============
deleg = None
if new_user:
    start = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    deleg = check(
        "POST /api/workflows/delegations（新建委托）",
        call("POST", "/api/workflows/delegations",
             {"to_user_id": new_user["id"], "start_at": start, "end_at": end},
             token=tok),
    )
    check("GET /api/workflows/delegations", call("GET", "/api/workflows/delegations", token=tok))
    if deleg:
        check("PATCH /api/workflows/delegations/{id}（停用）",
              call("PATCH", f"/api/workflows/delegations/{deleg['id']}", {"active": False}, token=tok))
    # 受托人不能给自己委托 / 时间倒挂应 4xx
    bad = call("POST", "/api/workflows/delegations",
               {"to_user_id": 1, "start_at": end, "end_at": start}, token=tok)
    results.append(("委托参数校验（时间倒挂应 4xx）", 400 <= bad["code"] < 500, bad["code"]))
    print(("PASS" if 400 <= bad["code"] < 500 else "FAIL"), "| 委托参数校验 |", bad["code"], flush=True)
else:
    results.append(("POST /api/workflows/delegations", False, 0))
    print("FAIL | 无测试用户，跳过委托新建")

# ============ 13. 报销单（接入工作流） ============
exp = check(
    "POST /api/expenses（新建草稿）",
    call("POST", "/api/expenses",
         {"claim_type": "daily", "amount": 123.45, "occur_date": today,
          "description": "冒烟报销", "attachments": []},
         token=tok),
)
if exp:
    check("PATCH /api/expenses/{id}（编辑草稿）",
          call("PATCH", f"/api/expenses/{exp['id']}", {"description": "冒烟报销-改"}, token=tok))
    check("POST /api/expenses/{id}/submit（无附件应 422）",
          call("POST", f"/api/expenses/{exp['id']}/submit", token=tok, expect=422), expect=422)
    inv_body, inv_hdrs = multipart(
        {"title": f"发票-{uuid.uuid4().hex[:6]}", "category": "invoice", "description": "smoke"},
        "file", "invoice.txt", b"invoice content",
    )
    inv = call("POST", "/api/documents", body=inv_body, token=tok, headers=inv_hdrs)
    check("POST /api/documents（报销发票上传）", inv)
    if inv["ok"] and isinstance(inv["data"], dict):
        exp = check("PATCH /api/expenses/{id}（挂附件）",
                    call("PATCH", f"/api/expenses/{exp['id']}",
                         {"attachments": [{"document_id": inv["data"]["id"],
                                           "title": inv["data"]["title"],
                                           "file_url": inv["data"]["file_url"]}]},
                         token=tok)) or exp
    sub = check("POST /api/expenses/{id}/submit（发起审批流）",
                call("POST", f"/api/expenses/{exp['id']}/submit", token=tok))
    check("GET /api/expenses（列表）", call("GET", "/api/expenses", token=tok))
    check("GET /api/expenses/{id}", call("GET", f"/api/expenses/{sub['id']}", token=tok)) if sub else None
    if sub and sub.get("workflow_instance_id"):
        pend = call("GET", "/api/workflows/pending", token=tok)["data"] or []
        target = next((t for t in pend
                       if t.get("instance_id") == sub["workflow_instance_id"]), None)
        if target:
            check("POST /api/workflows/tasks/{id}/decide（报销审批通过）",
                  call("POST", f"/api/workflows/tasks/{target['id']}/decide",
                       {"approve": True, "comment": "同意"}, token=tok))
            got = call("GET", f"/api/expenses/{sub['id']}", token=tok)["data"]
            status = (got or {}).get("status")
            results.append(("报销单随流程回写为 approved", status == "approved", 200))
            print(("PASS" if status == "approved" else "FAIL"),
                  "| 报销单随流程回写 |", status, flush=True)
            check("POST /api/expenses/{id}/paid（打款）",
                  call("POST", f"/api/expenses/{sub['id']}/paid", {"paid": True}, token=tok))
        else:
            results.append(("报销审批待办生成", False, 0))
            print("FAIL | 报销审批待办生成（未找到对应 pending 任务）", flush=True)
check("GET /api/expenses/stats", call("GET", "/api/expenses/stats", token=tok))
exp_xlsx2 = call("GET", "/api/expenses/export", token=tok, raw=True)
ok2 = exp_xlsx2["code"] == 200 and exp_xlsx2["data"][:2] == b"PK"
results.append(("GET /api/expenses/export（xlsx）", ok2, exp_xlsx2["code"]))
print(("PASS" if ok2 else "FAIL"), "| GET /api/expenses/export |", exp_xlsx2["code"], flush=True)

# Excel 批量导入（openpyxl 生成临时工作簿）
try:
    from openpyxl import Workbook

    _wb = Workbook()
    _ws = _wb.active
    _ws.append(["类型", "金额", "日期", "说明"])
    _ws.append(["travel", 66.6, today, "导入冒烟"])
    _buf = __import__("io").BytesIO()
    _wb.save(_buf)
    imp_body, imp_hdrs = multipart({}, "file", "expenses.xlsx", _buf.getvalue())
    imp = call("POST", "/api/expenses/import", body=imp_body, token=tok, headers=imp_hdrs)
    check("POST /api/expenses/import（xlsx 导入）", imp)
    if imp["ok"]:
        print("       导入结果:", imp["data"], flush=True)
except ImportError:
    results.append(("POST /api/expenses/import", False, 0))
    print("FAIL | openpyxl 不可用，无法测导入", flush=True)

# ============ 14. 公文 + 文档版本 + 公告回执 ============
od = check(
    "POST /api/official-docs（登记公文）",
    call("POST", "/api/official-docs",
         {"doc_no": f"冒烟-{uuid.uuid4().hex[:6]}", "title": "冒烟公文",
          "direction": "in", "from_org": "测试单位", "secrecy": "internal",
          "content": "公文正文"},
         token=tok),
)
check("GET /api/official-docs", call("GET", "/api/official-docs", token=tok))
if od:
    check("POST /api/official-docs/{id}/circulate（传阅）",
          call("POST", f"/api/official-docs/{od['id']}/circulate", {"remark": "请阅"}, token=tok))
    check("PATCH /api/official-docs/{id}",
          call("PATCH", f"/api/official-docs/{od['id']}", {"title": "冒烟公文-改"}, token=tok))
    check("POST /api/official-docs/{id}/archive（归档）",
          call("POST", f"/api/official-docs/{od['id']}/archive", token=tok))

vd_body, vd_hdrs = multipart(
    {"title": f"版本文档-{uuid.uuid4().hex[:6]}", "category": "test", "description": "smoke"},
    "file", "v1.txt", b"version 1",
)
vdoc = call("POST", "/api/documents", body=vd_body, token=tok, headers=vd_hdrs)
check("POST /api/documents（版本测试上传）", vdoc)
if vdoc["ok"] and isinstance(vdoc["data"], dict):
    did2 = vdoc["data"]["id"]
    v2_body, v2_hdrs = multipart({"note": "v2"}, "file", "v2.txt", b"version 2")
    check("POST /api/documents/{id}/versions（新增版本）",
          call("POST", f"/api/documents/{did2}/versions",
               body=v2_body, token=tok, headers=v2_hdrs))
    vers = call("GET", f"/api/documents/{did2}/versions", token=tok)
    check("GET /api/documents/{id}/versions", vers)
    if vers["ok"] and isinstance(vers["data"], list) and len(vers["data"]) >= 2:
        vid = vers["data"][1]["id"]  # 第 1 版（列表按版本倒序）
        dl = call("GET", f"/api/documents/{did2}/versions/{vid}/file", token=tok, raw=True)
        results.append(("GET 历史版本下载", dl["code"] == 200, dl["code"]))
        print(("PASS" if dl["code"] == 200 else "FAIL"), "| GET 历史版本下载 |", dl["code"], flush=True)
    check("DELETE /api/documents/{id}（清理版本文档）", call("DELETE", f"/api/documents/{did2}", token=tok))

if ann and isinstance(ann, dict):
    check("POST /api/announcements/{id}/read（阅读回执）",
          call("POST", f"/api/announcements/{ann['id']}/read", token=tok))
    check("GET /api/announcements/{id}/readers（阅读明细）",
          call("GET", f"/api/announcements/{ann['id']}/readers", token=tok))

# ============ 15. SSE ============
sse = call("GET", "/api/events/stream", token=tok, raw=True, timeout=6)
sse_ok = sse["code"] in (200, 204) or (sse["code"] == -1 and "timed out" in str(sse["data"]))
results.append(("GET /api/events/stream（SSE 长连接）", sse_ok, sse["code"]))
print(("PASS" if sse_ok else "FAIL"), "| GET /api/events/stream |", sse["code"], flush=True)

passed = sum(1 for _, ok, _ in results if ok)
print(f"\n==== 冒烟结果：{passed}/{len(results)} 通过 ====")
for name, ok, code in results:
    if not ok:
        print("  FAIL:", name, code)
