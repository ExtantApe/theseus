#!/bin/bash
# Keeps Claude Code's Remote Control server running in the Theseus workspace, so the Mac always shows up in the Claude app's
# Code tab and a fresh Theseus session can be started from your phone (or claude.ai/code) at any time.
# Installed by: engine/install.sh --schedule (when config.remote_control.enabled) or --remote · removed by: --unschedule
# launchd restarts this if it exits (KeepAlive), including after a reboot or crash.
set -u
WS="${THESEUS_HOME:-$HOME/Theseus}"
CLAUDE_BIN="__CLAUDE_BIN__"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$PATH"
cd "$WS" || exit 1
mkdir -p logs
LOG="logs/remote-control.log"
note() { echo "$(date '+%F %T') $*" >> "$LOG"; }

read -r ENABLED NAME < <(/usr/bin/python3 - <<'PY'
import json
try:
    r = json.load(open("config.json")).get("remote_control") or {}
except Exception:
    r = {}
print("yes" if r.get("enabled", True) else "no", r.get("name", "Theseus"))
PY
)
if [[ "$ENABLED" != "yes" ]]; then note "remote control disabled in config.json; sleeping"; sleep 3600; exit 0; fi
[[ -x "$CLAUDE_BIN" ]] || { note "claude not found at $CLAUDE_BIN; re-run engine/install.sh --schedule"; sleep 600; exit 1; }

note "starting Remote Control server \"$NAME\" in $WS"
# `script` gives the server a terminal to run in while nobody is watching.
script -q /dev/null "$CLAUDE_BIN" remote-control --name "$NAME" >> "$LOG" 2>&1
note "Remote Control server exited (code $?); launchd will restart it"
