"""Async-safe upsert helper for CaptureLatency rows keyed by task_id.

Instrumentation must never crash the pipeline — all exceptions are swallowed
and printed to stdout for post-mortem inspection.
"""

import uuid

from sqlalchemy import select

from app.db.database import async_session
from app.analysis.models import CaptureLatency


async def record(task_id: int, **fields):
    """Upsert a CaptureLatency row by task_id.

    Creates the row if it does not exist; merges new non-None fields into an
    existing row.  Pass any column name as a keyword argument.
    """
    try:
        async with async_session() as db:
            row = (
                await db.execute(
                    select(CaptureLatency).where(CaptureLatency.task_id == task_id)
                )
            ).scalar_one_or_none()
            if row is None:
                row = CaptureLatency(task_id=task_id, **fields)
                db.add(row)
            else:
                for k, v in fields.items():
                    if v is not None:
                        setattr(row, k, v)
            await db.commit()
    except Exception as e:
        print(f"[BENCH] timing.record failed task_id={task_id}: {e}")


def new_run_id() -> str:
    """Return a short 16-hex-char run identifier."""
    return uuid.uuid4().hex[:16]
