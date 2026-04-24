<!-- crag:auto-start -->
# Copilot Instructions — thesis-iot-monitoring

> Generated from governance.md by [crag](https://crag.sh). Regenerate: `crag compile --target copilot`

Autonomous IoT Visual Monitoring — STM32 firmware + FastAPI server + Next.js dashboard

**Stack:** python, typescript, c, docker

## Runtimes

node, python

## Quality Gates

When you propose changes, the following checks must pass before commit:

- **server (working-directory: server)**: `python -m pytest tests/ -v --tb=short`
- **dashboard (working-directory: dashboard)**: `npx biome check --no-errors-on-unmatched --diagnostic-level=error`
- **dashboard (working-directory: dashboard)**: `npx tsc --noEmit`
- **dashboard (working-directory: dashboard)**: `npm run build`
- **firmware (working-directory: firmware)**: `make -j8`

## Expectations for AI-Assisted Code

1. **Run gates before suggesting a commit.** If you cannot run them (no shell access), explicitly remind the human to run them.
2. **Respect classifications.** `MANDATORY` gates must pass. `OPTIONAL` gates should pass but may be overridden with a note. `ADVISORY` gates are informational only.
3. **Respect workspace paths.** When a gate is scoped to a subdirectory, run it from that directory.
4. **No hardcoded secrets.** - No hardcoded secrets — grep for sk_live, AKIA, password= before commit
5. **Conventional commits** for all changes. Trailer: `Co-Authored-By: Claude <noreply@anthropic.com>`
6. **Conservative changes.** Do not rewrite unrelated files. Do not add new dependencies without explaining why.

## Tool Context

This project uses **crag** (https://crag.sh) as its AI-agent governance layer. The `governance.md` file is the authoritative source. If you have shell access, run `crag check` to verify the infrastructure and `crag diff` to detect drift.

<!-- crag:auto-end -->
