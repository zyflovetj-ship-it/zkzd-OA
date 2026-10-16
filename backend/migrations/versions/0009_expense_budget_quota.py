"""add budget/quota fields to expense_claims

Revision ID: 0009_expense_budget_quota
Revises: 0008_attendance_gps
Create Date: 2026-09-29 16:00:00
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0009_expense_budget_quota'
down_revision = '0007_attendance_gps'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 幂等：本地库可能处于半应用状态（对象已存在但版本未 stamp），存在即跳过
    insp = sa.inspect(op.get_bind())
    if not insp.has_table('budgets'):
        op.create_table(
            'budgets',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('code', sa.String(40), unique=True, nullable=False, index=True),
            sa.Column('total_amount', sa.Float(), nullable=False, default=0.0),
            sa.Column('used_amount', sa.Float(), nullable=False, default=0.0),
            sa.Column('start_date', sa.Date(), nullable=False),
            sa.Column('end_date', sa.Date(), nullable=False),
            sa.Column('department_id', sa.Integer(), nullable=True),
            sa.Column('category', sa.String(30), nullable=True),  # travel/daily/entertain/other/all
            sa.Column('status', sa.String(20), nullable=False, default='active'),  # active/inactive/expired
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        )

    budget_idx = {i['name'] for i in insp.get_indexes('budgets')} if insp.has_table('budgets') else set()
    for idx, cols in (
        ('ix_budgets_department_id', ['department_id']),
        ('ix_budgets_status', ['status']),
        ('ix_budgets_date_range', ['start_date', 'end_date']),
    ):
        if idx not in budget_idx:
            op.create_index(idx, 'budgets', cols)

    # Add budget/quota fields to expense_claims
    # SQLite 不支持 ALTER TABLE ADD CONSTRAINT：先加普通列，外键仅在非 SQLite 方言上补建
    claim_cols = {c['name'] for c in insp.get_columns('expense_claims')}
    if 'budget_id' not in claim_cols:
        op.add_column(
            'expense_claims',
            sa.Column('budget_id', sa.Integer(), nullable=True)
        )
        if insp.dialect.name != 'sqlite':
            op.create_foreign_key(
                'fk_expense_claims_budget_id', 'expense_claims', 'budgets',
                ['budget_id'], ['id'],
            )
    if 'quota_amount' not in claim_cols:
        op.add_column(
            'expense_claims',
            sa.Column('quota_amount', sa.Float(), nullable=True)
        )
    if 'remaining_quota' not in claim_cols:
        op.add_column(
            'expense_claims',
            sa.Column('remaining_quota', sa.Float(), nullable=True)
        )
    claim_idx = {i['name'] for i in insp.get_indexes('expense_claims')}
    if 'ix_expense_claims_budget_id' not in claim_idx:
        op.create_index('ix_expense_claims_budget_id', 'expense_claims', ['budget_id'])


def downgrade() -> None:
    op.drop_index('ix_expense_claims_budget_id', table_name='expense_claims')
    op.drop_column('expense_claims', 'remaining_quota')
    op.drop_column('expense_claims', 'quota_amount')
    op.drop_column('expense_claims', 'budget_id')
    op.drop_table('budgets')