"""Add scheduler_runs table

Migrates scheduler run tracking from Iceberg (full table
overwrite per update, ~9s) to PostgreSQL (single-row
UPDATE, <5ms).

Revision ID: c4d9e2f1a8b3
Revises: b3c7d1e5f9a2
Create Date: 2026-04-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d9e2f1a8b3"
down_revision: Union[str, None] = "b3c7d1e5f9a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduler_runs",
        sa.Column(
            "run_id",
            sa.String(36),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.String(36),
            nullable=False,
        ),
        sa.Column(
            "job_name",
            sa.String(200),
            nullable=False,
        ),
        sa.Column(
            "job_type",
            sa.String(50),
            nullable=False,
        ),
        sa.Column(
            "scope",
            sa.String(20),
            nullable=False,
            server_default="all",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "duration_secs",
            sa.Float,
            nullable=True,
        ),
        sa.Column(
            "tickers_total",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "tickers_done",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "error_message",
            sa.String(500),
            nullable=True,
        ),
        sa.Column(
            "trigger_type",
            sa.String(50),
            nullable=True,
        ),
        sa.Column(
            "pipeline_run_id",
            sa.String(36),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "ix_scheduler_runs_started_at",
        "scheduler_runs",
        [sa.text("started_at DESC")],
    )
    op.create_index(
        "ix_scheduler_runs_job_id",
        "scheduler_runs",
        ["job_id"],
    )
    op.create_index(
        "ix_scheduler_runs_pipeline_run_id",
        "scheduler_runs",
        ["pipeline_run_id"],
    )
    op.create_index(
        "ix_scheduler_runs_status",
        "scheduler_runs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("scheduler_runs")
