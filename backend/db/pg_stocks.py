"""PostgreSQL-backed stock registry + scheduler operations."""
import logging
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models.pipeline import (
    Pipeline,
    PipelineStep,
)
from backend.db.models.registry import StockRegistry
from backend.db.models.scheduler import ScheduledJob

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
