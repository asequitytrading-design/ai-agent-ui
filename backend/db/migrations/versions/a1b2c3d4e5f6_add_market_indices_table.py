"""add market_indices table

Revision ID: a1b2c3d4e5f6
Revises: ede952a36b38
Create Date: 2026-04-13 15:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'ede952a36b38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS stocks")

    op.create_table(
        'market_indices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'nifty_data',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            'sensex_data',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            'market_state',
            sa.String(length=10),
            nullable=False,
        ),
        sa.Column(
            'fetched_at',
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            'id = 1',
            name='ck_market_indices_single',
        ),
        sa.PrimaryKeyConstraint('id'),
        schema='stocks',
    )


def downgrade() -> None:
    op.drop_table('market_indices', schema='stocks')
