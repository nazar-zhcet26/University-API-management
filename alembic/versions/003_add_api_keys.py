"""add api_keys table

Revision ID: 003
Revises: 002
Create Date: 2026-03-15
"""
from alembic import op
import sqlalchemy as sa

revision = '003_add_api_keys'
down_revision = '002_add_book_embeddings'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'api_keys',
        sa.Column('id',          sa.String(36),  primary_key=True),
        sa.Column('name',        sa.String(255), nullable=False),
        sa.Column('key_hash',    sa.String(64),  nullable=False),
        sa.Column('key_prefix',  sa.String(12),  nullable=False),
        sa.Column('user_id',     sa.String(36),  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role',        sa.String(50),  nullable=False, server_default='service'),
        sa.Column('is_active',   sa.Boolean(),   nullable=False, server_default='true'),
        sa.Column('expires_at',  sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at',  sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at',  sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_api_keys_key_hash', 'api_keys', ['key_hash'], unique=True)
    op.create_index('ix_api_keys_user_id',  'api_keys', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_api_keys_user_id',  table_name='api_keys')
    op.drop_index('ix_api_keys_key_hash', table_name='api_keys')
    op.drop_table('api_keys')