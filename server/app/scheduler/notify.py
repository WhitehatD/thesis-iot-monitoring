"""
Schedule change notification via MQTT.

Called after any schedule state change (activate, deactivate, delete, task completion)
to push the full schedule list to the dashboard in real time.
"""

import json

from app.config import settings
from app.db.database import async_session
from app.mqtt.client import mqtt_client
from app.scheduler import service


async def notify_schedule_update():
    """Load all schedules and publish to dashboard via MQTT.

    Non-fatal: failures are logged but never propagate to the caller,
    since dashboard notification is supplementary to the main operation.
    """
    try:
        async with async_session() as db:
            schedules = await service.list_schedules(db)
            # Build payload inside session context to avoid detached ORM access
            payload = {
                "schedules": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "description": s.description,
                        "is_active": s.is_active,
                        "created_at": s.created_at.isoformat() if s.created_at else None,
                        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                        "tasks": [
                            {
                                "id": t.id,
                                "time": t.time,
                                "action": t.action,
                                "objective": t.objective,
                                "order": t.order,
                                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                            }
                            for t in s.tasks
                        ],
                    }
                    for s in schedules
                ]
            }
    except Exception as e:
        print(f"[WARN] notify_schedule_update: DB read failed: {e}")
        return

    try:
        topic = settings.mqtt_topic_dashboard_schedules
        message = json.dumps(payload)
        mqtt_client.publish(topic, message)
        print(f"[OK] notify_schedule_update: published {len(payload['schedules'])} schedules to {topic} ({len(message)} bytes)")
    except Exception as e:
        print(f"[WARN] notify_schedule_update: MQTT publish failed: {e}")
