<!-- crag:auto-start -->
---
description: Quality gates and coding standards from governance.md
alwaysApply: true
---

# Quality Gates

> Generated from governance.md by crag — https://crag.sh
> Regenerate: `crag compile --target kiro`

## Server (working-directory: server)
- `python -m pytest tests/ -v --tb=short`

## Dashboard (working-directory: dashboard)
- `npx biome check --no-errors-on-unmatched --diagnostic-level=error`
- `npx tsc --noEmit`
- `npm run build`

## Firmware (working-directory: firmware)
- `make -j8`

<!-- crag:auto-end -->
