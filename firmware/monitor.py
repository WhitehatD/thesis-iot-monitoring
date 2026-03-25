#!/usr/import sys
import serial
import serial.tools.list_ports
import json
import time
import paho.mqtt.client as mqtt

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
TOPIC_LOGS = "dashboard/logs"
TOPIC_STATE = "dashboard/state"

RESET = "\033[0m"
CYAN  = "\033[36m"
YELLOW = "\033[33m"
RED   = "\033[31m"
GREEN = "\033[32m"
DIM   = "\033[2m"

def colorize(line: str) -> str:
    """Apply ANSI colors based on log level tags."""
    if "[ERROR]" in line or "FATAL" in line:
        return f"{RED}{line}{RESET}"
    if "[WARN]" in line:
        return f"{YELLOW}{line}{RESET}"
    if "[DEBUG]" in line:
        return f"{DIM}{line}{RESET}"
    if "====" in line or "Boot complete" in line or "synced" in line.lower():
        return f"{GREEN}{line}{RESET}"
    return line

def determine_level(line: str) -> str:
    if "[ERROR]" in line or "FATAL" in line: return "error"
    if "[WARN]" in line: return "warning"
    if "[DEBUG]" in line: return "debug"
    if "[INFO]" in line: return "info"
    return "log"

def extract_state(line: str):
    """Simple parser to deduce board state from standard logs."""
    state_updates = {}
    if "=== BOOT ===" in line:
        state_updates["phase"] = "booting"
    elif "Boot complete" in line:
        state_updates["phase"] = "online"
    elif "WIFI: Connected" in line:
        state_updates["network"] = "connected"
    elif "MQTT: Connected" in line:
        state_updates["mqtt"] = "connected"
    elif "OTA:" in line or "firmware" in line.lower():
        state_updates["ota_status"] = "processing"
    
    return state_updates if state_updates else None

def on_connect(client, userdata, flags, rc):
    print(f"{CYAN}║  MQTT Connected to {MQTT_BROKER}:{MQTT_PORT} (rc={rc}){RESET}")

def main():
    print(f"{CYAN}╔══════════════════════════════════════════════╗{RESET}")
    print(f"{CYAN}║  STM32 Serial Monitor — {PORT} @ {BAUD}    ║{RESET}")
    print(f"{CYAN}║  Press Ctrl+C to stop                       ║{RESET}")
    print(f"{CYAN}╚══════════════════════════════════════════════╝{RESET}")
    print()

    # Setup MQTT
    mqttc = mqtt.Client()
    mqttc.on_connect = on_connect
    try:
        mqttc.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqttc.loop_start()
    except Exception as e:
        print(f"{RED}Could not connect to MQTT {MQTT_BROKER}: {e}{RESET}")

    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
    except serial.SerialException as e:
        print(f"{RED}Could not open {PORT}: {e}{RESET}")
        print(f"\nAvailable ports:")
        for p in serial.tools.list_ports.comports():
            print(f"  {p.device}  —  {p.description}")
        sys.exit(1)

    try:
        while True:
            raw = ser.readline()
            if raw:
                line = raw.decode("utf-8", errors="replace").rstrip()
                print(colorize(line))
                
                # Publish log line
                log_payload = {
                    "timestamp": time.time(),
                    "level": determine_level(line),
                    "text": line
                }
                mqttc.publish(TOPIC_LOGS, json.dumps(log_payload))

                # Publish implicit state if any
                state_updates = extract_state(line)
                if state_updates:
                    state_updates["timestamp"] = time.time()
                    mqttc.publish(TOPIC_STATE, json.dumps(state_updates))

    except KeyboardInterrupt:
        print(f"\n{YELLOW}Monitor stopped.{RESET}")
    finally:
        ser.close()
        mqttc.loop_stop()
        mqttc.disconnect()

if __name__ == "__main__":
    main()
