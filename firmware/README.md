# IoT Visual Monitoring — STM32 Firmware

Embedded firmware for the **B-U585I-IOT02A Discovery Kit** that implements the edge node of an autonomous IoT visual monitoring system.

## Architecture

```text
┌───────────────────────────────────────────────────┐
│                  main.c (Orchestrator)              │
│                                                     │
│  BOOT → Wi-Fi → MQTT → Poll Schedule → Execute     │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ wifi.c   │  │ camera.c │  │ mqtt_handler.c   │  │
│  │ EMW3080  │  │ OV5640   │  │ MQTT 3.1.1       │  │
│  │ SPI/TCP  │  │ DCMI/DMA │  │ over TCP socket  │  │
│  └──────────┘  └──────────┘  └──────────────────┘  │
│                                                     │
│  ┌────────────────────┐  ┌───────────────────────┐  │
│  │ scheduler.c        │  │ debug_log.c           │  │
│  │ cJSON + RTC Alarm  │  │ USART1 (ST-Link VCP)  │  │
│  │ STOP2 low-power    │  │ Timestamped logging   │  │
│  └────────────────────┘  └───────────────────────┘  │
└───────────────────────────────────────────────────┘
```

## Firmware Lifecycle

1. **Boot** — HAL init, 160 MHz clock, ICACHE, UART debug logging
2. **Connect** — Wi-Fi (WPA2) → MQTT broker (subscribe to `device/stm32/commands`)
3. **Wait** — Poll MQTT for AI-generated schedule (with keepalive pings)
4. **Execute** — For each scheduled task:
   - Set RTC Alarm → Enter STOP2 (ultra-low power, ~2 μA)
   - Wake → Init camera → Capture JPEG frame
   - Reconnect Wi-Fi → HTTP POST image to server
   - Publish status via MQTT → Next task
5. **Complete** — Enter Standby mode until next power cycle

## File Structure

```text
firmware/
├── Core/
│   ├── Inc/
│   │   ├── firmware_config.h    ← Central configuration (Wi-Fi, server, etc.)
│   │   ├── debug_log.h          ← UART logging macros
│   │   ├── wifi.h               ← Wi-Fi connection + HTTP client API
│   │   ├── camera.h             ← Camera capture API
│   │   ├── mqtt_handler.h       ← MQTT client API
│   │   ├── scheduler.h          ← Schedule parser + RTC alarm API
│   │   ├── cJSON.h              ← JSON parser (MIT, Dave Gamble)
│   │   ├── main.h               ← HAL/BSP includes + shared handles
│   │   └── stm32u5xx_hal_conf.h ← HAL module selection
│   └── Src/
│       ├── main.c               ← Application orchestrator
│       ├── wifi.c               ← EMW3080 BSP driver + TCP HTTP POST
│       ├── camera.c             ← OV5640 DCMI capture + JPEG detection
│       ├── mqtt_handler.c       ← Bare-metal MQTT 3.1.1 client
│       ├── scheduler.c          ← cJSON schedule parser + RTC + STOP2
│       ├── debug_log.c          ← USART1 init + printf redirect
│       ├── cJSON.c              ← JSON parser implementation
│       ├── stm32u5xx_it.c       ← ISR handlers (RTC, DCMI, DMA)
│       └── system_stm32u5xx.c   ← System clock startup (ST-generated)
└── STM32CubeIDE/
    ├── .cproject / .project     ← IDE project files
    ├── Drivers/                 ← BSP + HAL + CMSIS (must be populated)
    └── STM32U585AIIX_FLASH.ld   ← Linker script
```

## Prerequisites

1. **STM32CubeIDE** (v1.14+) with STM32U5 support
2. **B-U585I-IOT02A BSP pack** — install via CubeMX Package Manager
3. **Camera module** — MB1379 (OV5640) plugged into DCMI connector

## Configuration

Edit `Core/Inc/firmware_config.h` before building:

```c
#define WIFI_SSID       "YourNetwork"
#define WIFI_PASSWORD   "YourPassword"
#define SERVER_HOST     "192.168.1.100"  // FastAPI server IP
#define MQTT_BROKER_HOST SERVER_HOST      // Mosquitto broker IP
```

## Build & Flash

1. Open `STM32CubeIDE/` as an existing project in STM32CubeIDE
2. **Build** → `Project > Build All` (Ctrl+B)
3. **Flash** → `Run > Debug As > STM32 C/C++ Application`
4. **Monitor** → Open serial terminal on ST-Link VCP (115200 baud)

## UART Debug Output

```text
[      0ms] [INFO] [BOOT] ========================================
[      0ms] [INFO] [BOOT]   IoT Visual Monitoring Firmware v0.1
[      1ms] [INFO] [BOOT]   Board: B-U585I-IOT02A
[      1ms] [INFO] [BOOT] ========================================
[    125ms] [INFO] [WIFI] Connecting to 'MyNetwork'...
[   2340ms] [INFO] [WIFI] Connected (IP: 192.168.1.42)
[   2890ms] [INFO] [MQTT] Connected to broker OK
[   3100ms] [INFO] [MQTT] Subscribed to 'device/stm32/commands'
[   3200ms] [INFO] [BOOT] Boot complete — waiting for schedule...
```

## Communication Protocols

| Channel | Protocol                     | Direction      | Purpose                                      |
|---------|------------------------------|----------------|----------------------------------------------|
| MQTT    | `device/stm32/commands`      | Server → Board | General command & schedule delivery          |
| MQTT    | `device/stm32/status`        | Board → Server | Status updates and telemetry                 |
| HTTP    | `POST /api/upload`           | Board → Server | High-bandwidth image/binary payload upload   |
| HTTP    | `GET /api/firmware/version`  | Board → Server | OTA firmware version check                   |
| HTTP    | `GET /api/firmware/download` | Board → Server | OTA `.bin` stream download                   |
| MQTT    | `device/stm32/logs`          | Board → Server | Live UART log tunneling for dash/observability|

## Supported MQTT Commands

The board acts dynamically based on JSON payloads sent to `device/stm32/commands`:

- **Schedule (`"type":"schedule"` or legacy array)**: Parses a list of tasks and sleeps/wakes to execute them autonomously.
- **Capture Now (`"type":"capture_now"`, optional `"task_id"`)**: Instantly captures an image and tracks it via the server-provided ID.
- **Capture Sequence (`"type":"capture_sequence"`, `"delays_ms":[...]`, optional `"task_id"`)**: Captures multiple images at exact sub-second millisecond offsets.
- **Sleep Toggle (`"type":"sleep_mode"`, `"enabled":true`)**: Modifies behavioral routing to STOP2 low-power mode between tasks.
- **Firmware Update (`"type":"firmware_update"`)**: Initiates the Dual-Bank OTA sequence.

## Status Telemetry & Log Tunneling (MQTT)

During any image capture cycle (manual or scheduled), the board broadcasts its exact hardware state to `device/stm32/status` to feed the dashboard's real-time stepper.
Additionally, UART debug logs are natively tunneled to `device/stm32/logs` in real-time, removing the dependency on physical serial monitors.

1. `{"status":"job_received"}` — Command intercepted / Alarm triggered.
2. `{"status":"camera_init"}` — Sensor power-up and warm-up sequence (emitted if cold).
3. `{"status":"capturing"}` — DCMI/DMA engaged; exact moment the image is being taken.
4. `{"status":"uploading"}` — HTTP POST transfer to the server initiated.
5. `{"status":"captured"}` / `{"status":"uploaded"}` — Cycle complete successfully.

## Hardware Triggers

- **B3 USER Button (Blue)**: Pressing this hardware interrupt instantly triggers a warm image capture and HTTP upload.

## LED Status Indicators

The physical `LED_GREEN` and `LED_RED` embedded on the board provide distinct visual feedback for every system state.

### General Operation

- **Booting Initialization**: Both **GREEN** and **RED** are solidly ON during hardware config.
- **Board Ready**: 3 crisp **GREEN** flashes signal a successful network/MQTT connection.
- **Idle / Monitoring**: Slow 50ms pulse on **GREEN** every 3 seconds confirms the node is monitoring.
- **MQTT Command Received**: Brief 50ms pulse of **GREEN + RED** confirms packet delivery.
- **Image Capturing**: **RED** turns solid ON (functioning identically to a camera recording light).
- **Image Uploading (HTTP POST)**: **RED** stays solid, while **GREEN** flickers rapidly to symbolize dense data transfer.
- **Fatal Error**: **RED** continuously blinks rapidly across infinite blocking loops.

### Over-The-Air (OTA) Updates

- **Update Checking**: **RED** stays ON during the blocking HTTP version request.
- **Update Received**: 5 rapid strobe flashes on both **RED + GREEN** before commencing flash ops.
- **Flushing Update (Flash Erase)**: Both **GREEN** and **RED** stay solidly ON representing a volatile hardware erasure state.
- **Diff Update (Downloading)**: **RED** is mostly solid and **GREEN** rapidly pulses as granular chunks are dynamically streamed and programmed into flash.
- **OTA Success**: **GREEN** guarantees integrity and completes a solid 1.5-second sequence right before hardware restart.

## Over-The-Air (OTA) Architecture

This firmware deeply utilizes the STM32U585's 2MB dual-bank flash architecture to provide resilient, atomic firmware updates.

1. **Poll**: The board verifies the latest application version with the server API.
2. **Download**: The new `.bin` is natively streamed bit-by-bit directly into the *inactive* flash bank.
3. **Verify**: Native software CRC32 validation guarantees bit-level accuracy against the file.
4. **Swap & Reboot**: The non-volatile `SWAP_BANK` option bytes are flipped atomically during reboot.
5. **Rollback (Rescue)**: If the new firmware fails to boot properly across 3 consecutive times, the MCU trips its RTC backup registry threshold and intrinsically forces a secondary bootbank reversion swap to rescue the node.

## Security Hardening (March 2026)

Enterprise-grade security audit conducted against **OWASP IoT Top 10 2025**, **CERT C Secure Coding**, and **NIST SP 800-183**. The following 8 vulnerability categories were identified and patched:

| ID | Finding | Severity | Standard | Files Changed |
|----|---------|----------|----------|---------------|
| SEC-01 | Hardcoded Wi-Fi/server credentials | Critical | OWASP I1 | `firmware_config.h` |
| SEC-02 | Unauthenticated MQTT broker access | High | OWASP I3 | `firmware_config.h`, `mqtt_handler.c` |
| SEC-03 | Integer overflow in MQTT remaining-length decoder | High | CERT C INT32-C | `mqtt_handler.c` |
| SEC-04 | Missing range validation on RTC time fields | Medium | CERT C INT32-C | `wifi.c`, `scheduler.c` |
| SEC-05 | Server error details leaked in logs | Medium | OWASP I7 | `wifi.c` |
| SEC-06 | OTA firmware downgrade attack vector | High | OWASP I4 | `ota_update.c`, `ota_update.h` |
| SEC-07 | No hardware watchdog (IWDG) for autonomous recovery | High | OWASP I9 | `main.c`, `firmware_config.h` |
| SEC-08 | Unsafe `atoi()` usage (undefined on overflow) | Medium | CERT C MSC24-C | `wifi.c`, `ota_update.c` |
| SEC-09 | Watchdog starvation during slow network OTA downloads | High | OWASP I9 | `ota_update.c` |

### Key Remediations

- **Credentials** are now overridable via `-D` build flags (`WIFI_SSID`, `WIFI_PASSWORD`, `SERVER_HOST`, `MQTT_USERNAME`, `MQTT_PASSWORD`)
- **MQTT CONNECT** packet supports optional username/password authentication per MQTT 3.1.1 spec
- **OTA anti-downgrade** uses semantic version comparison — only strictly newer versions are accepted
- **IWDG watchdog** with 16s timeout provides autonomous hardware reset on main-loop stalls
- **`atoi()` → `strtol()`** with error checking prevents undefined behavior from malformed HTTP responses
- **Time/date fields** are range-validated before writing to RTC registers
- **Network yield watchdog wrapper** explicitly feeds `IWDG` during all blocking HTTP sockets to prevent OTA download resets.
