"""
Thesis IoT Server — Scheduler CRUD Service
Business logic for creating, updating, and activating monitoring schedules.
"""

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
