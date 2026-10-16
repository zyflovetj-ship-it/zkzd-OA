---
summary: "「P3 建模引擎交付概览（2026-09-25）」：对齐泛微 e-cology 七大引擎路线图，继 P0 流程引擎、P1 组织权限中心、P2 内容门户、P3 运维中心之后，
tags: [md, zk-oa, 中科平台_zk-oa, 文档]
dblink_managed: true
---

# P3 建模引擎交付概览（2026-09-25）

对齐泛微 e-cology 七大引擎路线图，继 P0 流程引擎、P1 组织权限中心、P2 内容门户、P3 运维中心之后，
完成 **建模引擎（动态实体建模 + 自定义表单 + 动态数据）** 的全栈落地。

## 一句话说明

业务人员可以在界面上「零 DDL」新建一个业务实体（例如客户档案、供应商台账、合同台账），
定义它的字段（类型/必填/唯一/选项），发布后即可录入数据、按字段搜索过滤、分页浏览与维护。

## 后端改动

| 文件 | 改动 |
| --- | --- |
| `app/models.py` | 新增 `ModelEntity`（实体定义：code/fields schema/display_field/status）与 `ModelRecord`（数据行：serial_no + JSON data） |
| `app/model_fields.py` | **新增**零依赖纯函数模块：字段 schema 校验、取值转换、数据清洗、行过滤 |
| `app/repositories.py` | 新增 `ModelEntityRepository` / `ModelRecordRepository`；记录数统计用 group by 避免 N+1；`MAX_SCAN=2000` 限制单次扫描 |
| `app/schemas.py` | 新增实体/记录/分页/统计共 8 个 Schema |
| `app/services.py` | 新增 `ModelingService`：实体 CRUD + 生命周期、数据行 CRUD + 唯一校验、概览统计；把 ValueError 统一映射为 422 |
| `app/api/routers.py` | 新增 `/api/models` 路由组（10 个端点）与三个权限依赖 |
| `app/seed.py` | 新增权限点 `model:view` / `model:manage` / `model:data:edit`，菜单「建模引擎 → 模型与数据」`/models` |

### 端点清单

```
GET    /api/models/entities                 实体列表（含记录数）        model:view
POST   /api/models/entities                 新建实体（201）             model:manage
GET    /api/models/entities/{id}            实体详情                    model:view
PATCH  /api/models/entities/{id}            改字段/状态/元信息          model:manage
DELETE /api/models/entities/{id}            删除实体（有数据则拒绝）    model:manage
GET    /api/models/entities/{id}/records    数据分页 + 过滤 + 模糊搜索  model:view
POST   /api/models/entities/{id}/records    新增数据（仅已发布实体）    model:data:edit
PATCH  /api/models/records/{id}             局部更新数据                model:data:edit
DELETE /api/models/records/{id}             删除数据                    model:data:edit
GET    /api/models/stats                    建模概览统计                model:view
```

## 前端改动

| 文件 | 改动 |
| --- | --- |
| `src/types.ts` | 新增 `ModelField` / `ModelEntityOut` / `ModelRecordOut` / `ModelRecordsPage` / `ModelStatsOut` 与 `FIELD_TYPE_LABELS` |
| `src/api/endpoints.ts` | 新增 `modelApi`（filters 以 JSON 字符串传递） |
| `src/pages/ModelStudio.tsx` | **新增**建模引擎主页：实体列表 + 实体设计器（字段行编辑/排序）+ 动态表格（按 schema 生成列）+ 动态表单（按类型渲染控件）+ 概览统计卡 |
| `src/App.tsx` | 新增路由 `/models` |
| `src/components/AppLayout.tsx` | 图标注册表补 `AppstoreOutlined` |

支持的字段类型：单行文本 / 多行文本 / 整数 / 金额 / 日期 / 日期时间 / 是否 / 下拉单选 / 单选按钮 / 多选 / 邮箱。

## 关键设计决策

1. **元数据 + JSON 数据列，而非动态建表**：新增实体无需 DDL 迁移，代价是 JSON 字段无法建跨方言索引，
   因此列表过滤在服务层内存完成，并用 `MAX_SCAN=2000` 限流；超量时应升为物理列或改用 PG JSONB + GIN。
2. **校验逻辑抽为零依赖模块**：`app/model_fields.py` 不 import fastapi / sqlalchemy，可被纯 Python 单测直接覆盖；
   服务层只做编排与异常映射（ValueError → 422）。这样把最易出错的类型转换与必填判定变成了可验证代码。
3. **实体生命周期**：`draft`（设计中，禁止录数）→ `published`（开放录入）；实体下有数据时禁止删除，避免误删业务台账。
4. **服务端才是校验边界**：前端的动态表单只做即时反馈，落库前所有取值仍按 schema 重新转换，未知字段一律丢弃。

## 验证结果

| 项 | 结果 |
| --- | --- |
| 后端 `python3 -m compileall app` | ✅ exit 0 |
| `python3 tests/test_model_fields.py` | ✅ 33 项断言全通过 |
| `python3 tests/test_workflow_engine.py` | ✅ 回归通过 |
| 前端 `tsc --noEmit` | ✅ 0 错误 |
| 运行时冒烟 / `vite build` | ⚠️ 沙箱 openharmony aarch64 无编译器、rollup 原生模块无法加载，需在你的标准环境执行 |

## 你环境里的验证方式

```bash
cd zk-oa/backend && python3 tests/test_model_fields.py      # 纯逻辑测试，任何环境可跑
cd zk-oa/backend && ./run.sh                                 # 启动后端 :8000
cd zk-oa/frontend && npm run dev                             # 启动前端 :5173
# 登录 admin/admin123 → 左侧「建模引擎 → 模型与数据」
```

冒烟脚本：

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"admin","password":"admin123"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -s -X POST http://localhost:8000/api/models/entities \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"code":"customer","name":"客户档案","status":"published","fields":[
       {"key":"name","label":"客户名称","type":"text","required":true},
       {"key":"level","label":"等级","type":"select","options":["A","B","C"]}]}'

curl -s -X POST http://localhost:8000/api/models/entities/1/records \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"data":{"name":"中科智电","level":"A"}}'

curl -s "http://localhost:8000/api/models/entities/1/records?q=中科" -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8000/api/models/stats -H "Authorization: Bearer $TOKEN"
```

## 后续可扩展

- 实体数据接入审批流：把建模记录作为流程发起时的数据源，实现「台账变更走审批」。
- 列表视图/布局自定义（每实体保存列宽、排序、默认筛选）。
- CSV/Excel 导入导出，以及字段级校验规则扩展（正则、数值范围、跨字段依赖）。
- 行级与字段级权限（谁能看哪些行、哪些列）。

<!-- OBSIDIAN_DBLINK_RELATED_START -->
## 关联文档（双链自动生成）
- [[00-文档总索引.md]]
<!-- OBSIDIAN_DBLINK_RELATED_END -->
