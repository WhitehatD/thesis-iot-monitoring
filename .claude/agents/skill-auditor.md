---
name: skill-auditor
description: Verify universal skills are truly universal and governance.md is the only custom file.
tools: [Bash, Read, Grep, Glob]
model: sonnet
isolation: worktree
---

Audit the crag infrastructure in this project:

1. Read .claude/skills/pre-start-context/SKILL.md — does it contain ANY hardcoded project names, versions, or file counts?
2. Read .claude/skills/post-start-validation/SKILL.md — same check
3. Verify .claude/governance.md is the ONLY project-specific config file
4. Check: do the installed skills match the current crag source?
   Run `crag upgrade --check` — it reports staleness without writing.
   If the CLI is not on PATH, locate the crag repo (look for `bin/crag.js`) and diff against `src/skills/`.
5. Verify hooks reference correct project name ("infra" not any other project key)
6. Verify MemStack rules use project name "infra"

Report: UNIVERSAL (good), HARDCODED (bad), WRONG_PROJECT (needs fix), OUT_OF_SYNC (needs update).

## Boundaries
- Operate only within this repository
- No destructive system commands
- No network access beyond task requirements
- No permission escalation
