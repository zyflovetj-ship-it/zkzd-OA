"""公文流转事件表：official_doc_events

Revision ID: 0011_official_doc_events
Revises: 0010_field_work_orders
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa

revision = '0011_official_doc_events'
down_revision = '0010_field_work_orders'
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table('official_doc_events'):
        op.create_table(
            'official_doc_events',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('doc_id', sa.Integer(), nullable=False),
            sa.Column('action', sa.String(50), nullable=False),
            sa.Column('from_status', sa.String(20), nullable=True),
            sa.Column('to_status', sa.String(20), nullable=True),
            sa.Column('actor_id', sa.Integer(), nullable=False),
            sa.Column('actor_name', sa.String(50), nullable=False, server_default=''),
            sa.Column('remark', sa.Text(), nullable=False, server_default=''),
            sa.Column('meta', sa.JSON(), nullable=False, server_default='{}'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        )
    idx = {i['name'] for i in insp.get_indexes('official_doc_events')} \
        if insp.has_table('official_doc_events') else set()
    for name, cols in (
        ('ix_official_doc_events_doc_id', ['doc_id']),
        ('ix_official_doc_events_action', ['action']),
        ('ix_official_doc_events_actor_id', ['actor_id']),
    ):
        if name not in idx:
            op.create_index(name, 'official_doc_events', cols)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table('official_doc_events'):
        idx = {i['name'] for i in insp.get_indexes('official_doc_events')}
        for name in ('ix_official_doc_events_doc_id', 'ix_official_doc_events_action', 'ix_official_doc_events_actor_id'):
            if name in idx:
                op.drop_index(name, table_name='official_doc_events')
        op.drop_table('official_doc_events')
