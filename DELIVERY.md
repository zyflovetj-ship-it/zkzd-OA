---
summary: "「zk-oa 全栈交付说明」：| 模块 | 后端 | 前端 |
tags: [md, zk-oa, 中科平台_zk-oa, 文档]
dblink_managed: true
---

# zk-oa 全栈交付说明

## 已实现

| 模块 | 后端 | 前端 |
| --- | --- | --- |
| 认证（JWT 双令牌 + RBAC） | `/api/auth/login`、`/refresh`、`/logout`、`/me`；刷新令牌服务端存储、可吊销、登录时轮换 | 登录页、AuthContext、401 自动刷新重试 |
| **账户管理** | `GET /api/users?q=`（搜索）、`GET/POST /api/users`、`PATCH /api/users/{id}`（改资料/角色/部门/启停/密码）、`GET/POST /api/departments` | 账户管理页：搜索、新建、编辑、启用·停用（二次确认）、重置密码 |
| **组织权限中心** | `GET /api/users/roles`、`POST/PATCH/DELETE /api/users/roles/{id}`（角色 CRUD，需 `org:role:manage`）、`GET/POST /api/permissions`、`GET/POST /api/permissions/roles/{role_id}`、`GET/POST /api/menus` | 角色权限页：角色列表 + 新建/编辑/删除（admin 与有用户角色受保护）、按分类勾选权限、数据范围；菜单管理页 |
| 考勤 / 请假审批 | `GET/POST /api/leave`、`POST /api/leave/{id}/review` | 请假审批（申请 + 通过/驳回） |
| 公告 / 文档 | `GET/POST /api/announcements`、`PATCH /api/announcements/{id}` | 公告文档（列表 + 发布） |
| 审批工作流引擎 | `GET/POST /api/workflows/definitions`、`POST /api/workflows/instances`、`GET /api/workflows/pending`、`POST /api/workflows/instances/{id}/review`、`GET /api/workflows/stats` | 工作流（发起 + 待办 + 逐步审批 + 监控看板） |
| 电子签单 | `GET/POST /api/signatures/{ref_type}/{ref_id}` | 签单页（canvas 手写签名画板 + SHA-256 哈希留痕） |
| **内容门户（角色化工作台）** | `GET /api/portal/overview`（按角色聚合统计 + 待办/在途/请假/公告挂件） | 工作台首页：角色相关统计卡、待我审批/在途流程/我的请假/最新公告四挂件、快捷入口 |
| **运维中心（P3 建模运维）** | `GET /api/ops/overview`（实体计数 / 流程实例状态分布 / 角色人数矩阵 / 最近实例，管理员） | 运维中心页：统计卡 + 实例状态/角色人数双横条图 + 最近实例表 |
| **建模引擎（P3 重头戏）** | `GET/POST /api/models/entities`、`GET/PATCH/DELETE /api/models/entities/{id}`、`GET/POST /api/models/entities/{id}/records`、`PATCH/DELETE /api/models/records/{id}`、`GET /api/models/stats` | 建模引擎页 `/models`：实体设计器（字段 schema 编辑）+ 数据动态表格 / 动态表单 + 概览统计；三个权限点 `model:view` / `model:manage` / `model:data:edit` |
| **日志中心（P3 收官）** | 审计中间件自动落审计（所有变更类请求 + 登录/登出/刷新，按路径语义识别 module/action/target，不记录密码/令牌）；`GET /api/audit/logs`（模块/动作/状态/关键字/时间窗过滤）、`GET /api/audit/stats`（概览聚合）、`POST /api/audit/purge`（清理，需 `audit:manage`）；`AuditLog` 全部查询维度为物理列，检索直接下推数据库 | 日志中心页 `/settings/audit`：统计卡 + 模块/结果分布双横条图 + 14 天趋势折线 + 过滤表 + 详情抽屉；`audit:view` 可见，`audit:manage` 可清理 |
| **内容引擎（文档中心 + 文件上传）** | `GET/POST /api/documents`、`PATCH /api/documents/{id}`、`GET /api/documents/{id}/file`（鉴权下载：local 流式 / s3 签名 URL 302 跳转）、`DELETE /api/documents/{id}`；受控上传（扩展名白名单 + 单文件 ≤20MB + `{id}.{ext}` 防路径穿越）、**存储抽象（local 磁盘 / s3 签名 URL 自动切换，`file_url` 逻辑地址不变）**、RBAC `doc:view`/`doc:upload`/`doc:manage`；文档计数接入运维中心 | 文档中心页 `/documents`：分类过滤 + 标题搜索 + 服务端分页、上传弹窗（标题/分类/描述/文件）、权限化下载与删除 |
| **消息中心（通知收件箱）** | `GET /api/notifications`（含未读总数）、`POST /api/notifications/{id}/read`、`POST /api/notifications/read-all`；按业务触发点自动写入：**请假提交→通知审批人（admin/manager）**、**工作流任务指派/抄送→通知处理人**、**公告发布→广播全员**；`notifications` 表（user_id 索引 + 级联删除），RBAC `msg:view`，用户仅可见自己的 | 消息中心页 `/messages`：列表 + 未读筛选 + 单条/全部已读 + 跳转关联页；布局顶部铃铛 `Badge` 未读角标 + 30s 轮询；前端零硬编码 URL |
| **审批超时自动流转 + 后台调度（优先级 ④）** | 后台 `Scheduler` 按 `SCHEDULER_ENABLED` 周期扫描 `workflow_instances` 中 `status='running'` 且超 `WORKFLOW_SLA_DAYS` 且 `escalated_at IS NULL` 的实例 → 通知 admin/manager（`/workflows/monitor`）；幂等（IS NULL 边界 + 处理后写标记，仅一次）、失败写 `scheduler_dead_letters` 死信、下轮自然重试；`POST /api/ops/scheduler/run-once`（管理员手动触发一轮）；迁移 `0003_scheduler` 加 `escalated_at` 列 + 死信表；轻量限流中间件 `RateLimitMiddleware`（固定窗口按 IP，默认关闭，豁免探针） | 前端无改动（消息中心铃铛已呈现升级提醒）；`alembic upgrade head` 后自动生效 |
| **报表中心（统一数据看板）** | `GET /api/dashboard`（个人视图恒返回，组织级需 `report:view`）：个人四项（未读/待审批/请假/在途）、KPI 8 项、流程状态分布、近 30 天发起·完成趋势、部门人数、最近动态；`WorkflowRepository` 新增 `count_for_initiator` / `trend(30)`（日期分桶在 Python 侧，规避 SQLite/PG 方言差异）；计数与分组全部下推 SQL，不捞全表；`seed.py` 新增 `report:view` 权限 + `/reports` 菜单（仅 admin/manager，不给 employee） | `pages/Reports.tsx`（`/reports`）：ECharts 环形图/折线/柱状 + KPI 卡 + 最近动态表；菜单由后端动态下发，前端零硬编码 URL |
| 基础设施 | `/health`、`/ready`、结构化 JSON 日志 + request_id、类型化错误、CORS 显式来源、安全头 | 类型化 axios 客户端、加载/错误态 |

## 架构分层

控制器（routers）→ 服务层（services，业务逻辑 + 事务）→ 仓储层（repositories，`selectinload` 防 N+1）。
配置全部走环境变量并启动校验；生产环境强制强 JWT 密钥 + 禁用 SQLite。

## 启动方式

```bash
# 本地开发（SQLite，无需数据库服务）
cd zk-oa/backend && pip install -r requirements.txt && ./run.sh   # 自动 alembic upgrade head + :8000  admin/admin123
cd zk-oa/frontend && npm install && npm run dev                    # :5173

# 生产（PostgreSQL，Docker）
echo "JWT_SECRET=$(python3 -c 'import secrets;print(secrets.token_hex(32))')" > .env
docker compose up -d --build
```

## 验证状态

| 项 | 结果 |
| --- | --- |
| 后端 Python 语法编译 | ✅ `python3 -m compileall` exit 0 |
| 流程引擎纯逻辑测试 | ✅ `python3 tests/test_workflow_engine.py` 26 项断言全通过 |
| **建模引擎纯逻辑测试** | ✅ `python3 tests/test_model_fields.py` 33 项断言全通过（字段校验 / 取值转换 / 必填拦截 / 过滤搜索） |
| **pytest 超时升级测试套件（Phase 5，④）** | ✅ `tests/test_timeout_escalation.py` 编写完成：5 项 Fake 单元测试（幂等边界 / 死信跳过 / notify / escalate / 异常落死信）+ 3 项真实 SQLite 集成测试（notify / escalate / 二次幂等）；`python3 -m compileall` exit 0；运行需标准环境（`pip install -r requirements.txt pytest pytest-asyncio && pytest`） |
| 前端依赖安装 | ✅ 164 包成功 |
| 前端 TS 类型检查 | ✅ `tsc --noEmit` 0 错误 |
| 前端生产构建 | ⚠️ 本沙箱因 openharmony 平台加载 rollup 原生模块失败，需在你标准环境执行 |
| 后端运行时冒烟 | ⚠️ 本沙箱无编译器、无 PostgreSQL，需在你标准环境 / Docker 执行 |

## 沙箱限制说明（非代码缺陷）

当前运行环境为 openharmony (ohos) aarch64：**无 gcc/clang、`/tmp` 只读**。
- `bcrypt` 需 Rust 构建 → 已改为标准库 `hashlib.pbkdf2_hmac`（更安全可移植，生产同样可用）。
- SQLAlchemy / pydantic 的 C 扩展无法构建 → 后端无法在此启动运行。
- npm 将平台识别为 openharmony，rollup 原生二进制 `dlopen` 失败 → `vite build` 无法在此完成。

## 测试套件（Phase 5 验证）

为优先级 ④ 审批超时自动升级落地 pytest 验证（全栈专家规范的「单测 mock 仓储层、集成测试用真实库」）。

- **依赖注入支撑测试**：`WorkflowService.__init__` 新增关键字注入 `workflow_repo` / `user_repo` / `notification_service` / `scheduler_repo`（默认回退现接线，向后兼容）；`timeout_escalate_all` 改用 `self.users` / `self.notifications` / `self.scheduler`，不再内联 `UserRepository(self.session)` 等，使单测可注入 Fake 隔离数据库。
- **单元测试（零数据库）**：`tests/test_timeout_escalation.py` 内 `FakeWorkflowRepo` / `FakeUserRepo` / `FakeNotificationService` / `FakeSchedulerRepo` / `_FakeSession` 模拟依赖；覆盖 ① 幂等边界（`list_running_overdue` 仅返回 `escalated_at IS NULL`，标记后二次运行 scanned=0）；② 死信跳过（已存在死信则跳过重通知）；③ `notify` 策略（仅通知、不重分配）；④ `escalate` 策略（待办轮询转交兜底角色、`origin_approver_id` 留痕、`escalate` 节点日志）；⑤ 异常落死信（通知失败写 `scheduler_dead_letters` 且不计升级）；⑥ 返回结构 `{scanned,escalated,reassigned,dead_letters}`。通过 `unittest.mock.patch("app.core.config.get_settings", ...)` 控制 `workflow_timeout_action` / `fallback_role` / `sla_days`。
- **集成测试（真实 SQLite + aiosqlite）**：`Base.metadata.create_all` 建表（不依赖 Alembic），种子 admin/manager/兜底角色与用户 + 超时运行中实例 + 待审批任务，验证 notify / escalate 全链路与二次运行幂等；`asyncio_mode=auto` + 异步 fixture（StaticPool 内存库）。
- **运行方式**：`cd backend && python3 tests/test_timeout_escalation.py`（仅 Fake 单元，需已装依赖）/ `pytest -q`（单元 + 集成）；`pytest.ini` 已设 `asyncio_mode=auto`、`testpaths=tests`、`pythonpath=.`；`requirements.txt` 增加 `pytest==8.3.4` + `pytest-asyncio==0.25.0`。
- **沙箱限制**：openharmony 沙箱未装 `sqlalchemy` / `pytest`，无法在本环境执行，仅完成 `compileall` 语法校验；标准 Linux/Docker 环境可一键 `pytest`。

## 下一步建议

1. 生产把刷新令牌改为 `httpOnly + Secure + SameSite` Cookie，实现刷新页面免登录。
2. ✅ **Alembic 迁移已落地**：表结构改由 `migrations/versions/0001_initial.py` 基线迁移管理，启动前自动 `alembic upgrade head`（run.sh 与 Dockerfile 已内置），不再使用 `create_all`，支持可回滚/可升级部署。
3. ✅ **pytest 测试套件已落地（Phase 5）**：`tests/test_timeout_escalation.py` 含 Fake 单元测试（mock 仓储层）与真实 SQLite 集成测试，覆盖优先级 ④ 审批超时自动升级的幂等 / 死信 / notify / escalate 全路径（详见上方「测试套件」节）。后续可把该模式推广到其它服务层（用户/部门、工作流引擎、建模引擎）。
4. 加限流（如 slowapi）、后台任务队列（请假到期提醒 / 审批超时自动流转）。
5. ✅ **对象存储签名 URL 已落地（文件存储抽象）**：新增 `app/core/storage.py`，定义 `StorageBackend` 抽象 + `LocalStorageBackend`（开发落盘）+ `S3StorageBackend`（S3 兼容，aioboto3 惰性导入），由 `get_storage()` 按 `STORAGE_BACKEND` 工厂选择。`DocumentService` 的上传/下载/删除全部走存储抽象，下载端点本地走 `FileResponse`、S3 走 `RedirectResponse(302)` 到签名 URL（`ResponseContentDisposition` 携带下载文件名，有效期 `SIGNED_URL_EXPIRE_MINUTES`）。`file_url` 仍是逻辑地址 `/api/documents/{id}/file`，**前端零改动**。配置新增 `STORAGE_BACKEND` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `S3_ENDPOINT_URL` / `S3_REGION` / `S3_BUCKET` / `SIGNED_URL_EXPIRE_MINUTES`，`s3` 后端缺配置启动即快速失败；`requirements.txt` 新增 `aioboto3==15.5.0`。详见下条。
6. **监控看板已补齐（P0 收尾）**：`/workflows/monitor` 含统计卡片、状态分布/发起量/趋势三图、超时待办与在途实例表，需 `wf:monitor` 权限（管理员/经理）。超时以 SLA_DAYS=3 派生（库未回填 `due_at` 时）；后续可接入真实 SLA 与审批超时自动流转。
7. **P3 运维中心已落地（核心切片）**：`/settings/ops` 提供管理员视角的系统级运行概览（实体计数、流程实例状态分布、角色人数矩阵、最近实例）。后续可接入真实 DB 监控指标（连接数、慢查询、表空间）。
8. **P3 建模引擎已落地（动态实体 + 自定义表单建模）**：`/models` 支持零 DDL 建实体、字段级类型/必填/唯一校验、实体生命周期（草稿→发布）、数据行 CRUD 与模糊搜索。设计取舍见下：

   - 数据以 `model_records.data` JSON 列存储：**换灵活性、让渡索引能力**。SQLite 的 `json_extract` 与 PostgreSQL 的 `->>` 方言不同，因此列表过滤在服务层完成并以 `MAX_SCAN=2000` 限制单次扫描；实体数据量超过该量级时，应把高频筛选字段提升为物理列或改用 PostgreSQL JSONB + GIN 索引。
   - 字段 schema 校验放在 `app/model_fields.py`（零框架依赖），既可被单测直接覆盖，也让 services 层只负责编排与事务。
9. 建模引擎后续可扩展：**实体数据接入审批流**（建模记录作为流程表单数据源）、视图/列表布局自定义、数据导入导出（CSV/Excel）、行级权限与字段级权限。
10. **P3 日志中心已落地（七大引擎收官）**：`AuditMiddleware` 对所有变更类请求与登录/登出/刷新自动写审计，按路径语义标注 module/action/target（审批通过/驳回、建模删除等精准识别），`AuditLog` 查询维度全部为物理列可下推检索。前端 `/settings/audit` 提供统计、分布、趋势、过滤与详情。后续可扩展：异常登录/高频失败告警、审计实时流（SSE）、按模块导出、与 SIEM 对接。
11. **内容引擎已落地（路线图收官切片）**：文档中心 `/documents` 支持受控上传（扩展名白名单 + ≤20MB + `{id}.{ext}` 防穿越）、分类/搜索/分页列表、鉴权流式下载（`file_url` 仅逻辑地址，经 `doc:view` 端点返回）、`doc:*` 三级权限与审计联动（upload/download/update/delete 入 `doc` 模块）。详见 `P4_CONTENT_ENGINE.md`。后续：生产改对象存储签名 URL、文档版本/在线预览、大文件分片上传、与电子签单联动合同签署。
12. **Alembic 数据库迁移已落地（可回滚部署基础）**：新增 `alembic.ini` + `migrations/env.py`（异步引擎，DB URL 从 `settings.database_url` 注入，密钥不落库）+ `migrations/versions/0001_initial.py`（全 22 张表基线，含内容引擎 `documents` 新列；`users`↔`departments` 循环外键以 ALTER 补建）+ `migrations/versions/0002_notifications.py`（消息中心 `notifications` 表，`user_id` 索引 + 级联删除 + `(user_id,is_read)` 复合索引加速未读计数）。`requirements.txt` 加入 `alembic==1.14.0`；`run.sh` 与 `Dockerfile` 启动前执行 `alembic upgrade head`；`db.py` 的 `init_db`/`create_all` 已移除。后续结构变更统一新增迁移：`alembic revision --autogenerate -m "..."` 后人工核对再 `alembic upgrade head`。⚠️ 旧版 `create_all` 本地库（如 `oa.db`，已有 22 表但缺 `notifications`）：先 `alembic stamp 0001_initial` 标记基线（不建表），再 `alembic upgrade head` 仅补建 `0002`；切勿直接 `alembic stamp head`（会跳过 0002 建表）。全新库直接 `alembic upgrade head` 即可。
13. **对象存储抽象已落地（local ↔ s3 无缝切换）**：新增 `app/core/storage.py`。`StorageBackend(ABC)` 定义 `save` / `get_download` / `delete` / `exists`；`LocalStorageBackend` 落盘 `uploads/{id}.{ext}`（沿用旧命名，下载时校验存在性）；`S3StorageBackend` 用 `aioboto3` 异步 `put_object` / `delete_object` / `head_object`，`get_download` 经 `generate_presigned_url`（含 `ResponseContentDisposition` 中文文件名，`ExpiresIn=SIGNED_URL_EXPIRE_MINUTES*60`）返回签名 URL。`get_storage()` 工厂按 `STORAGE_BACKEND` 选择并 `lru_cache` 缓存。`DocumentService` 三处 IO 全部改为走 `self.storage`，`/api/documents/{id}/file` 端点据返回决定 `FileResponse` 还是 `RedirectResponse(302)`。生产切 S3 只需 `.env` 设 `STORAGE_BACKEND=s3` + 四个 S3 变量，代码与前端无需改动。
14. **消息中心已落地（统一待办 / 通知收件箱）**：新增 `notifications` 表 + 迁移 `0002_notifications`；`NotificationRepository`（按用户分页/未读计数/标记已读/全部已读）+ `NotificationService`（`list_for_user` 返回 `{items,total,unread,limit,offset}`；`add` 仅落库供工作流事务打包提交、`notify`/`notify_many` 落库即提交）。`msg_router` 三端点：`GET /api/notifications`、`POST /api/notifications/{id}/read`、`POST /api/notifications/read-all`，RBAC `msg:view`，用户只能操作自己的行（越权 404）。**触发点写入通知**：① 请假提交 → 通知 admin/manager（`UserRepository.list_ids_by_roles`）；② 公告发布/由未发布转发布 → 广播全员（`UserRepository.list_ids`）；③ 工作流任务指派与抄送节点激活时 → 通知处理人（在 `_activate` 内用 `add` 打包进既有事务，流程推进时自动通知下一处理人）。`seed.py` 新增 `msg:view` 权限、`消息中心` 菜单（`/messages`，`BellOutlined`）、并为 admin 灌入 3 条示例通知（幂等）。前端：`types.NotificationOut`/`NotificationsPage`、`msgApi`、`pages/Messages.tsx`（列表 + 未读筛选 + 单条/全部已读 + 跳转关联路由）、`App.tsx` 路由 `/messages`、布局顶部铃铛 `Badge` 未读角标 + 30s `refetchInterval` 轮询。设计取舍：消息中心用轮询而非 WebSocket（OA 通知实时性要求不高、避免长连接复杂度）；如需强实时可后续升级 SSE。
15. **审批超时自动流转 + 后台调度已落地（优先级 ④）**：新增 `app/core/scheduler.py`（`Scheduler`：独立 asyncio 循环 + 分片可取消 sleep，由 `main.py` lifespan 按 `SCHEDULER_ENABLED` 启动/停止；`run_once()` 供手动触发与测试）。`WorkflowService.timeout_escalate_all(sla_days?)`：扫描超时运行中实例 → 按策略处理（见 16）→ 写 `escalated_at` 标记。**幂等**：扫描以 `escalated_at IS NULL` 为边界、处理后写标记，保证每实例仅升级一次；**死信与重试**：处理异常写入 `scheduler_dead_letters`（task_name/ref_id/payload/error），且同 `ref_id` 已死信则跳过重通知，下一轮调度自然重试。**迁移 `0003_scheduler`**：`workflow_instances.escalated_at`（+ 索引）与 `scheduler_dead_letters` 表（`down_revision=0002_notifications`，`alembic upgrade head` 自动应用）。运维端点 `POST /api/ops/scheduler/run-once`（admin）复用同一逻辑返回 `{scanned,escalated,reassigned,dead_letters}`。配套轻量限流 `app/core/middleware.py:RateLimitMiddleware`（固定窗口、按客户端 IP、`rate_limit_per_minute` 默认 0 关闭、豁免 `/health`/`/ready`，置于最外层先行拦截，纯标准库无新依赖）。配置新增 `SCHEDULER_ENABLED`/`SCHEDULER_INTERVAL_SECONDS`/`WORKFLOW_SLA_DAYS`/`WORKFLOW_TIMEOUT_ACTION`/`WORKFLOW_TIMEOUT_FALLBACK_ROLE`/`RATE_LIMIT_PER_MINUTE`，`.env.example` 已注释。设计取舍：超时以实例 `started_at` 起算 SLA（与监控看板一致，库未回填 `due_at` 时），后续可升级为按节点 `due_at` 精确计时。
16. **超时自动转交（升级策略）已落地（优先级 ④ 增强）**：`config.py` 新增 `workflow_timeout_action`（`notify` 默认 / `escalate`，带校验）与 `workflow_timeout_fallback_role`（默认 `admin`）。`timeout_escalate_all` 在 `action=="escalate"` 时，将超时实例的待审批任务（`WorkflowRepository.list_pending_tasks`）按轮询转交至兜底角色审批人：写 `origin_approver_id` 留痕、`approver_id` 改为兜底人、追加 `WorkflowNodeLog(action="escalate")` 并 `commit`；`SchedulerRunOut` 增加 `reassigned` 计数。无新迁移（`WorkflowTask` 已有 `approver_id`/`origin_approver_id`/`due_at`）。`notify` 模式保持纯提醒；`escalate` 模式让卡住的审批真正流转到兜底人，而非仅通知。`.env.example` 已注释两项。
17. **报表中心已落地（统一数据看板）**：补齐此前已定义但未落地的 `Dashboard*` schema（`schemas.py` L652+）。新增 `DashboardService`（个人视图 `_personal` 恒返回；`_org` 组织级含 KPI 8 项、流程状态分布、近 30 天发起·完成趋势、部门人数、最近动态），路由 `GET /api/dashboard`（`dashboard_router`），以 `has_org_scope = "*" in perms or "report:view" in perms` 判定。**关键安全取舍**：未复用 `dashboard:view`（那是"工作台"首页权限，employee 也持有），改用独立的 `report:view` 且只授予 admin/manager——否则普通员工将看到全公司人数、审计总量等敏感聚合。`WorkflowRepository` 新增 `count_for_initiator(user_id, status?)` 与 `trend(days)`（日期分桶在 Python 侧完成，同 `AuditRepository.stats`，规避 SQLite/PostgreSQL 日期函数方言差异；仅取 `started_at`/`finished_at` 两列不捞整行）。`seed.py` 幂等新增 `report:view` 权限 + `/reports` 菜单（`BarChartOutlined`，order 10）。前端 `pages/Reports.tsx`：ECharts（已装依赖，此前零使用）环形图/折线/柱状 + KPI 卡 + 最近动态表，沿用既有页面的加载/错误/刷新约定；菜单由后端动态下发故无需改导航。新增 `tests/test_dashboard.py` 两项集成测试（个人视图 / 组织级聚合）。**顺带修复**：`routers.py` 中 `/api/ops/scheduler/run-once` 被重复注册两次（同名 `run_scheduler_once`），已删除重复块。

18. **报表中心增强（时间范围筛选 + CSV 导出）**：在 17 基础上补齐两项能力。
    - **时间范围筛选**：`GET /api/dashboard` 新增 `days` 查询参数（`Query(30, ge=7, le=365)`），仅影响组织级 `workflow_trend` 分桶窗口；`DashboardService.overview(user, has_org_scope, days)` 透传至 `_org(days)`。`DashboardOrgOut` 字段 `workflow_trend_30d` 重命名为 `workflow_trend`，并新增 `trend_days: int`（回传实际窗口）。前端 `Segmented`（近 7/30/90 天）驱动 `reportApi.overview(days)`，`useQuery` 的 `queryKey` 含 `days` 自动复用缓存；趋势卡标题随选展示「近 N 天」。
    - **CSV 导出**：`GET /api/dashboard/export`（`require_permissions("report:view")` 硬约束，与看板同源权限；无权限 403），支持 `days` + `format=csv`（`pattern` 校验，当前仅 csv）。`DashboardService.export_tables(days)` 把组织级聚合规整为 5 张二维字符串表（`kpi` / `workflow_status` / `workflow_trend` / `department_headcount` / `recent_activities`，KPI 与流程状态映射中文标签，零业务耦合）。路由层 `_csv_zip` 用标准库 `csv` + `zipfile` 打包为带 UTF-8 BOM 的 zip（Windows Excel 直接打开中文不乱码，**无任何第三方依赖**）。前端 `reportApi.exportCsv(days)` 经 `api` 实例（自动附 Bearer 令牌、不裸链绕过权限）以 blob 触发下载；导出按钮仅在持 `report:view` 时展示，并带 `exporting` 加载态与失败 `Alert`。
    - **测试**：更新 `tests/test_dashboard.py`（字段改名 + `trend_days==30` 断言），新增 `test_dashboard_export_tables` 校验 5 张表齐全、KPI 用户数=2、状态映射「审批中」、趋势 31 行且 `started` 和=1、部门含「研发部」、动态 2 行。
    - **校验**：后端 `compileall`（app + tests）exit 0；前端 `tsc --noEmit` exit 0。沙箱限制同上（无 sqlalchemy/pytest/可跑 vite）；标准 Linux/Docker 环境 `pytest` 共 **11 项**（④ 8 项 + 报表中心 3 项）应全绿。

19. **工作流引擎测试推广（服务层测试覆盖）**：把全栈专家规范的测试模式从「超时升级（④）」推广到工作流引擎这一核心业务层。
    - **既有**：`tests/test_workflow_engine.py` 已覆盖引擎纯逻辑（`advance` / `countersign_result` / 条件分支 / 并行汇聚防死锁），不依赖 DB、可 `python3` 直跑。
    - **新增** `tests/test_workflow_service.py`（真实 SQLite 集成测试，与 `test_dashboard.py` 同范式，**不 mock 服务层**）：覆盖 `WorkflowService` 端到端——发起激活节点与待办、审批通过/驳回置终态、非审批人决策 `ForbiddenError`、转办改派并留痕 `origin_approver_id`、发起人撤回 `canceled`、催办生成日志并返回数量、会签 `strategy=all` 需全员通过（首人通过后仍 running）、定义生命周期（create→重复编码 `ConflictError`→save_version→publish→可发起）、监控看板 `get_stats` 结构。共 **10 项**。
    - **设计要点**：服务层各 `Service.__init__` 仅吃 `session`（内部自建 repo），天然适配真实 SQLite 集成测试，无需为测试重构 DI；`decide/withdraw/urge` 内部读 `user.role.name` 做 RBAC，故测试 `_get_user` 用 `selectinload(User.role)` 预加载，避免异步惰性加载抛 `MissingGreenlet`。
    - **校验**：`compileall`（app + tests）exit 0；沙箱限制同上，标准环境 `pytest` 现共 **27 项**（④ 8 + 报表 3 + 引擎纯逻辑 6 + 服务层 10）应全绿。

20. **生产加固 + 实时能力（Phase 6）**：补齐全栈专家规范「上线前加固清单」缺口，并新增 SSE 实时推送。
    - **实时能力（SSE，此前完全缺失）**：新增 `app/realtime/events.py`（`EventBus` 进程内 asyncio pub/sub，每用户一条 `asyncio.Queue`，定向投递 `user_ids` 或广播；`publish` 非阻塞 `put_nowait`，慢消费者丢弃最旧事件避免拖垮主流程）+ `app/api/realtime.py`（`GET /api/events/stream`，`get_current_user` 鉴权，返回 `text/event-stream`，心跳间隔取自 `sse_heartbeat_seconds` 默认 25s，客户端断开经 `finally` 取消订阅）。`WorkflowService` 构造器新增可选 `event_bus` 注入（缺省 `None` 即关闭，单测/离线零副作用），在事务 `commit` 后发射 `workflow.task_assigned`（待办分派）、`workflow.status`（通过/驳回/撤回）、`workflow.decision`（催办/会签进展）；路由层用 `_wf(session)` 统一注入进程级单例 `get_event_bus()`。前端 `api/events.ts` 用 `fetch` + `ReadableStream` 手动解析 SSE（因原生 `EventSource` 无法携带 Authorization 头，令牌仅留请求头、不入 URL），断线指数退避自动重连；`components/RealtimeToasts.tsx` + `main.tsx` 包裹 antd `<App>` 上下文，将事件转为右上角即时提示。新增 `tests/test_realtime.py`（DB 无关 4 项：定向投递/广播/退订/队列溢出保护）。
    - **优雅停机（此前仅日志）**：新增 `middleware.ActiveRequestMiddleware`（在途请求计数器，置于中间件栈最外层），`main.py` lifespan 在 `yield` 后 drained 等待在途请求完成（`graceful_shutdown_timeout_seconds` 默认 15s，超时记录 `shutdown_drain_timeout` 并退出），避免强行中断在途事务与下行推送。
    - **配置**：`config.py` 新增 `sse_heartbeat_seconds` / `graceful_shutdown_timeout_seconds`，统一走环境变量。
    - **加固清单文档**：`HARDENING.md` 逐条核对 CORS（显式来源）/ `/health`+`/ready` / 限流 / 安全头（X-Content-Type-Options、X-Frame-Options、Referrer-Policy、CSP）/ 审计 / 请求链路 ID（request_id）/ 集中配置启动校验（生产快速失败）/ 优雅停机 / SSE 实时能力，并列出仍需运维配合项（HTTPS 终止、Nginx 关闭缓冲、刷新令牌改 httpOnly Cookie、PostgreSQL、限流阈值调参）。
    - **校验**：后端 `compileall`（app + tests）exit 0；前端 `tsc --noEmit` exit 0；`EventBus` 行为以 stdlib asyncio 直跑 5 项断言全绿。沙箱限制同上（无 sqlalchemy/pytest/可跑 vite），标准环境 `pytest` 现共 **31 项**（④ 8 + 报表 3 + 引擎纯逻辑 6 + 服务层 10 + 实时 4）应全绿。

21. **实时链路打通（消息/公告/请假事件 + 前端缓存失效）**：把 20 铺好的 SSE 通道从「只覆盖工作流」扩展为全链路实时，并让前端收到推送即刷新。
    - **后端补发射点**：`NotificationService.__init__` 新增 `event_bus` 注入 + `_emit` 助手，`notify` / `notify_many` 在 `commit` **之后**发射 `notification.created`（定向收件人）；`add` 仅落库不发射（由工作流自身事件表达，避免重复提醒）。`AnnouncementService` 注入总线，`_notify_published` 除逐人通知外另广播 `announcement.published`。`LeaveService` 注入总线，请假提交实时通知审批人。`WorkflowService` 改为 `NotificationService(session, event_bus=event_bus)`，并把 `_activate` 里两处 `NotificationService(self.session).add(...)` 收敛为复用 `self.notifications`（顺带去掉每次调用新建服务对象，且注入 Fake 时更可测）。路由层新增 `_ann(session)` / `_leave(session)` 两个注入助手（各替换 3 处内置实例化）。
    - **前端实时桥接**：`RealtimeToasts.tsx` → `components/RealtimeBridge.tsx`（已删除旧文件，`App.tsx` 同步改名）。除 toast 外新增**失效 React Query 缓存**：`notification.created` → `["notifications"]`（静默，不弹提示）；`announcement.published` → `["announcements"]` + `["notifications"]`；`workflow.task_assigned` → `wf-pending`/`wf-notified`；`workflow.status` → `wf-pending`/`wf-done`/`wf-mine`/`wf-stats` + `["wf-instance", id]`；`workflow.decision` → `wf-pending`/`wf-done` + `["wf-instance-logs", id]`。**效果**：顶部铃铛未读角标与待办列表由「30s 轮询才更新」变为事件到达即刷新。
    - **测试**：`tests/test_realtime.py` 扩至 6 项，新增服务层发射接线用例（用哑 session 构造 `NotificationService`，验证注入总线可送达、未注入时静默 no-op 不抛异常）。
    - **文档**：`HARDENING.md` 实时设计要点按服务拆分列出各事件与发射时机。
    - **校验**：后端 `compileall`（app + tests）exit 0；前端 `tsc --noEmit` exit 0。标准环境 `pytest` 现共 **33 项**（④ 8 + 报表 3 + 引擎纯逻辑 6 + 服务层 10 + 实时 6）应全绿。
    - **设计取舍**：消息中心保留 30s 轮询作为兜底（SSE 断线期间仍能最终一致），实时推送只做「加速」而非唯一数据源，避免长连接异常导致数据永久陈旧。

22. **部署就绪度核查 + 收尾加固（应 Elvis「能部署了吗」提问）**：做了一次完整的可部署性审计，并修掉其中几处确凿缺口。
    - **审计结论**：后端 **81 个端点**（17 个路由前缀）、前端 **21 页面 / 20 路由**；`docker-compose.yml` + `backend/Dockerfile` + `run.sh` + 迁移链 `0001→0002→0003` + 前后端 `.env.example` + 种子账号 `admin/admin123` 齐备；README 部署步骤准确。**静态校验全绿**：`compileall` exit 0、`tsc --noEmit` exit 0、**60 条 app 内部 import 全部可解析**（自写 AST 脚本扫描，无缺失模块/符号）。
    - **补的缺口**：① `backend/.env.example` 补上新增的 `SSE_HEARTBEAT_SECONDS` / `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS`；② README 新增「生产部署注意事项」（前端改 `npm run build` + Nginx 托管，含 `proxy_buffering off` / `proxy_http_version 1.1` 这两行决定 SSE 是否实时）；③ `security.py` PBKDF2 迭代 **10 万 → 60 万**（对齐 OWASP；哈希串自带迭代次数故**向后兼容**，存量账号无需重置密码，代价是单次登录 CPU 上升）；④ 前端 `mapError` 对**无响应**的网络失败统一返回「网络连接不可用，请检查网络后重试」，不再把 `Network Error` 抛给用户；⑤ `QueryClient` 重试策略改为 **4xx 不重试 / 5xx 与网络错误最多重试 3 次**（原为无差别重试 1 次）；⑥ 新增 `components/ErrorBoundary.tsx` 并在 `main.tsx` 包裹应用，避免组件异常导致白屏。
    - **⚠️ 已知未做（需决策/标准环境）**：生产前端仍需在标准环境执行 `npm run build`（沙箱 rollup 原生库无法 dlopen）；`docker-compose` 的 frontend 服务目前跑 `npm run dev`（开发态），生产建议改为构建 + Nginx（README 已给配置）；无 CI 配置；无 `/metrics` 监控端点；无 E2E 测试。
    - **校验**：后端 `compileall` exit 0；前端 `tsc --noEmit` exit 0。运行时冒烟与 `npm run build` 在本沙箱**无法执行**，需标准环境验证。

23. **生产部署形态落地 + CI 流水线**：把上一轮列出的 B 类空白里优先级最高的两项做掉。
    - **前端生产镜像**：新增 `frontend/Dockerfile`（多阶段：`node:20-alpine` 构建 → `nginx:1.27-alpine` 托管）+ `frontend/nginx.conf`（SPA `try_files` 回退、静态资源长缓存、安全头，并附**注释版**的 `/api` 同源反代配置，含 `proxy_buffering off` / `proxy_http_version 1.1`——这两行决定 SSE 是否实时）。`docker-compose.yml` 的 frontend 服务由「`npm run dev` 开发态」改为「build + Nginx」，宿主端口仍 `5173`（映射容器 80），沿用既有访问习惯与 CORS 默认来源；`VITE_API_BASE` 作为 **build arg** 传入（Vite 在构建期内联该变量，运行期改环境变量无效）。
    - **CI**：新增 `.github/workflows/ci.yml`，push/PR 触发，并行两个 job——后端 `compileall` + `pytest`（SQLite 免外部 DB）、前端 `npm run typecheck` + `npm run build`。用 GitLab CI / Jenkins 可按同样四步迁移。
    - **README 重写部署章节**：三个服务的形态表格、「部署到正式域名（必做）」说明（`VITE_API_BASE` 与 `CORS_ORIGINS` 必须同步且前端需重建）、外部 Nginx 反代片段、CI 说明。
    - **关键取舍**：前端默认走「绝对 API 地址 + 后端 CORS」（改动最小、CORS 已实现且显式来源）；同源反代方案作为**注释选项**留在 `nginx.conf`，启用需同时把 `VITE_API_BASE` 置空并把 `client.ts` 的 `||` 改为 `??`（否则空字符串会回落 localhost:8000）——未直接启用以免引入未验证的联动改动。
    - **校验**：`docker-compose.yml` 与 `ci.yml` 均通过 `yaml.safe_load` 解析（本次临时装上 pyyaml 用于校验）；`package.json` 的 `build`=`tsc --noEmit && vite build`、`typecheck` 存在；后端 `compileall` exit 0；前端 `tsc --noEmit` exit 0。
    - **⚠️ 仍未验证（有据可查）**：本轮实测确认沙箱**装不上**后端运行时——`pydantic` 需 Rust 工具链（报 "Rust not found"）、`greenlet`（SQLAlchemy 依赖）需 gcc（平台 `ohos-aarch64` 无编译器），`aiosqlite` 可装但无意义。因此**后端运行时冒烟在此环境确定无法执行**，非推测。`npm run build` 同样受阻于 rollup 原生库 dlopen。两者均需标准环境/CI 验证。

24. **部署手册（应 Elvis「写一份部署手册」）**：整合 README 部署章节与 `HARDENING.md` 运维项，产出独立手册 `DEPLOYMENT.md`，面向「服务器 Docker 生产」与「PC 机本地 SQLite」两类场景。
    - **结构**：0 场景一览 / 1 环境前置（Docker 与本地两套要求 + 端口规划）/ 2 服务器 Docker 部署（准备 `.env`（根目录，强随机 `JWT_SECRET`）、`docker compose up -d --build`、三服务形态表、curl 验证 `/health`+`/ready`、初始账号 admin/manager/employee、换域名必重建前端、`VITE_API_BASE`/`CORS_ORIGINS` 同步、外部 Nginx 反代片段（关缓冲保 SSE）、数据卷备份 `pg_dump` 恢复）/ 3 PC 本地 SQLite 部署（backend `cp .env.example .env` + `bash run.sh`、frontend `npm install` + `npm run dev`、访问 5173、停止重启重置）/ 4 配置项速查（后端 10 项 + 前端 1 项变量）/ 5 上线前加固清单（HTTPS/SSE 缓冲/刷新令牌 httpOnly/端口收敛/限流/改默认密码/密钥管理）/ 6 常见问题 7 条（含 VITE_API_BASE 构建期内联、SSE 缓冲、JWT 弱密钥启动失败、CORS、旧 SQLite 迁移、镜像拉取、忘密码）/ 7 升级回滚 / 8 验证边界说明。
    - **补充的真实坑**：服务器远程访问时 `VITE_API_BASE` 必须填**浏览器可达的后端地址**（如 `http://<服务器IP>:8000`），若填 `localhost:8000` 远程用户会去连自己机器的 8000 端口而失败——这是手册相对 README 新增的关键提示。
    - **校验**：文件已写入 `zk-oa/DEPLOYMENT.md`；内容与现有 `docker-compose.yml` / `frontend/Dockerfile` / `frontend/nginx.conf` / `backend/Dockerfile` / `backend/run.sh` / 两端 `.env.example` 逐项核对一致。

25. **部署教程补「迁移到新机器」专章（应 Elvis「写部署教程以便迁移」）**：上一轮 `DEPLOYMENT.md` 只覆盖全新安装，本次补上「迁移」这一真实诉求。
    - 新增第 8 章「迁移到新机器」：搬迁清单（代码/配置/库/上传文件/对象存储，标注必搬项）、SQLite→新 PC 整体 tar 拷贝、PostgreSQL（Docker）→新服务器（pg_dump 导入 + 或搬卷两种）、SQLite→PostgreSQL 跨类型迁移说明（系统无内置数据搬迁工具，给 ETL 路径）、迁移后验证清单、常见迁移坑 4 条。
    - **关键事实已核实**：SQLite 库位于 `backend/oa.db`（`sqlite+aiosqlite:///./oa.db` 相对 backend cwd）；上传目录 `backend/uploads/`（`config.upload_dir` 默认 `uploads`，`STORAGE_BACKEND=local` 时落盘，S3 时不在本机）；`JWT_SECRET` 必须原样迁移否则刷新令牌全失效。
    - 标题由「部署手册」改为「部署与迁移教程」，原第 8 章验证边界顺延为第 9 章；更新日期 2026-09-28。
    - **校验**：手册内容与 `config.py`（upload_dir / storage_backend / jwt_secret 快速失败校验）一致。

<!-- OBSIDIAN_DBLINK_RELATED_START -->
## 关联文档（双链自动生成）
- [[00-文档总索引.md]]
<!-- OBSIDIAN_DBLINK_RELATED_END -->
