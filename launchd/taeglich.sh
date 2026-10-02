#!/bin/bash
# Täglicher Lauf (launchd): nur Jobs ohne Rückfrage. Log: ~/Library/Logs/ww-gf-cockpit/YYYY-MM-DD.log
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
LOGDIR="$HOME/Library/Logs/ww-gf-cockpit"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/$(date +%F).log"

{
  echo "=== $(date '+%F %T') sevdesk-buchen ==="
  "$PY" "$ROOT/cockpit.py" job sevdesk-buchen --ja
  RC1=$?
  echo "=== $(date '+%F %T') gmi-suche ==="
  "$PY" "$ROOT/cockpit.py" job gmi-suche
  RC2=$?
  echo "=== Ende rc=$RC1/$RC2 ==="
} >> "$LOG" 2>&1

ERG="$(grep -E '^geschrieben:|GESTOPPT|STOPP' "$LOG" | tail -1)"
if [ "$RC1" -ne 0 ] || grep -qE 'GESTOPPT|STOPP|Traceback' "$LOG"; then
  osascript -e "display notification \"Fehler/Stopp – Log: $LOG\" with title \"GF-Cockpit ⚠︎\""
else
  osascript -e "display notification \"${ERG:-Lauf ok}\" with title \"GF-Cockpit\""
fi
