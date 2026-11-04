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
REASON=""
if [[ "$JOB" == check ]]; then   # frequent check: a cheap local test first, and Claude runs only if something changed (or a full refresh is due)
  REASON="$(/usr/bin/python3 engine/tools/changes.py 2>>"logs/check-errors.log")"; RC=$?
  echo "$(date '+%F %T') $REASON" >> logs/checks.log
  [[ $RC -eq 10 ]] && exit 0
  JOB_KIND=sync
else
  JOB_KIND="$JOB"
fi
bash engine/scheduled/before-run.sh
read -r -d '' PROMPT < <(/usr/bin/python3 - "$JOB_KIND" "$REASON" <<'PY'
import json, sys
p = json.load(open("engine/scheduled/prompts.json"))
kind, reason = sys.argv[1], sys.argv[2]
if kind not in p or kind == "unattended":
    sys.exit(f"unknown job {kind}")
print(p[kind] + (f" Reason for this run: {reason}." if reason else "") + " " + p["unattended"])
PY
)
[[ -n "${PROMPT:-}" ]] || { echo "unknown job $JOB"; exit 2; }
LIMIT="$(/usr/bin/python3 -c 'import json; print(int(json.load(open("config.json")).get("job_time_limit_minutes", 45)) * 60)' 2>/dev/null || echo 2700)"
# One hung run must not hold up every later one. perl's alarm survives exec, and launchd won't start this job again while it's running.
/usr/bin/perl -e 'alarm shift; exec @ARGV or exit 127' "$LIMIT" "$CLAUDE_BIN" -p "$PROMPT" --output-format text > "logs/$JOB-$STAMP.out" 2> "logs/$JOB-$STAMP.err"
code=$?
[[ $code -eq 142 ]] && echo "$(date '+%F %T') $JOB stopped after $((LIMIT / 60)) minutes" >> logs/checks.log
# The changes this run was for count as handled only now that it has finished. If it failed, they wait for the next one.
if [[ $code -eq 0 && ( "$JOB" == check || "$JOB" == sync ) ]]; then
  /usr/bin/python3 engine/tools/changes.py --ack 2>>"logs/check-errors.log"
fi
exit $code
