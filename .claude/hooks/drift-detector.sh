#!/bin/bash
# Drift detector for thesis-iot-monitoring.
# Verifies critical project files exist. Fails softly — exits 0 always.
WARNINGS=""
DIR="${CLAUDE_PROJECT_DIR:-.}"

# Critical project files (must exist)
for path in \
  "README.md" \
  ".claude/governance.md" \
  "server/pyproject.toml" \
  "dashboard/package.json" \
  "firmware/Makefile" \
  "docker-compose.yml" \
  "mosquitto/mosquitto.conf"; do
  [ ! -f "$DIR/$path" ] && WARNINGS="${WARNINGS}  DRIFT: $path not found\n"
done

[ -n "$WARNINGS" ] && echo -e "DRIFT DETECTED:\n$WARNINGS"
exit 0
