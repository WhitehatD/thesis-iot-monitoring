#!/bin/bash
# event-queue-sync.sh — SessionStart hook
# Syncs pending events from VPS queue file to MemStack DB.
# If the VPS is unreachable or the queue is empty, exits silently.

PYTHON="/c/Users/alexc/headroom-venv/Scripts/python.exe"
DB_SCRIPT="D:/playground/memstack/db/memstack-db.py"
VPS="root@89.167.11.147"
VPS_QUEUE="/var/lib/memstack/event-queue.jsonl"
LOCAL_QUEUE="/tmp/memstack-event-queue-sync.jsonl"

# Try to fetch the queue file from VPS (5s timeout)
scp -o ConnectTimeout=5 -o BatchMode=yes "$VPS:$VPS_QUEUE" "$LOCAL_QUEUE" 2>/dev/null
if [ $? -ne 0 ] || [ ! -s "$LOCAL_QUEUE" ]; then
    # No queue file or VPS unreachable — nothing to sync
    rm -f "$LOCAL_QUEUE"
    exit 0
fi

# Import events into MemStack
RESULT=$($PYTHON "$DB_SCRIPT" import-events "$LOCAL_QUEUE" 2>/dev/null)
IMPORTED=$(echo "$RESULT" | grep -o '"imported":[0-9]*' | grep -o '[0-9]*')

if [ "${IMPORTED:-0}" -gt 0 ]; then
    # Clear the VPS queue file after successful import
    ssh -o ConnectTimeout=5 -o BatchMode=yes "$VPS" "truncate -s 0 $VPS_QUEUE" 2>/dev/null
    echo "Synced $IMPORTED events from VPS queue"
fi

rm -f "$LOCAL_QUEUE"
exit 0
