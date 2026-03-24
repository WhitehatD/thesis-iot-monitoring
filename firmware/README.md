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

## Supported MQTT Commands

The board acts dynamically based on JSON payloads sent to `device/stm32/commands`:

- **Schedule (`"type":"schedule"` or legacy array)**: Parses a list of tasks and sleeps/wakes to execute them autonomously.
- **Capture Now (`"type":"capture_now"`)**: Instantly captures an image.
- **Capture Sequence (`"type":"capture_sequence"`, `"delays_ms":[...]`)**: Captures multiple images at exact sub-second millisecond offsets.
- **Sleep Toggle (`"type":"sleep_mode"`, `"enabled":true`)**: Modifies behavioral routing to STOP2 low-power mode between tasks.
- **Firmware Update (`"type":"firmware_update"`)**: Initiates the Dual-Bank OTA sequence.

## Hardware Triggers

- **B3 USER Button (Blue)**: Pressing this hardware interrupt instantly triggers a warm image capture and HTTP upload bypass.

## LED Status Indicators

The physical `LED_GREEN` and `LED_RED` embedded on the board provide distinct visual feedback for every system state.

### General Operation

- **Booting Initialization**: Both **GREEN** and **RED** are solidly ON during hardware config.
- **Board Ready**: 3 crisp **GREEN** flashes signal a successful network/MQTT connection.
- **Idle / Monitoring**: Slow ~1Hz "breathing" toggle on **GREEN** confirms the node is monitoring.
- **MQTT Command Received**: Brief 50ms pulse of **GREEN + RED** confirms packet delivery.
- **Image Capturing**: **RED** turns solid ON (functioning identically to a camera recording light).
- **Image Uploading (HTTP POST)**: **GREEN** flickers rapidly to symbolize dense data transfer.
- **Fatal Error**: **RED** continuously blinks rapidly across infinite blocking loops.

### Over-The-Air (OTA) Updates

- **Update Checking**: **RED** stays ON during the blocking HTTP version request.
- **Update Received**: 5 rapid strobe flashes on both **RED + GREEN** before commencing flash ops.
- **Flushing Update (Flash Erase)**: Both **GREEN** and **RED** stay solidly ON representing a volatile hardware erasure state.
- **Diff Update (Downloading)**: **RED** and **GREEN** rapidly alternate (police-siren effect) as granular chunks are dynamically streamed and programmed into flash.
- **OTA Success**: **GREEN** guarantees integrity and completes a solid 1.5-second sequence right before hardware restart.

## Over-The-Air (OTA) Architecture

This firmware deeply utilizes the STM32U585's 2MB dual-bank flash architecture to provide resilient, atomic firmware updates.

1. **Poll**: The board verifies the latest application version with the server API.
2. **Download**: The new `.bin` is natively streamed bit-by-bit directly into the *inactive* flash bank.
3. **Verify**: Native software CRC32 validation guarantees bit-level accuracy against the file.
4. **Swap & Reboot**: The non-volatile `SWAP_BANK` option bytes are flipped atomically during reboot.
5. **Rollback (Rescue)**: If the new firmware fails to boot properly across 3 consecutive times, the MCU trips its RTC backup registry threshold and intrinsically forces a secondary bootbank reversion swap to rescue the node.
