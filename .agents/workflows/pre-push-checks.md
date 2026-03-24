# Pre-Push Checks

Run these checks **before** `git add / commit / push` to avoid wasting CI minutes and breaking the main branch.
The checks mirror the automated jobs in `.github/workflows/ci-cd.yml`. **ALL applications MUST always go through the CI/CD pipeline for final deployment. Local deployments are for testing only.**

---

## 1. Determine which modules changed

Before running anything, figure out what was touched:

- **Frontend changed?** — any file under `frontend/`
- **Backend changed?** — any file under `backend/`
- **Firmware changed?** — any file under `firmware/`

Only run the checks for the modules that actually changed. If multiple changed, run all applicable sections.

---

## 2. Frontend checks (if `frontend/` changed)

Run these three commands **in order** from the `frontend/` directory. Stop at the first failure and fix before continuing.

### 2a. Biome lint + format

// turbo
```bash
cd frontend && npx biome check --write --no-errors-on-unmatched --diagnostic-level=error
```

> **`--write`** auto-fixes formatting and safe lint issues. CI runs **without** `--write` so it will reject anything Biome would have changed. Running with `--write` locally means CI will always pass.

### 2b. TypeScript type-check

// turbo
```bash
cd frontend && npx tsc --noEmit
```

> This catches type errors that Biome does not check. Fix all errors before proceeding.

### 2c. Next.js production build

// turbo
```bash
cd frontend && npm run build
```

> **Only run this if the other two passed.** The build catches runtime-level issues (missing exports, bad imports, SSR errors). This is the slowest check (~30-60 s) so it is last.

---

## 3. Backend checks (if `backend/` changed)

### 3a. Run tests

// turbo
```bash
cd backend && gradle test --no-daemon
```

> Mirrors CI exactly. All tests must pass.

---

## 4. Firmware checks (if `firmware/` changed)

### 4a. Compile Firmware

// turbo
```bash
cd firmware && make -j8
```

> This ensures the firmware compiles without syntax errors or missing dependencies before pushing to CI.

### 4b. Flash Firmware (Optional local check)

// turbo
```powershell
.\scripts\flash.ps1 -FirmwarePath .\firmware\build\thesis-iot-firmware.bin
```

> Flashes the compiled firmware to the connected STM32 board to verify runtime behavior before committing.

---

## 5. Commit and push

Only after **all applicable checks pass**:

// turbo
```bash
git add -A
git commit -m "<conventional commit message>"
git push origin main
```

> **Hanging commits:** `git commit` may appear to hang indefinitely (especially on Windows with GPG signing or credential helpers). If the command has been running for more than ~10 seconds and produced no error output, it is safe to assume it succeeded and continue with `git push`. Do **not** wait for it — just proceed.

---

## When to skip

- **Docs-only changes** (README, .md files outside project folders): safe to skip all checks.
- **Infra-only changes** (docker-compose, nginx, deploy scripts, .github/workflows): no local checks needed — CI will do a full rebuild anyway.
