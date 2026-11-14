"""Add backup_snapshots table

Revision ID: 004
Revises: 003
Create Date: 2026-11-14 09:00:00.000000

เก็บไฟล์สำรองของหน้าเว็บทั้งก้อน (POST /api/v1/sync/snapshots) — ตารางใหม่ ไม่แตะตารางเดิม
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'backup_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('store_id', sa.Integer(), sa.ForeignKey('stores.id', ondelete='CASCADE'), nullable=False),
        sa.Column('label', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('counts', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('store_id', 'label', 'sha256', name='uq_backup_snapshots_store_label_sha'),
    )
    op.create_index('ix_backup_snapshots_store_id', 'backup_snapshots', ['store_id'])
    op.create_index('ix_backup_snapshots_created_at', 'backup_snapshots', ['created_at'])
    op.create_index(
        'ix_backup_snapshots_store_label_created', 'backup_snapshots', ['store_id', 'label', 'created_at']
    )


def downgrade() -> None:
    op.drop_index('ix_backup_snapshots_store_label_created', table_name='backup_snapshots')
    op.drop_index('ix_backup_snapshots_created_at', table_name='backup_snapshots')
    op.drop_index('ix_backup_snapshots_store_id', table_name='backup_snapshots')
    op.drop_table('backup_snapshots')
