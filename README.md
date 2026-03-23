<p align="center">
  <h1 align="center">🔬 Autonomous IoT Visual Monitoring System</h1>
  <p align="center">
    <strong>STM32-powered edge camera with cloud-hosted multimodal LLM analysis</strong>
  </p>
  <p align="center">
    <em>Bachelor Thesis — Computer Science & Engineering</em>
    <br/>
    <sub>by <strong>Alexandru-Ionut Cioc</strong></sub>
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/STM32-U585AI-03234B?style=for-the-badge&logo=stmicroelectronics&logoColor=white" alt="STM32" />
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Next.js-16-000000?style=for-the-badge&logo=next.js&logoColor=white" alt="Next.js" />
  <img src="https://img.shields.io/badge/MQTT-3.1.1-660066?style=for-the-badge&logo=eclipsemosquitto&logoColor=white" alt="MQTT" />
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker" />
  <img src="https://img.shields.io/badge/CI%2FCD-GitHub_Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white" alt="CI/CD" />
  <img src="https://img.shields.io/badge/OTA-Dual_Bank_Flash-FF6F00?style=for-the-badge&logo=lightning&logoColor=white" alt="OTA" />
</p>

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Hardware](#hardware)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [1. Cloud Stack (Docker)](#1-cloud-stack-docker)
  - [2. Firmware (STM32)](#2-firmware-stm32)
- [Configuration](#configuration)
- [MQTT Protocol](#mqtt-protocol)
- [API Reference](#api-reference)
- [OTA Firmware Updates](#ota-firmware-updates)
- [CI/CD Pipeline](#cicd-pipeline)
- [Dashboard](#dashboard)
- [Firmware Modules](#firmware-modules)
- [AI Analysis Pipeline](#ai-analysis-pipeline)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

---

## Overview

An end-to-end autonomous visual monitoring system designed for industrial and environmental applications. An **STM32U585AI** microcontroller captures images via an **OV5640** camera sensor, transmits them over **Wi-Fi** to a self-hosted server, and triggers **multimodal LLM analysis** (Gemini / local vLLM) for intelligent scene understanding.

**Key capabilities:**

- ⏱️ **Second-precision scheduling** — RTC-based task scheduling with `HH:MM:SS` granularity
- 📸 **On-demand capture** — instant MQTT-triggered captures and timed sequences
- 🧠 **AI-powered analysis** — multimodal LLM scene interpretation (Gemini 3 Flash / Qwen3-VL)
- 🌐 **Real-time dashboard** — live image feed, schedule management, and device status
- 💤 **Configurable sleep mode** — toggle between always-awake polling and low-power STOP2
- 🔄 **Full-stack Docker** — one-command deployment with health checks
- 🚀 **OTA firmware updates** — dual-bank flash with CRC32 verification and automatic rollback
- ⚡ **CI/CD pipeline** — GitHub Actions → GHCR → Watchtower auto-deploy on every push

---

## Architecture

```
┌─────────────────┐     MQTT 3.1.1      ┌──────────────────┐     HTTP REST     ┌──────────────────┐
│   STM32U585AI   │◄───────────────────►│  Mosquitto MQTT  │◄────────────────►│  Next.js 16      │
│   + OV5640 Cam  │     (commands)       │  Broker :1883    │   (WebSocket)    │  Dashboard :3000 │
│   + EMW3080 WiFi│                      │  WS :9001        │                  │  React 19        │
└────────┬────────┘                      └────────┬─────────┘                  └──────────────────┘
         │ HTTP POST                              │
         │ (image upload)                         │ MQTT pub/sub
         │                                        │
         └──────────────►┌────────────────────────┴───────┐
                         │  FastAPI Server :8000           │
                         │  ├── Scheduler Service          │
                         │  ├── Image Upload + Storage     │
                         │  ├── Firmware OTA Management    │
                         │  ├── AI Analysis (Gemini/vLLM)  │
                         │  └── SQLite (async) Database    │
                         └────────────────────────────────┘
```

### Communication Flow

| Path | Protocol | Direction | Description |
|------|----------|-----------|-------------|
| Board → Server | HTTP POST | Upload | Raw RGB565 image frames (614 KB each) |
| Board → Server | HTTP GET | OTA | Version check + firmware binary download |
| Server → Board | MQTT | Command | Schedules, captures, sleep toggle, firmware updates |
| Board → Server | MQTT | Status | Online/executing/uploaded/OTA status messages |
| Server → Dashboard | MQTT WS | Real-time | Image notifications, status updates |
| Dashboard → Server | HTTP REST | Control | CRUD schedules, trigger captures, toggle sleep |
| CI → Server | HTTP POST | Deploy | Upload new firmware binary from GitHub Actions |

---

## Project Structure

```
thesis-iot-monitoring/
├── firmware/                    # STM32 bare-metal firmware (C)
│   ├── Core/
│   │   ├── Inc/                 # Header files
│   │   │   ├── firmware_config.h    # Wi-Fi, server, camera, OTA settings
│   │   │   ├── scheduler.h          # Task scheduling structs & API
│   │   │   ├── mqtt_handler.h       # MQTT 3.1.1 client API
│   │   │   ├── wifi.h               # Wi-Fi + HTTP abstraction
│   │   │   ├── app_camera.h         # OV5640 camera driver API
│   │   │   ├── ota_update.h         # OTA firmware update API
│   │   │   └── debug_log.h          # Leveled logging (INFO/DBG/WARN/ERR)
│   │   └── Src/                 # Implementation files
│   │       ├── main.c               # Application entry — unified main loop
│   │       ├── scheduler.c          # JSON schedule parser + RTC alarm
│   │       ├── mqtt_handler.c       # Bare-metal MQTT 3.1.1 client
│   │       ├── wifi.c               # EMW3080 Wi-Fi + HTTP POST
│   │       ├── camera.c             # OV5640 DCMI capture driver
│   │       ├── ota_update.c         # Dual-bank flash OTA update engine
│   │       └── mx_wifi_hw.c         # SPI transport for MXCHIP module
│   ├── Drivers/                 # STM32 HAL, BSP, component drivers
│   ├── Makefile                 # ARM GCC build system
│   └── monitor.py               # Serial monitor script (COM port)
│
├── server/                      # FastAPI backend (Python)
│   ├── app/
│   │   ├── main.py                  # FastAPI app, lifespan, CORS
│   │   ├── config.py                # Pydantic settings (env-based)
│   │   ├── api/
│   │   │   ├── routes.py            # Image upload, time sync, health
│   │   │   ├── scheduler_routes.py  # Schedule CRUD + MQTT activation
│   │   │   ├── firmware_routes.py   # OTA: version check, download, upload
│   │   │   └── schemas.py           # Pydantic request/response models
│   │   ├── db/
│   │   │   ├── database.py          # Async SQLAlchemy engine + session
│   │   │   └── models.py            # ORM models (Schedule, Task, Image)
│   │   ├── mqtt/
│   │   │   └── client.py            # MQTT publisher (paho-mqtt)
│   │   ├── scheduler/
│   │   │   └── service.py           # Schedule business logic
│   │   ├── analysis/                # AI analysis pipeline
│   │   └── planning/                # AI planning module
│   ├── tests/                   # Pytest test suite (27 tests)
│   ├── requirements.txt         # Python dependencies
│   ├── Dockerfile               # Server container image
│   └── .env.example             # Environment variable template
│
├── dashboard/                   # Next.js frontend
│   ├── app/                     # Next.js App Router pages
│   ├── components/
│   │   ├── SchedulerPanel.js        # Schedule CRUD + sleep toggle
│   │   ├── ScheduleCard.js          # Individual schedule card
│   │   ├── CaptureButton.js         # On-demand capture trigger
│   │   ├── ImageGrid.js             # Live image gallery
│   │   └── ConnectionStatus.js      # MQTT connection indicator
│   ├── hooks/                   # Custom React hooks
│   ├── Dockerfile               # Dashboard container image
│   └── package.json             # Node.js dependencies
│
├── mosquitto/                   # MQTT broker configuration
│   └── mosquitto.conf               # Listeners, persistence, logging
│
├── .github/workflows/
│   └── ci.yml                       # CI/CD: test → build → push GHCR
├── docker-compose.yml           # Development orchestration
├── docker-compose.prod.yml      # Production overlay (Watchtower)
└── scripts/                     # Utility scripts
```

---

## Hardware

| Component | Model | Role |
|-----------|-------|------|
| **MCU** | STM32U585AI (Cortex-M33, 160 MHz) | Main controller |
| **Board** | B-U585I-IOT02A Discovery Kit | Development platform |
| **Camera** | OV5640 (5 MP, DCMI interface) | Image capture (VGA RGB565) |
| **Wi-Fi** | MXCHIP EMW3080 (SPI transport) | Network connectivity |
| **RTC** | Internal (LSE crystal, 32.768 kHz) | Second-precision scheduling |
| **RAM** | 768 KB SRAM | Frame buffer + stack |

---

## Getting Started

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| [Docker](https://docs.docker.com/get-docker/) | 24+ | Cloud stack deployment |
| [ARM GCC](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads) | 13+ | Firmware compilation |
| [STM32CubeProgrammer](https://www.st.com/en/development-tools/stm32cubeprog.html) | 2.16+ | Firmware flashing |
| [GNU Make](https://gnuwin32.sourceforge.net/packages/make.htm) | 4+ | Build orchestration |
| [Python](https://www.python.org/) | 3.10+ | Serial monitor script |

### 1. Cloud Stack (Docker)

```bash
# Clone the repository
git clone https://github.com/<your-username>/thesis-iot-monitoring.git
cd thesis-iot-monitoring

# Configure environment variables
cp server/.env.example server/.env
# Edit server/.env with your settings (AI API keys, etc.)

# Build and start all services
docker-compose up --build -d

# Verify services are running
docker-compose ps
```

| Service | URL | Description |
|---------|-----|-------------|
| **Dashboard** | [http://localhost:3000](http://localhost:3000) | Web monitoring interface |
| **API Server** | [http://localhost:8000](http://localhost:8000) | REST API + image upload |
| **API Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) | Swagger / OpenAPI |
| **MQTT Broker** | `localhost:1883` | MQTT 3.1.1 (TCP) |
| **MQTT WebSocket** | `localhost:9001` | MQTT over WebSocket |

```bash
# View service logs
docker-compose logs -f server
docker-compose logs -f dashboard

# Rebuild after code changes
docker-compose up --build -d

# Full teardown (preserves data volumes)
docker-compose down

# Full teardown including data
docker-compose down -v
```

### 2. Firmware (STM32)

#### Configure

Edit `firmware/Core/Inc/firmware_config.h`:

```c
/* Wi-Fi Credentials */
#define WIFI_SSID          "YourNetworkSSID"
#define WIFI_PASSWORD      "YourNetworkPassword"

/* Server Endpoints (IP of your Docker host) */
#define SERVER_HOST        "192.168.1.100"
#define SERVER_PORT        8000
#define MQTT_BROKER_HOST   "192.168.1.100"
#define MQTT_BROKER_PORT   1883
```

#### Build

```bash
cd firmware

# Compile (parallel build)
make -j8

# Check binary size
make size

# Output:
#   text    data     bss     dec     hex  filename
#  80552     600  639552  720704   aff40  build/thesis-iot-firmware.elf
```

#### Flash

Connect the B-U585I-IOT02A board via USB ST-Link, then:

```bash
# Flash via ST-Link
make flash

# Clean build artifacts
make clean

# Full rebuild + flash
make clean && make -j8 && make flash
```

#### Monitor Serial Output

```bash
# Start the serial monitor (default: COM7 @ 115200 baud)
python monitor.py

# Example output:
# [  11814ms] [INFO] [HTTP] Fetching server time from 192.168.1.100:8000/api/time...
# [  13849ms] [INFO] [HTTP] Server time: 04:22:10  2026-03-08 (wd=7)
# [  15857ms] [INFO] [BOOT] RTC synced to server: 04:22:10  2026-03-08
# [  18410ms] [INFO] [MQTT] Subscribing to 'device/stm32/commands'...
# [  18935ms] [INFO] [BOOT] Boot complete — waiting for commands...
```

---

## Configuration

### Environment Variables (Server)

| Variable | Default | Description |
|----------|---------|-------------|
| `MQTT_BROKER_HOST` | `localhost` | MQTT broker hostname |
| `MQTT_BROKER_PORT` | `1883` | MQTT broker port |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/thesis.db` | Async database connection |
| `VLLM_BASE_URL` | `http://localhost:8001/v1` | Local vLLM server for AI analysis |
| `VLLM_MODEL` | `Qwen/Qwen3-VL-30B-A3B` | Multimodal LLM model name |
| `GEMINI_API_KEY` | *(required)* | Google Gemini API key |
| `GEMINI_MODEL` | `gemini-3-flash` | Gemini model variant |
| `UPLOAD_DIR` | `./data/uploads` | Image storage directory |
| `FIRMWARE_DIR` | `./data/firmware` | OTA firmware binary storage |
| `FIRMWARE_UPLOAD_TOKEN` | *(optional)* | API key for CI firmware uploads |

### Firmware Configuration (`firmware_config.h`)

| Define | Description |
|--------|-------------|
| `WIFI_SSID` / `WIFI_PASSWORD` | Wi-Fi network credentials |
| `SERVER_HOST` / `SERVER_PORT` | FastAPI server address |
| `MQTT_BROKER_HOST` / `MQTT_BROKER_PORT` | MQTT broker address |
| `CAMERA_DEFAULT_RESOLUTION` | Capture resolution (VGA = 640×480) |
| `SCHEDULER_MQTT_POLL_MS` | Main loop polling interval (ms) |
| `SCHEDULER_MQTT_WAIT_TOTAL_S` | Idle timeout before standby |
| `STACK_WATERMARK_ENABLED` | Enable runtime stack usage tracking |
| `DEEP_SLEEP_ON_COMPLETE` | Enter Standby mode after all tasks |
| `FW_VERSION` | Current firmware version string (e.g. `"0.2"`) |
| `OTA_CHECK_INTERVAL_MS` | OTA version poll interval (default: 30 min) |
| `OTA_MAX_FW_SIZE` | Maximum firmware binary size (896 KB) |

---

## MQTT Protocol

### Topics

| Topic | Direction | Description |
|-------|-----------|-------------|
| `device/stm32/commands` | Server → Board | Command dispatch |
| `device/stm32/status` | Board → Server | Device status updates |
| `dashboard/images/new` | Server → Dashboard | New image notifications |

### Command Types

#### Schedule Activation

```json
{
  "type": "schedule",
  "tasks": [
    { "id": 1, "time": "09:30:00", "action": "capture_image", "objective": "Morning check" },
    { "id": 2, "time": "14:00:30", "action": "capture_image", "objective": "Afternoon scan" }
  ]
}
```

#### Instant Capture

```json
{ "type": "capture_now" }
```

#### Capture Sequence (Timed Burst)

```json
{
  "type": "capture_sequence",
  "delays_ms": [0, 5000, 10000, 30000]
}
```

#### Sleep Mode Toggle

```json
{ "type": "sleep_mode", "enabled": true }
```

#### Delete Schedule

```json
{ "type": "delete_schedule", "schedule_id": 1 }
```

#### Firmware Update (OTA trigger)

```json
{ "type": "firmware_update", "version": "0.3", "force": false }
```

### Status Messages (Board → Server)

```json
{ "status": "online", "firmware": "0.2" }
{ "status": "executing", "task_id": 1, "action": "CAPTURE_IMAGE" }
{ "status": "uploaded", "task_id": 1, "bytes": 614400 }
{ "status": "complete", "all_tasks_done": true }
{ "status": "error", "task_id": 1, "reason": "camera_init" }
{ "status": "schedule_cleared" }
{ "status": "ota_checking" }
{ "status": "ota_downloading", "new_version": "0.3", "size": 102400 }
{ "status": "ota_rebooting" }
{ "status": "ota_up_to_date", "firmware": "0.2" }
{ "status": "ota_error", "reason": "version_check_failed", "code": 2 }
```

---

## API Reference

### Health & Time

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Server health check |
| `GET` | `/api/time` | Current server time (for RTC sync) |

### Image Upload

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/upload/{task_id}` | Upload raw RGB565 image frame |
| `GET` | `/api/images` | List all captured images |
| `GET` | `/api/images/{image_id}` | Get image by ID (JPEG) |

### Firmware OTA

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/firmware/version` | Current firmware metadata (version, size, CRC32) |
| `GET` | `/api/firmware/download` | Stream firmware binary to the board |
| `POST` | `/api/firmware/upload` | Upload new firmware from CI (auth required) |

### Scheduler

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/schedules` | Create a new schedule |
| `GET` | `/api/schedules` | List all schedules |
| `GET` | `/api/schedules/{id}` | Get schedule details |
| `PUT` | `/api/schedules/{id}` | Update a schedule |
| `DELETE` | `/api/schedules/{id}` | Delete schedule (notifies board) |
| `POST` | `/api/schedules/{id}/activate` | Activate schedule via MQTT |
| `POST` | `/api/schedules/sleep-mode?enabled=true` | Toggle sleep mode |

> 📖 Full interactive API docs available at [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Dashboard

The web dashboard provides real-time monitoring and control:

| Feature | Component | Description |
|---------|-----------|-------------|
| **Image Gallery** | `ImageGrid` | Live feed of captured images with metadata |
| **Schedule Manager** | `SchedulerPanel` | Create, edit, activate, and delete schedules |
| **Schedule Cards** | `ScheduleCard` | Expandable cards with task details |
| **Capture Button** | `CaptureButton` | One-click instant capture trigger |
| **Sleep Toggle** | `SchedulerPanel` | ☀️ Awake / 🌙 Sleep mode switch |
| **Connection Status** | `ConnectionStatus` | Real-time MQTT connection indicator |

---

## Firmware Modules

### Boot Sequence

```
1. SystemClock_Config()     → 160 MHz via PLL from MSI
2. RTC_Init()               → LSE 32.768 kHz crystal
3. OTA_ValidateBoot()       → Check boot counter, rollback if 3× failure
4. WiFi_Init() + Connect()  → EMW3080 SPI + DHCP
5. HTTP Time Sync           → GET /api/time → set RTC
6. MQTT_Init() + Subscribe  → Connect broker + subscribe commands
7. OTA_MarkBootSuccessful() → Reset boot failure counter
8. Main Loop (forever)      → Poll MQTT + RTC + OTA check (30 min)
```

### Module Map

| Module | File | Responsibility |
|--------|------|----------------|
| **Main** | `main.c` | Unified main loop, command dispatch, task execution |
| **Scheduler** | `scheduler.c/h` | JSON parsing, task sorting, RTC alarm, STOP2 sleep |
| **MQTT** | `mqtt_handler.c/h` | Bare-metal MQTT 3.1.1 (CONNECT, SUBSCRIBE, PUBLISH, PING) |
| **Wi-Fi** | `wifi.c/h` | EMW3080 init, connect, HTTP GET/POST, image upload |
| **Camera** | `camera.c/h` | OV5640 DCMI capture, AEC convergence, multi-frame warmup |
| **OTA** | `ota_update.c/h` | Dual-bank flash OTA: download, verify, swap, rollback |
| **SPI Transport** | `mx_wifi_hw.c` | Low-level SPI + handshake for MXCHIP module |
| **Logging** | `debug_log.c/h` | Timestamped leveled logging (`INFO`/`DBG`/`WARN`/`ERR`) |
| **JSON** | `cJSON.c/h` | Lightweight JSON parser for MQTT payloads |

### Scheduling Modes

| Mode | Description | Trigger |
|------|-------------|---------|
| **Awake (default)** | Board stays connected, polls RTC every loop iteration | Default behavior |
| **Sleep** | Board enters STOP2 between tasks, wakes on RTC alarm | `sleep_mode` MQTT command |
| **Immediate** | Task executes instantly if its time has already passed | Automatic |

---

## AI Analysis Pipeline

The server supports two multimodal LLM backends for automated image analysis:

| Backend | Model | Deployment |
|---------|-------|------------|
| **vLLM** | Qwen3-VL-30B-A3B | Self-hosted GPU server |
| **Gemini** | Gemini 3 Flash | Google Cloud API |

The pipeline:

1. Board captures and uploads a raw RGB565 frame
2. Server converts RGB565 → JPEG and stores it
3. AI module sends the image to the configured LLM with the task objective as prompt
4. Analysis results are stored alongside the image metadata

---

## OTA Firmware Updates

The system supports **over-the-air firmware updates** using the STM32U585's dual-bank flash architecture.

### How It Works

```
┌──────────────┐     HTTP GET       ┌──────────────────┐
│  STM32 Board │────────────────────►│  /firmware/version│ ← version check
│              │                    └──────────────────┘
│  (every 30m) │     HTTP GET       ┌──────────────────┐
│              │────────────────────►│ /firmware/download│ ← stream .bin
│              │                    └──────────────────┘
│  Inactive    │
│  Flash Bank  │ ← write chunks, CRC32 verify
│              │
│  OB_Launch() │ ← atomic bank swap + system reset
└──────────────┘
```

### Safety Guarantees

| Feature | Implementation |
|---------|----------------|
| **Atomic swap** | Single Option Byte write swaps the active flash bank |
| **Old firmware preserved** | Previous firmware stays intact on the other bank |
| **Automatic rollback** | Boot counter in RTC backup register — 3 failures → revert |
| **Integrity check** | CRC32 verification before bank swap |
| **Graceful failure** | Download errors leave current firmware running |
| **Push + Poll** | Server pushes via MQTT, board also polls every 30 min |

---

## CI/CD Pipeline

### GitHub Actions Workflow

```
git push main
    ├── Stage 1: pytest (27 tests)
    ├── Stage 1.5: Build STM32 firmware (ARM GCC) + HTTP Upload to Server
    ├── Stage 2: Docker build + push to GHCR (Server & Dashboard)
    └── Stage 3: Watchtower auto-pulls on server + MQTT OTA Notify
```

### Production Deployment

```bash
# Deploy with production overlay (GHCR images + Watchtower)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Watchtower polls GHCR every 5 minutes for new images
# New pushes to main → automatic container restart
```

### Automated Firmware Upload (CI)

```bash
# Upload a new firmware binary to the server
curl -X POST http://server:8000/api/firmware/upload \
  -H "X-Firmware-Token: $FIRMWARE_UPLOAD_TOKEN" \
  -F "version=0.3" \
  -F "file=@build/firmware.bin"

# The server computes CRC32 and notifies the board via MQTT
```

---

## Development

### Server (Local)

```bash
cd server
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your settings

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Dashboard (Local)

```bash
cd dashboard
npm install
npm run dev
# Open http://localhost:3000
```

### Running Tests

```bash
cd server
pip install -r requirements-dev.txt
pytest tests/ -v
# 27 tests: capture flow + scheduler + firmware OTA
```

### Serial Monitor

The `monitor.py` script provides a formatted serial console for debugging:

```bash
cd firmware
python monitor.py
# Press Ctrl+C to stop
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| **Board doesn't connect to Wi-Fi** | Verify SSID/password in `firmware_config.h`. Check EMW3080 SPI init logs. |
| **MQTT connection refused** | Ensure Mosquitto is running: `docker-compose ps`. Check `mosquitto.conf` allows anonymous. |
| **Images are dark** | OV5640 AEC needs ~1.5s convergence. Camera driver includes 3-frame warmup. |
| **RTC time is wrong** | Board syncs RTC from `/api/time` on boot. Ensure server timezone is correct (`TZ` env var). |
| **Schedule doesn't execute** | Verify schedule is activated (POST `/{id}/activate`). Check serial logs for task polling. |
| **Docker build fails** | Run `docker-compose build --no-cache` for a clean rebuild. |
| **OTA boot loop** | After 3 failed boots, board auto-reverts to previous firmware. Check serial logs for `OTA_ValidateBoot`. |
| **OTA CRC mismatch** | Firmware binary may be corrupted during upload. Re-upload via `/api/firmware/upload`. |
| **Serial monitor can't open port** | Close STM32CubeIDE/other serial tools. Check COM port in Device Manager. |

---

<p align="center">
  <sub>Built with ❤️ for autonomous monitoring research</sub>
</p>
