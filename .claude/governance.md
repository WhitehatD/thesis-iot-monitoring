# Governance — thesis-iot-monitoring
# Reviewed and corrected from crag analyze output

## Identity
- Project: thesis-iot-monitoring
- Description: Autonomous IoT Visual Monitoring — STM32 firmware + FastAPI server + Next.js dashboard
- Stack: python, typescript, c, docker
- Workspace: monorepo (server, dashboard, firmware)

## Gates (run in order, stop on failure)
### Server (working-directory: server)
- python -m pytest tests/ -v --tb=short

### Dashboard (working-directory: dashboard)
- npx biome check --no-errors-on-unmatched --diagnostic-level=error
- npx tsc --noEmit
- npm run build

### Firmware (working-directory: firmware)
- make -j8

## Advisories (informational, not enforced)
- hadolint Dockerfile  # [ADVISORY]
- actionlint  # [ADVISORY]

## Branch Strategy
- Trunk-based development
- Conventional commits
- Commit trailer: Co-Authored-By: Claude <noreply@anthropic.com>

## Security
- No hardcoded secrets — grep for sk_live, AKIA, password= before commit

## Autonomy
- Auto-commit after gates pass

## Deployment
- Target: docker-compose
- CI: github-actions
- Registry: ghcr.io
- Services: mosquitto (MQTT broker), server (FastAPI), dashboard (Next.js)
- Deploy: SSH to VPS, docker compose pull + up

## Architecture
- Type: monorepo
- Backend: FastAPI (Python 3.12), SQLAlchemy async, MQTT
- Frontend: Next.js 16, React 19, Biome, TypeScript
- Firmware: STM32 (ARM GCC, C), OTA updates via MQTT
- Broker: Eclipse Mosquitto 2

## Key Directories
- `server/` — FastAPI backend (AI planning engine + MQTT handler)
- `dashboard/` — Next.js frontend (real-time monitoring UI)
- `firmware/` — STM32 embedded C (sensor + OTA)
- `mosquitto/` — MQTT broker config
- `scripts/` — tooling
- `docs/` — documentation
- `.github/` — CI/CD

## Testing
- Server: pytest + pytest-asyncio (async tests, SQLite in-memory)
- Dashboard: (no test framework configured yet)
- Firmware: manual / hardware-in-loop

## Anti-Patterns

Do not:
- Do not catch bare `Exception` — catch specific exceptions
- Do not use mutable default arguments (e.g., `def f(x=[])`)
- Do not use `import *` — use explicit imports
- Do not use `latest` tag in FROM — pin to a specific version
- Do not run containers as root — use a non-root USER
