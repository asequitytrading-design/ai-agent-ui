"""add conversation_contexts table

Revision ID: f1a2b3c4d5e6
Revises: ede952a36b38
Create Date: 2026-04-13 17:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'conversation_contexts',
        sa.Column(
            'session_id', sa.String(36),
            nullable=False,
        ),
        sa.Column(
            'user_id', sa.String(36),
            nullable=False,
        ),
        sa.Column(
            'current_topic', sa.Text(),
            server_default='',
        ),
        sa.Column(
            'last_agent', sa.String(64),
            server_default='',
        ),
        sa.Column(
            'last_intent', sa.String(64),
            server_default='',
        ),
        sa.Column(
            'summary', sa.Text(),
            server_default='',
        ),
        sa.Column(
            'last_response', sa.Text(),
            server_default='',
        ),
        sa.Column(
            'tickers_mentioned',
            postgresql.ARRAY(sa.String(20)),
            server_default='{}',
        ),
        sa.Column(
            'user_tickers',
            postgresql.ARRAY(sa.String(20)),
            server_default='{}',
        ),
        sa.Column(
            'market_preference', sa.String(20),
            server_default='',
        ),
        sa.Column(
            'subscription_tier', sa.String(20),
            server_default='',
        ),
        sa.Column(
            'turn_count', sa.Integer(),
            server_default='0',
        ),
        sa.Column(
            'last_updated', sa.Float(),
            server_default='0',
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
        ),
        sa.PrimaryKeyConstraint('session_id'),
    )
    op.create_index(
        'ix_conversation_contexts_user_id',
        'conversation_contexts',
        ['user_id'],
    )
    op.create_index(
        'ix_conversation_contexts_updated_at',
        'conversation_contexts',
        ['updated_at'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_conversation_contexts_updated_at',
    )
    op.drop_index(
        'ix_conversation_contexts_user_id',
    )
    op.drop_table('conversation_contexts')
