#!/bin/bash
# Install/refresh pi-ai cron jobs idempotently.
set -euo pipefail

PI_AI_DIR="/home/pi/pi-ai"
PY="$PI_AI_DIR/venv/bin/python"

# Strip any prior pi-ai cron block, then append a fresh one.
TMP="$(mktemp)"
crontab -l 2>/dev/null | sed '/# >>> pi-ai >>>/,/# <<< pi-ai <<</d' > "$TMP" || true

cat >> "$TMP" <<EOF
# >>> pi-ai >>>
0 3 * * 0 $PY $PI_AI_DIR/reflection.py >> $PI_AI_DIR/reflection.log 2>&1
0 4 * * * $PY $PI_AI_DIR/consolidation.py >> $PI_AI_DIR/consolidation.log 2>&1
30 4 * * * $PI_AI_DIR/scripts/backup_db.sh >> $PI_AI_DIR/backup.log 2>&1
# <<< pi-ai <<<
EOF

crontab "$TMP"
rm -f "$TMP"
echo "cron installed:"
crontab -l | sed -n '/pi-ai/,/<<< pi-ai/p'
