#!/bin/bash
# Theseus installer for macOS. Safe to re-run; it never overwrites your personal files.
#   ./install.sh               create or update your workspace (default ~/Theseus), build tools, check access
#   ./install.sh --update      update the engine only (rules, tools, commands), no checks
#                              install and --update stop if pending local changes aren't in this source; add --force to overwrite them
#   ./install.sh --check       just run the access checks
#   ./install.sh --schedule    install the nightly and morning jobs (and hourly sync if enabled)
#   ./install.sh --unschedule  remove the scheduled jobs
# Workspace location: set THESEUS_HOME to change it.
set -e
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="${THESEUS_HOME:-$HOME/Theseus}"
MODE=install; FORCE=0
for arg in "$@"; do                      # flags in any order: --update --force == --force --update
  if [[ "$arg" == "--force" ]]; then FORCE=1; else MODE="$arg"; fi
done
ON_MAC=1; [[ "$(uname)" == "Darwin" ]] || ON_MAC=0
if [[ $ON_MAC == 0 && -z "${THESEUS_SKIP_MAC:-}" ]]; then echo "Theseus runs on macOS only."; exit 1; fi

uid() { id -u; }
if [[ "$MODE" == "--unschedule" ]]; then
  for j in morning nightly sync check; do
    p="$HOME/Library/LaunchAgents/com.theseus.$j.plist"
    launchctl bootout "gui/$(uid)" "$p" 2>/dev/null || true; rm -f "$p"
  done
  echo "Scheduled jobs removed."; exit 0
fi

copy_engine() {
  if [[ "$SRC" != "$WS" && $FORCE == 0 ]]; then
    python3 "$SRC/engine/tools/local_changes.py" guard --src "$SRC" --home "$WS"
  fi
  echo "== Engine → $WS/engine"
  mkdir -p "$WS"
  if [[ "$SRC" != "$WS" ]]; then
    rm -rf "$WS/engine.new" && cp -R "$SRC/engine" "$WS/engine.new"
    rm -rf "$WS/engine" && mv "$WS/engine.new" "$WS/engine"
    mkdir -p "$WS/docs" && cp -R "$SRC/docs/." "$WS/docs/"
  fi
  mkdir -p "$WS/.claude/commands" "$WS/bin" "$WS/cache" "$WS/exports" "$WS/briefings" "$WS/logs" \
           "$WS/data/drafts" "$WS/data/archive" "$WS/data/prep"
  cp "$WS/engine/workflows/"*.md "$WS/.claude/commands/"          # engine-managed
  cp "$WS/engine/templates/settings.json" "$WS/.claude/settings.json"   # engine-managed; put overrides in settings.local.json
  for f in "$WS/engine/templates/data/"*; do                          # personal: only create if missing
    [[ -e "$WS/data/$(basename "$f")" ]] || cp "$f" "$WS/data/"
  done
  [[ -e "$WS/config.json" ]] || cp "$WS/engine/templates/config.json" "$WS/config.json"
  [[ -e "$WS/profile.md" ]]  || cp "$WS/engine/templates/profile.md"  "$WS/profile.md"
  [[ -e "$WS/CLAUDE.md" ]]   || cp "$WS/engine/templates/CLAUDE.md"   "$WS/CLAUDE.md"
  printf 'cache/\nexports/\nlogs/\nbriefings/\ndata/\nprofile.md\nconfig.json\nbin/\n' > "$WS/.gitignore"
  chmod +x "$WS/engine/tools/"*.py "$WS/engine/scheduled/"*.sh 2>/dev/null || true
}

build_ek() {
  [[ $ON_MAC == 1 ]] || { echo "(skipping Swift build: not macOS)"; return; }
  echo "== Building Calendar/Reminders bridge"
  command -v swiftc >/dev/null || { echo "swiftc missing → run: xcode-select --install"; exit 1; }
  swiftc -O "$WS/engine/tools/ek.swift" -o "$WS/bin/ek" && echo "Built bin/ek"
}

enabled() { python3 -c "import json,sys;c=json.load(open('$WS/config.json'));v=c['integrations'].get('$1') if '$1' in c.get('integrations',{}) else c.get('$1');print('yes' if (v is True or v=='$2') else 'no')"; }

checks() {
  [[ $ON_MAC == 1 ]] || { echo "(skipping access checks: not macOS)"; return; }
  cd "$WS"; local fail=0
  echo "== Calendar + Reminders (click Allow)"; bin/ek access || fail=1
  if [[ $(enabled texts) == yes ]]; then echo "== Messages + Contacts"; python3 engine/tools/imsg.py doctor || fail=1; fi
  if [[ $(enabled email_source apple_mail) == yes ]]; then echo "== Apple Mail"; python3 engine/tools/mail.py doctor || fail=1; fi
  if [[ $(enabled notes) == yes ]]; then echo "== Notes (click OK on the Automation prompt)"; python3 engine/tools/notes.py inbox >/dev/null && echo "Notes OK" || fail=1; fi
  if [[ $(enabled iphone_alarms) == yes ]]; then echo "== iPhone alarms"; python3 engine/tools/alarms.py --text || true; fi
  if [[ $fail == 1 ]]; then
    echo; echo ">>> Something needs permission. See docs/SETUP.md §1 (Full Disk Access for your terminal app and /bin/bash), then run ./install.sh --check"
    open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles" 2>/dev/null || true
    return 1
  fi
  echo "✅ All enabled services reachable."
}

schedule() {
  [[ $ON_MAC == 1 ]] || { echo "Scheduling needs macOS."; exit 1; }
  CLAUDE_BIN="$(command -v claude || true)"; [[ -n "$CLAUDE_BIN" ]] || { echo "Can't find 'claude' on PATH"; exit 1; }
  sed -e "s#__CLAUDE_BIN__#$CLAUDE_BIN#" "$WS/engine/scheduled/run-job.sh" > "$WS/bin/run-job.sh" && chmod +x "$WS/bin/run-job.sh"
  python3 - "$WS" <<'PY'
import json, sys, plistlib, pathlib, subprocess, os
ws = pathlib.Path(sys.argv[1]); cfg = json.loads((ws/"config.json").read_text())
la = pathlib.Path.home()/"Library/LaunchAgents"; la.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ws/"engine/tools"))
import schedule as sched
jobs = sched.runs_for_launchd(cfg)            # per-weekday morning/nightly runs from config.json → schedule
chk = cfg.get("checks") or {}
interval = None
if chk.get("enabled"):
    interval = max(1, int(chk.get("every_minutes", 5))) * 60   # the cheap local test; changes.py enforces awake hours + cooldown
    jobs["check"] = None
for name, when in jobs.items():
    label = f"com.theseus.{name}"; p = la/f"{label}.plist"
    timing = {"StartInterval": interval} if when is None else {"StartCalendarInterval": when}
    plistlib.dump({"Label": label, "ProgramArguments": ["/bin/bash", str(ws/"bin/run-job.sh"), name],
                   "EnvironmentVariables": {"THESEUS_HOME": str(ws)}, **timing,
                   "StandardOutPath": str(ws/f"logs/launchd-{name}.log"),
                   "StandardErrorPath": str(ws/f"logs/launchd-{name}.log")}, p.open("wb"))
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(p)], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(p)], check=True)
    print(f"Scheduled {name}: " + ((f"{when[0]['Hour']:02d}:{when[0]['Minute']:02d} daily" if len(when) == 1 else "varies by day: " + ", ".join(f"{'Sun Mon Tue Wed Thu Fri Sat'.split()[e['Weekday']]} {e['Hour']:02d}:{e['Minute']:02d}" for e in when)) if when else
          f"local check every {interval//60} min; Claude at most every {chk.get('min_minutes_between_claude_runs', 15)} min, only when something changed"))
PY
  echo "Keep the Mac awake for these (System Settings → Energy, or: sudo pmset repeat wakeorpoweron MTWRFSU <5 min before morning_time>)."
}

case "$MODE" in
  install)    copy_engine; build_ek; checks || true
              echo; echo "✅ Theseus installed at $WS"
              echo "Next: cd \"$WS\" && claude   then run /theseus:setup (plugin) or follow docs/SETUP.md, then /migrate" ;;
  --update)   copy_engine; build_ek; echo "✅ Engine updated. Your profile, config and data were not touched." ;;
  --check)    checks ;;
  --schedule) schedule ;;
  *) echo "Unknown option $MODE"; exit 2 ;;
esac
