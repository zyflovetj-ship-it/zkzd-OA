"""部署验收检查（只读）：验证一套已部署的 zk-oa 是否真正可用。

与 tests/smoke_live.py 的区别：本脚本**只做读操作**（除登录外），
不向数据库写入任何业务数据，因此任何阶段都能安全运行——包括生产库已有真实数据时。

检查内容：
  1. 容器/进程存活        /health
  2. 数据库连通           /ready
  3. 鉴权边界             未带令牌必须 401
  4. 登录链路             账号密码换取令牌
  5. 身份与权限           当前用户、角色、权限码数量
  6. 菜单下发             新前端外壳的数据源
  7. 全量只读接口         自动从 /openapi.json 发现所有无参 GET 接口并逐个请求

用法：
    python tests/deploy_check.py
    python tests/deploy_check.py http://192.168.1.10:8000
    docker compose exec backend python tests/deploy_check.py

退出码：0 = 全部通过；1 = 存在失败项（可直接用于 CI / 上线卡点）。
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = (
    sys.argv[1] if len(sys.argv) > 1
    else os.environ.get("CHECK_BASE", "http://127.0.0.1:8000")
).rstrip("/")

USERNAME = os.environ.get("CHECK_USER", "admin")
PASSWORD = os.environ.get("CHECK_PASSWORD", "admin123")

passed = 0
failed = 0
warned = 0


def call(method, path, body=None, token=None, timeout=20):
    url = BASE + path
    data = None
    hdrs = {}
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    if token:
        hdrs["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return -1, str(e).encode()


def ok(label, detail=""):
    global passed
    passed += 1
    print("  PASS  " + label + (("   " + detail) if detail else ""))


def bad(label, detail=""):
    global failed
    failed += 1
    print("  FAIL  " + label + (("   " + detail) if detail else ""))


def warn(label, detail=""):
    global warned
    warned += 1
    print("  WARN  " + label + (("   " + detail) if detail else ""))


def expect_status(label, got, want, detail=""):
    if got in want:
        ok(label, detail or ("HTTP " + str(got)))
    else:
        bad(label, detail or ("HTTP " + str(got) + "，期望 " + "/".join(str(w) for w in want)))


print("=" * 64)
print("zk-oa 部署验收（只读）  目标: " + BASE)
print("=" * 64)

# ---------- 1. 存活 ----------
print()
print("[1/7] 进程存活")
code, body = call("GET", "/health")
if code == 200:
    try:
        ok("/health", "status=" + str(json.loads(body).get("status")))
    except Exception:
        ok("/health", "HTTP 200")
else:
    bad("/health", "HTTP " + str(code) + "（后端未启动或端口不通）")

# ---------- 2. 就绪（含数据库）----------
print()
print("[2/7] 数据库连通")
code, body = call("GET", "/ready")
if code == 200:
    try:
        ok("/ready", "status=" + str(json.loads(body).get("status")))
    except Exception:
        ok("/ready")
else:
    detail = ""
    try:
        detail = str(json.loads(body).get("detail", ""))[:120]
    except Exception:
        pass
    bad("/ready", "HTTP " + str(code) + " " + detail)

# ---------- 3. 鉴权边界 ----------
print()
print("[3/7] 鉴权边界（未登录必须被拒）")
code, _ = call("GET", "/api/auth/me")
expect_status("未带令牌访问 /api/auth/me 被拒", code, (401, 403))
code, _ = call("GET", "/api/users")
expect_status("未带令牌访问 /api/users 被拒", code, (401, 403))

# ---------- 4. 登录 ----------
print()
print("[4/7] 登录链路")
code, body = call("POST", "/api/auth/login", body={"username": USERNAME, "password": PASSWORD})
token = ""
if code == 200:
    try:
        d = json.loads(body)
        token = d.get("access_token", "")
        has_refresh = bool(d.get("refresh_token"))
        if token:
            ok("登录成功", "access_token 已签发，refresh_token=" + ("有" if has_refresh else "无"))
        else:
            bad("登录成功", "响应中没有 access_token")
    except Exception as e:
        bad("登录成功", "响应解析失败: " + str(e))
else:
    bad("登录成功", "HTTP " + str(code) + "（账号 " + USERNAME + " 密码错误或账号被停用？）")

if not token:
    print()
    print("登录失败，后续检查无法继续。")
    print("=" * 64)
    print("结果: " + str(passed) + " 通过 / " + str(failed) + " 失败 / " + str(warned) + " 警告")
    sys.exit(1)

# ---------- 5. 身份与权限 ----------
print()
print("[5/7] 身份与权限")
code, body = call("GET", "/api/auth/me", token=token)
if code == 200:
    try:
        d = json.loads(body)
        perms = d.get("permissions") or []
        ok("获取当前用户", "用户=" + str(d.get("username")) + " 角色=" + str(d.get("role_name")))
        if perms:
            ok("权限码已下发", str(len(perms)) + " 个" + ("（含通配 *）" if "*" in perms else ""))
        else:
            bad("权限码已下发", "permissions 为空，前端菜单与按钮会全部不可见")
    except Exception as e:
        bad("获取当前用户", "解析失败: " + str(e))
else:
    bad("获取当前用户", "HTTP " + str(code))

# ---------- 6. 菜单 ----------
print()
print("[6/7] 菜单下发（前端外壳数据源）")
code, body = call("GET", "/api/auth/menus", token=token)
if code == 200:
    try:
        menus = json.loads(body)
        tops = [m for m in menus if m.get("parent_id") is None]
        if menus:
            ok("菜单已下发", str(len(menus)) + " 条，其中一级模块 " + str(len(tops)) + " 个")
        else:
            bad("菜单已下发", "返回空列表，前端将没有导航")
    except Exception as e:
        bad("菜单已下发", "解析失败: " + str(e))
else:
    bad("菜单已下发", "HTTP " + str(code))

# ---------- 7. 全量只读接口 ----------
print()
print("[7/7] 全量只读接口（自动从 /openapi.json 发现）")
code, body = call("GET", "/openapi.json")
if code != 200:
    bad("获取 /openapi.json", "HTTP " + str(code))
else:
    spec = json.loads(body)
    targets = []
    for path, ops in (spec.get("paths") or {}).items():
        if "{" in path:
            continue  # 带路径参数的接口需要真实 id，跳过
        op = ops.get("get")
        if not op:
            continue
        required_params = [p for p in (op.get("parameters") or []) if p.get("required")]
        if required_params:
            continue  # 必填查询参数无法猜测，跳过
        if path in ("/health", "/ready", "/openapi.json"):
            continue
        targets.append(path)

    targets.sort()
    n_ok = n_fail = n_warn = 0
    for path in targets:
        code, _ = call("GET", path, token=token)
        if code in (200, 204):
            n_ok += 1
        elif code in (401, 403):
            n_fail += 1
            bad("GET " + path, "HTTP " + str(code) + "（已登录仍被拒 → 权限/令牌接线异常）")
        elif code >= 500:
            n_fail += 1
            bad("GET " + path, "HTTP " + str(code) + "（服务端错误）")
        else:
            n_warn += 1
            warn("GET " + path, "HTTP " + str(code))

    if n_fail == 0:
        ok("只读接口批量检查", str(len(targets)) + " 个接口：" + str(n_ok) + " 正常 / " + str(n_warn) + " 需参数或暂无数据 / 0 失败")
    else:
        bad("只读接口批量检查", str(n_fail) + " 个接口失败")

# ---------- 汇总 ----------
print()
print("=" * 64)
print("结果: " + str(passed) + " 通过 / " + str(failed) + " 失败 / " + str(warned) + " 警告")
if failed == 0:
    print("部署验收通过 —— 后端、数据库、鉴权、菜单、只读接口全部正常。")
else:
    print("部署验收未通过，请根据上面 FAIL 项排查。")
print("=" * 64)
sys.exit(0 if failed == 0 else 1)
