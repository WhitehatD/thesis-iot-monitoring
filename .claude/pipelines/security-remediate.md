---
name: security-remediate
description: End-to-end security issue resolution — scan, assess, fix, verify, report.
trigger: manual
---

# Security Remediation Pipeline

Trigger: manual invocation or scheduled security scan.

## Stage 1: Scan

**Agent**: security-reviewer (worktree isolation, Opus)
**On failure**: stop

Prompt:
```
Review the current branch for security issues:
1. Leaked secrets (API keys, tokens, passwords, private keys)
2. Credentials outside docs/credentials.md
3. New IPs or hostnames without context
4. SSH private key material
5. Database connection strings with passwords

Report each finding with severity, file, line, and description.
```

## Stage 2: Assess

**Agent**: none (inline — orchestrator filters and prioritizes)
**On failure**: skip

From the scan results:

{{previous_output}}

Filter and classify:
- **CRITICAL/HIGH**: must fix before merge
- **MEDIUM**: should fix, can defer with justification
- **LOW/INFO**: log for awareness, no action needed
- **FALSE POSITIVE**: explain why and exclude

Output: prioritized findings list with action plan.

## Stage 3: Fix

**Agent**: remediation-agent (worktree isolation, Sonnet)
**On failure**: skip (partial fixes are acceptable)

Prompt:
```
Apply fixes for the following HIGH+ security findings:

{{previous_output}}

For each finding:
- Leaked secrets: extract to env vars, add to .env.example
- Credentials in wrong location: move reference to docs/credentials.md
- Insecure patterns: apply secure alternative

Skip LOW/INFO findings. Report what was fixed and what was skipped.
```

## Stage 4: Verify

**Agent**: test-runner (worktree isolation, Sonnet)
**On failure**: stop

Prompt:
```
Run governance gates after security fixes were applied.
Focus on the security gate — verify no secrets remain in staged files.

{{previous_output}}
```

## Stage 5: Report

**Agent**: none (inline — orchestrator compiles the report)
**On failure**: skip

Compile a summary:
```
Security Remediation Report
===========================
Scan date: <date>
Findings: <total> (CRITICAL: N, HIGH: N, MEDIUM: N, LOW: N)
Fixed: <count>
Remaining: <count> (with justification)
Gates: PASSED/FAILED

Details:
- [FIXED] <finding> → <what was done>
- [DEFERRED] <finding> → <why>
- [FALSE POSITIVE] <finding> → <explanation>
```
