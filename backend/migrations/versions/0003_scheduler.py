"""add scheduler support: instance escalation flag + dead-letter table

Revision ID: 0003_scheduler
Revises: 0002_notifications
Create Date: 2026-09-26

后台调度（审批超时自动升级提醒）依赖两层保障：
1. workflow_instances.escalated_at —— 标记已升级的实例，查询以 IS NULL 过滤保证幂等（仅通知一次）；
2. scheduler_dead_letters —— 调度任务处理失败落盘（task_name / ref_id / payload / error），
   同 ref_id 已死信则跳过重通知，下一轮调度自然重试。
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0003_scheduler"
down_revision = "0002_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_instances",
        sa.Column("escalated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_workflow_instances_escalated_at",
        "workflow_instances",
        ["escalated_at"],
    )
    op.create_table(
        "scheduler_dead_letters",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("task_name", sa.String(64), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_scheduler_dead_letters_task_name",
        "scheduler_dead_letters",
        ["task_name"],
    )
    op.create_index(
        "ix_scheduler_dead_letters_ref_id",
        "scheduler_dead_letters",
        ["ref_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scheduler_dead_letters_ref_id", table_name="scheduler_dead_letters"
    )
    op.drop_index(
        "ix_scheduler_dead_letters_task_name", table_name="scheduler_dead_letters"
    )
    op.drop_table("scheduler_dead_letters")
    op.drop_index(
        "ix_workflow_instances_escalated_at", table_name="workflow_instances"
    )
    op.drop_column("workflow_instances", "escalated_at")
