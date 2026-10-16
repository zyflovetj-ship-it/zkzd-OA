"""增强审计日志：新增 before_value, after_value, correlation_id, duration_ms

Revision ID: 0005_enhance_audit_log
Revises: 0004_features
Create Date: 2026-09-29 10:30:00
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0005_enhance_audit_log'
down_revision = '0004_features'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'audit_logs',
        sa.Column('before_value', sa.JSON(), nullable=True)
    )
    op.add_column(
        'audit_logs',
        sa.Column('after_value', sa.JSON(), nullable=True)
    )
    op.add_column(
        'audit_logs',
        sa.Column('correlation_id', sa.String(64), nullable=True)
    )
    op.create_index(
        'ix_audit_logs_correlation_id',
        'audit_logs',
        ['correlation_id']
    )
    op.add_column(
        'audit_logs',
        sa.Column('duration_ms', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_index('ix_audit_logs_correlation_id', table_name='audit_logs')
    op.drop_column('audit_logs', 'duration_ms')
    op.drop_column('audit_logs', 'correlation_id')
    op.drop_column('audit_logs', 'after_value')
    op.drop_column('audit_logs', 'before_value')