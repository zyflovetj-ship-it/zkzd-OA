"""旧线性流程 → 图结构引擎 的兼容迁移脚本（幂等，可重复执行）。

背景：旧版流程用 workflow_definitions.steps（有序线性步骤）+ workflow_instances.current_step
驱动流转；新引擎改为「流程定义 + 版本(graph 图结构) + 节点任务」。本脚本负责：
  1. 补齐新模型所需的列（老库升级场景）；
  2. 把线性 steps 转成 start → n0 → n1 → ... → end 的图结构并发布为版本 1；
  3. 迁移实例与任务（状态 pending→running、done→approved，step_index→node_id）；
  4. 依据任务生成流转日志，保证监控时间线可用；
  5. 清理旧列（SQLite 3.35+ / PostgreSQL 支持 DROP COLUMN，失败则跳过不影响使用）。

用法：cd backend && python3 migrate_workflow.py
"""
import asyncio
import json
import sys
from datetime import datetime

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import init_db

settings = get_settings()

NEW_COLUMNS = {
    "workflow_definitions": [
        ("code", "VARCHAR(60)"),
        ("category", "VARCHAR(50) DEFAULT 'general'"),
        ("icon", "VARCHAR(40) DEFAULT ''"),
        ("status", "VARCHAR(20) DEFAULT 'draft'"),
        ("current_version", "INTEGER DEFAULT 0"),
        ("updated_at", "TIMESTAMP"),
    ],
    "workflow_instances": [
        ("code", "VARCHAR(40)"),
        ("version_id", "INTEGER"),
        ("form_data", "JSON"),
        ("current_nodes", "JSON"),
        ("started_at", "TIMESTAMP"),
        ("finished_at", "TIMESTAMP"),
    ],
    "workflow_tasks": [
        ("node_id", "VARCHAR(60)"),
        ("node_type", "VARCHAR(30) DEFAULT 'approval'"),
        ("origin_approver_id", "INTEGER"),
        ("mode", "VARCHAR(20) DEFAULT 'single'"),
        ("seq", "INTEGER DEFAULT 0"),
        ("due_at", "TIMESTAMP"),
    ],
}
OLD_COLUMNS = {
    "workflow_definitions": ["steps"],
    "workflow_instances": ["current_step"],
    "workflow_tasks": ["step_index"],
}


async def _columns(conn, table: str) -> set:
    if settings.database_url.startswith("sqlite"):
        res = await conn.execute(text(f"PRAGMA table_info({table})"))
        return {r[1] for r in res.all()}
    res = await conn.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
        {"t": table},
    )
    return {r[0] for r in res.all()}


async def ensure_new_columns(conn) -> None:
    for table, cols in NEW_COLUMNS.items():
        existing = await _columns(conn, table)
        if not existing:
            continue  # 表还不存在，交给 create_all
        for name, ddl in cols:
            if name not in existing:
                try:
                    await conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                    )
                    print(f"  + 补列 {table}.{name}")
                except Exception as e:  # noqa: BLE001
                    print(f"  ! 补列 {table}.{name} 失败（可能已存在）: {e}")


async def migrate(conn) -> int:
    defs_cols = await _columns(conn, "workflow_definitions")
    if "steps" not in defs_cols:
        print("未发现旧线性字段 steps，无需迁移数据。")
        return 0

    rows = (
        await conn.execute(
            text("SELECT id, name, description, steps FROM workflow_definitions")
        )
    ).mappings().all()

    migrated = 0
    for r in rows:
        def_id = r["id"]
        try:
            steps = json.loads(r["steps"]) if isinstance(r["steps"], str) else (r["steps"] or [])
        except Exception:  # noqa: BLE001
            steps = []
        if not isinstance(steps, list):
            steps = []

        # 线性步骤 → 串行图结构
        nodes = [{"id": "start", "type": "start", "name": "发起"}]
        edges = []
        prev = "start"
        for i, step in enumerate(steps):
            nid = f"n{i}"
            nodes.append(
                {
                    "id": nid,
                    "type": "approval",
                    "name": (step or {}).get("name", f"步骤{i + 1}"),
                    "assignee": {"type": "role", "value": (step or {}).get("role")},
                }
            )
            edges.append({"id": f"e_{prev}_{nid}", "source": prev, "target": nid})
            prev = nid
        nodes.append({"id": "end", "type": "end", "name": "结束"})
        edges.append({"id": f"e_{prev}_end", "source": prev, "target": "end"})
        graph = {"nodes": nodes, "edges": edges}

        code = f"LEGACY{def_id:04d}"
        await conn.execute(
            text(
                "UPDATE workflow_definitions SET code = :code, status = 'published', "
                "current_version = 1, category = 'general' WHERE id = :id"
            ),
            {"code": code, "id": def_id},
        )
        await conn.execute(
            text(
                "INSERT INTO workflow_versions "
                "(definition_id, version, graph, form_id, status, published_at, remark, created_at) "
                "VALUES (:d, 1, :g, NULL, 'published', :p, '由旧线性流程迁移', :p)"
            ),
            {"d": def_id, "g": json.dumps(graph, ensure_ascii=False), "p": datetime.utcnow()},
        )
        migrated += 1

    # 实例：补 code/version_id/form_data/current_nodes/started_at，pending→running
    await conn.execute(
        text(
            "UPDATE workflow_instances SET "
            "code = 'WFLEGACY' || CAST(id AS TEXT), "
            "version_id = (SELECT id FROM workflow_versions v WHERE v.definition_id = workflow_instances.definition_id ORDER BY v.id LIMIT 1), "
            "form_data = '{}', "
            "current_nodes = CASE WHEN status = 'pending' THEN '[\"n0\"]' ELSE '[]' END, "
            "started_at = created_at, "
            "finished_at = CASE WHEN status = 'pending' THEN NULL ELSE created_at END, "
            "status = CASE WHEN status = 'pending' THEN 'running' ELSE status END"
        )
    )

    # 任务：step_index → node_id，done → approved
    await conn.execute(
        text(
            "UPDATE workflow_tasks SET "
            "node_id = 'n' || CAST(step_index AS TEXT), "
            "node_type = 'approval', "
            "mode = 'single', "
            "seq = 0, "
            "status = CASE WHEN status = 'done' THEN 'approved' ELSE status END"
        )
    )

    # 依据任务生成流转日志，保证监控时间线可用
    tasks = (
        await conn.execute(
            text(
                "SELECT id, instance_id, node_id, node_name, status, approver_id, "
                "comment, created_at, decided_at FROM workflow_tasks"
            )
        )
    ).mappings().all()
    for t in tasks:
        if t["status"] == "pending":
            action, when = "enter", t["created_at"]
        else:
            action = "approve" if t["status"] == "approved" else "reject"
            when = t["decided_at"] or t["created_at"]
        await conn.execute(
            text(
                "INSERT INTO workflow_node_logs "
                "(instance_id, node_id, node_name, action, operator_id, comment, created_at) "
                "VALUES (:i, :n, :nm, :a, :o, :c, :w)"
            ),
            {
                "i": t["instance_id"],
                "n": t["node_id"],
                "nm": t["node_name"] or "",
                "a": action,
                "o": t["approver_id"],
                "c": t["comment"] or "",
                "w": when or datetime.utcnow(),
            },
        )

    # 清理旧列（失败不影响使用）
    for table, cols in OLD_COLUMNS.items():
        existing = await _columns(conn, table)
        for col in cols:
            if col in existing:
                try:
                    await conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))
                    print(f"  - 删除旧列 {table}.{col}")
                except Exception as e:  # noqa: BLE001
                    print(f"  ! 旧列 {table}.{col} 未删除（可忽略）: {e}")

    return migrated


async def main() -> None:
    print("1/3 确保新表与新列就绪 ...")
    await init_db()
    from app.core.db import engine

    async with engine.begin() as conn:
        await ensure_new_columns(conn)
        print("2/3 迁移旧线性流程数据 ...")
        n = await migrate(conn)
        print(f"3/3 完成：迁移流程定义 {n} 条")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:  # noqa: BLE001
        print(f"迁移失败: {e}", file=sys.stderr)
        sys.exit(1)
