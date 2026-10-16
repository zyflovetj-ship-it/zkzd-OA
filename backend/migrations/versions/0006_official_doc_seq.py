"""add seq column to official_documents for auto-generated doc_no

Revision ID: 0006_official_doc_seq
Revises: 0005_enhance_audit_log
Create Date: 2026-09-29 11:00:00
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0006_official_doc_seq'
down_revision = '0005_enhance_audit_log'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'official_documents',
        sa.Column('seq', sa.Integer(), nullable=False, server_default='0')
    )
    # Create index for efficient seq lookup
    op.create_index(
        'ix_official_documents_seq',
        'official_documents',
        ['seq']
    )


def downgrade() -> None:
    op.drop_index('ix_official_documents_seq', table_name='official_documents')
    op.drop_column('official_documents', 'seq')