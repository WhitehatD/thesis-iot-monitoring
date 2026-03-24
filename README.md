<p align="center">
  <h1 align="center">🔬 Autonomous IoT Visual Monitoring System</h1>
  <p align="center">
    <strong>Enterprise-Grade STM32 Edge Camera with Multimodal LLM Intelligence</strong>
  </p>
  <p align="center">
    <em>Bachelor Thesis — Computer Science & Engineering</em>
    <br/>
    <sub>by <strong>Alexandru Cioc (WhitehatD)</strong></sub>
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

## 🚀 The Vision: Beyond Simple Sensors

Legacy industrial monitoring relies on dumb network cameras streaming petabytes of useless, empty footage to the cloud. This project introduces a fundamentally different paradigm: **Autonomous Visual Intelligence at the Edge**.

By combining a heavily optimized bare-metal STM32 microcontroller with state-of-the-art Multimodal Large Language Models (Gemini 3 Flash, Qwen3-VL), we deploy a zero-maintenance "eye" that actively understands its environment. It processes natural language prompts, creates its own execution schedules, captures high-fidelity RGB565 frames, and interprets the scene—all autonomously.

Built with YC-grade engineering rigor, the system features a complete CI/CD-driven Over-The-Air (OTA) update pipeline, ensuring the edge devices continuously evolve without ever being physically touched.

---

## ✨ Enterprise-Grade Features

*   🧠 **LLM-Driven Scheduling**: NLP planning engine translates human instructions ("Check if the delivery bay is clear every morning at 9 AM") into machine-executable RTC alarm sequences over MQTT.
*   ⚡ **Bare-Metal Performance**: Stripped-down, zero-RTOS C firmware maximizing the Cortex-M33's 160MHz capabilities. Total memory control via comprehensive stack watermark auditing.
*   🔄 **Zero-Downtime OTA Updates**: Dual-bank flash architecture. New firmware streams via chunked HTTP, verifies via CRC32, and executes an atomic memory bank swap. Built-in automatic rollback upon boot failure ensures devices can't be bricked remotely.
*   🚦 **Mutually Exclusive Observability**: A strictly defined visual state machine through onboard LEDs guarantees zero ambiguity during diagnostics (Green heartbeat for Idle, Solid Red for Capture, Green Blink for Network Transfer, Strobe Warnings for OTA Updates).
*   🌐 **"Mechanical Luxury" Dashboard**: A Next.js 16 control center featuring sub-millisecond tactile feedback, real-time MQTT WebSocket pipelines, and live visual feeds.
*   🛡️ **Resilient CI/CD Deployment**: End-to-end GitHub Actions pipeline. A single `git push` runs tests, compiles the ARM GCC payload, builds Docker containers, synchronizes the cloud VPS, and pushes the binary update directly to the edge hardware over-the-air.

---

## 🏗️ Architecture Blueprint

The system spans from raw C hardware drivers to cloud-native Python services.

```mermaid
graph TD
    classDef hardware fill:#03234B,color:#fff,stroke:#fff
    classDef cloud fill:#009688,color:#fff,stroke:#fff
    classDef frontend fill:#000,color:#fff,stroke:#fff

    subgraph Edge ["Edge Device (STM32 B-U585I-IOT02A)"]
        MCU[Bare-Metal STM32U5]:::hardware
        CAM[OV5640 Camera]:::hardware
        WIFI[EMW3080 Wi-Fi]:::hardware
        
        CAM -- DCMI --> MCU
        MCU -- SPI --> WIFI
    end

    subgraph Infrastructure ["Cloud Infrastructure (VPS / Docker)"]
        Broker[Mosquitto MQTT :1883]:::cloud
        Server[FastAPI Backend :8000]:::cloud
        DB[(SQLite Async)]:::cloud
        AI[Multimodal LLM Engine]:::cloud
        
        Broker <--> Server
        Server <--> DB
        Server <--> AI
    end

    subgraph Control ["User Interface"]
        Dash[Next.js 16 Dashboard]:::frontend
    end

    WIFI -- "MQTT (Commands, Status)" <--> Broker
    WIFI -- "HTTP POST (Raw Image)" --> Server
    WIFI -- "HTTP GET (OTA Binary)" <-- Server
    
    Server -- "REST API" <--> Dash
    Broker -- "WebSockets :9001" <--> Dash
```

---

## 📂 Codebase Anatomy

The monorepo contains four primary components, strictly separated by concern:

### 1. `firmware/` (The Brains of the Edge)
Bare-metal C code compiled via `arm-none-eabi-gcc`.
*   **`main.c`**: The unified non-blocking event loop. Handles RTC wakeups, MQTT command dispatch, and graceful standby.
*   **`ota_update.c`**: Dual-bank firmware flashing mechanism. Implements secure chunk downloading, CRC32 verification, and atomic memory swapping.
*   **`camera.c`**: Interacts with the OV5640 sensor. Initializes persistent configurations to enable warm sub-second capturing.
*   **`wifi.c` / `mqtt_handler.c`**: High-durability networking stack. Handles automatic silent reconnection loops, mitigating standard IoT drop-off flaws.

### 2. `server/` (The Cloud Engine)
Modern Python `FastAPI` application engineered for speed and resilience.
*   **API Layer**: Ingests image arrays, coordinates LLM generation, curates metadata, and handles OTA payload authorization. Error handling prevents malformed uploads. 
*   **MQTT Layer**: Connects asynchronously to Mosquitto, pushing live commands (`capture_sequence`, `firmware_update`) to the fleet in real-time.
*   **AI Planner**: Converts abstract prompt strings to discrete JSON cron tasks using `gemini-3-flash` or local `vLLM`.

### 3. `dashboard/` (The Cockpit)
React 19 / Next.js 16 highly-responsive "YC-grade" frontend.
*   Utilizes WebSocket-MQTT listeners for instantaneous feed updates without HTTP polling lag.
*   "Mechanical Luxury" interactions: Clean aesthetics tailored for efficient human-machine supervision. 

### 4. `scripts/` & `.github/workflows/` (The Factory)
*   **`ci.yml`**: Comprehensive automated factory. Stages include PyTest gating -> ARM Binary Compilation -> Container Image Generation -> VPS Server Synchronization -> OTA Trigger.

---

## 🚦 Edge Hardware Observability

Ambiguous flashing LEDs are the bane of IoT engineering. This system employs a strictly enforced visual state machine via the board's Red and Green LEDs:

| Hardware State | LED Pattern | What it means |
| :--- | :--- | :--- |
| **Boot Success** | 🟢 3× Fast Flashes | Hardware initialized, mapped to MQTT, ready. |
| **Idling** | 🟢 50ms Pulse / 3 sec | Ultra-low power "heartbeat" proving system vitality. |
| **Image Capture** | 🔴 Solid Red | Sensor is active and acquiring frame data. |
| **Data Transfer** | 🟢 Rapid Strobe | Active HTTP chunk transfer (Upload / Check). |
| **OTA Initialize** | 🔴+🟢 5× Strobe | Over-The-Air firmware manipulation is imminent. |
| **OTA Flashing** | 🔴 Solid + 🟢 Pulse | Critical memory write in progress. Do not unplug. |

---

## 🛠️ Deployment & Setup (The "Zero-Friction" Way)

### 1. The Cloud Platform (VPS)
We bypass complicated third-party runners in favor of an aggressively streamlined VPS Docker model.
```bash
# Clone the repository
git clone https://github.com/<your-username>/thesis-iot-monitoring.git
cd thesis-iot-monitoring

# Set up your environment (AI API Keys, Host IPs)
cp server/.env.example server/.env

# Summon the stack
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### 2. The Edge Firmware
```bash
# Navigate to the firmware workspace
cd firmware

# Compile using your machine's parallel cores
make -j8

# First-time flash through ST-Link (subsequent fixes will push via OTA)
make flash
```
Edit `firmware/Core/Inc/firmware_config.h` to supply your respective `WIFI_SSID` and `SERVER_HOST`.

### 3. The CI/CD OTA Loop
When modifying Edge Firmware (`main.c` / `camera.c`), you no longer physically touch the board.
1. Commit and push your C code to GitHub `main` branch.
2. The GitHub Action spins up an Ubuntu node, runs GNU Make, and packages `thesis-iot-firmware.bin`.
3. The Action authenticates and pushes the binary straight to your live VPS over `/api/firmware/upload`.
4. Your VPS securely brokers an MQTT payload to the board (`"type": "firmware_update"`).
5. The board intercepts the payload, downloads chunks out of standard execution paths, flashes the inactive bank, and self-resets gracefully into the new logic.

---

<p align="center">
  <sub>Built with ❤️ for autonomous vision research</sub>
</p>
