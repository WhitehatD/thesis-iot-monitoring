# Progress Update — March 10, 2026

---

## 1. What am I working on?

Since last meeting, I received the board and completed the full hardware bring-up:

- **Firmware done** — camera driver (OV5640), Wi-Fi/MQTT stack (EMW3080), and low-power scheduler are all working on bare-metal
- **End-to-end pipeline working** — STM32 captures an image, uploads it over Wi-Fi, server processes it, dashboard displays it live via MQTT-over-WebSocket
- **Server & deployment ready** — FastAPI backend, Mosquitto broker, Next.js dashboard, all containerized with Docker Compose
- **Currently integrating the AI planning engine** — connecting Gemini 3 Flash to generate the JSON capture schedules from natural-language prompts

---

## 2. Where do I need help?

- **DACS Scheduling interview** — I haven't reached out yet to dacs-scheduling@maastrichtuniversity.nl. Should I go ahead and email them directly, or would you prefer to introduce me?
- **Second evaluator** — any update on this?
- **Benchmarking approach** — for comparing Gemini 3 Flash vs Qwen3-VL vs Qwen2.5-VL, any suggestions on how to evaluate plan quality?

---

## 3. What's next?

| Phase | Status |
|-------|--------|
| 1. Foundation (HW/SW) | ✅ Done |
| 2. AI Planning & Backend | 🔄 Almost done |
| 3. Integration & Monitoring | ⬜ Next |
| 4. Benchmarking | ⬜ Planned |
| 5. Writing | ⬜ Planned |

**Next week:**
- Finish LLM → schedule generation integration
- 24-hour overnight deployment test for reliability
- Reach out to DACS Scheduling
- Start LaTeX thesis structure
