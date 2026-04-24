#!/bin/bash
MSDB="/c/Users/alexc/headroom-venv/Scripts/python.exe D:/playground/memstack/db/memstack-db.py"
echo "=== POST-COMPACTION RECOVERY ==="
git log --oneline -3 2>/dev/null
$MSDB get-context infra 2>/dev/null | head -20
$MSDB get-sessions infra --limit 1 2>/dev/null | head -20
$MSDB get-insights infra 2>/dev/null | head -15
echo "=== Context recovered ==="
exit 0
