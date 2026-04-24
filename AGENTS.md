<!-- crag:auto-start -->
# AGENTS.md

> Generated from governance.md by [crag](https://crag.sh). Regenerate: `crag compile --target agents-md`

## Project: thesis-iot-monitoring

Autonomous IoT Visual Monitoring — STM32 firmware + FastAPI server + Next.js dashboard

## Quality Gates

All changes must pass these checks before commit:

### Server (working-directory: server)
1. `python -m pytest tests/ -v --tb=short`

### Dashboard (working-directory: dashboard)
1. `npx biome check --no-errors-on-unmatched --diagnostic-level=error`
2. `npx tsc --noEmit`
3. `npm run build`

### Firmware (working-directory: firmware)
1. `make -j8`

## Coding Standards

- Stack: python, typescript, c, docker
- Conventional commits (feat:, fix:, docs:, etc.)
- Commit trailer: Co-Authored-By: Claude <noreply@anthropic.com>

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

## Security

- No hardcoded secrets — grep for sk_live, AKIA, password= before commit

## Workflow

1. Read `governance.md` at the start of every session — it is the single source of truth.
2. Run all mandatory quality gates before committing.
3. If a gate fails, fix the issue and re-run only the failed gate.
4. Use the project commit conventions for all changes.

<!-- crag:auto-end -->
