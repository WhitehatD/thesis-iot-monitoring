# Token Ledger — Cost Tracking

After completing a task (during post-start knowledge capture), log token usage:

```bash
/c/Users/alexc/headroom-venv/Scripts/python.exe D:/playground/memstack/db/memstack-db.py add-token-record '{"project":"thesis","session_id":"<CLAUDE_SESSION_ID>","task_summary":"<one-line>","tokens_in":<est_in>,"tokens_out":<est_out>,"model":"<model>"}'
```

When the user asks "cost report" or "token stats":
```bash
/c/Users/alexc/headroom-venv/Scripts/python.exe D:/playground/memstack/db/memstack-db.py cost-report --project thesis --days 7
```

## Ownership
- "cost" / "tokens" / "spending" = Token Ledger
