#!/bin/bash
# Theseus installer for macOS. Safe to re-run; it never overwrites your personal files.
#   ./install.sh               create or update your workspace (default ~/Theseus), build tools, check access
#   ./install.sh --update      update the engine only (rules, tools, commands), no checks
#                              install and --update stop if pending local changes aren't in this source; add --force to overwrite them
#   ./install.sh --check       just run the access checks
#   ./install.sh --schedule    install the nightly and morning jobs (and hourly sync if enabled)
#   ./install.sh --remote      keep a Remote Control server running (reach Theseus from the Claude app; part of --schedule by default)
#   ./install.sh --channel     keep an iMessage channel session running (text Theseus from your phone; opt-in)
#   ./install.sh --grant       ask macOS for Calendar/Reminders/Notes access for the background jobs (also part of --schedule)
#   ./install.sh --unschedule  remove the scheduled jobs (and the channel session)
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
  for j in morning nightly sync check channel remote watchdog wall; do
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
    if [[ -d "$SRC/apps/wall/pi" ]]; then   # what `theseus wall setup` hands to a Pi
      rm -rf "$WS/wall" && mkdir -p "$WS/wall" && cp -R "$SRC/apps/wall/display" "$SRC/apps/wall/pi" "$WS/wall/"
    fi
  fi
  mkdir -p "$WS/.claude/commands" "$WS/bin" "$WS/cache" "$WS/exports" "$WS/briefings" "$WS/logs" \
           "$WS/data/drafts" "$WS/data/archive" "$WS/data/prep"
  for old in status review voice thread-report text-research sync-check compliance-check; do rm -f "$WS/.claude/commands/$old.md"; done  # renamed
  cp "$WS/engine/workflows/"*.md "$WS/.claude/commands/"          # engine-managed
  cp "$WS/engine/templates/settings.json" "$WS/.claude/settings.json"   # engine-managed; put overrides in settings.local.json
  for f in "$WS/engine/templates/data/"*; do                          # personal: only create if missing
    [[ -e "$WS/data/$(basename "$f")" ]] || cp "$f" "$WS/data/"
  done
  [[ -e "$WS/config.json" ]] || cp "$WS/engine/templates/config.json" "$WS/config.json"
  [[ -e "$WS/profile.md" ]]  || cp "$WS/engine/templates/profile.md"  "$WS/profile.md"
  [[ -e "$WS/CLAUDE.md" ]]   || cp "$WS/engine/templates/CLAUDE.md"   "$WS/CLAUDE.md"
  printf 'cache/\nexports/\nlogs/\nbriefings/\ndata/\nprofile.md\nconfig.json\nbin/\nwall/\n.wall/\n' > "$WS/.gitignore"
  chmod +x "$WS/engine/tools/"*.py "$WS/engine/scheduled/"*.sh "$WS/engine/bin/"* 2>/dev/null || true
  # Theseus.app starts from Finder without your shell's THESEUS_HOME, so this is how it finds a workspace that isn't ~/Theseus.
  mkdir -p "$HOME/Library/Application Support/Theseus" && printf '%s\n' "$WS" > "$HOME/Library/Application Support/Theseus/workspace"
}

link_command() {
  # So `theseus` works from anywhere, the way `ariadne` does. It never replaces a command that isn't this workspace's own.
  local target="$WS/engine/bin/theseus" link="$HOME/.local/bin/theseus"
  mkdir -p "$HOME/.local/bin"
  if [[ -e "$link" || -L "$link" ]] && [[ "$(readlink "$link")" != "$target" ]]; then
    echo "⚠️  Left $link as it is, because it isn't this workspace's. To use this one, point it at $target"
    return 0
  fi
  ln -sf "$target" "$link"
  case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "⚠️  To run theseus from anywhere, add ~/.local/bin to your PATH." ;; esac
}

refresh_bin() {
  # The scripts launchd runs live in bin/ with Claude's path filled in. Without this, an update wouldn't reach them.
  local CLAUDE_BIN; CLAUDE_BIN="$(command -v claude || true)"; [[ -n "$CLAUDE_BIN" ]] || return 0
  for f in run-job run-remote run-channel; do
    if [[ -f "$WS/bin/$f.sh" ]]; then
      sed -e "s#__CLAUDE_BIN__#$CLAUDE_BIN#" "$WS/engine/scheduled/$f.sh" > "$WS/bin/$f.sh" && chmod +x "$WS/bin/$f.sh"
    fi
  done
}

migrate_connectors() {
  # Connectors used to be allowed whole, which let unattended runs change and delete things. Reads now go through send_guard.py and config.json.
  python3 - "$WS" <<'PY'
import json, os, pathlib, sys, tempfile
ws = pathlib.Path(sys.argv[1])
p = ws / ".claude/settings.local.json"
if not p.exists():
    sys.exit(0)
c = json.loads(p.read_text())
allow = c.get("permissions", {}).get("allow", [])
whole = [r for r in allow if r.startswith("mcp__") and "__" not in r[5:]]
if not whole:
    sys.exit(0)
allow[:] = [r for r in allow if r not in whole]
p.write_text(json.dumps(c, indent=2) + "\n")
cp = ws / "config.json"; cfg = json.loads(cp.read_text())
names = cfg.setdefault("unattended_read_connectors", [])
names.extend(n for n in (r[5:] for r in whole if r != "mcp__plugin") if n not in names)
fd, tmp = tempfile.mkstemp(dir=ws, prefix=".config.")
with os.fdopen(fd, "w") as f:
    f.write(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
os.replace(tmp, cp)
print("Connectors are now read-only in unattended runs:", ", ".join(names))
print("To let one change something unattended, allow that exact tool in .claude/settings.local.json.")
PY
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
  allow_connectors
  if [[ "$(python3 -c "import json;print('yes' if (json.load(open('$WS/config.json')).get('remote_control') or {}).get('enabled', True) else 'no')")" == yes ]]; then
    remote
  fi
  grant
  echo "Keep the Mac awake for these (System Settings → Energy, or: sudo pmset repeat wakeorpoweron MTWRFSU <5 min before morning_time>)."
}

grant() {
  [[ $ON_MAC == 1 ]] || { echo "Needs macOS."; exit 1; }
  # Background jobs don't inherit the permissions you gave Terminal. Running the tools once *from a launchd job* makes macOS ask for them.
  python3 - "$WS" <<'PY'
import sys, plistlib, pathlib, subprocess, os, time
ws = pathlib.Path(sys.argv[1]); label = "com.theseus.grant"
p = pathlib.Path.home() / "Library/LaunchAgents" / f"{label}.plist"
cmd = f'cd "{ws}" && bin/ek access; python3 engine/tools/notes.py inbox >/dev/null; python3 engine/tools/imsg.py doctor; echo done'
plistlib.dump({"Label": label, "ProgramArguments": ["/bin/bash", "-c", cmd], "RunAtLoad": True,
               "EnvironmentVariables": {"THESEUS_HOME": str(ws)},
               "StandardOutPath": str(ws / "logs/grant.log"), "StandardErrorPath": str(ws / "logs/grant.log")}, p.open("wb"))
uid = os.getuid()
subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(p)], capture_output=True)
subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(p)], check=True)
print("Asking macOS for access from the background jobs: click Allow on any Calendar, Reminders or Notes prompts (they may say \"bash\" or \"ek\").")
time.sleep(45)
subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(p)], capture_output=True); p.unlink(missing_ok=True)
log = (ws / "logs/grant.log").read_text() if (ws / "logs/grant.log").exists() else ""
if "Full Disk Access" in log or "authorization denied" in log or "unable to open" in log:
    print("⚠️  Texts still need Full Disk Access for /bin/bash: System Settings → Privacy & Security → Full Disk Access → + → ⌘⇧G /bin/bash")
print("Details: logs/grant.log")
PY
}

allow_connectors() {
  # Unattended runs can't answer permission prompts, so they get plain reads from the connectors you have. send_guard.py lets those through
  # and refuses anything that sends; anything else needs a person. Composio can do both, so only its discovery and run tools are allowed, and
  # send_guard.py checks every action it runs. Connectors you've taken out stay out: the first run lists them, and later runs only mention new ones.
  local listing; listing="$(claude mcp list 2>/dev/null)"
  [[ -n "$listing" ]] || { echo "(no connectors found with 'claude mcp list'; skipping)"; return; }
  LISTING="$listing" python3 - "$WS" <<'PY'
import json, os, pathlib, re, sys, tempfile
ws = pathlib.Path(sys.argv[1])
names = []
for line in os.environ["LISTING"].splitlines():
    m = re.match(r"^(.+?): .+ - \S", line)      # "name: target - status"
    if m:
        names.append(m.group(1))
p = ws / ".claude/settings.local.json"
c = json.loads(p.read_text()) if p.exists() else {}
allow = c.setdefault("permissions", {}).setdefault("allow", [])
if "claude.ai Composio" in names:
    for t in ("SEARCH_TOOLS", "GET_TOOL_SCHEMAS", "MULTI_EXECUTE_TOOL"):
        r = f"mcp__claude_ai_Composio__COMPOSIO_{t}"
        if r not in allow:
            allow.append(r)
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(c, indent=2) + "\n")
cp = ws / "config.json"; cfg = json.loads(cp.read_text())
local = [n for n in names if not n.startswith(("plugin:", "claude.ai ")) and "slack" not in n.lower()]
if "unattended_read_connectors" in cfg:
    new = [n for n in local if n not in cfg["unattended_read_connectors"]]
    if new:
        print("  New connectors, not read in unattended runs until you add them to unattended_read_connectors in config.json:", ", ".join(new))
else:
    cfg["unattended_read_connectors"] = local
    fd, tmp = tempfile.mkstemp(dir=ws, prefix=".config.")
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, cp)
    print("  Read in unattended runs:", ", ".join(local) or "none")
for n in names:
    if (n.startswith("claude.ai ") and n != "claude.ai Composio") or "slack" in n.lower():
        print(f"  {n}: not read in unattended runs. To add it, put its name in unattended_read_connectors in config.json.")
PY
}

remote() {
  [[ $ON_MAC == 1 ]] || { echo "Remote Control needs macOS."; exit 1; }
  CLAUDE_BIN="$(command -v claude || true)"; [[ -n "$CLAUDE_BIN" ]] || { echo "Can't find 'claude' on PATH"; exit 1; }
  sed -e "s#__CLAUDE_BIN__#$CLAUDE_BIN#" "$WS/engine/scheduled/run-remote.sh" > "$WS/bin/run-remote.sh" && chmod +x "$WS/bin/run-remote.sh"
  python3 - "$WS" <<'PY'
import sys, plistlib, pathlib, subprocess, os, json
ws = pathlib.Path(sys.argv[1]); label = "com.theseus.remote"
p = pathlib.Path.home() / "Library/LaunchAgents" / f"{label}.plist"; p.parent.mkdir(parents=True, exist_ok=True)
plistlib.dump({"Label": label, "ProgramArguments": ["/bin/bash", str(ws / "bin/run-remote.sh")],
               "EnvironmentVariables": {"THESEUS_HOME": str(ws)}, "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 60,
               "StandardOutPath": str(ws / "logs/launchd-remote.log"), "StandardErrorPath": str(ws / "logs/launchd-remote.log")}, p.open("wb"))
subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(p)], capture_output=True)
subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(p)], check=True)
name = (json.loads((ws / "config.json").read_text()).get("remote_control") or {}).get("name", "Theseus")
print(f'Remote Control running: open the Claude app → Code → your Mac ("{name}"), pick the Theseus folder, and start a session.')
PY
}

channel() {
  [[ $ON_MAC == 1 ]] || { echo "The channel needs macOS."; exit 1; }
  CLAUDE_BIN="$(command -v claude || true)"; [[ -n "$CLAUDE_BIN" ]] || { echo "Can't find 'claude' on PATH"; exit 1; }
  command -v bun >/dev/null || { echo "The iMessage channel plugin needs Bun: curl -fsSL https://bun.sh/install | bash   (then re-run)"; exit 1; }
  echo "This keeps a Claude Code session running in $WS while your Mac is awake, so you can text yourself to reach Theseus."
  echo "It replies only in your own self-chat. Remove it anytime with: engine/install.sh --unschedule"
  read -r -p "Install it? [y/N] " ok; [[ "$ok" == [yY]* ]] || { echo "Not installed."; exit 0; }
  "$CLAUDE_BIN" plugin install "$(python3 -c "import json;print((json.load(open('$WS/config.json')).get('channel') or {}).get('plugin','imessage@claude-plugins-official'))")" || true
  python3 - "$WS" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1]) / "config.json"; c = json.loads(p.read_text())
c.setdefault("channel", {})["enabled"] = True; p.write_text(json.dumps(c, indent=2, ensure_ascii=False))
PY
  sed -e "s#__CLAUDE_BIN__#$CLAUDE_BIN#" "$WS/engine/scheduled/run-channel.sh" > "$WS/bin/run-channel.sh" && chmod +x "$WS/bin/run-channel.sh"
  python3 - "$WS" <<'PY'
import sys, plistlib, pathlib, subprocess, os
ws = pathlib.Path(sys.argv[1]); label = "com.theseus.channel"
p = pathlib.Path.home() / "Library/LaunchAgents" / f"{label}.plist"; p.parent.mkdir(parents=True, exist_ok=True)
plistlib.dump({"Label": label, "ProgramArguments": ["/bin/bash", str(ws / "bin/run-channel.sh")],
               "EnvironmentVariables": {"THESEUS_HOME": str(ws)}, "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 60,
               "StandardOutPath": str(ws / "logs/launchd-channel.log"), "StandardErrorPath": str(ws / "logs/launchd-channel.log")}, p.open("wb"))
subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(p)], capture_output=True)
subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(p)], check=True)
print("Channel session running. Text yourself \"status\" to try it. Log: logs/channel.log")
PY
}

case "$MODE" in
  install)    copy_engine; link_command; build_ek; checks || true
              echo; echo "✅ Theseus installed at $WS"
              echo "Next: cd \"$WS\" && claude   then run /theseus:setup (plugin) or follow docs/SETUP.md, then /migrate" ;;
  --update)   copy_engine; link_command; build_ek; refresh_bin; migrate_connectors
              if [[ $ON_MAC == 1 && -f "$HOME/Library/LaunchAgents/com.theseus.remote.plist" ]]; then
                launchctl kickstart -k "gui/$(id -u)/com.theseus.remote" 2>/dev/null && echo "Restarted Remote Control so it uses the new engine."
              fi
              echo "✅ Engine updated. Your profile, config and data were not touched." ;;
  --check)    checks ;;
  --schedule) schedule ;;
  --channel)  channel ;;
  --remote)   remote ;;
  --grant)    grant ;;
  *) echo "Unknown option $MODE"; exit 2 ;;
esac
