"""外勤申请单：field_work_orders 表 + attendances.field_work_order_id 关联列

Revision ID: 0010_field_work_orders
Revises: 0009_expense_budget_quota
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa


revision = '0010_field_work_orders'
down_revision = '0009_expense_budget_quota'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 幂等：本地库可能处于半应用状态（对象已存在但版本未 stamp），存在即跳过
    insp = sa.inspect(op.get_bind())

    if not insp.has_table('field_work_orders'):
        op.create_table(
            'field_work_orders',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('start_date', sa.Date(), nullable=False),
            sa.Column('end_date', sa.Date(), nullable=False),
            sa.Column('address', sa.String(500), nullable=False, server_default=''),
            sa.Column('purpose', sa.String(300), nullable=False, server_default=''),
            sa.Column('remark', sa.Text(), nullable=False, server_default=''),
            sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
            sa.Column('approver_id', sa.Integer(), nullable=True),
            sa.Column('review_comment', sa.Text(), nullable=False, server_default=''),
            sa.Column('reviewed_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        )

    idx = {i['name'] for i in insp.get_indexes('field_work_orders')} \
        if insp.has_table('field_work_orders') else set()
    for name, cols in (
        ('ix_field_work_orders_user_id', ['user_id']),
        ('ix_field_work_orders_start_date', ['start_date']),
        ('ix_field_work_orders_end_date', ['end_date']),
        ('ix_field_work_orders_status', ['status']),
    ):
        if name not in idx:
            op.create_index(name, 'field_work_orders', cols)

    # 考勤表关联列（SQLite 不支持 ALTER ADD CONSTRAINT，外键仅在非 SQLite 方言补建）
    if insp.has_table('attendances'):
        att_cols = {c['name'] for c in insp.get_columns('attendances')}
        if 'field_work_order_id' not in att_cols:
            op.add_column(
                'attendances',
                sa.Column('field_work_order_id', sa.Integer(), nullable=True),
            )
            if insp.dialect.name != 'sqlite':
                op.create_foreign_key(
                    'fk_attendances_field_work_order_id', 'attendances',
                    'field_work_orders', ['field_work_order_id'], ['id'],
                )
        att_idx = {i['name'] for i in insp.get_indexes('attendances')}
        if 'ix_attendances_field_work_order_id' not in att_idx:
            op.create_index(
                'ix_attendances_field_work_order_id', 'attendances', ['field_work_order_id']
            )
        # 列表查询恒按 (user_id, day) 过滤：复合索引对打卡/月度视图都有增益
        if 'ix_attendances_user_day' not in att_idx:
            op.create_index('ix_attendances_user_day', 'attendances', ['user_id', 'day'])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table('attendances'):
        att_idx = {i['name'] for i in insp.get_indexes('attendances')}
        for name in ('ix_attendances_field_work_order_id', 'ix_attendances_user_day'):
            if name in att_idx:
                op.drop_index(name, table_name='attendances')
        att_cols = {c['name'] for c in insp.get_columns('attendances')}
        if 'field_work_order_id' in att_cols:
            op.drop_column('attendances', 'field_work_order_id')
    if insp.has_table('field_work_orders'):
        op.drop_table('field_work_orders')
