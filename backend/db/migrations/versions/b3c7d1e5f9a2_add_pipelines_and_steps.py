"""add pipelines and pipeline_steps tables

Revision ID: b3c7d1e5f9a2
Revises: ead20959ea5b
Create Date: 2026-04-10 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b3c7d1e5f9a2"
down_revision: Union[str, None] = "ead20959ea5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipelines",
        sa.Column(
            "pipeline_id", sa.String(36),
            nullable=False,
        ),
        sa.Column(
            "name", sa.String(100), nullable=False,
        ),
        sa.Column(
            "scope", sa.String(50), nullable=False,
        ),
        sa.Column(
            "enabled", sa.Boolean(),
            server_default="true", nullable=False,
        ),
        sa.Column(
            "cron_days", sa.String(200),
            nullable=True,
        ),
        sa.Column(
            "cron_time", sa.String(10),
            nullable=True,
        ),
        sa.Column(
            "cron_dates", sa.String(200),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("pipeline_id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "pipeline_steps",
        sa.Column(
            "id", sa.Integer(),
            autoincrement=True, nullable=False,
        ),
        sa.Column(
            "pipeline_id", sa.String(36),
            nullable=False,
        ),
        sa.Column(
            "step_order", sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "job_type", sa.String(50),
            nullable=False,
        ),
        sa.Column(
            "job_name", sa.String(100),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_id"],
            ["pipelines.pipeline_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pipeline_id", "step_order",
            name="uq_pipeline_step_order",
        ),
    )


def downgrade() -> None:
    op.drop_table("pipeline_steps")
    op.drop_table("pipelines")
