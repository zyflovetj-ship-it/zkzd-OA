"""add GPS fields to attendance for field work support

Revision ID: 0007_attendance_gps
Revises: 0006_official_doc_seq
Create Date: 2026-09-29 15:00:00
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0007_attendance_gps'
down_revision = '0006_official_doc_seq'
branch_labels = None
depends_on = None

# 需要补齐的考勤列（列名 -> 列定义）
_COLUMNS = [
    ('check_in_lat', sa.Float()),
    ('check_in_lng', sa.Float()),
    ('check_out_lat', sa.Float()),
    ('check_out_lng', sa.Float()),
    ('check_in_address', sa.String(500)),
    ('check_out_address', sa.String(500)),
    ('is_field_work', sa.Boolean(), '0'),
    ('field_work_address', sa.String(500)),
    ('field_work_note', sa.Text()),
]

_INDEXES = [
    ('ix_attendances_check_in_location', ['check_in_lat', 'check_in_lng']),
    ('ix_attendances_check_out_location', ['check_out_lat', 'check_out_lng']),
    ('ix_attendances_is_field_work', ['is_field_work']),
]


def upgrade() -> None:
    # 幂等：本地库可能处于半应用状态（列已存在但版本未 stamp），存在即跳过
    insp = sa.inspect(op.get_bind())
    existing = {c['name'] for c in insp.get_columns('attendances')}
    existing_idx = {i['name'] for i in insp.get_indexes('attendances')}

    for spec in _COLUMNS:
        name, coltype = spec[0], spec[1]
        if name in existing:
            continue
        if len(spec) > 2:
            op.add_column(
                'attendances', sa.Column(name, coltype, nullable=False, server_default=spec[2])
            )
        else:
            op.add_column('attendances', sa.Column(name, coltype, nullable=True))

    for idx_name, cols in _INDEXES:
        if idx_name not in existing_idx:
            op.create_index(idx_name, 'attendances', cols)


def downgrade() -> None:
    for idx_name, _cols in reversed(_INDEXES):
        op.drop_index(idx_name, table_name='attendances')
    for spec in reversed(_COLUMNS):
        op.drop_column('attendances', spec[0])
