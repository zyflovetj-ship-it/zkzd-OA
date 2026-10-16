"""initial baseline: full schema (roles/permissions/users/.../documents/audit)

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-26

基线迁移：覆盖 zk-oa 当前全部 22 张表（含内容引擎 documents 新列）。
此迁移为「从空库到当前 schema」的唯一来源；之后所有表结构变更都新增独立迁移，
不再使用 create_all，从而支持可回滚、可升级的部署。

说明：users <-> departments 存在循环外键，departments.manager_id 指向 users.id，
统一在 users 表创建后再以 ALTER 方式补建，保证建表顺序与回滚安全。
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("description", sa.String(200), default=""),
        sa.Column("data_scope", sa.String(20), default="all"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_roles_name", "roles", ["name"], unique=True)
    op.create_index("ix_roles_name_idx", "roles", ["name"])  # 模型同时声明 index=True

    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(100), default=""),
        sa.Column("category", sa.String(50), default="general"),
        sa.Column("type", sa.String(20), default="operation"),
        sa.Column("description", sa.String(200), default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_permissions_code", "permissions", ["code"], unique=True)
    op.create_index("ix_permissions_code_idx", "permissions", ["code"])

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("permission_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], ondelete="CASCADE",
            name="fk_role_permissions_role_id",
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"], ["permissions.id"], ondelete="CASCADE",
            name="fk_role_permissions_permission_id",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permissions"),
    )

    op.create_table(
        "menus",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("parent_id", sa.Integer(),
                  sa.ForeignKey("menus.id", name="fk_menus_parent_id"), nullable=True),
        sa.Column("name", sa.String(100), default=""),
        sa.Column("path", sa.String(200), default=""),
        sa.Column("icon", sa.String(50), default=""),
        sa.Column("order", sa.Integer(), default=0),
        sa.Column("permission_code", sa.String(100), default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # departments：manager_id 循环外键延后到 users 之后补建
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("parent_id", sa.Integer(),
                  sa.ForeignKey("departments.id", name="fk_departments_parent_id"), nullable=True),
        sa.Column("manager_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_departments_name", "departments", ["name"], unique=True)
    op.create_index("ix_departments_name_idx", "departments", ["name"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("email", sa.String(120), default=""),
        sa.Column("full_name", sa.String(100), default=""),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role_id", sa.Integer(),
                  sa.ForeignKey("roles.id", name="fk_users_role_id"), nullable=True),
        sa.Column("department_id", sa.Integer(),
                  sa.ForeignKey("departments.id", name="fk_users_department_id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_username_idx", "users", ["username"])

    # 循环外键：departments.manager_id -> users.id（ALTER 补建）
    if op.get_bind().dialect.name == "sqlite":
        # SQLite 不支持 ALTER TABLE ADD CONSTRAINT：改走 batch（复制重建表）路径，
        # 否则本地 SQLite（run.sh / DEPLOYMENT.md 的 PC 部署形态）`alembic upgrade head` 直接报
        # NotImplementedError: No support for ALTER of constraints in SQLite dialect.
        with op.batch_alter_table("departments") as batch_op:
            batch_op.create_foreign_key(
                "fk_departments_manager_id_users", "users",
                ["manager_id"], ["id"],
            )
    else:
        op.create_foreign_key(
            "fk_departments_manager_id_users", "departments", "users",
            ["manager_id"], ["id"],
        )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_refresh_tokens_user_id"), nullable=True),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)
    op.create_index("ix_refresh_tokens_token_hash_idx", "refresh_tokens", ["token_hash"])

    op.create_table(
        "leave_requests",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_leave_requests_user_id"), nullable=True),
        sa.Column("leave_type", sa.String(30), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), default=""),
        sa.Column("status", sa.String(20), default="pending"),
        sa.Column("approver_id", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_leave_requests_approver_id"), nullable=True),
        sa.Column("rejection_reason", sa.Text(), default=""),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_leave_requests_user_id", "leave_requests", ["user_id"])

    op.create_table(
        "attendances",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_attendances_user_id"), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("check_in", sa.DateTime(), nullable=True),
        sa.Column("check_out", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(200), default=""),
    )
    op.create_index("ix_attendances_user_id", "attendances", ["user_id"])
    op.create_index("ix_attendances_day", "attendances", ["day"])

    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), default=""),
        sa.Column("author_id", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_announcements_author_id"), nullable=True),
        sa.Column("pinned", sa.Boolean(), default=False),
        sa.Column("published", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )
    op.create_index("ix_announcements_title", "announcements", ["title"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("category", sa.String(50), default="general"),
        sa.Column("file_type", sa.String(30), default=""),
        sa.Column("file_size", sa.Integer(), default=0),
        sa.Column("description", sa.String(500), default=""),
        sa.Column("file_url", sa.String(500), default=""),
        sa.Column("owner_id", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_documents_owner_id"), nullable=True),
        sa.Column("owner_name", sa.String(50), default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )
    op.create_index("ix_documents_title", "documents", ["title"])
    op.create_index("ix_documents_category", "documents", ["category"])

    op.create_table(
        "model_entities",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("name", sa.String(120), default=""),
        sa.Column("category", sa.String(50), default="general"),
        sa.Column("icon", sa.String(40), default=""),
        sa.Column("description", sa.String(300), default=""),
        sa.Column("fields", sa.JSON(), default=list),
        sa.Column("display_field", sa.String(60), default=""),
        sa.Column("status", sa.String(20), default="draft"),
        sa.Column("created_by", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_model_entities_created_by"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )
    op.create_index("ix_model_entities_code", "model_entities", ["code"], unique=True)
    op.create_index("ix_model_entities_code_idx", "model_entities", ["code"])

    op.create_table(
        "model_records",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("entity_id", sa.Integer(),
                  sa.ForeignKey("model_entities.id", name="fk_model_records_entity_id"), nullable=True),
        sa.Column("serial_no", sa.String(40), nullable=False),
        sa.Column("data", sa.JSON(), default=dict),
        sa.Column("created_by", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_model_records_created_by"), nullable=True),
        sa.Column("updated_by", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_model_records_updated_by"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )
    op.create_index("ix_model_records_entity_id", "model_records", ["entity_id"])
    op.create_index("ix_model_records_serial_no", "model_records", ["serial_no"], unique=True)
    op.create_index("ix_model_records_serial_no_idx", "model_records", ["serial_no"])

    op.create_table(
        "form_definitions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("name", sa.String(120), default=""),
        sa.Column("fields", sa.JSON(), default=list),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )
    op.create_index("ix_form_definitions_code", "form_definitions", ["code"], unique=True)
    op.create_index("ix_form_definitions_code_idx", "form_definitions", ["code"])

    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("name", sa.String(120), default=""),
        sa.Column("category", sa.String(50), default="general"),
        sa.Column("description", sa.String(300), default=""),
        sa.Column("icon", sa.String(40), default=""),
        sa.Column("status", sa.String(20), default="draft"),
        sa.Column("current_version", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )
    op.create_index("ix_workflow_definitions_code", "workflow_definitions", ["code"], unique=True)
    op.create_index("ix_workflow_definitions_code_idx", "workflow_definitions", ["code"])

    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("definition_id", sa.Integer(),
                  sa.ForeignKey("workflow_definitions.id",
                                name="fk_workflow_versions_definition_id"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("graph", sa.JSON(), default=dict),
        sa.Column("form_id", sa.Integer(),
                  sa.ForeignKey("form_definitions.id",
                                name="fk_workflow_versions_form_id"), nullable=True),
        sa.Column("status", sa.String(20), default="draft"),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("remark", sa.String(300), default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_workflow_versions_definition_id", "workflow_versions", ["definition_id"])

    op.create_table(
        "workflow_instances",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("definition_id", sa.Integer(),
                  sa.ForeignKey("workflow_definitions.id",
                                name="fk_workflow_instances_definition_id"), nullable=True),
        sa.Column("version_id", sa.Integer(),
                  sa.ForeignKey("workflow_versions.id",
                                name="fk_workflow_instances_version_id"), nullable=True),
        sa.Column("title", sa.String(200), default=""),
        sa.Column("initiator_id", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_workflow_instances_initiator_id"), nullable=True),
        sa.Column("form_data", sa.JSON(), default=dict),
        sa.Column("current_nodes", sa.JSON(), default=list),
        sa.Column("status", sa.String(20), default="running"),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_workflow_instances_definition_id", "workflow_instances", ["definition_id"])
    op.create_index("ix_workflow_instances_version_id", "workflow_instances", ["version_id"])
    op.create_index("ix_workflow_instances_code", "workflow_instances", ["code"], unique=True)
    op.create_index("ix_workflow_instances_code_idx", "workflow_instances", ["code"])
    op.create_index("ix_workflow_instances_initiator_id", "workflow_instances", ["initiator_id"])

    op.create_table(
        "workflow_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("instance_id", sa.Integer(),
                  sa.ForeignKey("workflow_instances.id",
                                name="fk_workflow_tasks_instance_id"), nullable=True),
        sa.Column("node_id", sa.String(60), nullable=False),
        sa.Column("node_name", sa.String(120), default=""),
        sa.Column("node_type", sa.String(30), nullable=False),
        sa.Column("approver_id", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_workflow_tasks_approver_id"), nullable=True),
        sa.Column("origin_approver_id", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_workflow_tasks_origin_approver_id"), nullable=True),
        sa.Column("mode", sa.String(20), default="single"),
        sa.Column("status", sa.String(20), default="pending"),
        sa.Column("comment", sa.Text(), default=""),
        sa.Column("seq", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_workflow_tasks_instance_id", "workflow_tasks", ["instance_id"])
    op.create_index("ix_workflow_tasks_node_id", "workflow_tasks", ["node_id"])
    op.create_index("ix_workflow_tasks_approver_id", "workflow_tasks", ["approver_id"])

    op.create_table(
        "workflow_node_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("instance_id", sa.Integer(),
                  sa.ForeignKey("workflow_instances.id",
                                name="fk_workflow_node_logs_instance_id"), nullable=True),
        sa.Column("node_id", sa.String(60), default=""),
        sa.Column("node_name", sa.String(120), default=""),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("operator_id", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_workflow_node_logs_operator_id"), nullable=True),
        sa.Column("comment", sa.Text(), default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_workflow_node_logs_instance_id", "workflow_node_logs", ["instance_id"])
    op.create_index("ix_workflow_node_logs_operator_id", "workflow_node_logs", ["operator_id"])

    op.create_table(
        "workflow_delegations",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("from_user_id", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_workflow_delegations_from_user_id"), nullable=True),
        sa.Column("to_user_id", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_workflow_delegations_to_user_id"), nullable=True),
        sa.Column("definition_id", sa.Integer(),
                  sa.ForeignKey("workflow_definitions.id",
                                name="fk_workflow_delegations_definition_id"), nullable=True),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_workflow_delegations_from_user_id", "workflow_delegations", ["from_user_id"])
    op.create_index("ix_workflow_delegations_to_user_id", "workflow_delegations", ["to_user_id"])
    op.create_index("ix_workflow_delegations_definition_id", "workflow_delegations", ["definition_id"])

    op.create_table(
        "signatures",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("ref_type", sa.String(30), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=False),
        sa.Column("signer_id", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_signatures_signer_id"), nullable=True),
        sa.Column("signature_data", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), default=""),
        sa.Column("comment", sa.Text(), default=""),
        sa.Column("signed_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_signatures_ref_id", "signatures", ["ref_id"])
    op.create_index("ix_signatures_signer_id", "signatures", ["signer_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("actor_id", sa.Integer(),
                  sa.ForeignKey("users.id", name="fk_audit_logs_actor_id"), nullable=True),
        sa.Column("actor_name", sa.String(50), default=""),
        sa.Column("module", sa.String(50), default=""),
        sa.Column("action", sa.String(40), default=""),
        sa.Column("target_type", sa.String(50), default=""),
        sa.Column("target_id", sa.String(40), default=""),
        sa.Column("method", sa.String(10), default=""),
        sa.Column("path", sa.String(200), default=""),
        sa.Column("status", sa.String(20), default="success"),
        sa.Column("status_code", sa.Integer(), default=200),
        sa.Column("message", sa.String(300), default=""),
        sa.Column("detail", sa.JSON(), default=dict),
        sa.Column("ip", sa.String(45), default=""),
        sa.Column("request_id", sa.String(64), default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_module", "audit_logs", ["module"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_status", "audit_logs", ["status"])
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    # 反向顺序拆除；users <-> departments 循环外键先拆 manager_id 约束。
    op.drop_table("audit_logs")
    op.drop_table("signatures")
    op.drop_table("workflow_delegations")
    op.drop_table("workflow_node_logs")
    op.drop_table("workflow_tasks")
    op.drop_table("workflow_instances")
    op.drop_table("workflow_versions")
    op.drop_table("workflow_definitions")
    op.drop_table("form_definitions")
    op.drop_table("model_records")
    op.drop_table("model_entities")
    op.drop_table("documents")
    op.drop_table("announcements")
    op.drop_table("attendances")
    op.drop_table("leave_requests")
    op.drop_table("refresh_tokens")
    # 拆循环外键后删除 users 与 departments
    op.drop_constraint("fk_departments_manager_id_users", "departments", type_="foreignkey")
    op.drop_table("users")
    op.drop_table("departments")
    op.drop_table("menus")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
