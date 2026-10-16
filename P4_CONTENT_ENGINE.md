---
summary: "「zk-oa 内容引擎（文档中心 + 文件上传）」：> 路线图收官切片：在已完成「流程引擎 / 组织权限中心 / 内容门户 / 建模运维（运维中心 + 建模引擎 + 日志中心）」之后，补齐泛微七大引擎中的**内容"
tags: [md, zk-oa, 中科平台_zk-oa, 文档]
dblink_managed: true
---

# zk-oa 内容引擎（文档中心 + 文件上传）

> 路线图收官切片：在已完成「流程引擎 / 组织权限中心 / 内容门户 / 建模运维（运维中心 + 建模引擎 + 日志中心）」之后，补齐泛微七大引擎中的**内容引擎**，实现企业文档的集中管理、受控上传与权限化下载。

## 1. 目标与范围

| 能力 | 说明 |
| --- | --- |
| 文档元数据管理 | 标题 / 分类 / 类型 / 大小 / 描述 / 上传人 / 时间，列表支持分类过滤 + 标题搜索 + 服务端分页 |
| 受控文件上传 | 单文件 ≤ 20MB，扩展名白名单（pdf/doc/docx/xls/xlsx/ppt/pptx/png/jpg/jpeg/gif/txt/zip/csv/md），落盘为 `{id}.{ext}` |
| 鉴权下载 | `file_url` 仅存逻辑地址 `/api/documents/{id}/file`，由后端校验 `doc:view` 后流式返回，杜绝直链绕过权限 |
| 权限模型 | `doc:view`（查看/菜单）、`doc:upload`（上传/编辑元数据）、`doc:manage`（删除）；管理员通配 `*` 放行 |
| 审计可追溯 | 上传/下载/更新/删除均被 `AuditMiddleware` 自动记录于 `doc` 模块，与既有审计体系一致 |

## 2. 设计取舍

- **文件以 `{id}.{ext}` 落盘，绝不用客户端原始文件名拼路径** → 杜绝路径穿越；扩展名取自受约束白名单，拒绝可执行/非常规类型。
- **元数据与文件一对一**：先 `flush` 取自增 `id` 再写文件，文件写入失败则回滚元数据，保证一致。
- **逻辑下载地址而非裸静态目录**：前端不持有磁盘路径，下载经鉴权端点，未授权用户无法直链获取。
- **本地 `uploads/` 目录 + 生产可换对象存储**：`Settings.upload_dir` / `max_upload_size` 集中配置；生产环境建议改走 S3/OSS 并下发签名 URL（当前为本地落盘基线实现）。
- **文档计接入运维中心**：`OpsService` 概览新增「文档」计数，管理员视角可见全量规模。

## 3. 端点清单

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/documents` | `doc:view` | 列表：`category` / `q` / `offset` / `limit`，返回 `DocumentsPage` |
| POST | `/api/documents` | `doc:upload` | multipart 上传 + 创建（title/category/description/file） |
| PATCH | `/api/documents/{id}` | `doc:upload` | 更新元数据（标题/分类/描述） |
| GET | `/api/documents/{id}/file` | `doc:view` | 鉴权后流式下载 |
| DELETE | `/api/documents/{id}` | `doc:manage` | 删除元数据并 best-effort 清理磁盘文件 |

## 4. 数据模型变更（`documents` 表）

在原有 `id / title / file_url / owner_id / created_at` 基础上扩展：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `category` | String(50), index | 分类（general/policy/contract/report/training/other） |
| `file_type` | String(30) | 扩展名（如 pdf/docx） |
| `file_size` | Integer | 字节 |
| `description` | String(500) | 描述 |
| `owner_name` | String(50) | 上传人快照（避免关联查询） |
| `updated_at` | DateTime, onupdate | 更新时间 |

> 注：开发库为 SQLite，模型变更在 `init_db()` 的 `create_all` 下生效；生产 PostgreSQL 环境建议后续引入 Alembic 迁移（见 DELIVERY.md 下一步建议 #2）。

## 5. 涉及文件

- `backend/app/models.py` — `Document` 模型扩展
- `backend/app/core/config.py` — `upload_dir` / `max_upload_size`
- `backend/app/main.py` — 启动时确保上传目录存在
- `backend/app/schemas.py` — `DocumentUpdate` / `DocumentOut` / `DocumentsPage`
- `backend/app/repositories.py` — `DocumentRepository`
- `backend/app/services.py` — `DocumentService` + `ALLOWED_EXTENSIONS`（含 `upload_and_create` / `get_file` / `delete`）+ `OpsService` 计数
- `backend/app/api/routers.py` — `doc_router` + RBAC 依赖
- `backend/app/core/middleware.py` — 审计 classify 新增 `doc` 模块
- `backend/app/seed.py` — 权限点 `doc:*` + 菜单「文档中心」
- `frontend/src/types.ts` — `DocumentOut` / `DocumentUpdate` / `DocumentsPage` / `DOC_CATEGORY_LABELS`
- `frontend/src/api/endpoints.ts` — `docApi`（list/upload/update/remove/download，upload 走 multipart）
- `frontend/src/App.tsx` — 路由 `/documents`
- `frontend/src/components/AppLayout.tsx` — 注册 `FileTextOutlined`
- `frontend/src/pages/Documents.tsx` — 文档中心页（上传/筛选/搜索/分页/下载/删除）

## 6. 验证状态

| 项 | 结果 |
| --- | --- |
| 后端 Python 语法编译 | ✅ `python3 -m compileall` exit 0 |
| 前端 TS 类型检查 | ✅ `tsc --noEmit` 0 错误 |
| 运行时冒烟 / `vite build` | ⚠️ 沙箱限制（无编译器 / openharmony 平台），需在标准 Linux / Docker 执行 |

## 7. 后续建议

1. 生产文件存储切换对象存储（S3/OSS），`file_url` 改为签名 URL，`upload_and_create` 改为流式中转。
2. 引入 Alembic 替代 `create_all`，覆盖本切片的新增字段迁移。
3. 文档可接入版本管理 / 在线预览（Office 文档转 PDF 预览）。
4. 大文件改为分片上传 + 进度回传，前端 `Upload` 的 `customRequest` 对接。
5. 与「电子签单」联动：合同类文档可直接发起签署。

<!-- OBSIDIAN_DBLINK_RELATED_START -->
## 关联文档（双链自动生成）
- [[00-文档总索引.md]]
<!-- OBSIDIAN_DBLINK_RELATED_END -->
