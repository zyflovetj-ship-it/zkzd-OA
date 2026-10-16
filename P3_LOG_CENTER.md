---
summary: "「P3 日志中心（审计日志）— 交付里程碑」：> 所属：zk-oa 全栈 OA ·「七大引擎」收官切片（运维中心 → 建模引擎 → 日志中心）
tags: [md, zk-oa, 中科平台_zk-oa, 文档]
dblink_managed: true
---

# P3 日志中心（审计日志）— 交付里程碑

> 所属：zk-oa 全栈 OA ·「七大引擎」收官切片（运维中心 → 建模引擎 → 日志中心）
> 日期：2026-09-25 / 2026-09-26

## 一、目标

沉淀「谁在何时、对什么对象、做了什么操作、结果如何」的完整审计轨迹，覆盖所有变更类请求与关键认证动作，并以物理列存储、可直接下推数据库检索。

## 二、设计取舍

1. **写入由中间件统一完成，而非散落在各端点**
   - 新增 `AuditMiddleware`：自动审计所有 `POST/PUT/PATCH/DELETE` 以及 `登录/登出/刷新`。
   - 好处：零侵入、不会遗漏任何变更；新增端点天然被审计，无需逐处埋点。
   - 读侧聚合（列表/统计/清理）仍走 `AuditService`，职责清晰。

2. **查询维度全部是物理列**（`actor_id / module / action / status / created_at` 等建索引）
   - 与建模引擎的 JSON 数据列不同，审计检索直接下推数据库，无需服务层内存过滤。
   - 趋势按天分桶在 **Python 侧** 完成，规避 SQLite `date()` 与 PostgreSQL `date_trunc` 的方言差异。

3. **按路径语义识别 module / action / target**
   - 例如 `POST /api/workflows/tasks/123/decide` → `module=workflow, action=approve|reject, target=workflow_task#123`（依据 body 的 `approve` 区分通过/驳回）。
   - 建模删除、权限授权/撤销、用户创建等均被精准标注，而非笼统的「修改 XXX」。

4. **安全与稳健**
   - `detail` 仅保存脱敏上下文（如审批意见前 200 字、加签 user_ids），**绝不写入密码/令牌/签名图像**。
   - 审计写入使用独立事务，**任何失败只告警、不影响主响应**。
   - 审计写入失败被 `try/except` 屏蔽，主链路零影响。

## 三、接口清单

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/audit/logs` | `audit:view` | 审计日志列表；支持 `module / action / status / q / start / end / offset / limit` 过滤 |
| GET | `/api/audit/stats` | `audit:view` | 概览：总量、成功/失败、按模块/状态分布、近 14 天趋势 |
| POST | `/api/audit/purge` | `audit:manage` | 清理 N 天前的审计记录（请求体 `{"days": 90}`） |

## 四、数据模型（AuditLog）

`audit_logs` 表核心列：`actor_id`、`actor_name`（快照，用户注销后仍可追溯）、`module`、`action`、`target_type`、`target_id`、`method`、`path`、`status`(success/failed)、`status_code`、`detail`(JSON)、`ip`、`request_id`、`created_at`。

## 五、涉及文件

后端：
- `backend/app/models.py` — `AuditLog` 模型（物理列 + 索引）
- `backend/app/schemas.py` — `AuditLogOut / AuditLogsPage / AuditStatsOut / AuditPurgeRequest / AuditPurgeOut`
- `backend/app/repositories.py` — `AuditRepository`（过滤列表/计数/聚合统计/清理）
- `backend/app/services.py` — `AuditService`（list_logs / stats / purge）
- `backend/app/core/middleware.py` — `AuditMiddleware`（自动落审计）+ `RequestContextMiddleware` 的 response 绑定加固
- `backend/app/api/routers.py` — `audit_router` 三个端点
- `backend/app/seed.py` — `audit:view` / `audit:manage` 权限与「日志中心」菜单（置于组织权限中心下，order=4）

前端：
- `frontend/src/types.ts` — `AuditLogOut / AuditLogsPage / AuditStatsOut`
- `frontend/src/api/endpoints.ts` — `auditApi`（logs / stats / purge）
- `frontend/src/pages/AuditCenter.tsx` — 日志中心页（统计卡 + 模块/结果分布 + 14 天趋势 + 过滤表 + 详情抽屉 + 受权限保护的清理）
- `frontend/src/App.tsx` — `/settings/audit` 路由
- `frontend/src/components/AppLayout.tsx` — 注册 `FileSearchOutlined` 图标

## 六、验证状态

| 项 | 结果 |
| --- | --- |
| 后端 Python 语法编译 | ✅ `python3 -m compileall` exit 0 |
| 前端 TS 类型检查 | ✅ `tsc --noEmit` 0 错误 |

> 后端运行时冒烟与 `vite build` 需在标准 Linux/Docker 环境执行（本沙箱为 openharmony aarch64，缺编译器且 rollup 原生模块不可加载，非代码缺陷）。

## 七、冒烟脚本（标准环境）

```bash
# 登录取令牌
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 触发一次变更（如新建角色），审计中间件会自动落一条记录

# 查看审计统计与列表
curl -s localhost:8000/api/audit/stats -H "Authorization: Bearer $TOKEN" | head -c 800
curl -s localhost:8000/api/audit/logs -H "Authorization: Bearer $TOKEN" | head -c 800

# 清理 90 天前（需 audit:manage，admin 具备）
curl -s -X POST localhost:8000/api/audit/purge \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"days":90}'
```

## 八、后续扩展

- 异常登录 / 高频失败告警（如同一 IP 多次 401）。
- 审计实时流（SSE）推送至日志中心页。
- 按模块/时间窗导出 CSV，或与 SIEM 对接。
- 长周期归档策略（热表保留 90 天，冷数据转存对象存储）。

<!-- OBSIDIAN_DBLINK_RELATED_START -->
## 关联文档（双链自动生成）
- [[00-文档总索引.md]]
<!-- OBSIDIAN_DBLINK_RELATED_END -->
