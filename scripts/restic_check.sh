#!/usr/bin/env bash
# Monthly restic repository integrity check. Alerts via Telegram on failure.
set -uo pipefail
set -a; source /home/pi/pi-ai/.env; set +a

REPO="b2:lache-backups:/"
LOG="/home/pi/pi-ai/restic.log"

echo "[$(date -Iseconds)] restic check start" >> "$LOG"
if restic -r "$REPO" check >> "$LOG" 2>&1; then
  echo "[$(date -Iseconds)] restic check ok" >> "$LOG"
else
  echo "[$(date -Iseconds)] restic check FAILED" >> "$LOG"
  /home/pi/pi-ai/scripts/tg_alert.sh "⚠️ restic check FAILED — repo integrity problem, see restic.log" || true
fi
