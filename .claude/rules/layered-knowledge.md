# Layered Knowledge — Confidence-Scored Insights

## Enhanced Verification
When verifying insights, use verify-insight-v2:
```bash
/c/Users/alexc/headroom-venv/Scripts/python.exe D:/playground/memstack/db/memstack-db.py verify-insight-v2 '{"id":<id>,"status":"verified"}'
```

## Principles
Load principles FIRST in pre-start (highest trust):
```bash
/c/Users/alexc/headroom-venv/Scripts/python.exe D:/playground/memstack/db/memstack-db.py get-principles thesis
```

## Auto-Prune
During post-start knowledge capture:
```bash
/c/Users/alexc/headroom-venv/Scripts/python.exe D:/playground/memstack/db/memstack-db.py auto-prune
```

## Ownership
- Verification during pre-start, pruning during post-start
- "distill insights" / "merge insights" = manual distillation
