# Autonomous IoT Visual Monitoring System

> **Bachelor Thesis** — Alexandru-Ionut Cioc, Maastricht University (DACS)
>
> *Design and Implementation of an Autonomous IoT Visual Monitoring System with Cloud-Based AI Planning and Analysis*

## Architecture

```
┌──────────────────┐     MQTT (commands)      ┌────────────────────┐
│   STM32 Board    │◄────────────────────────►│   Cloud Server     │
│  B-U585I-IOT02A  │     HTTP (images)        │   (FastAPI)        │
│                  │─────────────────────────►│                    │
│  • OV5640 Camera │                          │  • AI Planning     │
│  • EMW3080 Wi-Fi │                          │  • Qwen3-VL (vLLM) │
│  • RTC Scheduler │                          │  • Gemini 3 Flash  │
│  • Low-Power     │                          │  • Mosquitto MQTT  │
└──────────────────┘                          └────────────────────┘
                                                       │
                                                       ▼
                                              ┌────────────────────┐
                                              │   Web Dashboard    │
                                              │  (React + Vite)    │
                                              │                    │
                                              │  • Prompt input    │
                                              │  • Schedule viz    │
                                              │  • Image gallery   │
                                              └────────────────────┘
```

## Project Structure

| Directory | Description |
|---|---|
| `firmware/` | STM32CubeIDE project — FreeRTOS + coreMQTT + camera + Wi-Fi |
| `server/` | FastAPI backend — AI planning engine, MQTT handler, REST API |
| `dashboard/` | React frontend — user prompt input and results visualization |
| `mosquitto/` | Eclipse Mosquitto MQTT broker configuration |
| `benchmarks/` | Evaluation scripts for RQ1 (plan accuracy), RQ2 (model comparison), RQ3 (power) |
| `docs/` | Thesis LaTeX source and architecture diagrams |
| `scripts/` | Utility scripts (flash, setup) |

## Quick Start

### Server

```bash
cd server
python -m venv .venv && .venv\Scripts\activate  # Windows
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

### MQTT Broker

```bash
docker compose up mosquitto
```

### Firmware

Open `firmware/` in STM32CubeIDE, build, and flash via ST-Link.

## Research Questions

1. **RQ1**: How can NL requirements be decomposed into executable hardware schedules?
2. **RQ2**: Qwen3-VL vs Gemini 3 — latency, accuracy, and cost trade-offs?
3. **RQ3**: How much power does AI-planned monitoring save vs continuous?

## License

Academic use — Maastricht University, 2026.
