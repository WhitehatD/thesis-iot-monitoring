<!-- crag:auto-start -->
# Conventions

> Generated from governance.md by [crag](https://crag.sh). Regenerate: `crag compile --target aider`

## Quality Gates

### Server (working-directory: server)
- `python -m pytest tests/ -v --tb=short`

### Dashboard (working-directory: dashboard)
- `npx biome check --no-errors-on-unmatched --diagnostic-level=error`
- `npx tsc --noEmit`
- `npm run build`

### Firmware (working-directory: firmware)
- `make -j8`

<!-- crag:auto-end -->
