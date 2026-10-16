"""add attendance, delegation-ready, expense, official doc & document version support

Revision ID: 0004_features
Revises: 0003_scheduler
Create Date: 2026-09-28

补齐四块业务能力所需的表结构：
1. 考勤：扩展既有 attendances（状态/迟到早退/工时/来源），新增班次设置与加班申请；
2. 报销：expense_claims，提交后挂 workflow_instances，审批结束由服务回写状态；
3. 公文：official_documents 收发文登记、传阅与归档；
4. 内容增强：document_versions 文档版本历史、announcement_reads 公告阅读回执，
   以及 announcements / documents 的新增列（附件、有效期、当前版本等）。

SQLite 兼容要点：ALTER TABLE ADD COLUMN 与 CREATE INDEX 均受支持，
但 ALTER 添加外键约束不被支持，故本版本不使用 op.create_foreign_key。
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0004_features"
down_revision = "0003_scheduler"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- 1. 考勤 ----------
    op.add_column(
        "attendances",
        sa.Column("status", sa.String(20), nullable=False, server_default="normal"),
    )
    op.add_column(
        "attendances",
        sa.Column("late_minutes", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "attendances",
        sa.Column("early_minutes", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "attendances",
        sa.Column("work_minutes", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "attendances",
        sa.Column("source", sa.String(10), nullable=False, server_default="clock"),
    )
    op.add_column(
        "attendances",
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.add_column(
        "attendances",
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_attendances_status", "attendances", ["status"])
    # 一天一人一行：服务层按 (user_id, day) upsert，唯一索引兜底防并发重复
    op.create_index(
        "uq_attendances_user_day", "attendances", ["user_id", "day"], unique=True
    )

    op.create_table(
        "attendance_settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(60), nullable=False, server_default="标准班次"),
        sa.Column("work_start", sa.String(8), nullable=False, server_default="09:00"),
        sa.Column("work_end", sa.String(8), nullable=False, server_default="18:00"),
        sa.Column("late_grace_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("workdays", sa.JSON(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "overtime_requests",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("hours", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("approver_id", sa.Integer(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_overtime_requests_user_id", "overtime_requests", ["user_id"])
    op.create_index("ix_overtime_requests_day", "overtime_requests", ["day"])
    op.create_index("ix_overtime_requests_status", "overtime_requests", ["status"])

    # ---------- 2. 报销 ----------
    op.create_table(
        "expense_claims",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("claim_type", sa.String(30), nullable=False, server_default="daily"),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("occur_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attachments", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("workflow_instance_id", sa.Integer(), nullable=True),
        sa.Column("approver_id", sa.Integer(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_expense_claims_code", "expense_claims", ["code"], unique=True)
    op.create_index("ix_expense_claims_user_id", "expense_claims", ["user_id"])
    op.create_index("ix_expense_claims_status", "expense_claims", ["status"])
    op.create_index(
        "ix_expense_claims_workflow_instance_id", "expense_claims", ["workflow_instance_id"]
    )

    # ---------- 3. 公文 ----------
    op.create_table(
        "official_documents",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("doc_no", sa.String(60), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False, server_default="in"),
        sa.Column("from_org", sa.String(120), nullable=True),
        sa.Column("to_org", sa.String(120), nullable=True),
        sa.Column("secrecy", sa.String(20), nullable=False, server_default="internal"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("attachments", sa.JSON(), nullable=True, server_default="[]"),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("owner_name", sa.String(50), nullable=True),
        sa.Column("read_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_official_documents_doc_no", "official_documents", ["doc_no"], unique=True)
    op.create_index("ix_official_documents_title", "official_documents", ["title"])
    op.create_index("ix_official_documents_status", "official_documents", ["status"])
    op.create_index("ix_official_documents_owner_id", "official_documents", ["owner_id"])

    # ---------- 4. 文档版本 + 公告增强 ----------
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("file_type", sa.String(30), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_key", sa.String(120), nullable=True),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("uploader_id", sa.Integer(), nullable=True),
        sa.Column("uploader_name", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])

    op.create_table(
        "announcement_reads",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("announcement_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("read_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_announcement_reads_announcement_id", "announcement_reads", ["announcement_id"])
    op.create_index("ix_announcement_reads_user_id", "announcement_reads", ["user_id"])
    # 同一用户对同一公告只记一次回执
    op.create_index(
        "uq_announcement_reads_ann_user",
        "announcement_reads",
        ["announcement_id", "user_id"],
        unique=True,
    )

    op.add_column(
        "announcements",
        # server_default 保证存量行拿到 [] 而非 NULL（否则响应模型校验失败）
        sa.Column("attachments", sa.JSON(), nullable=True, server_default="[]"),
    )
    op.add_column("announcements", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.add_column(
        "announcements",
        sa.Column("read_count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column(
        "documents",
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "documents",
        sa.Column("current_file_key", sa.String(120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "current_file_key")
    op.drop_column("documents", "current_version")
    op.drop_column("announcements", "read_count")
    op.drop_column("announcements", "expires_at")
    op.drop_column("announcements", "attachments")
    op.drop_table("announcement_reads")
    op.drop_table("document_versions")
    op.drop_table("official_documents")
    op.drop_table("expense_claims")
    op.drop_table("overtime_requests")
    op.drop_table("attendance_settings")
    op.drop_index("uq_attendances_user_day", table_name="attendances")
    op.drop_index("ix_attendances_status", table_name="attendances")
    op.drop_column("attendances", "updated_at")
    op.drop_column("attendances", "created_at")
    op.drop_column("attendances", "source")
    op.drop_column("attendances", "work_minutes")
    op.drop_column("attendances", "early_minutes")
    op.drop_column("attendances", "late_minutes")
    op.drop_column("attendances", "status")
