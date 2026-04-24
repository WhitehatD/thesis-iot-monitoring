<!-- crag:auto-start -->
# GEMINI.md

> Generated from governance.md by [crag](https://crag.sh). Regenerate: `crag compile --target gemini`

## Project Context

- **Name:** thesis-iot-monitoring
- **Description:** Autonomous IoT Visual Monitoring — STM32 firmware + FastAPI server + Next.js dashboard
- **Stack:** python, typescript, c, docker
- **Runtimes:** node, python

## Rules

### Quality Gates

Run these checks in order before committing any changes:

1. [server (working-directory: server)] `python -m pytest tests/ -v --tb=short`
2. [dashboard (working-directory: dashboard)] `npx biome check --no-errors-on-unmatched --diagnostic-level=error`
3. [dashboard (working-directory: dashboard)] `npx tsc --noEmit`
4. [dashboard (working-directory: dashboard)] `npm run build`
5. [firmware (working-directory: firmware)] `make -j8`

### Security

- No hardcoded secrets — grep for sk_live, AKIA, password= before commit

### Workflow

- Conventional commits (feat:, fix:, docs:, chore:, etc.)
- Commit trailer: Co-Authored-By: Claude <noreply@anthropic.com>
- Run quality gates before committing
- Review security implications of all changes

<!-- crag:auto-end -->
