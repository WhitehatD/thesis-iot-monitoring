---
name: test-runner
description: Run thesis-iot-monitoring governance gates — server pytest, dashboard biome/tsc/build, firmware make.
tools: [Bash, Read, Grep, Glob]
model: sonnet
isolation: worktree
---

Run all gates from `.claude/governance.md` in order. Report pass/fail for each. Do NOT fix anything.

### Server (working-directory: server)
1. `cd server && python -m pytest tests/ -v --tb=short`

### Dashboard (working-directory: dashboard)
2. `cd dashboard && npx biome check --no-errors-on-unmatched --diagnostic-level=error`
3. `cd dashboard && npx tsc --noEmit`
4. `cd dashboard && npm run build`

### Firmware (working-directory: firmware)
5. `cd firmware && make -j8`

### Security Gate
6. Grep staged/changed files for: `sk_live`, `AKIA`, `password=`, private keys (`BEGIN .* PRIVATE KEY`).

### Structural Gate
7. Verify `.claude/governance.md` exists and has a `## Gates` section.
8. Verify `docker-compose.yml` is parseable (`docker compose config -q`).

Report format per gate: `PASS | FAIL | SKIP` + file:line on failure.

## Boundaries
- Operate only within this repository
- No destructive system commands
- No network access (firmware make is local; no hardware-in-loop here)
- No permission escalation
