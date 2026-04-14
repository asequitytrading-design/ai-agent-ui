"""add ticker_type to stock_registry

Revision ID: b2c3d4e5f6a7
Revises: f1a2b3c4d5e6
Create Date: 2026-04-14 21:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tickers that are indices or commodities, not stocks.
_INDEX_TICKERS = (
    "^NSEI",
    "^INDIAVIX",
    "^GSPC",
    "^VIX",
)
_COMMODITY_TICKERS = (
    "^TNX",
    "^IRX",
    "CL=F",
    "DX-Y.NYB",
)


def upgrade() -> None:
    op.add_column(
        "stock_registry",
        sa.Column(
            "ticker_type",
            sa.String(20),
            nullable=False,
            server_default="stock",
        ),
    )
    op.create_index(
        "ix_stock_registry_ticker_type",
        "stock_registry",
        ["ticker_type"],
    )

    # Seed existing index tickers
    for tk in _INDEX_TICKERS:
        op.execute(
            sa.text(
                "UPDATE stock_registry "
                "SET ticker_type = 'index' "
                "WHERE ticker = :tk"
            ).bindparams(tk=tk)
        )
    # Seed existing commodity tickers
    for tk in _COMMODITY_TICKERS:
        op.execute(
            sa.text(
                "UPDATE stock_registry "
                "SET ticker_type = 'commodity' "
                "WHERE ticker = :tk"
            ).bindparams(tk=tk)
        )


def downgrade() -> None:
    op.drop_index(
        "ix_stock_registry_ticker_type",
        table_name="stock_registry",
    )
    op.drop_column("stock_registry", "ticker_type")
