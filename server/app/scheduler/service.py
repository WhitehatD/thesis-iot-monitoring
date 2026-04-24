"""
Thesis IoT Server — Scheduler CRUD Service
Business logic for creating, updating, and activating monitoring schedules.
"""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.scheduler.models import Schedule, ScheduleTask


async def create_schedule(db: AsyncSession, name: str, description: str, tasks: list[dict]) -> Schedule:
    """Create a new schedule with its tasks."""
    schedule = Schedule(name=name, description=description)
    for i, t in enumerate(tasks):
        schedule.tasks.append(
            ScheduleTask(
                time=t["time"],
                action=t.get("action", "CAPTURE_IMAGE"),
                objective=t.get("objective", ""),
                order=i,
            )
        )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule, attribute_names=["tasks"])
    return schedule


async def list_schedules(db: AsyncSession) -> list[Schedule]:
    """Return all schedules with their tasks loaded."""
    result = await db.execute(
        select(Schedule).options(selectinload(Schedule.tasks)).order_by(Schedule.created_at.desc())
    )
    return list(result.scalars().all())


async def get_schedule(db: AsyncSession, schedule_id: int) -> Schedule:
    """Return a single schedule by ID, or 404."""
    result = await db.execute(
        select(Schedule).options(selectinload(Schedule.tasks)).where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


async def update_schedule(
    db: AsyncSession, schedule_id: int, name: str, description: str, tasks: list[dict]
) -> Schedule:
    """Replace a schedule's metadata and tasks atomically."""
    schedule = await get_schedule(db, schedule_id)

    schedule.name = name
    schedule.description = description

    # Delete old tasks via explicit query (avoids MissingGreenlet from .clear())
    from sqlalchemy import delete
    await db.execute(
        delete(ScheduleTask).where(ScheduleTask.schedule_id == schedule_id)
    )

    # Add new tasks
    for i, t in enumerate(tasks):
        db.add(ScheduleTask(
            schedule_id=schedule_id,
            time=t["time"],
            action=t.get("action", "CAPTURE_IMAGE"),
            objective=t.get("objective", ""),
            order=i,
        ))

    await db.commit()
    # Expire cached schedule so re-fetch picks up new tasks
    db.expire(schedule)
    return await get_schedule(db, schedule_id)


async def delete_schedule(db: AsyncSession, schedule_id: int) -> None:
    """Delete a schedule and all its tasks (cascade)."""
    schedule = await get_schedule(db, schedule_id)
    await db.delete(schedule)
    await db.commit()


async def deactivate_schedule(db: AsyncSession, schedule_id: int) -> Schedule:
    """Deactivate a specific schedule."""
    schedule = await get_schedule(db, schedule_id)
    schedule.is_active = False
    await db.commit()
    await db.refresh(schedule, attribute_names=["tasks"])
    return schedule


def _schedule_span_hours(tasks: list) -> float:
    """Return hours between first and last task time (handles midnight wrap)."""
    if not tasks or len(tasks) < 2:
        return 0.0
    try:
        fmt = lambda t: datetime.strptime(t.time[:5], "%H:%M")
        first = fmt(tasks[0])
        last = fmt(tasks[-1])
        diff = (last - first).total_seconds() / 3600
        return diff if diff >= 0 else 24 + diff
    except Exception:
        return 0.0


async def cleanup_stale_schedules(db: AsyncSession) -> int:
    """
    Delete stale inactive schedules.

    Rules (never deletes active schedules):
    - "Quick:" sequences — delete after 4 h inactive (they accumulate fast)
    - Any schedule where all tasks are completed — delete after 7 days
    - Long schedules (span > 2 h) that are still incomplete — never auto-delete
    - Short incomplete schedules — delete after 48 h inactive

    Returns count of deleted schedules.
    """
    schedules = await list_schedules(db)
    deleted = 0
    now = datetime.now()

    for schedule in schedules:
        if schedule.is_active:
            continue

        age_hours = (now - schedule.created_at).total_seconds() / 3600

        if schedule.name.startswith("Quick:"):
            if age_hours > 4:
                await db.delete(schedule)
                deleted += 1
            continue

        all_done = schedule.tasks and all(t.completed_at is not None for t in schedule.tasks)

        if all_done:
            # Fully completed schedules: clean up after 7 days
            if age_hours > 168:
                await db.delete(schedule)
                deleted += 1
        else:
            span = _schedule_span_hours(schedule.tasks)
            if span > 2:
                # Long / multi-hour monitoring: keep — user may want to re-activate
                pass
            else:
                # Short incomplete schedule: clean up after 48 h
                if age_hours > 48:
                    await db.delete(schedule)
                    deleted += 1

    if deleted:
        await db.commit()
    return deleted


async def activate_schedule(db: AsyncSession, schedule_id: int) -> dict:
    """
    Mark a schedule as active (deactivating all others).
    Returns the MQTT payload dict ready to be published.
    """
    # Deactivate all
    all_schedules = await list_schedules(db)
    for s in all_schedules:
        s.is_active = False

    # Activate the target
    schedule = await get_schedule(db, schedule_id)
    schedule.is_active = True
    await db.commit()
    await db.refresh(schedule, attribute_names=["tasks"])

    # Build MQTT payload matching firmware expectations
    mqtt_tasks = []
    for task in schedule.tasks:
        mqtt_tasks.append({
            "time": task.time,
            "action": task.action,
            "id": task.id,
            "objective": task.objective,
        })

    return {
        "type": "schedule",
        "schedule_id": schedule.id,
        "schedule_name": schedule.name,
        "tasks": mqtt_tasks,
    }
