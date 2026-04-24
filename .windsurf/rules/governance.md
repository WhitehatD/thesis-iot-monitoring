---
trigger: always_on
description: Governance rules for thesis-iot-monitoring — compiled from governance.md by crag
---

# Windsurf Rules — thesis-iot-monitoring

Generated from governance.md by [crag](https://crag.sh). Regenerate: `crag compile --target windsurf`

## Project

Autonomous IoT Visual Monitoring — STM32 firmware + FastAPI server + Next.js dashboard

**Stack:** python, typescript, c, docker

## Runtimes

node, python

## Cascade Behavior

When Windsurf's Cascade agent operates on this project:

- **Always read governance.md first.** It is the single source of truth for quality gates and policies.
- **Run all mandatory gates before proposing changes.** Stop on first failure.
- **Respect classifications.** OPTIONAL gates warn but don't block. ADVISORY gates are informational.
- **Respect path scopes.** Gates with a `path:` annotation must run from that directory.
- **No destructive commands.** Never run rm -rf, dd, DROP TABLE, force-push to main, curl|bash, docker system prune.
- - No hardcoded secrets — grep for sk_live, AKIA, password= before commit
- **Conventional commits.** Every commit must follow `<type>(<scope>): <description>`.
- **Commit trailer:** Co-Authored-By: Claude <noreply@anthropic.com>

## Quality Gates (run in order)

1. `python -m pytest tests/ -v --tb=short`
2. `npx biome check --no-errors-on-unmatched --diagnostic-level=error`
3. `npx tsc --noEmit`
4. `npm run build`
5. `make -j8`

## Rules of Engagement

1. **Minimal changes.** Don't rewrite files that weren't asked to change.
2. **No new dependencies** without explicit approval.
3. **Prefer editing** existing files over creating new ones.
4. **Always explain** non-obvious changes in commit messages.
5. **Ask before** destructive operations (delete, rename, migrate schema).

---

**Tool:** crag — https://crag.sh
