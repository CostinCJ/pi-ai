#!/usr/bin/env bash
# Weekly offsite backup to Backblaze B2 via Restic.
#
# Prerequisites (one-time manual setup):
#   1. sudo apt install -y restic
#   2. Create a Backblaze B2 bucket named "lache-backups"
#   3. Add these to /home/pi/pi-ai/.env:
#      B2_ACCOUNT_ID=...
#      B2_ACCOUNT_KEY=...
#      RESTIC_PASSWORD=<strong unique value>
#   4. Initialize the repo (one-shot):
#      source /home/pi/pi-ai/.env
#      restic -r b2:lache-backups:/ init
#   5. Add to crontab:
#      (crontab -l; echo "0 5 * * 0 /home/pi/pi-ai/scripts/restic_push.sh") | crontab -
set -euo pipefail
trap '/home/pi/pi-ai/scripts/tg_alert.sh "⚠️ weekly restic backup FAILED — see restic.log" || true' ERR

# Load env (B2_ACCOUNT_ID, B2_ACCOUNT_KEY, RESTIC_PASSWORD)
set -a; source /home/pi/pi-ai/.env; set +a

REPO="b2:lache-backups:/"
LOG="/home/pi/pi-ai/restic.log"

# Dump crontab for backup
mkdir -p /home/pi/backups
crontab -l > /home/pi/backups/crontab.txt 2>/dev/null || true

# Refuse to run without a fresh DB dump — a silent gap here went unnoticed for 2 months once.
if [ -z "$(find /home/pi/backups/pi-ai -name 'memory-*.db.gz' -mtime -2 2>/dev/null)" ]; then
  echo "[$(date -Iseconds)] ABORT: no recent memory.db dump in /home/pi/backups/pi-ai" >> "$LOG"
  false
fi

echo "[$(date -Iseconds)] restic backup start" >> "$LOG"

restic -r "$REPO" backup \
  /home/pi/backups/pi-ai \
  /home/pi/pi-ai/.env \
  /home/pi/pi-ai/persona.py \
  /home/pi/pi-ai/schedule.py \
  /home/pi/pi-ai/piai.service \
  /home/pi/pi-ai/piaibot.service \
  /home/pi/pi-ai/lache-status.service \
  /home/pi/backups/crontab.txt \
  --tag weekly \
  --exclude '__pycache__' \
  >> "$LOG" 2>&1

restic -r "$REPO" forget --keep-weekly 8 --keep-monthly 6 --prune >> "$LOG" 2>&1

echo "[$(date -Iseconds)] restic backup done" >> "$LOG"
