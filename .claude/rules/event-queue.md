# Event Queue — Pending Events from Between Sessions

During pre-start context loading (Step 1, after MemStack load), check for pending events:

```bash
/c/Users/alexc/headroom-venv/Scripts/python.exe D:/playground/memstack/db/memstack-db.py get-events --project thesis --limit 10
```

If events exist, present them grouped by priority. For each, offer to claim, defer, or expire.
After task completion, mark claimed events as completed.

## Ownership
- "pending events" / "what happened" / "queue" = Event Queue
