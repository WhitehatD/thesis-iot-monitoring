import time
import json
import paho.mqtt.client as mqtt

broker_address = "localhost"
port = 1883
topic = "device/stm32/status"

client = mqtt.Client()
client.connect(broker_address, port)

print("Waiting 6 seconds for browser subagent to load page...")
time.sleep(6)

print("Publishing schedule_received...")
client.publish(topic, json.dumps({"status": "schedule_received", "tasks": 1}))
time.sleep(2)

print("Publishing executing...")
client.publish(topic, json.dumps({"status": "executing", "task_id": 1, "action": "CAPTURE_IMAGE"}))
time.sleep(2)

print("Publishing uploading...")
client.publish(topic, json.dumps({"status": "uploading", "task_id": 1}))
time.sleep(2)

print("Publishing uploaded...")
client.publish(topic, json.dumps({"status": "uploaded", "task_id": 1, "bytes": 150000}))
print("Done.")

time.sleep(1)
