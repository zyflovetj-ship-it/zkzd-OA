#!/usr/bin/env bash
# 本地开发启动：迁移数据库 + 初始化数据 + 启动服务
set -e
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "已生成 .env（默认 SQLite，生产请改为 PostgreSQL）"
fi
# 表结构由 Alembic 管理：启动前执行迁移（已是最新则自动跳过）。
# 若本地已有旧版 create_all 生成的库（无 alembic_version 表），请先执行
# `alembic stamp head` 标记为基线，或删除旧库（如 oa.db）后重启，避免重复建表报错。
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
