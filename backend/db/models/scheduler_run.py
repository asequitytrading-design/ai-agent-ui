"""SchedulerRun ORM model — job execution records."""
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class SchedulerRun(Base):
    __tablename__ = "scheduler_runs"
    __table_args__ = (
        Index(
            "ix_scheduler_runs_started_at",
            "started_at",
            postgresql_using="btree",
        ),
        Index(
            "ix_scheduler_runs_job_id",
            "job_id",
        ),
        Index(
            "ix_scheduler_runs_pipeline_run_id",
            "pipeline_run_id",
        ),
        Index(
            "ix_scheduler_runs_status",
            "status",
        ),
        {"extend_existing": True},
    )

    run_id: Mapped[str] = mapped_column(
        String(36), primary_key=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(36), nullable=False,
    )
    job_name: Mapped[str] = mapped_column(
        String(200), nullable=False,
    )
    job_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
    )
    scope: Mapped[str] = mapped_column(
        String(20), nullable=False,
        server_default="all",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False,
        server_default="running",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    duration_secs: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )
    tickers_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    tickers_done: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    error_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    trigger_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
    )
    pipeline_run_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
    )
