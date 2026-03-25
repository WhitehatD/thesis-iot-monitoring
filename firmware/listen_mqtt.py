import paho.mqtt.client as mqtt
import time

def on_message(client, userdata, msg):
    print(f"[MQTT] {msg.topic}: {msg.payload.decode()}")

client = mqtt.Client()
client.on_message = on_message
client.connect("broker.hivemq.com", 1883, 60)
client.subscribe("device/stm32/status")
client.subscribe("device/stm32/logs")

print("Listening for 30 seconds...")
client.loop_start()
time.sleep(30)
client.loop_stop()
print("Done.")
