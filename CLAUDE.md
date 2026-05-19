<!-- crag:auto-start -->
# CLAUDE.md — thesis-iot-monitoring

> Generated from governance.md by [crag](https://crag.sh). Regenerate: `crag compile --target claude`

Autonomous IoT Visual Monitoring — STM32 firmware + FastAPI server + Next.js dashboard

**Stack:** python, typescript, c, docker
**Runtimes:** node, python

## Quality Gates

Run these in order before committing. Stop on first MANDATORY failure:

- `python -m pytest tests/ -v --tb=short`
- `npx biome check --no-errors-on-unmatched --diagnostic-level=error`
- `npx tsc --noEmit`
- `npm run build`
- `make -j8`

## Rules

1. Read `governance.md` at the start of every session — it is the single source of truth.
2. Run all mandatory quality gates before committing.
3. If a gate fails, attempt an automatic fix (lint/format) with bounded retry (max 2 attempts). If it still fails, escalate to the user.
4. Never modify files outside this repository.
5. Never run destructive system commands (`rm -rf /`, `DROP TABLE`, force-push to main).
- Use conventional commits (feat:, fix:, docs:, etc.)
- Commit trailer: `Co-Authored-By: Claude <noreply@anthropic.com>`

## Anti-Patterns

Do not:
- Do not catch bare `Exception` — catch specific exceptions
- Do not use mutable default arguments (e.g., `def f(x=[])`)
- Do not use `import *` — use explicit imports
- Do not use `latest` tag in FROM — pin to a specific version
- Do not run containers as root — use a non-root USER

## Security

- No hardcoded secrets — grep for sk_live, AKIA, password= before commit

## Tool Context

This project uses **crag** (https://crag.sh) as its governance engine. The `governance.md` file is the authoritative source. Run `crag audit` to detect drift and `crag compile --target all` to recompile all targets.

<!-- crag:auto-end -->

## Inference Infrastructure

- Cloud backends: Anthropic API (Claude Sonnet 4.6 / Haiku 4.5), Google GenAI (gemini-3-flash-preview)
- Open-weight: llama.cpp serving Qwen3-VL-30B-A3B Q4_K_XL + Qwen2.5-VL-3B Q4_K_M via OpenAI-compatible HTTP
- Inference server: Ernis GPU (Maastricht University, RTX 6000 Ada 48 GB, VPN-only)
  - SSH: `I6365661@ernis.dacs.maastrichtuniversity.nl` (VPN: `vpn.maastrichtuniversity.nl`)
  - Tunnel: `ssh -N -L 8001:localhost:8001 I6365661@ernis...` — keep running during experiments
  - Local FastAPI connects to `VLLM_BASE_URL=http://localhost:8001/v1` — no code changes needed
- Benchmark scope: 20 captures × 4 backends = 80 runs (claude-haiku, claude-sonnet, gemini-3-flash-preview, qwen3-vl)

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
node /d/nodejs/node_modules/@whitehatd/crag/bin/crag.js compile --target claude
```
Note: plain `crag` may be rewritten by RTK hooks — use the node invocation above.

Commit `governance.md` + `CLAUDE.md` in the same commit as the fix, prefixed `docs(governance):` when the only change is documentation.

## Deployment

- **All code changes go through git push → CI. Never SSH to edit code or restart containers manually.**
- Push to `main` → `ci.yml` builds images → pushes to GHCR → deploy-vps job force-recreates containers on VPS.
- VPS: 89.167.11.147 (Hetzner Helsinki). Project dir found by CI via `find`.
- **All secrets in GitHub Secrets only.** CI writes them to `.env.prod` on VPS on every deploy — manual edits are overwritten.
- Required GitHub Secrets: `ANTHROPIC_API_KEY`, `FIRMWARE_UPLOAD_TOKEN`, `GEMINI_API_KEY`, `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PORT`
- Adding a new env var: (1) `${VAR:-}` in `docker-compose.prod.yml`, (2) add to `envs:` + `printf` + `env:` in `ci.yml` deploy-vps job, (3) add value in GitHub Secrets.

## Brain as Ground Truth

- **Before acting on any assumption about this system, call `recall(query="...", project="thesis")` first.**
- Brain MCP is authoritative for architecture, gotchas, and conventions across sessions.
- Save insights immediately after every discovery — never batch at end of task.
- `save_insight` types: `gotcha` (bugs/traps), `pattern` (solutions), `architecture` (design), `feedback` (corrections).
