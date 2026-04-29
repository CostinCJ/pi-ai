#!/bin/bash
# Nightly SQLite backup of memory.db with 7-day rotation.
set -euo pipefail

SRC="/home/pi/pi-ai/memory.db"
DEST_DIR="/home/pi/backups/pi-ai"
KEEP=7

mkdir -p "$DEST_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
DEST="$DEST_DIR/memory-$TS.db"

# Use sqlite3 .backup for an online consistent snapshot.
sqlite3 "$SRC" ".backup '$DEST'"
gzip -f "$DEST"

# Rotate: keep the newest $KEEP files.
ls -1t "$DEST_DIR"/memory-*.db.gz | tail -n +$((KEEP+1)) | xargs -r rm -f

echo "[$(date)] backup ok -> $DEST.gz"
