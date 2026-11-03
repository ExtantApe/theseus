#!/bin/bash
# Keeps a Claude Code session running in the Theseus workspace with the iMessage channel, so the user can text themselves.
# Installed by: engine/install.sh --channel   ·   removed by: engine/install.sh --unschedule
# launchd restarts this script if it exits (KeepAlive). It exits on purpose once a day at config.channel.restart_hour,
# so the session picks up new rules.
set -u
WS="${THESEUS_HOME:-$HOME/Theseus}"
CLAUDE_BIN="__CLAUDE_BIN__"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.bun/bin:$HOME/.local/bin:$PATH"
cd "$WS" || exit 1
mkdir -p logs
LOG="logs/channel.log"
note() { echo "$(date '+%F %T') $*" >> "$LOG"; }

read -r PLUGIN RESTART_HOUR ENABLED < <(/usr/bin/python3 - <<'PY'
import json
try:
    c = json.load(open("config.json")).get("channel") or {}
except Exception:
    c = {}
print(c.get("plugin", "imessage@claude-plugins-official"), int(c.get("restart_hour", 4)), "yes" if c.get("enabled") else "no")
PY
)
if [[ "$ENABLED" != "yes" ]]; then note "channel disabled in config.json; sleeping"; sleep 3600; exit 0; fi
command -v bun >/dev/null || { note "Bun is missing (the iMessage plugin needs it): curl -fsSL https://bun.sh/install | bash"; sleep 600; exit 1; }
[[ -x "$CLAUDE_BIN" ]] || { note "claude not found at $CLAUDE_BIN; re-run engine/install.sh --channel"; sleep 600; exit 1; }

note "starting channel session ($PLUGIN)"
# `script` gives the interactive session a terminal it can run in while nobody is watching.
script -q /dev/null "$CLAUDE_BIN" --channels "plugin:$PLUGIN" >> "$LOG" 2>&1 &
PID=$!
STARTED_DAY=$(date +%F)
while kill -0 "$PID" 2>/dev/null; do
  sleep 60
  if [[ "$(date +%F)" != "$STARTED_DAY" && "$(date +%-H)" -ge "$RESTART_HOUR" ]]; then
    note "daily restart (pick up new rules)"; kill "$PID" 2>/dev/null; sleep 5; kill -9 "$PID" 2>/dev/null; break
  fi
done
wait "$PID" 2>/dev/null; note "session ended (code $?); launchd will restart it"
