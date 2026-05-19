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
- Target: docker-compose (docker-compose.yml + docker-compose.prod.yml overlay)
- CI: github-actions (`ci.yml`) — push to `main` triggers build → push to GHCR → deploy to VPS
- Registry: ghcr.io
- Services: mosquitto (MQTT broker), server (FastAPI), dashboard (Next.js), watchtower (auto-pull backup)
- VPS: 89.167.11.147 (Hetzner Helsinki)
- **All code changes go through git push → CI. Never SSH to edit code or restart containers manually.**
- **All secrets are stored in GitHub Secrets.** `ci.yml` writes them to `.env.prod` on VPS on every deploy — never edit `.env.prod` manually (it is overwritten each deploy).
- Secrets required in GitHub Secrets: `ANTHROPIC_API_KEY`, `FIRMWARE_UPLOAD_TOKEN`, `GEMINI_API_KEY`, `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PORT`
- Adding a new env var requires: (1) add to `docker-compose.prod.yml` environment block as `${VAR:-}`, (2) add to `envs:`, `printf`, and `env:` blocks in `ci.yml` deploy-vps job, (3) add value as GitHub Secret
- **After every `git push`, ALWAYS watch the CI run.** Either via subagent or `gh run watch <id> --exit-status` with `run_in_background: true`. Never push and walk away — the push outcome IS the deploy outcome.

## Brain as Ground Truth
- Brain MCP is the authoritative source for all architectural decisions, gotchas, and conventions across sessions.
- Before acting on any assumption about the system, call `recall(query="...", project="thesis")` first.
- After every root-cause fix or new discovery, call `save_insight` immediately — never batch at end-of-task.
- Governance.md is the human-readable policy; Brain is the queryable knowledge graph. Both must be kept in sync.

## Inference Infrastructure
- Cloud backends: Anthropic API (Claude Sonnet 4.6 / Haiku 4.5), Google GenAI (gemini-3-flash-preview)
- Local open-weight: llama.cpp serving Qwen3-VL-30B-A3B Q4_K_XL + Qwen2.5-VL-3B Q4_K_M
- Inference server: Ernis GPU (Maastricht University, RTX 6000 Ada 48GB, VPN-only)
  - SSH: `I6365661@ernis.dacs.maastrichtuniversity.nl`
  - Tunnel: `ssh -N -L 8001:localhost:8001 I6365661@ernis...` (VPN must be active)
  - Backend connects to `VLLM_BASE_URL=http://localhost:8001/v1` — no code changes needed
- Benchmark target: 20 captures × 4 backends = 80 runs (claude-haiku, claude-sonnet, gemini-3-flash-preview, qwen3-vl)

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

## Passive Knowledge Capture (Continuous)

Save insights AS you learn them — not at end-of-task. The cost of a `save_insight` call is trivial; the cost of losing an insight to compaction is permanent. Trigger `save_insight` immediately whenever any of these occur:

| Trigger | Insight type |
|---|---|
| You confirm a root cause for a bug | `gotcha` |
| You discover a non-obvious architectural fact (env var, port, code path) | `architecture` |
| User corrects your approach or stated preference | `feedback` |
| A reusable solution works (commands, scripts, patterns) | `pattern` |
| You make a design decision with reasoning | `decision` |
| You permanently rule out an approach | `decision` (state the reason) |
| You discover a tool/library quirk | `tool` |

Rules:
- Always pass `project: "thesis"`.
- Call `suggest_tags` first if creating a new tag family, to avoid fragmentation.
- Do not batch — save in the moment so future sessions inherit the knowledge.
- Use Brain MCP tools only (never `bash` to brain-cli.py).

## Post-Fix Knowledge Loop

Every root-cause fix is incomplete until these steps are done. No exceptions.

### 1. Update `governance.md`
- New bug class uncovered → add it under the relevant domain section as a gotcha
- New convention established → document it as normative policy with examples
- Approach permanently ruled out → state it explicitly with the reason

### 2. Save to Brain
Use the `save_insight` Brain MCP tool (never bash):
- `type`: `gotcha` (bugs/traps), `pattern` (reusable solutions), `feedback` (user corrections), `architecture` (design decisions)
- Always pass `project: "thesis"`

### 3. Regenerate `CLAUDE.md`
```bash
crag compile --target claude
```

Commit `governance.md` + `CLAUDE.md` in the same commit as the fix, prefixed `docs(governance):` when the only change is documentation.
