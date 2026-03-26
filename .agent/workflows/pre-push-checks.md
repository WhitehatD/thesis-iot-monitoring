---
description: Run local lint, type-check, and build checks before committing/pushing to avoid failing CI
---
# Pre-Push Checks

Run these checks **before** `git add / commit / push` to avoid wasting CI minutes.
The checks mirror the **Frontend · Lint & Build** and **Backend · Test** jobs in `.github/workflows/ci-cd.yml`.

---

## 1. Determine which modules changed

Before running anything, figure out what was touched:

- **Frontend changed?** — any file under `frontend/`
- **Backend changed?** — any file under `backend/`

Only run the checks for the modules that actually changed. If both changed, run both.

---

## 2. Frontend checks (if `frontend/` changed)

Run these three commands **in order** from the `frontend/` directory. Stop at the first failure and fix before continuing.

### 2a. Biome lint + format

// turbo
```bash
cd frontend && npx biome check --write --no-errors-on-unmatched --diagnostic-level=error
```

> **`--write`** auto-fixes formatting and safe lint issues. CI runs **without** `--write` so it will reject anything Biome would have changed. Running with `--write` locally means CI will always pass.
>
> If `--write` cannot fix an issue (e.g. a lint error that needs manual intervention), the command will still fail and print the error. Fix it manually.

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
>
> Required env vars are set in `.env.local` or the build will use defaults. CI uses `JAVA_API_URL=http://backend:8080/api/v1`.

---

## 3. Backend checks (if `backend/` changed)

### 3a. Run tests

```bash
cd backend && gradle test --no-daemon
```

> Mirrors CI exactly. All tests must pass.

---

## 4. Commit and push

Only after **all applicable checks pass**:

```powershell
git add -A
git commit --no-gpg-sign -m "<conventional commit message>"
git push origin main
```

> **IMPORTANT (Windows/PowerShell):**
> 
> - Use **separate commands** — do NOT chain with `&&` (that is bash syntax). In PowerShell, `&&` may silently fail or behave unexpectedly.
> - Always use `--no-gpg-sign` to prevent indefinite hangs caused by GPG agent prompts that are invisible in non-interactive terminals.
> - If `git commit` has been running for more than ~10 seconds and produced no error output, it is safe to assume it succeeded and continue with `git push`. Do **not** wait for it — just proceed.


---

## Quick-reference: one-liner (frontend only)

// turbo
```bash
cd frontend && npx biome check --write --no-errors-on-unmatched --diagnostic-level=error && npx tsc --noEmit
```

> This covers the two fast checks. Add `&& npm run build` if you want the full gate.

---

## When to skip

- **Docs-only changes** (README, .md files outside `frontend/` and `backend/`): safe to skip all checks.
- **Infra-only changes** (docker-compose, nginx, deploy scripts, .github/workflows): no local checks needed — CI will do a full rebuild anyway.
