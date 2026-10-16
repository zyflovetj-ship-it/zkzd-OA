---
summary: "「生产加固清单（Phase 6）」：> 对照全栈专家规范「健康检查 / 优雅停机 / 安全头 / 限流 / HTTPS / 实时能力」逐条核对。
tags: [md, zk-oa, 中科平台_zk-oa, 文档]
dblink_managed: true
---

# 生产加固清单（Phase 6）

> 对照全栈专家规范「健康检查 / 优雅停机 / 安全头 / 限流 / HTTPS / 实时能力」逐条核对。
> 所有结论均基于本仓库当前代码（`backend/app/main.py`、`core/config.py`、`core/middleware.py`、`api/realtime.py`、`realtime/events.py`、`services.py`）。

## ✅ 已落地项

| 加固项 | 状态 | 实现位置 | 说明 |
| --- | --- | --- | --- |
| 健康检查 | ✅ | `main.py` `/health` + `/ready` | `/health` 轻量存活；`/ready` 探活数据库（`SELECT 1`），异常返回 503 |
| 显式 CORS | ✅ | `config.cors_origin_list` + `CORSMiddleware` | 来源来自 `cors_origins` 逗号拆分，`allow_credentials=True`，**生产禁用通配符** |
| 安全头 | ✅ | `middleware.SECURITY_HEADERS` | `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`、`Content-Security-Policy: default-src 'self'` |
| 限流 | ✅ | `middleware.RateLimitMiddleware` | 固定窗口（每分钟每 IP），`rate_limit_per_minute=0` 默认关闭；探针/文档路径豁免；429 带 `Retry-After` |
| 审计日志 | ✅ | `middleware.AuditMiddleware` | 仅审计变更类与登录/登出/刷新，独立事务写入，失败只告警；不记录密码/令牌 |
| 请求上下文 / 链路 ID | ✅ | `middleware.RequestContextMiddleware` | 注入 `request_id`（支持 `x-request-id` 透传），访问日志与审计日志串联 |
| 集中配置 + 启动校验 | ✅ | `core/config.py` | 全部来自环境变量；生产环境**快速失败**：弱 JWT 密钥或 SQLite 直接启动报错 |
| 优雅停机 | ✅（本轮新增） | `middleware.ActiveRequestMiddleware` + `main.py` lifespan | 在途请求计数器，停机时 drained 等待在途请求完成，超时（默认 15s）记录并退出 |
| 实时能力（SSE） | ✅（本轮新增） | `api/realtime.py` + `realtime/events.py` + 前端 `api/events.ts` | 鉴权 SSE 推送，心跳保活，断线指数退避重连；令牌仅走 Authorization 头，不入 URL |

## ⚠️ 仍需运维/基础设施配合

| 加固项 | 状态 | 建议 |
| --- | --- | --- |
| HTTPS / TLS | ⚠️ 依赖部署 | 应用本身不终止 TLS；生产前置 Nginx / 云 LB 做 HTTPS 终止并下发 `Strict-Transport-Security` |
| 反向代理缓冲 | ⚠️ 依赖部署 | SSE 端点已下发 `X-Accel-Buffering: no`，Nginx 需确认未强制 buffering |
| 令牌存储 | ⚠️ 建议升级 | 当前前端访问令牌仅存内存（已规避 XSS 窃取）；刷新令牌建议生产改为 httpOnly Cookie |
| 数据库 | ⚠️ 依赖部署 | 生产使用 PostgreSQL（已在启动校验强制）；连接池参数按负载调优 |
| 限流阈值 | ⚠️ 建议调参 | 默认关闭；上线前按网关/SLB 容量设置 `rate_limit_per_minute` |

## 实时能力设计要点

- **事件总线** `realtime/events.py`：进程内 asyncio pub/sub，每用户一条 `asyncio.Queue`，定向投递（`user_ids`）或广播；`publish` 非阻塞（`put_nowait`），慢消费者丢弃最旧事件避免拖垮主流程。
- **SSE 端点** `GET /api/events/stream`：`get_current_user` 鉴权，返回 `text/event-stream`，心跳间隔取自 `sse_heartbeat_seconds`（默认 25s），客户端断开经 `finally` 取消订阅。
- **服务层发射**：各服务通过构造器注入 `event_bus`（缺省 `None` 即关闭，单测/离线零副作用）；一律在事务 `commit` **之后**发射，避免「已推送却回滚」。
  - `WorkflowService`：`workflow.task_assigned`（待办分派）、`workflow.status`（通过/驳回/撤回）、`workflow.decision`（催办/会签进展）。
  - `NotificationService`：`notify` / `notify_many` 提交后发射 `notification.created`（定向到收件人）；`add` 仅落库不发射——它由工作流自身事件表达，避免重复提醒。
  - `AnnouncementService`：发布（或由未发布转已发布）时，除逐人通知外另广播 `announcement.published`。
  - `LeaveService`：请假提交后经 `NotificationService` 实时通知审批人。
- **前端**：`api/events.ts` 用 `fetch` + `ReadableStream` 手动解析 SSE（因 `EventSource` 无法携带 Authorization 头），指数退避自动重连；`components/RealtimeBridge.tsx` 把事件转为两类动作——① 右上角即时提示（toast）；② **失效相关 React Query 缓存**（`notifications` / `wf-pending` / `wf-mine` / `wf-stats` / `wf-instance` 等），使未读角标与待办列表即时刷新，不再受 30s 轮询的可见延迟影响。`notification.created` 仅静默刷新缓存、不弹提示，由具体业务事件各自负责提示，避免重复打扰。

## 验证方式

```bash
# 后端语法校验
cd backend && python -m compileall -q app

# 事件总线单测（无需数据库）
cd backend && pytest -q tests/test_realtime.py

# 前端类型校验
cd frontend && npm run typecheck
```

<!-- OBSIDIAN_DBLINK_RELATED_START -->
## 关联文档（双链自动生成）
- [[00-文档总索引.md]]
<!-- OBSIDIAN_DBLINK_RELATED_END -->
