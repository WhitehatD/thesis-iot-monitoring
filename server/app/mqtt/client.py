"""
Thesis IoT Server — MQTT Client
Async MQTT integration using fastapi-mqtt.
"""

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
    # Subscribe to status updates from the STM32 board
    mqtt_client.client.subscribe(settings.mqtt_topic_status)
    print(f"✓ Subscribed to: {settings.mqtt_topic_status}")


@mqtt_client.on_message()
async def on_message(client, topic, payload, qos, properties):
    """Handle incoming MQTT messages from the STM32 board."""
    message = payload.decode()
    print(f"  MQTT [{topic}]: {message}")

    # TODO: Parse status messages and update task state in DB


@mqtt_client.on_disconnect()
def on_disconnect(client, packet, exc=None):
    """Called when MQTT connection is lost."""
    print("✗ MQTT disconnected — will auto-reconnect")
