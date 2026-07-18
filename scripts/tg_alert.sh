#!/usr/bin/env bash
# Send a Telegram message to the owner. Usage: tg_alert.sh "message"
set -euo pipefail
set -a; source /home/pi/pi-ai/.env; set +a
curl -fsS -m 10 "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
  -d chat_id="${CHAT_ID}" \
  --data-urlencode text="$1" > /dev/null
