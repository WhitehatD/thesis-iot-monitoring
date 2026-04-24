<!-- crag:auto-start -->
# Amazon Q Rules — thesis-iot-monitoring

> Generated from governance.md by [crag](https://crag.sh). Regenerate: `crag compile --target amazonq`

## About

Autonomous IoT Visual Monitoring — STM32 firmware + FastAPI server + Next.js dashboard

**Stack:** python, typescript, c, docker

**Runtimes detected:** node, python

## How Amazon Q Should Behave on This Project

### Code Generation

1. **Run governance gates before suggesting commits.** The gates below define the quality bar.
2. **Respect classifications:** MANDATORY (default) blocks on failure; OPTIONAL warns; ADVISORY is informational only.
3. **Respect scopes:** Path-scoped gates run from that directory. Conditional gates skip when their file does not exist.
4. **No secrets.** - No hardcoded secrets — grep for sk_live, AKIA, password= before commit
5. **Minimal diffs.** Prefer editing existing code over creating new files. Do not refactor unrelated areas.

### Quality Gates

- `python -m pytest tests/ -v --tb=short`
- `npx biome check --no-errors-on-unmatched --diagnostic-level=error`
- `npx tsc --noEmit`
- `npm run build`
- `make -j8`

### Commit Style

Use conventional commits: `feat(scope): description`, `fix(scope): description`, `docs: description`, etc.
Commit trailer: Co-Authored-By: Claude <noreply@anthropic.com>

### Boundaries

- All file operations must stay within this repository.
- No destructive shell commands (rm -rf above repo root, DROP TABLE without confirmation, force-push to main).
- No new dependencies without an explicit reason.

## Authoritative Source

When these instructions seem to conflict with something in the repo, **`.claude/governance.md` is the source of truth**. This file is a compiled view.

---

**Tool:** crag — https://crag.sh

<!-- crag:auto-end -->
