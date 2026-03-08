# IoT Visual Monitoring — STM32 Firmware

Embedded firmware for the **B-U585I-IOT02A Discovery Kit** that implements the edge node of an autonomous IoT visual monitoring system.

## Architecture

```
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

```
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

```
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

| Channel | Protocol | Direction | Purpose |
|---------|----------|-----------|---------|
| MQTT | `device/stm32/commands` | Server → Board | AI schedule delivery |
| MQTT | `device/stm32/status` | Board → Server | Status updates |
| HTTP | `POST /api/upload` | Board → Server | Image upload |
