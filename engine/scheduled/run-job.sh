#!/bin/bash
# Runs a Claude Code job headlessly. Usage: run-job.sh morning|nightly|sync|check
# Installed by setup.sh (which fills in CLAUDE_BIN). Logs go to <workspace>/logs/.
set -u
JOB="${1:-morning}"
WS="${THESEUS_HOME:-$HOME/Theseus}"
CLAUDE_BIN="__CLAUDE_BIN__"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$PATH"
cd "$WS" || exit 1
# When Theseus.app hosts the schedule, it runs these jobs itself (with the app's permissions); the old launchd jobs stand down.
if /usr/bin/python3 -c 'import json,sys; sys.exit(0 if json.load(open("config.json")).get("scheduler_host")=="app" else 1)' 2>/dev/null; then
  exit 0
fi
mkdir -p logs briefings
STAMP="$(date +%Y-%m-%d_%H%M)"
# Make sure helper apps are running (quietly, in the background). config.json → "ensure_apps": ["Claude", "Mail"]
# Apple Mail is added automatically when email_source is "apple_mail".
/usr/bin/python3 - "$WS/config.json" <<'PY' | while IFS= read -r app; do
import json, sys
try:
    c = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
apps = list(c.get("ensure_apps", []))
if c.get("email_source") == "apple_mail" and "Mail" not in apps:
    apps.append("Mail")
print("\n".join(apps))
PY
  [[ -z "$app" ]] && continue
  if ! pgrep -xq "$app"; then
    open -g -j -a "$app" 2>/dev/null && echo "$(date) opened $app" >> logs/apps.log
    sleep 20   # give it a moment to launch (e.g. Mail fetching new mail)
  fi
done
case "$JOB" in
  morning) PROMPT="Run the morning briefing exactly as defined in engine/workflows/morning.md. This is an unattended scheduled run." ;;
  nightly) PROMPT="Run the nightly prep exactly as defined in engine/workflows/nightly.md. This is an unattended scheduled run." ;;
  sync)    PROMPT="Run the quiet sync exactly as defined in engine/workflows/sync.md. This is an unattended scheduled run." ;;
  check)   # frequent check: a cheap local test first, and Claude runs only if something changed (or a full refresh is due)
           REASON="$(/usr/bin/python3 engine/tools/changes.py 2>>"logs/check-errors.log")"; RC=$?
           echo "$(date '+%F %T') $REASON" >> logs/checks.log
           [[ $RC -eq 10 ]] && exit 0
           PROMPT="Run the quiet sync exactly as defined in engine/workflows/sync.md. Reason for this run: $REASON. This is an unattended scheduled run." ;;
  *) echo "unknown job $JOB"; exit 2 ;;
esac
"$CLAUDE_BIN" -p "$PROMPT" --output-format text > "logs/$JOB-$STAMP.out" 2> "logs/$JOB-$STAMP.err"
code=$?
# keep logs for 30 days
find logs -type f -mtime +30 -delete 2>/dev/null
exit $code
