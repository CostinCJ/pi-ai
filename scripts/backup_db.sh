#!/bin/bash
# Nightly SQLite backup of memory.db with 7-day rotation.
set -euo pipefail
trap '/home/pi/pi-ai/scripts/tg_alert.sh "⚠️ nightly memory.db backup FAILED — see backup_db.log" || true' ERR

SRC="/home/pi/pi-ai/memory.db"
DEST_DIR="/home/pi/backups/pi-ai"
KEEP=7

mkdir -p "$DEST_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
DEST="$DEST_DIR/memory-$TS.db"

# Use sqlite3 online backup API for a consistent snapshot (no sqlite3 CLI on this box).
/home/pi/pi-ai/venv/bin/python - "$SRC" "$DEST" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close(); src.close()
PY
gzip -f "$DEST"

# Rotate: keep the newest $KEEP files.
ls -1t "$DEST_DIR"/memory-*.db.gz | tail -n +$((KEEP+1)) | xargs -r rm -f

echo "[$(date)] backup ok -> $DEST.gz"
