---
description: Run local compile, lint, and test checks before committing/pushing to avoid failing CI
---
# Pre-Push Checks

Run these checks **before** `git add / commit / push` to avoid wasting CI minutes. These checks mirror the GitHub Actions strategy precisely, adapting for the STM32 Firmware, FastAPI Server, and Next.js Dashboard.

---

## 1. Determine which modules changed

Before running anything, figure out what was touched:

- **Firmware changed?** — any file under `firmware/`
- **Dashboard changed?** — any file under `dashboard/`
- **Server changed?** — any file under `server/`

Only run the checks for the modules that actually changed. If multiple changed, run all respective blocks.

---

## 2. Firmware checks (if `firmware/` changed)

Run GNU Make to verify the bare-metal C codebase compiles natively without triggering ARM GCC errors or warnings.

// turbo
```
cd firmware && make -j8
```

> **Warning:** Ensure that you don't overlook any missing header path adjustments in the `Makefile` if you added new nested directories inside `Core/Src` or `Core/Inc`.

---

## 3. Dashboard checks (if `dashboard/` changed)

Run these commands **in order** from the `dashboard/` directory. Stop at the first failure and fix before continuing.

### 3a. Biome Lint + Format

// turbo
```
cd dashboard && npx biome check --write --no-errors-on-unmatched --diagnostic-level=error
```

> **`--write`** auto-fixes formatting and safe lint issues. Running this locally ensures the strict CI gate will pass natively.

### 3b. TypeScript Type-Check

// turbo
```
cd dashboard && npx tsc --noEmit
```

> Catch deep typing issues with the MQTT payload hooks (`useMqttImages`) or generic React state logic.

### 3c. Next.js Production Build

// turbo
```
cd dashboard && npm run build
```

> **Only run if the two fast checks passed.** This catches deep SSR mismatches. 

---

## 4. Server checks (if `server/` changed)

Verify the FastAPI application logic via Python's `pytest` utility.

// turbo
```
cd server && python -m pytest
```

> Ensure your virtual environment is activated before running this command, otherwise dependency import errors (e.g., `fastapi`, `paho-mqtt`) will fail the suite immediately.

---

## 5. Commit and push

Only after **all applicable checks pass**:

```
git add -A
git commit -m "<conventional commit message>"
git push origin main
```

> **Hanging commits:** `git commit` may appear to hang indefinitely on Windows with GPG signing or credential wrappers. If the command lacks error output after ~10 seconds, it likely succeeded. Do **not** wait for it endlessly — verify via `git status` and proceed with `git push`.

---

## Quick-Reference: One-Liners

**Full Monorepo Validation:**
// turbo-all
```
cd firmware && make -j8
cd ../dashboard && npx biome check --write --no-errors-on-unmatched --diagnostic-level=error && npx tsc --noEmit && npm run build
cd ../server && python -m pytest
```
