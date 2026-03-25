import paho.mqtt.client as mqtt
import time
import json

def on_connect(client, userdata, flags, rc):
    print("Connected to remote broker")
    client.subscribe("device/stm32/status")
    client.subscribe("device/stm32/logs")
    print("Publishing OTA trigger...")
    client.publish("device/stm32/commands", json.dumps({"type":"firmware_update"}))

def on_message(client, userdata, msg):
    try:
        print(f"[{msg.topic}] {msg.payload.decode('utf-8')}")
    except:
        pass

c = mqtt.Client()
c.on_connect = on_connect
c.on_message = on_message
c.connect("89.167.11.147", 1883, 60)

c.loop_start()
print("Waiting for 20 seconds...")
time.sleep(20)
c.loop_stop()
c.disconnect()
