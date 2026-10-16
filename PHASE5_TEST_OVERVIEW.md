---
summary: "「Phase 5 测试验证 — 审批超时自动升级（优先级 ④）」：| 文件 | 类型 | 说明 |
tags: [md, zk-oa, 中科平台_zk-oa, 文档]
dblink_managed: true
---

# Phase 5 测试验证 — 审批超时自动升级（优先级 ④）

## 交付内容

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `backend/tests/test_timeout_escalation.py` | 新增 | pytest 测试套件（5 项 Fake 单元 + 3 项真实 SQLite 集成） |
| `backend/pytest.ini` | 新增 | `asyncio_mode=auto`、`testpaths=tests`、`pythonpath=.` |
| `backend/requirements.txt` | 修改 | 加入 `pytest==8.3.4` + `pytest-asyncio==0.25.0` |
| `backend/app/services.py` | 修改 | `WorkflowService.__init__` 支持依赖注入；`timeout_escalate_all` 改用 `self.users`/`self.notifications`/`self.scheduler` |

## 为什么改 services.py（DI 支撑测试）

原 `timeout_escalate_all` 在方法体内 `UserRepository(self.session)` / `NotificationService(self.session)` / `SchedulerRepository(self.session)` 内联实例化，导致单测无法隔离数据库。
改为在构造期注入（`workflow_repo` / `user_repo` / `notification_service` / `scheduler_repo`，默认回退现接线，**向后兼容** `WorkflowService(session)`），单测即可注入 Fake。

## 测试覆盖

**单元测试（Fake 注入，零数据库）**
1. 幂等边界：`list_running_overdue` 仅返回 `escalated_at IS NULL` 实例；标记后二次运行 `scanned=0`、`escalated=0`，通知仅一次。
2. 死信跳过：同 `ref_id` 已存在死信则跳过重通知（`dead_letters=0`、`escalated=0`）。
3. `notify` 策略：仅通知 admin/manager，不重分配（`reassigned=0`）。
4. `escalate` 策略：待办任务轮询转交兜底角色审批人，`origin_approver_id` 留痕、`escalate` 节点日志写入。
5. 异常落死信：通知失败写 `scheduler_dead_letters` 且不计升级（`escalated=0`、`dead_letters=1`）。

**集成测试（真实 SQLite + aiosqlite）**
- `test_integration_notify`：全链路通知 + `escalated_at` 标记。
- `test_integration_escalate`：待办转交兜底人 + `escalate` 日志。
- `test_integration_idempotent`：二次运行幂等。

## 运行方式

```bash
cd zk-oa/backend
pip install -r requirements.txt pytest pytest-asyncio
pytest -q                      # 单元 + 集成
python3 tests/test_timeout_escalation.py   # 仅 Fake 单元（需已装依赖）
```

## 沙箱限制（非代码缺陷）

当前 openharmony 沙箱未安装 `sqlalchemy` / `pytest`，无法在本环境执行，仅完成 `python3 -m compileall` 语法校验（exit 0）。在**标准 Linux / Docker 环境**即可一键 `pytest`。

<!-- OBSIDIAN_DBLINK_RELATED_START -->
## 关联文档（双链自动生成）
- [[00-文档总索引.md]]
<!-- OBSIDIAN_DBLINK_RELATED_END -->
