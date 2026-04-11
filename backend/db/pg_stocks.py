"""PostgreSQL-backed stock registry + scheduler operations."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models.pipeline import (
    Pipeline,
    PipelineStep,
)
from backend.db.models.registry import StockRegistry
from backend.db.models.scheduler import ScheduledJob
from backend.db.models.scheduler_run import SchedulerRun

log = logging.getLogger(__name__)


async def get_registry(
    session: AsyncSession,
    ticker: str | None = None,
) -> dict | pd.DataFrame | None:
    """Get registry entry by ticker or all entries."""
    if ticker:
        result = await session.execute(
            select(StockRegistry).where(
                StockRegistry.ticker == ticker
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {
            c.name: getattr(row, c.name)
            for c in row.__table__.columns
        }

    result = await session.execute(select(StockRegistry))
    rows = [
        {
            c.name: getattr(r, c.name)
            for c in r.__table__.columns
        }
        for r in result.scalars().all()
    ]
    return pd.DataFrame(rows) if rows else pd.DataFrame()


async def upsert_registry(
    session: AsyncSession,
    data: dict[str, Any],
) -> None:
    """Insert or update registry entry by ticker."""
    ticker = data["ticker"]
    result = await session.execute(
        select(StockRegistry).where(
            StockRegistry.ticker == ticker
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        for key, value in data.items():
            if key != "ticker" and hasattr(existing, key):
                setattr(existing, key, value)
    else:
        session.add(StockRegistry(**{
            k: v for k, v in data.items()
            if hasattr(StockRegistry, k)
        }))

    await session.commit()
    log.info("Upserted registry: %s", ticker)


async def get_scheduled_jobs(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """Return all scheduled job definitions."""
    result = await session.execute(select(ScheduledJob))
    return [
        {
            c.name: getattr(j, c.name)
            for c in j.__table__.columns
        }
        for j in result.scalars().all()
    ]


async def upsert_scheduled_job(
    session: AsyncSession,
    job: dict[str, Any],
) -> None:
    """Insert or update scheduled job by job_id."""
    job_id = job["job_id"]
    result = await session.execute(
        select(ScheduledJob).where(
            ScheduledJob.job_id == job_id
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        for key, value in job.items():
            if key != "job_id" and hasattr(existing, key):
                setattr(existing, key, value)
    else:
        session.add(ScheduledJob(**{
            k: v for k, v in job.items()
            if hasattr(ScheduledJob, k)
        }))

    await session.commit()
    log.info("Upserted job: %s", job_id)


async def delete_scheduled_job(
    session: AsyncSession,
    job_id: str,
) -> None:
    """Delete scheduled job by job_id."""
    result = await session.execute(
        select(ScheduledJob).where(
            ScheduledJob.job_id == job_id
        )
    )
    job = result.scalar_one_or_none()
    if job:
        await session.delete(job)
        await session.commit()
        log.info("Deleted job: %s", job_id)


# -------------------------------------------------------
# Pipelines
# -------------------------------------------------------

async def get_pipelines(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """Return all pipelines with their steps."""
    from sqlalchemy.orm import selectinload

    result = await session.execute(
        select(Pipeline).options(
            selectinload(Pipeline.steps),
        )
    )
    pipelines = []
    for p in result.scalars().all():
        d = {
            c.name: getattr(p, c.name)
            for c in p.__table__.columns
        }
        d["steps"] = [
            {
                "step_order": s.step_order,
                "job_type": s.job_type,
                "job_name": s.job_name,
            }
            for s in sorted(
                p.steps, key=lambda s: s.step_order,
            )
        ]
        pipelines.append(d)
    return pipelines


async def upsert_pipeline(
    session: AsyncSession,
    data: dict[str, Any],
) -> None:
    """Insert or update a pipeline + steps."""
    from sqlalchemy.orm import selectinload

    pid = data["pipeline_id"]
    result = await session.execute(
        select(Pipeline)
        .options(selectinload(Pipeline.steps))
        .where(Pipeline.pipeline_id == pid)
    )
    existing = result.scalar_one_or_none()

    if existing:
        for key in (
            "name", "scope", "enabled",
            "cron_days", "cron_time", "cron_dates",
        ):
            if key in data:
                setattr(existing, key, data[key])
        if "steps" in data:
            for s in list(existing.steps):
                await session.delete(s)
            await session.flush()
            for s in data["steps"]:
                session.add(PipelineStep(
                    pipeline_id=pid,
                    step_order=s["step_order"],
                    job_type=s["job_type"],
                    job_name=s["job_name"],
                ))
    else:
        p = Pipeline(
            pipeline_id=pid,
            name=data["name"],
            scope=data.get("scope", "all"),
            enabled=data.get("enabled", True),
            cron_days=data.get("cron_days"),
            cron_time=data.get("cron_time"),
            cron_dates=data.get("cron_dates"),
        )
        session.add(p)
        await session.flush()
        for s in data.get("steps", []):
            session.add(PipelineStep(
                pipeline_id=pid,
                step_order=s["step_order"],
                job_type=s["job_type"],
                job_name=s["job_name"],
            ))

    await session.commit()
    log.info("Upserted pipeline: %s", pid)


async def delete_pipeline(
    session: AsyncSession,
    pipeline_id: str,
) -> None:
    """Delete pipeline (cascades to steps)."""
    result = await session.execute(
        select(Pipeline).where(
            Pipeline.pipeline_id == pipeline_id,
        )
    )
    p = result.scalar_one_or_none()
    if p:
        await session.delete(p)
        await session.commit()
        log.info("Deleted pipeline: %s", pipeline_id)


# ── Scheduler Runs ──────────────────────────────────


def _run_to_dict(r: SchedulerRun) -> dict:
    """Convert ORM row to dict with ISO timestamps."""
    d: dict[str, Any] = {}
    for c in r.__table__.columns:
        v = getattr(r, c.name)
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        d[c.name] = v
    return d


async def insert_scheduler_run(
    session: AsyncSession,
    run: dict[str, Any],
) -> None:
    """Insert a single scheduler run record."""
    obj = SchedulerRun(
        **{
            k: v
            for k, v in run.items()
            if hasattr(SchedulerRun, k)
        }
    )
    session.add(obj)
    await session.commit()


async def update_scheduler_run_pg(
    session: AsyncSession,
    run_id: str,
    updates: dict[str, Any],
) -> None:
    """Update fields on an existing run."""
    result = await session.execute(
        select(SchedulerRun).where(
            SchedulerRun.run_id == run_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        log.warning(
            "update_scheduler_run: %s not found",
            run_id,
        )
        return
    for k, v in updates.items():
        if hasattr(row, k):
            setattr(row, k, v)
    await session.commit()


async def get_scheduler_runs_pg(
    session: AsyncSession,
    days: int = 7,
    job_type: str | None = None,
    status: str | None = None,
    pipeline_run_id: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> tuple[list[dict], int]:
    """Return scheduler runs with filters.

    Returns (rows, total_count).
    """
    utc = timezone.utc
    cutoff = datetime.now(utc) - timedelta(days=days)

    filters = [SchedulerRun.started_at >= cutoff]
    if job_type:
        filters.append(
            SchedulerRun.job_type == job_type,
        )
    if status:
        filters.append(
            SchedulerRun.status == status,
        )
    if pipeline_run_id:
        filters.append(
            SchedulerRun.pipeline_run_id
            == pipeline_run_id,
        )

    # Total count.
    cnt_q = select(
        func.count(SchedulerRun.run_id),
    ).where(*filters)
    total = (await session.execute(cnt_q)).scalar() or 0

    # Paginated rows.
    q = (
        select(SchedulerRun)
        .where(*filters)
        .order_by(SchedulerRun.started_at.desc())
        .offset(offset)
    )
    if limit:
        q = q.limit(limit)
    result = await session.execute(q)
    rows = [_run_to_dict(r) for r in result.scalars()]
    return rows, total


async def get_scheduler_run_stats_pg(
    session: AsyncSession,
) -> dict:
    """Aggregate stats for the dashboard."""
    utc = timezone.utc
    cutoff = datetime.now(utc) - timedelta(days=1)
    base = select(SchedulerRun).where(
        SchedulerRun.started_at >= cutoff,
    )
    result = await session.execute(base)
    runs = result.scalars().all()
    total = len(runs)
    success = sum(
        1 for r in runs if r.status == "success"
    )
    failed = sum(
        1 for r in runs if r.status == "failed"
    )
    running = sum(
        1 for r in runs if r.status == "running"
    )
    return {
        "runs_today": total,
        "runs_today_success": success,
        "runs_today_failed": failed,
        "runs_today_running": running,
    }


async def get_pipeline_run_status_pg(
    session: AsyncSession,
    pipeline_run_id: str,
) -> list[dict]:
    """Return all runs for a pipeline_run_id."""
    result = await session.execute(
        select(SchedulerRun)
        .where(
            SchedulerRun.pipeline_run_id
            == pipeline_run_id,
        )
        .order_by(SchedulerRun.started_at.asc())
    )
    return [_run_to_dict(r) for r in result.scalars()]


async def get_last_pipeline_run_id_pg(
    session: AsyncSession,
    pipeline_id: str,
) -> str | None:
    """Get latest pipeline_run_id for a pipeline."""
    result = await session.execute(
        select(SchedulerRun.pipeline_run_id)
        .where(
            SchedulerRun.job_id == pipeline_id,
            SchedulerRun.pipeline_run_id.isnot(None),
        )
        .order_by(SchedulerRun.started_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return str(row) if row else None


async def get_last_run_for_job_pg(
    session: AsyncSession,
    job_id: str,
) -> dict | None:
    """Return the most recent run for a job."""
    result = await session.execute(
        select(SchedulerRun)
        .where(SchedulerRun.job_id == job_id)
        .order_by(SchedulerRun.started_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return _run_to_dict(row) if row else None
