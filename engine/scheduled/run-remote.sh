#!/bin/bash
# Keeps Claude Code's Remote Control server running for the Theseus workspace, so the Mac always shows up in the Claude app's
# Code tab and a fresh Theseus session can be started from your phone (or claude.ai/code) at any time.
# Installed by: engine/install.sh --schedule (when config.remote_control.enabled) or --remote · removed by: --unschedule
#
# config.remote_control.host:
#   "terminal" (default): the server runs in a Terminal window, and this job is only a watchdog that reopens that window if it's
#              closed. Terminal is then the app in charge, so sessions get Terminal's permissions (Full Disk Access, Calendar,
#              Reminders, Notes), exactly like running `claude` from the command line.
#   "background": the server runs directly under launchd. No window, but macOS checks Claude Code's own permissions instead.
#   "app": Theseus.app hosts it (planned); this job then does nothing.
set -u
WS="${THESEUS_HOME:-$HOME/Theseus}"
CLAUDE_BIN="__CLAUDE_BIN__"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$PATH"
cd "$WS" || exit 1
mkdir -p logs cache bin
LOG="logs/remote-control.log"
note() { echo "$(date '+%F %T') $*" >> "$LOG"; }

read -r ENABLED NAME HOST < <(/usr/bin/python3 - <<'PY'
import json
try:
    r = json.load(open("config.json")).get("remote_control") or {}
except Exception:
    r = {}
print("yes" if r.get("enabled", True) else "no", r.get("name", "Theseus").replace(" ", "_"), r.get("host", "terminal"))
PY
)
NAME="${NAME//_/ }"
if [[ "$ENABLED" != "yes" || "$HOST" == "app" ]]; then note "remote control: enabled=$ENABLED host=$HOST; nothing to do here"; sleep 3600; exit 0; fi
[[ -x "$CLAUDE_BIN" ]] || { note "claude not found at $CLAUDE_BIN; re-run engine/install.sh --remote"; sleep 600; exit 1; }

if [[ "$HOST" == "terminal" ]]; then
  CMDF="$WS/bin/Theseus Remote.command"
  PIDF="$WS/cache/remote-terminal.pid"
  cat > "$CMDF" <<CMD
#!/bin/bash
# Opened by the Theseus watchdog. Keep this window open (minimizing is fine): it's how your phone reaches Theseus.
cd "$WS" || exit 1
echo \$\$ > "$PIDF"
printf '\\033]0;Theseus · Remote Control\\007'
echo "Theseus Remote Control: keep this window open (minimize is fine). If it gets closed, it reopens within a minute. To turn phone access off, set remote_control.enabled to false in config.json."
wait_s=5
while true; do
  started=\$(date +%s)
  "$CLAUDE_BIN" remote-control --name "$NAME"
  if (( \$(date +%s) - started < 20 )); then
    # Quit right away: usually another copy (or the Claude desktop app) is already serving this folder. Back off instead of spamming.
    wait_s=\$(( wait_s < 60 ? 60 : (wait_s >= 300 ? 300 : wait_s * 2) ))
    echo "\$(date '+%F %T') Remote Control couldn't start (see the line above). Retrying in \$wait_s s." | tee -a "$WS/$LOG"
  else
    wait_s=5
    echo "\$(date '+%F %T') Remote Control stopped; restarting in 5 s." | tee -a "$WS/$LOG"
  fi
  sleep "\$wait_s"
done
CMD
  chmod +x "$CMDF"
  note "watchdog started (host: terminal)"
  trap 'note "watchdog stopping (the Terminal window keeps running)"; exit 0' TERM INT HUP
  while true; do
    alive=no
    if [[ -f "$PIDF" ]] && kill -0 "$(cat "$PIDF" 2>/dev/null)" 2>/dev/null; then alive=yes; fi
    if [[ $alive == no ]]; then
      # Stop a server left over from the old background mode, then open the Terminal window.
      pkill -f "script -q /dev/null .*remote-control --name $NAME" 2>/dev/null
      note "opening the Terminal window for Remote Control"
      open -g -a Terminal "$CMDF"
      sleep 30
    fi
    sleep 30
  done
fi

# ---- host: background ---------------------------------------------------------------------------------------------------
if pgrep -f "remote-control --name $NAME" >/dev/null; then
  note "stopping a leftover Remote Control server for \"$NAME\""
  pkill -f "remote-control --name $NAME"; sleep 3; pkill -9 -f "remote-control --name $NAME" 2>/dev/null
fi
/usr/bin/python3 engine/tools/imsg.py --fresh doctor >/dev/null 2>&1 || note "couldn't refresh the texts copy"
FIFO="cache/remote-control.stdin"; rm -f "$FIFO"; mkfifo "$FIFO"; exec 3<>"$FIFO"
note "starting Remote Control server \"$NAME\" in $WS (host: background)"
script -q /dev/null "$CLAUDE_BIN" remote-control --name "$NAME" < "$FIFO" >> "$LOG" 2>&1 &
CHILD=$!
cleanup() { kill -TERM "$CHILD" 2>/dev/null; pkill -f "remote-control --name $NAME" 2>/dev/null; exec 3>&-; rm -f "$FIFO"; }
trap 'note "stopping (restart requested)"; cleanup; exit 0' TERM INT HUP
wait "$CHILD"; code=$?
cleanup
note "Remote Control server exited (code $code); launchd will restart it"
