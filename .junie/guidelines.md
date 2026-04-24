<!-- crag:auto-start -->
# Project Guidelines

> Generated from governance.md by crag — https://crag.sh
> Regenerate: `crag compile --target junie`

## Quality Gates

Run these in order. Stop on first mandatory failure.

### Server (working-directory: server)
- `python -m pytest tests/ -v --tb=short`

### Dashboard (working-directory: dashboard)
- `npx biome check --no-errors-on-unmatched --diagnostic-level=error`
- `npx tsc --noEmit`
- `npm run build`

### Firmware (working-directory: firmware)
- `make -j8`

## Stack

- **Stack:** python, typescript, c, docker
- **Runtimes:** node, python

<!-- crag:auto-end -->
