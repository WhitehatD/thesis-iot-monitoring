"""
Thesis IoT Server — MQTT Client
Async MQTT integration using fastapi-mqtt.
"""

import json

from fastapi_mqtt import FastMQTT, MQTTConfig

from app.config import settings


mqtt_config = MQTTConfig(
    host=settings.mqtt_broker_host,
    port=settings.mqtt_broker_port,
    keepalive=60,
    username=None,
    password=None,
)

mqtt_client = FastMQTT(config=mqtt_config)


@mqtt_client.on_connect()
def on_connect(client, flags, rc, properties):
    """Called when MQTT connection is established."""
    mqtt_client.client.subscribe(settings.mqtt_topic_status)
    print(f"[OK] Subscribed to: {settings.mqtt_topic_status}")


@mqtt_client.on_message()
async def on_message(client, topic, payload, qos, properties):
    """Handle incoming MQTT messages from the STM32 board."""
    message = payload.decode()

    try:
        data = json.loads(message)
    except (json.JSONDecodeError, ValueError):
        return

    status = data.get("status")

    # Auto-deactivate schedule when board finishes all tasks
    if status == "cycle_complete":
        try:
            from app.db.database import async_session
            from app.scheduler.service import list_schedules
            from sqlalchemy import update
            from app.scheduler.models import Schedule

            async with async_session() as db:
                active = [s for s in await list_schedules(db) if s.is_active]
                if active:
                    await db.execute(
                        update(Schedule).where(Schedule.is_active == True).values(is_active=False)
                    )
                    await db.commit()
                    print(f"[OK] Auto-deactivated schedule: {active[0].name}")
                    from app.scheduler.notify import notify_schedule_update
                    await notify_schedule_update()
        except Exception as e:
            print(f"[WARN] Failed to deactivate schedule: {e}")


@mqtt_client.on_disconnect()
def on_disconnect(client, packet, exc=None):
    """Called when MQTT connection is lost."""
    print("[WARN] MQTT disconnected -- will auto-reconnect")
