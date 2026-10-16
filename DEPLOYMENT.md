---
summary: "「中科智电 OA 系统（zk-oa）部署与迁移教程」：> 适用版本：zk-oa 全栈版（FastAPI + PostgreSQL + React 19 + AntD 5）
tags: [md, zk-oa, 中科平台_zk-oa, 文档]
dblink_managed: true
---

# 中科智电 OA 系统（zk-oa）部署与迁移教程

> 适用版本：zk-oa 全栈版（FastAPI + PostgreSQL + React 19 + AntD 5）
> 更新日期：2026-09-28
> 适用对象：需将本系统**全新部署**或**从旧机器迁移**到「服务器（生产）」或「PC 机（本地开发 / 演示 / 单机试用）」的人员。

## 0. 两种部署场景一览

| 场景 | 适用 | 数据库 | 运行方式 | 访问入口 |
| --- | --- | --- | --- | --- |
| 服务器生产 | 正式 / 团队使用 | PostgreSQL 16 | Docker Compose | 域名或服务器 IP |
| PC 本地 | 开发 / 演示 / 试用 | SQLite（零依赖） | 直接跑进程 | http://localhost:5173 |

核心差异：前端 `VITE_API_BASE` 是**构建期内联**的（Vite 编译期替换），服务器换地址必须**重建前端镜像**；PC 本地用 SQLite + 开发服务器，改配置即生效，无需构建。

## 1. 环境前置要求

### 1.1 服务器场景（Docker）

- Docker Engine ≥ 20.10
- Docker Compose ≥ v2（命令为 `docker compose`）
- 服务器可访问镜像仓库（或配置国内镜像源）
- 端口：前端 `5173`（对外）、后端 `8000`（建议仅内网）、数据库 `5432`（建议不对外开放）

### 1.2 PC 场景（本地）

- Python 3.12（后端）
- Node.js 20+（前端）
- 无需安装数据库（默认 SQLite 单文件）

### 1.3 端口规划

| 端口 | 服务 | 说明 |
| --- | --- | --- |
| 5173 | 前端 | 用户访问入口 |
| 8000 | 后端 API | 对外或仅内网 |
| 5432 | PostgreSQL | 仅服务器场景，建议内网 |

## 2. 场景一：服务器部署（Docker 生产）

### 2.1 准备配置文件

进入项目根目录，生成 Compose 环境文件 `.env`（注意是 zk-oa 根目录，不是 backend/）：

```bash
cd zk-oa

# 生成强随机 JWT 密钥（务必替换默认值，否则启动会失败）
echo "JWT_SECRET=$(python3 -c 'import secrets;print(secrets.token_hex(32))')" > .env

# 若从其他机器浏览器访问本服务器，必须补充以下两行（换成真实可达地址）
# VITE_API_BASE=http://<服务器IP>:8000
# CORS_ORIGINS=http://<服务器IP>:5173
```

⚠️ **关键坑**：`VITE_API_BASE` 会被写进前端产物，浏览器从**用户自己的机器**发起请求。若填 `http://localhost:8000`，远程用户访问时会去连他们本机的 8000 端口而失败。服务器远程访问务必填 `http://<服务器IP>:8000`（或正式域名对应的后端地址）。

`JWT_SECRET` 要求：生产**必须**是强随机值（长度 ≥ 32 字节）。若仍用示例默认值或弱密钥，后端**启动即报错退出**（快速失败机制）。

### 2.2 启动全部服务

```bash
docker compose up -d --build
```

该命令依次构建并启动三项服务：

| 服务 | 镜像 | 行为 |
| --- | --- | --- |
| db | postgres:16-alpine | 持久化卷 oa_pgdata，带健康检查 |
| backend | 本地构建 | 启动前自动 `alembic upgrade head`，再跑 uvicorn |
| frontend | 多阶段构建 | Node 构建静态资源，nginx:alpine 托管 |

首次构建需拉取镜像并执行 `npm ci` + 编译前端，耗时数分钟，请耐心等待。

### 2.3 验证服务存活

```bash
# 1. 后端存活（应返回 {"status":"ok"}）
curl http://localhost:8000/health

# 2. 后端就绪（应返回 {"status":"ready"}，已连通数据库）
curl http://localhost:8000/ready

# 3. 前端页面（应返回 HTML）
curl -s http://localhost:5173/ | head -n 5
```

### 2.4 登录与初始账号

浏览器访问 `http://<服务器IP>:5173`，使用初始账号登录：

| 账号 | 密码 | 角色 | 权限 |
| --- | --- | --- | --- |
| admin | admin123 | 管理员 | 全权限（`*` 通配） |

> **只有这一个账号。** 种子数据（`backend/app/seed.py`）只创建 `admin`，
> 角色 `admin / manager / employee` 会预置，但**不会**创建对应的 manager / employee 账号。
> 其余账号需登录后由管理员在「人事管理 → 员工管理」中新建（新建时可指定角色与部门）。

⚠️ 上线前务必在「人事管理 → 员工管理」中重置 admin 的默认密码；
   默认口令 `admin123` 是公开的，公网可达的部署必须改掉。

### 2.5 部署到正式域名（必做）

`VITE_API_BASE` 在**构建期**已写死进前端产物，运行期改环境变量无效。换域名必须重建：

```bash
cd zk-oa

# 编辑 .env，设置真实地址（替换 yourdomain.com）
cat >> .env <<'EOF'
VITE_API_BASE=https://api.yourdomain.com
CORS_ORIGINS=https://oa.yourdomain.com
EOF

# 重建并重启（仅改前端地址可只重建 frontend，但 backend 改了 CORS 需一起）
docker compose up -d --build
```

`CORS_ORIGINS` 必须与前端实际访问来源**完全一致**（协议 + 域名 + 端口）。生产禁用通配符，不一致会导致浏览器拒绝请求。

### 2.6 外部 Nginx 托管前端（可选）

若前端由你自己的 Nginx 托管、后端另起，关键配置（**务必关闭代理缓冲，否则 SSE 实时推送被缓存**）：

```nginx
server {
    listen 80;
    server_name oa.yourdomain.com;

    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;        # 关键：SSE 实时推送依赖
        proxy_read_timeout 3600s;
    }
}
```

完整版见仓库 `frontend/nginx.conf`（已内置 SPA 回退与安全头）。

### 2.7 数据持久化与备份

- 数据库数据存于 Docker 卷 `oa_pgdata`，删除容器不丢数据；删除卷才会清空。
- 备份：

```bash
docker compose exec db pg_dump -U oa oa > oa_backup_$(date +%F).sql
```

- 恢复：

```bash
docker compose exec -T db psql -U oa oa < oa_backup_YYYY-MM-DD.sql
```

## 3. 场景二：PC 机部署（本地开发 / 演示）

适合无 Docker 的笔记本、内网演示机。数据库用 SQLite（单文件，零依赖）。

### 3.1 后端（终端 1）

```bash
cd zk-oa/backend

# 1. 创建虚拟环境（可选但推荐）
python3 -m venv venv && source venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 初始化并启动（自动建表 + 种子数据 + 热更新）
cp .env.example .env      # 默认 SQLite，无需数据库服务
bash run.sh               # 或：python run.sh
```

启动后后端监听 `http://localhost:8000`，默认账号 admin/admin123。

### 3.2 前端（终端 2）

```bash
cd zk-oa/frontend

# 1. 安装依赖（首次较慢）
npm install

# 2. 启动开发服务器
cp .env.example .env      # VITE_API_BASE=http://localhost:8000
npm run dev               # 监听 http://localhost:5173
```

Vite 已配置 `/api` 代理到 `localhost:8000`；同时 `.env` 中 `VITE_API_BASE` 也指向该地址，两种方式均可连通，无需额外 CORS 配置。

### 3.3 访问

浏览器打开 `http://localhost:5173`，使用 admin/admin123 登录。

### 3.4 停止与重启

- 停止：在两个终端分别 `Ctrl+C`。
- 重启：重复 3.1 / 3.2 的启动命令即可（SQLite 数据已落盘 `backend/oa.db`）。
- 重置数据：删除 `backend/oa.db` 后重新 `bash run.sh`（会重建并重新种子化）。

## 4. 配置项速查

### 4.1 后端关键环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| DATABASE_URL | SQLite | 生产改 PostgreSQL |
| JWT_SECRET | 示例值 | 必须强随机，否则启动失败 |
| ACCESS_TOKEN_EXPIRE_MINUTES | 15 | 访问令牌时效 |
| REFRESH_TOKEN_EXPIRE_DAYS | 7 | 刷新令牌时效 |
| CORS_ORIGINS | localhost:5173 | 逗号分隔，禁用通配符 |
| SSE_HEARTBEAT_SECONDS | 25 | 心跳间隔，须小于代理空闲超时 |
| GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS | 15 | 优雅停机等待时长 |
| RATE_LIMIT_PER_MINUTE | 0 | 0 关闭，生产建议设值 |
| STORAGE_BACKEND | local | 生产可改 s3 |
| SCHEDULER_ENABLED | false | 审批超时升级，生产按需开 |

### 4.2 前端关键配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| VITE_API_BASE | http://localhost:8000 | 构建期内联，改域必须重建 |

## 5. 上线前加固清单（运维配合）

| 项 | 状态 | 建议 |
| --- | --- | --- |
| HTTPS / TLS | 依赖部署 | 前置 Nginx / 云 LB 终止 TLS，下发 HSTS |
| SSE 代理缓冲 | 依赖部署 | 反代必须 `proxy_buffering off` |
| 刷新令牌存储 | 建议升级 | 改 httpOnly + Secure + SameSite Cookie |
| 数据库暴露 | 建议收紧 | 服务器场景不要映射 5432 到公网 |
| 后端暴露 | 建议收紧 | 仅内网，经反代暴露 |
| 限流阈值 | 建议调参 | 设置 `RATE_LIMIT_PER_MINUTE` |
| 默认密码 | 必须改 | 上线前重置 admin/manager/employee |
| 密钥管理 | 必须做 | JWT_SECRET 用密钥管理服务，勿入代码库 |

后端已内置：健康检查、显式 CORS、安全头、审计日志、请求链路 ID、优雅停机、SSE 实时通道。详见 `HARDENING.md`。

## 6. 常见问题与排错

**Q1：改了域名，前端仍连旧地址？**
`VITE_API_BASE` 构建期内联，运行期改 `.env` 无效。必须在 `zk-oa/.env` 设新值后 `docker compose up -d --build` 重建前端。

**Q2：实时消息 / 待办不推送（SSE 失效）？**
检查反代是否关闭缓冲：Nginx 需 `proxy_buffering off` + `proxy_http_version 1.1`；后端已下发 `X-Accel-Buffering: no`。

**Q3：后端启动即退出，日志报 JWT / SQLite 错误？**
生产 `ENVIRONMENT=production` 会强制校验：JWT_SECRET 必须强随机、数据库不得用 SQLite。改用 PostgreSQL 并设置强密钥。

**Q4：浏览器报 CORS 错误？**
`CORS_ORIGINS` 必须与前端实际来源一致（含协议端口）。Compose 中通过根 `.env` 的 `CORS_ORIGINS` 注入。

**Q5：本地旧 SQLite 库迁移报错（重复建表）？**
若库由旧 `create_all` 生成、无 `alembic_version` 表，执行 `alembic stamp head` 标记为基线，或删除 `oa.db` 后重启。

**Q6：镜像拉取慢 / 失败？**
配置国内镜像源（如 Docker Hub 镜像加速器），或离线导入镜像。

**Q7：忘记 admin 密码？**
SQLite 本地可删 `oa.db` 重置；PostgreSQL 下用 `psql` 处理 `users` 表密码字段（PBKDF2 哈希），或走登录页重置流程。

## 7. 升级与回滚

### 7.1 代码更新

```bash
cd zk-oa
git pull            # 或拷贝新代码
docker compose up -d --build
```

数据库迁移在 backend 启动时由 `alembic upgrade head` 自动执行（向后兼容，无需手动）。

### 7.2 数据备份恢复

见 2.7。建议升级前先备份 `oa_pgdata` 卷或执行 `pg_dump`。

## 8. 迁移到新机器（从旧机搬数据 / 配置）——重点

适用：你已有一台机器上跑着的 zk-oa（无论 SQLite 还是 PostgreSQL），要把它**整体搬到另一台 PC 或服务器**，保留已有账号、流程、文档、附件。全新安装请看第 2 / 3 章。

### 8.1 要搬的东西清单

| 类别 | 本地（SQLite）路径 | Docker（PG）位置 | 必搬 |
| --- | --- | --- | --- |
| 代码 | zk-oa/ 整个目录 | zk-oa/ 整个目录 | 是 |
| 配置 | zk-oa/.env + backend/.env | zk-oa/.env（根） | 是 |
| 数据库 | backend/oa.db | Docker 卷 oa_pgdata | 是 |
| 上传文件 | backend/uploads/ | backend/uploads/（local 时） | 是 |
| 对象存储 | — | S3/OSS 桶（不在本机） | 否 |

⚠️ **JWT_SECRET 必须原样迁移**：刷新令牌由它签名。换值会导致所有已登录用户被强制登出、刷新令牌全部失效。迁移时**直接复制旧机 `.env` 里的 JWT_SECRET**，不要重新生成。

### 8.2 场景 A：SQLite → 新 PC（整体拷贝，最简单）

旧机操作（停掉后端，确保 oa.db 不再被写入）：

```bash
cd zk-oa
# 打包关键数据，排除虚拟环境与依赖缓存
tar czf zk-oa-migrate.tar.gz \
  --exclude=backend/venv --exclude=frontend/node_modules \
  --exclude=backend/__pycache__ --exclude='*.pyc' \
  backend/oa.db backend/uploads backend/.env .env frontend backend
```

新机操作（保持相同目录结构 `zk-oa/`）：

```bash
# 解包到目标位置
tar xzf zk-oa-migrate.tar.gz -C /目标路径/

# 后端（复用已有 oa.db，不会重建）
cd zk-oa/backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
bash run.sh

# 另一终端：前端
cd zk-oa/frontend && npm install && npm run dev
```

验证：浏览器登录，**旧账号、旧流程、旧附件都在**即成功。

> 若旧 `oa.db` 由早期 `create_all` 生成、缺 `alembic_version` 表，启动报重复建表，先执行 `alembic stamp head` 标记为基线，或删除 `oa.db` 后重启（后者会清空数据，慎选）。

### 8.3 场景 B：PostgreSQL（Docker）→ 新服务器

**方式一：pg_dump 导出导入（推荐，最完整）**

旧机：

```bash
cd zk-oa
docker compose exec db pg_dump -U oa oa > oa_dump.sql
# 同时拷贝 .env（含 JWT_SECRET）与 backend/uploads/（若 STORAGE_BACKEND=local）
```

新机（先把 `oa_dump.sql` 与 `.env` 放到 zk-oa/）：

```bash
cd zk-oa
docker compose up -d db                       # 先只起数据库
docker compose exec -T db psql -U oa oa < oa_dump.sql
docker compose up -d backend frontend         # 再起后端与前端
```

**方式二：直接搬 Docker 卷（同架构机器）**

旧机 `docker volume inspect` 找到 `oa_pgdata` 挂载点，`tar` 拷走；新机停服后覆盖该卷内容。适合无法 `pg_dump` 的受限环境，但跨主机 / 跨 PG 大版本兼容性差，**优先用方式一**。

⚠️ 迁到新服务器后，据新地址更新 `zk-oa/.env` 的 `VITE_API_BASE` / `CORS_ORIGINS`；改了前端地址需重建：`docker compose up -d --build`。`JWT_SECRET` 务必沿用旧值。

### 8.4 跨类型迁移（SQLite → PostgreSQL）

若你从 PC 本地 SQLite 试用，想迁到服务器 PostgreSQL 生产：

- 系统**没有内置** SQLite→PG 的自动数据搬迁工具（alembic 只管表结构，不转数据）。
- 最简稳妥路径：先在服务器按 2.x 起好 PostgreSQL 空库（admin 等种子账号自动建），再用你自己的 ETL 脚本把 `oa.db` 各表写入 PG（如 `sqlite3` + `psycopg`，或 `pandas` 读取后批量插入）。
- 若历史数据不重要，可直接重新种子化、不搬数据。
- 需要我写这个一次性迁移脚本可另行提出。

### 8.5 迁移后必做验证清单

- [ ] 旧账号可登录（证明 JWT_SECRET 一致、库已搬）
- [ ] 旧流程 / 请假 / 公告可见（证明业务数据已搬）
- [ ] 旧附件能下载（证明 uploads/ 已搬或 S3 配置正确）
- [ ] `/health`、`/ready` 正常
- [ ] CORS / 域名访问正常（VITE_API_BASE、CORS_ORIGINS 已按新地址更新）
- [ ] 刷新令牌续期正常（登入后静置超 15min 访问令牌时效，仍不需重登）

### 8.6 常见迁移坑

- **附件全部 404**：只搬了库没搬 `backend/uploads/`。
- **全员被踢下线**：`JWT_SECRET` 重新生成，刷新令牌全失效，需重登。
- **库启动报重复建表**：旧 `oa.db` 缺 `alembic_version`，先 `alembic stamp head`。
- **前端连旧地址**：换服务器后 `VITE_API_BASE` 没改或没重建前端。

## 9. 验证边界说明（重要）

本系统在开发沙箱（openharmony / aarch64）内**无法**执行以下验证，需在标准 Linux / macOS / Docker 环境或 CI 中完成：

- 前端 `npm run build`（沙箱 rollup 原生库无法 dlopen）
- 后端运行时冒烟（沙箱缺 Rust/gcc，pydantic、SQLAlchemy 等装不上）

已在本仓库完成的可验证项：后端 `compileall` 语法校验、前端 `tsc --noEmit` 类型校验、静态 import 全解析、单元测试（标准环境 `pytest` 共 33 项）。

部署到你的服务器 / PC 后，请按 2.3 / 3.3 的 curl 与浏览器步骤做**实际启动验证**，确认 `/health`、`/ready` 与登录通畅后再对外提供服务。

<!-- OBSIDIAN_DBLINK_RELATED_START -->
## 关联文档（双链自动生成）
- [[00-文档总索引.md]]
<!-- OBSIDIAN_DBLINK_RELATED_END -->
