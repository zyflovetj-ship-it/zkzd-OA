---
summary: "「中科智电 OA 系统（zk-oa）」：全栈 OA 系统：**FastAPI + PostgreSQL + React 19 + AntD 5**。覆盖员工/部门管理、考勤/请假审批、公告/文档、审批"
tags: [md, zk-oa, 中科平台_zk-oa, 文档]
dblink_managed: true
---

# 中科智电 OA 系统（zk-oa）

全栈 OA 系统：**FastAPI + PostgreSQL + React 19 + AntD 5**。覆盖员工/部门管理、考勤/请假审批、公告/文档、审批工作流、电子签单五大模块，采用 JWT 双令牌 + RBAC 鉴权。

## 架构

```
zk-oa/
├── backend/                 # FastAPI 后端（按功能分层）
│   ├── app/
│   │   ├── core/            # config / db / security / errors / logging / middleware
│   │   ├── models.py        # SQLAlchemy 模型（6 大模块）
│   │   ├── schemas.py       # Pydantic 校验
│   │   ├── repositories.py  # 仓储层（selectinload 防 N+1）
│   │   ├── services.py      # 服务层（业务逻辑 + 事务）
│   │   ├── model_fields.py  # 建模引擎字段 schema 纯函数（零依赖，可独立单测）
│   │   ├── api/             # 路由 + 依赖注入（RBAC）
│   │   ├── seed.py          # 初始角色与 admin 账号
│   │   ├── main.py          # 应用入口 / 中间件 / 健康检查
│   │   └── workflow_engine.py # 流程引擎纯函数（图遍历 / 条件 / 会签）
│   ├── requirements.txt
│   └── .env.example
└── frontend/                # React 前端
    └── src/
        ├── api/             # 类型化 axios 客户端（令牌附加 + 401 刷新重试）
        ├── auth/            # AuthContext
        ├── components/      # 布局
        └── pages/           # 各模块页面
```

## 快速开始（本地开发，SQLite）

```bash
# 后端
cd backend
cp .env.example .env          # 默认 SQLite，无需数据库服务
pip install -r requirements.txt
python run.sh                 # 建表 + 初始化 + 启动（http://localhost:8000）
# 默认账号：admin / admin123

# 前端（另开终端）
cd frontend
cp .env.example .env
npm install
npm run dev                   # http://localhost:5173
```

## 生产部署（PostgreSQL，Docker）

```bash
cd zk-oa
echo "JWT_SECRET=$(python3 -c 'import secrets;print(secrets.token_hex(32))')" > .env
docker compose up -d --build
```

- 后端 `/health`、`/ready` 健康检查；CORS 显式来源。
- 密码哈希使用 `hashlib.pbkdf2_hmac`（零原生依赖，跨平台可移植）。
- 访问令牌 15 分钟，刷新令牌服务端存储、可吊销、登录时轮换。

### 部署形态说明

`docker compose up -d --build` 会起三个服务：

| 服务 | 形态 | 说明 |
| --- | --- | --- |
| `db` | postgres:16-alpine | 带健康检查，后端等它 ready 才启动 |
| `backend` | Dockerfile 构建 | 启动前自动 `alembic upgrade head`，再跑 uvicorn |
| `frontend` | **多阶段构建 + Nginx 托管** | Node 构建静态资源 → nginx:alpine 托管，宿主 `5173` 映射容器 `80` |

前端是**生产形态**（`frontend/Dockerfile`）。需要热更新调试时不要用 compose，直接在 `frontend/` 下 `npm run dev`（`vite.config.ts` 已配 `/api` 代理）。

#### 部署到正式域名（必做）

`VITE_API_BASE` 是**构建期内联**的（Vite 的 `import.meta.env` 在编译期替换，运行期改环境变量无效），所以换域名必须重新构建：

```bash
# zk-oa 根目录 .env 中一并设置，再重建
echo "JWT_SECRET=$(python3 -c 'import secrets;print(secrets.token_hex(32))')" > .env
echo "VITE_API_BASE=https://api.yourdomain.com" >> .env
echo "CORS_ORIGINS=https://oa.yourdomain.com" >> .env
docker compose up -d --build
```

`CORS_ORIGINS` 必须与前端实际来源一致（生产禁用通配符，启动时无校验但浏览器会拒绝）。

#### 若前端由外部 Nginx 托管（不走 compose）

关键配置（**务必关闭代理缓冲，否则 SSE 实时推送会被缓存住**）：

```nginx
location / {
  root /usr/share/nginx/html;
  try_files $uri $uri/ /index.html;   # SPA 路由回退
}
location /api/ {
  proxy_pass http://backend:8000;
  proxy_set_header Host $host;
  proxy_http_version 1.1;
  proxy_set_header Connection "";     # SSE 长连接
  proxy_buffering off;                # 关键：否则 /api/events/stream 不实时
  proxy_read_timeout 3600s;
}
```

完整清单见 `frontend/nginx.conf`（已内置 SPA 回退与安全头）。

其余上线前加固项（HTTPS 终止、刷新令牌改 httpOnly Cookie、限流阈值、PostgreSQL 连接池）见 `HARDENING.md`。

### CI

`.github/workflows/ci.yml` 在 push/PR 时并行跑两个 job：后端 `compileall` + `pytest`（SQLite，无需外部数据库），前端 `npm run typecheck` + `npm run build`。若用 GitLab CI / Jenkins，按同样的四步迁移即可。

> **验证边界（重要）**：本仓库在开发沙箱（openharmony/aarch64）内**无法**执行 `npm run build` 与后端运行时冒烟——rollup 原生库无法 dlopen、pydantic 需 Rust 工具链、greenlet（SQLAlchemy 依赖）需 gcc，三者在该平台均不可用。上述步骤请在标准 Linux/macOS/Docker 环境（或 CI）执行验证。

## 认证安全说明

- 访问令牌短时效（15min），刷新令牌存于服务端 `refresh_tokens` 表，支持吊销与轮换。
- 当前前端令牌存于内存（不写 localStorage，降低 XSS 风险）；刷新页面需重新登录。
  **生产建议**：刷新令牌改用 `httpOnly` + `Secure` + `SameSite` Cookie，实现无感续期与持久登录。

## 接口一览

| 模块 | 端点 |
| --- | --- |
| 认证 | `POST /api/auth/login`、`/refresh`、`/logout`、`GET /me` |
| 用户/部门/角色 | `GET/POST /api/users`、`PATCH /api/users/{id}`、`GET /api/users/roles`、`POST/PATCH/DELETE /api/users/roles/{id}`（角色 CRUD，需 `org:role:manage`）、`GET/POST /api/departments` |
| 请假 | `GET/POST /api/leave`、`POST /api/leave/{id}/review` |
| **考勤** | `POST /api/attendance/clock`（打卡）、`GET /api/attendance/me?month=`（我的月度考勤）、`GET /api/attendance/settings` + `PUT`（班次，写需 `att:manage`）、`GET /api/attendance/records` + `PATCH /records/{id}`（全员记录/人工修正，`att:manage`）、`GET /api/attendance/stats?month=`（按人统计，`att:manage`）、`GET/POST /api/attendance/overtime` + `POST /overtime/{id}/review`、`GET /api/attendance/export?month=`（xlsx，`att:manage`） |
| **报销** | `GET/POST /api/expenses`、`GET/PATCH/DELETE /api/expenses/{id}`、`POST /api/expenses/{id}/submit`（发起内置审批流 `expense-claim`）、`POST /api/expenses/{id}/paid`（`expense:manage`）、`GET /api/expenses/stats`、`GET /api/expenses/export`（xlsx）、`POST /api/expenses/import`（xlsx 批量导入为草稿） |
| **公文** | `GET/POST /api/official-docs`、`GET/PATCH/DELETE /api/official-docs/{id}`、`POST /{id}/circulate`（传阅，空 user_ids=全体）、`POST /{id}/archive`；查看需 `doc:official:view`，登记/传阅/归档需 `doc:official:manage` |
| **审批委托** | `GET/POST /api/workflows/delegations`、`PATCH/DELETE /api/workflows/delegations/{id}`（时段内审批权自动改派给受托人） |
| 公告 | `GET/POST /api/announcements`、`PATCH /api/announcements/{id}`、`POST /{id}/read`（阅读回执）、`GET /{id}/readers`（阅读明细，需 `ann:manage`） |
| 工作流 | `GET/POST /api/workflows/definitions`、`POST /api/workflows/instances`、`GET /api/workflows/pending`、`POST /api/workflows/tasks/{id}/decide`（通过/驳回）、`POST .../transfer`、`POST .../addsign`、`POST .../withdraw`、`POST .../urge`、`GET /api/workflows/stats`（监控看板，需 `wf:monitor`） |
| 文档中心 | `GET/POST /api/documents`、`GET/PATCH/DELETE /api/documents/{id}`、`GET /{id}/file`、**版本**：`GET/POST /api/documents/{id}/versions`、`GET /{id}/versions/{vid}/file`（历史版本下载） |
| 签单 | `GET /api/signatures/{ref_type}/{ref_id}`、`POST /api/signatures` |
| 内容门户 | `GET /api/portal/overview`（角色化工作台聚合，登录即可） |
| 运维中心 | `GET /api/ops/overview`（系统级运行概览：实体计数 / 流程实例分布 / 角色人数矩阵 / 最近实例，需 `org:ops:view` 或管理员） |
| **建模引擎** | `GET/POST /api/models/entities`、`GET/PATCH/DELETE /api/models/entities/{id}`、`GET/POST /api/models/entities/{id}/records`、`PATCH/DELETE /api/models/records/{id}`、`GET /api/models/stats` |

### 新增模块权限点

| 权限码 | 角色发放 | 含义 |
| --- | --- | --- |
| `att:view` | admin / manager / employee | 打卡、我的月度考勤、班次查看、提交加班 |
| `att:manage` | admin / manager | 全员考勤记录与修正、班次设置、按人统计、加班审批、xlsx 导出 |
| `expense:view` | admin / manager / employee | 提交与查看自己的报销单 |
| `expense:manage` | admin / manager | 查看全部报销、打款、统计与导出、xlsx 导入 |
| `doc:official:view` | admin / manager / employee | 查看公文 |
| `doc:official:manage` | admin / manager | 登记、传阅、归档公文 |

> 报销提交时由 `seed.py` 预置的流程 `expense-claim`（费用报销审批）自动发起实例；
> 流程结束（通过/驳回/撤回）时回写报销单状态——撤回会退回草稿并解除关联。

### 建模引擎权限点

| 权限码 | 角色发放 | 含义 |
| --- | --- | --- |
| `model:view` | admin / manager / employee | 查看实体与数据、建模概览 |
| `model:manage` | admin / manager | 实体建模（字段 schema、发布/停用、删除） |
| `model:data:edit` | admin / manager / employee | 数据行新增 / 编辑 / 删除 |

> 实体处于 `draft` 时不可录入数据，发布为 `published` 后才开放录入；
> 实体下仍有数据时禁止删除。数据存 JSON 列，列表过滤在服务层完成并以 `MAX_SCAN=2000` 限流。
> 健康 | `GET /health`、`/ready` |

> 权限：admin 全权限；manager 可审批请假/发布公告；employee 仅提交与查看自身数据。

<!-- OBSIDIAN_DBLINK_RELATED_START -->
## 关联文档（双链自动生成）
- [[00-文档总索引.md]]
<!-- OBSIDIAN_DBLINK_RELATED_END -->
