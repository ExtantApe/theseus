#!/usr/bin/env python3
"""The wall display: what your Mac sends to a screen on your network, and how it gets there. No Claude, and it never changes your list.

The filter in snapshot() is the promise: it reads data/master.md and nothing else, sends only what your views use, and leaves out anything
it isn't sure about. Spec: docs/design/wall-display.md. The screen and the Pi's side live in apps/wall.
"""
import datetime as dt
import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cli  # noqa: E402
import schedule as sched  # noqa: E402

SCHEMA = 1
HEARTBEAT_SECONDS = 300  # how the screen tells "nothing changed" from "the Mac is asleep"
MOST_ITEMS = 60  # per section: more than any screen can show
LONGEST_TITLE = 120
TITLE_PIECES = {"top", "list", "sectors", "due"}
PIECES = TITLE_PIECES | {"clock", "counts", "note", "status"}
CHANGE_MODES = {"schedule", "rotate", "fixed"}
AGENT = "com.theseus.wall"

LOOKS_PRIVATE = re.compile(
    r"\S+@\S+\.\S+"  # an email address
    r"|https?://|\bwww\.|\b[\w-]+\.(?:com|org|net|io|ai|co|edu|gov|app|dev)\b"  # a web address
    r"|(?<![\d/])(?:\+?\d[\s().-]*){10,}",  # a phone number
    re.I,
)
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-⛿✀-✒✕-➿⭐⏩-⏺⌚⌛][️‍]*")
DATE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])")
HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class WallError(Exception):
    """Something isn't right, so nothing gets sent. The screen keeps the last good list and says how old it is."""


def fail(message):
    raise WallError(message)


# ---------- What can reach the wall ----------
def never_on_wall(key):
    """Done and Communications, whatever a layout asks for. Finds them the same way the app does (commsSection, isDoneKey in master.ts)."""
    return cli.is_done(key) or re.match(r"(comm|messages?\b|replies\b|people\b)", key) is not None


def start_views():
    """The views a new screen starts with. They show Now, Next and Later titles, and only counts for Waiting On, whose titles often name people."""
    def tile(kind, x, y, w, h, **opts):
        return {"type": kind, "x": x, "y": y, "w": w, "h": h, "opts": opts}

    status = tile("status", 0, 13, 12, 1)
    counts = {"sections": ["next", "waiting on"]}
    return {
        "change": {"mode": "fixed", "minutes": 5, "active": "Sectors"},
        "views": [
            {"name": "Sectors", "when": None, "layouts": {"landscape": [
                tile("top", 0, 0, 17, 3, section="now", size="XL"), tile("clock", 17, 0, 7, 3, date=True, size="M"),
                tile("sectors", 0, 3, 24, 10, section="now", skipTop=True, size="M"), status, tile("counts", 12, 13, 12, 1, **counts)]}},
            {"name": "Ranked", "when": None, "layouts": {"landscape": [
                tile("list", 0, 0, 16, 13, section="now", size="L"), tile("clock", 16, 0, 8, 4, date=True, size="L"),
                tile("counts", 16, 4, 8, 4, **counts), tile("due", 16, 8, 8, 5, days=14, size="M"), status]}},
            {"name": "One thing", "when": None, "layouts": {"landscape": [
                tile("clock", 0, 0, 24, 3, date=True, size="M"), tile("top", 0, 3, 24, 8, section="now", size="XXL"),
                tile("counts", 0, 11, 24, 2, **counts), status]}},
            {"name": "Board", "when": None, "layouts": {"landscape": [
                tile("list", 0, 0, 8, 13, section="now", size="S"), tile("list", 8, 0, 8, 13, section="next", size="S"),
                tile("list", 16, 0, 8, 13, section="later", size="S"), status, tile("counts", 12, 13, 12, 1, sections=["waiting on"])]}},
            {"name": "Clock", "when": None, "layouts": {"landscape": [
                tile("clock", 0, 2, 24, 7, date=True, size="XL"), tile("top", 3, 9, 18, 3, section="now", size="L"), status]}},
        ],
    }


def check_views(data):
    """A bad layout file sends nothing rather than something half right. The Pi checks again when it arrives."""
    if not isinstance(data, dict) or not isinstance(data.get("views"), list) or not data["views"]:
        fail("data/wall-views.json has no views in it.")
    change = data.get("change", {})
    if not isinstance(change, dict) or change.get("mode", "fixed") not in CHANGE_MODES:
        fail("data/wall-views.json has a view change setting I don't recognize.")
    hours = data.get("active_hours")
    if hours not in (None, "always") and not (isinstance(hours, dict) and all(CLOCK.match(str(hours.get(k))) for k in ("from", "to")) and hours["from"] != hours["to"]):
        fail("data/wall-views.json has active hours I can't read.")
    for view in data["views"]:
        if not isinstance(view, dict) or not isinstance(view.get("name"), str) or not isinstance(view.get("layouts"), dict):
            fail("data/wall-views.json has a view I can't read.")
        for shape, (cols, rows) in (("landscape", (24, 14)), ("portrait", (14, 24))):
            for t in view["layouts"].get(shape) or []:
                sized = all(isinstance(t.get(k), int) and not isinstance(t.get(k), bool) for k in "xywh") if isinstance(t, dict) else False
                if not sized or t.get("type") not in PIECES or not isinstance(t.get("opts", {}), dict):
                    fail(f'The "{view["name"]}" view in data/wall-views.json has a piece I can\'t read.')
                if t["x"] < 0 or t["y"] < 0 or t["w"] < 1 or t["h"] < 1 or t["x"] + t["w"] > cols or t["y"] + t["h"] > rows:
                    fail(f'The "{view["name"]}" view in data/wall-views.json has a piece off the {shape} grid.')
    return data


def load_views(ws):
    path = ws / "data/wall-views.json"
    if not path.exists():
        return start_views()
    try:
        return check_views(json.loads(path.read_text()))
    except ValueError:
        fail("data/wall-views.json isn't valid JSON.")


def wanted_sections(views):
    """(sections whose titles a view shows, sections a view only counts). Lower-case keys."""
    titles, counted = set(), set()
    for view in views["views"]:
        for layout in view["layouts"].values():
            for t in layout or []:
                opts = t.get("opts", {})
                if t["type"] == "due":
                    titles.add("now")
                elif t["type"] in TITLE_PIECES:
                    titles.add(str(opts.get("section", "now")).lower())
                elif t["type"] == "counts":
                    counted.update(str(s).lower() for s in opts.get("sections") or [])
    return titles, counted - titles


def clean_title(title):
    title = re.sub(r"\s{2,}", " ", EMOJI.sub("", title)).strip()
    return title if len(title) <= LONGEST_TITLE else title[:LONGEST_TITLE - 1].rstrip() + "…"


def due_of(parts, today):
    """(the words as you wrote them, the date if one can be read). The screen works out "Due today" from its own clock, so it stays true while the Mac sleeps."""
    seg = next((p for p in parts[1:] if re.match(r"due\b", p)), None)
    if not seg:
        return None, None
    words = seg[3:].strip() or None
    m = DATE.search(seg)
    if not m:
        return words, None
    month, day = int(m.group(1)), int(m.group(2))
    try:
        if m.group(3):
            year = int(m.group(3))
            return words, dt.date(year + 2000 if year < 100 else year, month, day).isoformat()
        date = dt.date(today.year, month, day)
        if (today - date).days > 183:  # December's list talking about January
            date = dt.date(today.year + 1, month, day)
        return words, date.isoformat()
    except ValueError:
        return words, None


def snapshot(ws, config, now=None):
    """Everything the screen gets. Anything not added here doesn't leave this Mac."""
    now = now or dt.datetime.now().astimezone()
    wall = config.get("wall") or {}
    path = ws / "data/master.md"
    try:
        text = path.read_text()
    except OSError:
        fail(f"There's no list yet at {path}.")
    found = cli.sections(text)
    if not found:
        fail("Your list has no sections, so nothing was sent.")
    lines = text.split("\n")
    views = load_views(ws)
    want_titles, want_counts = wanted_sections(views)
    show_titles = wall.get("titles") is True
    hidden = {str(c).lstrip("#").lower() for c in wall.get("private_categories") or []}
    today = now.date()

    # The top of the day, even if you've renamed NOW, found the same way as the app and `theseus next`.
    named_now = any(t.lower() == "now" for t, _, _ in found)
    first = next((t for t, _, _ in found if not never_on_wall(t.lower())), None)

    sections = {}
    number = 0
    for title, heading, end in found:
        key = "now" if not named_now and title == first else title.lower()
        if never_on_wall(key) or key not in want_titles | want_counts or key in sections:
            continue
        todo = list(cli.open_items(lines[heading + 1:end]))
        entry = {"title": title.title(), "open": len(todo)}
        if key in want_titles:
            if show_titles:
                items = []
                kept_private = more = 0
                for parts in todo:
                    category = next((p[1:] for p in parts[1:] if p.startswith("#")), None)
                    if (category or "").lower() in hidden or LOOKS_PRIVATE.search(parts[0]) or not clean_title(parts[0]):
                        kept_private += 1
                    elif len(items) >= MOST_ITEMS:
                        more += 1
                    else:
                        number += 1
                        words, date = due_of(parts, today)
                        items.append({"number": number, "title": clean_title(parts[0]), "due": words, "due_date": date, "category": category})
                entry.update(items=items, more=more, kept_private=kept_private)
            else:
                # Counts mode: the screen can't leak a title it never got.
                dates = [due_of(p, today)[1] for p in todo if (next((s[1:] for s in p[1:] if s.startswith("#")), "") or "").lower() not in hidden]
                entry.update(due_today=sum(d == today.isoformat() for d in dates), was_due=sum(bool(d) and d < today.isoformat() for d in dates))
        sections[key] = entry

    out = {"schema": SCHEMA, "generated_at": now.isoformat(timespec="seconds"), "mode": "titles" if show_titles else "counts", "sections": sections}
    if show_titles:
        out["views"] = views["views"]
        out["change"] = views.get("change") or {"mode": "fixed"}
    out["display"] = display_hours(config, today, views.get("active_hours"))
    return out


def display_hours(config, today, active_hours=None):
    """The screen's active hours. If you haven't set any, your wake and bed times. None means it stays on."""
    if active_hours == "always":
        return None
    if active_hours:
        return {"on": active_hours["from"], "off": active_hours["to"]}
    try:
        plan = sched.day_plan(json.loads(json.dumps(config)), today)
        return {"on": plan["wake"], "off": plan["awake_until"]}
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


# ---------- Getting it there ----------
def keys_dir(ws):
    return ws / ".wall"


def ssh_base(ws):
    return [shutil.which("ssh") or "/usr/bin/ssh", "-i", str(keys_dir(ws) / "id_ed25519"), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "-o", f"UserKnownHostsFile={keys_dir(ws) / 'known_hosts'}", "-o", "StrictHostKeyChecking=yes"]


def write_json(path, data):
    """Written whole, so a crash can't leave half a file. Keeps the file's permissions."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    if path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def read_json(path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return fallback


def state_path(ws):
    return ws / "data/wall-state.json"


def load_config(ws):
    try:
        return json.loads((ws / "config.json").read_text())
    except ValueError:
        fail("config.json isn't valid JSON, so nothing was sent.")


def fingerprint(snap):
    """What changed, leaving out the clock, so an unchanged list isn't sent every 30 seconds."""
    return hashlib.sha256(json.dumps({k: v for k, v in snap.items() if k != "generated_at"}, sort_keys=True).encode()).hexdigest()


def push(ws, force=False):
    """Sends if something changed, or if it's been a while. True if the screen is up to date."""
    config = load_config(ws)
    wall = config.get("wall") or {}
    if wall.get("enabled") is not True or not wall.get("host"):
        return True
    state = read_json(state_path(ws), {})
    now = time.time()
    try:
        snap = snapshot(ws, config)
    except WallError as e:
        write_json(state_path(ws), {**state, "last_error": str(e), "last_try": now})
        raise
    stamp = fingerprint(snap)
    if not force and state.get("fingerprint") == stamp and now - state.get("last_sent", 0) < HEARTBEAT_SECONDS:
        return True
    try:
        run = subprocess.run(ssh_base(ws) + [f"wall@{wall['host']}", "receive"], input=json.dumps(snap, ensure_ascii=False).encode(), capture_output=True, timeout=30)
        error = None if run.returncode == 0 else (run.stderr.decode(errors="replace").strip().splitlines() or ["ssh failed"])[-1]
    except (OSError, subprocess.TimeoutExpired) as e:
        error = str(e)
    if error:
        write_json(state_path(ws), {**state, "last_error": error, "last_try": now})
        return False
    write_json(state_path(ws), {"fingerprint": stamp, "last_sent": now, "last_try": now})
    return True


def agent_path():
    return Path.home() / "Library/LaunchAgents" / f"{AGENT}.plist"


def launchctl(*args):
    return subprocess.run([shutil.which("launchctl") or "/bin/launchctl", *args], capture_output=True)


def install_agent(ws):
    """Checks every 30 seconds. It only reads your list, and only sends when something changed."""
    path = agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        plistlib.dump({"Label": AGENT, "ProgramArguments": ["/usr/bin/python3", str(Path(__file__).resolve()), "push"], "StartInterval": 30, "RunAtLoad": True,
                       "EnvironmentVariables": {"THESEUS_HOME": str(ws)}, "StandardOutPath": "/dev/null", "StandardErrorPath": "/dev/null"}, f)
    target = f"gui/{os.getuid()}"
    launchctl("bootout", f"{target}/{AGENT}")
    if launchctl("bootstrap", target, str(path)).returncode != 0:
        fail("I couldn't start the background job that keeps the screen up to date. Try again, or run: theseus wall push")


def remove_agent():
    launchctl("bootout", f"gui/{os.getuid()}/{AGENT}")
    agent_path().unlink(missing_ok=True)


def kit():
    for base in (cli.workspace() / "wall", Path(__file__).resolve().parents[2] / "apps/wall"):
        if (base / "pi/install.sh").exists():
            return base
    fail("I can't find the Pi's files. Update Theseus with ./install.sh --update, then try again.")


def set_wall(ws, **changes):
    config = load_config(ws)
    config["wall"] = {**(config.get("wall") or {}), **changes}
    write_json(ws / "config.json", config)


def ask_who_can_see():
    if not sys.stdin.isatty():
        print("Titles stay off until you turn them on: theseus wall titles on")
        return False
    answer = input("Who can see this screen? 1 = just me (show task titles), 2 = other people too (counts only) [2]: ").strip()
    return answer == "1"


def setup(ws, args):
    usage = "Usage: theseus wall setup <host> [--user <name>] [--no-agent]"
    args = list(args)
    agent = "--no-agent" not in args
    args = [a for a in args if a != "--no-agent"]
    user = os.environ.get("USER") or "pi"
    if "--user" in args:
        at = args.index("--user")
        if at + 1 >= len(args):
            fail(usage)
        user = args[at + 1]
        del args[at:at + 2]
    if len(args) != 1 or not HOST.match(args[0]) or not re.fullmatch(r"[a-z_][a-z0-9_-]*", user):
        fail(usage)
    host = args[0]
    files = kit()

    keys = keys_dir(ws)
    keys.mkdir(mode=0o700, exist_ok=True)
    key = keys / "id_ed25519"
    if not key.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "theseus-wall", "-f", str(key)], check=True)
    public = (keys / "id_ed25519.pub").read_text().strip()

    print(f"Setting up {host}. This installs a few packages and can take several minutes.", flush=True)
    # Your own login, which has to work without a password. The key made above can only ever deliver a snapshot.
    remote = f'd=$(mktemp -d) && tar -xz -C "$d" && sudo bash "$d/pi/install.sh" {shlex.quote(public)} {shlex.quote(time_zone() or "")}; rc=$?; rm -rf "$d"; exit $rc'
    ssh = [shutil.which("ssh") or "/usr/bin/ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", f"UserKnownHostsFile={keys / 'known_hosts'}", "-o", "StrictHostKeyChecking=accept-new", f"{user}@{host}", remote]
    tar = subprocess.Popen(["tar", "-C", str(files), "-czf", "-", "display", "pi"], stdout=subprocess.PIPE, env={**os.environ, "COPYFILE_DISABLE": "1"})
    run = subprocess.run(ssh, stdin=tar.stdout)
    tar.stdout.close()
    tar.wait()
    if run.returncode != 0:
        fail(f"Setup didn't finish on {host}, so nothing was turned on. Check that this works without a password, then try again: ssh {user}@{host}")

    titles = (load_config(ws).get("wall") or {}).get("titles")
    set_wall(ws, enabled=True, host=host, titles=ask_who_can_see() if titles is None else titles)
    if not push(ws, force=True):
        fail(f"{host} is set up, but the first delivery failed: {read_json(state_path(ws), {}).get('last_error')}")
    if agent:
        install_agent(ws)
    print(f"Your list is on {host}. It stays up to date by itself.")


def clock_time(text):
    """'6am', '12a', '6:30pm', '18:00' or '6'. None if it isn't a time."""
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(a|am|p|pm)?", text.strip().lower())
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3):
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if m.group(3).startswith("p") else 0)
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def set_hours(ws, args):
    usage = "Usage: theseus wall hours <from> <to>, like: theseus wall hours 6am 12am. Or: theseus wall hours always"
    data = load_views(ws)
    if args == ["always"]:
        data["active_hours"] = "always"
        said = "The screen stays on all the time."
    else:
        times = [clock_time(a) for a in args]
        if len(times) != 2 or None in times:
            fail(usage)
        if times[0] == times[1]:
            fail("Those are the same time. To keep the screen on, use: theseus wall hours always")
        data["active_hours"] = {"from": times[0], "to": times[1]}
        said = f"The screen is on from {times[0]} to {times[1]}, and asleep the rest of the time."
    write_json(ws / "data/wall-views.json", data)
    print(said)
    push(ws)


def time_zone():
    """So the Pi's clock agrees with yours. None if macOS doesn't say."""
    found = os.path.realpath("/etc/localtime").split("/zoneinfo/")
    return found[1] if len(found) == 2 and re.fullmatch(r"[A-Za-z0-9_+/-]+", found[1]) else None


def set_view(ws, args):
    name = " ".join(args).strip()
    data = load_views(ws)
    names = {v["name"].lower(): v["name"] for v in data["views"]}
    if name.lower() not in names:
        fail("No view called that. You have: " + ", ".join(names.values()))
    data["change"] = {**(data.get("change") or {}), "mode": "fixed", "active": names[name.lower()]}
    write_json(ws / "data/wall-views.json", data)
    print(f"The screen will show {names[name.lower()]}.")
    push(ws)


def status(ws):
    wall = load_config(ws).get("wall") or {}
    if wall.get("enabled") is not True:
        print("The wall display is off. To connect one: theseus wall setup <host>")
        return
    print(f"Screen: {wall.get('host')}")
    print("Showing: " + ("task titles" if wall.get("titles") is True else "counts only"))
    views = load_views(ws)
    print("Views: " + ", ".join(v["name"] for v in views["views"]))
    hours = views.get("active_hours")
    print("Active hours: " + ("always on" if hours == "always" else f"{hours['from']} to {hours['to']}" if hours else "your wake and bed times"))
    state = read_json(state_path(ws), {})
    if state.get("last_sent"):
        print(f"Last delivered: {dt.datetime.fromtimestamp(state['last_sent']):%a %b %-d, %-I:%M %p}")
    else:
        print("Last delivered: not yet")
    if state.get("last_error"):
        print(f"Last try failed: {state['last_error']}")


def off(ws):
    wall = load_config(ws).get("wall") or {}
    remove_agent()
    if wall.get("host") and wall.get("enabled") is True:
        try:
            run = subprocess.run(ssh_base(ws) + [f"wall@{wall['host']}", "clear"], stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
            cleared = run.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            cleared = False
        print("The screen is cleared." if cleared else "I couldn't reach the screen, so it still shows the last list. It clears if the Pi restarts.")
    set_wall(ws, enabled=False)
    state_path(ws).unlink(missing_ok=True)
    print("The wall display is off. To turn it back on: theseus wall setup <host>")


def main(args=None):
    args = sys.argv[1:] if args is None else list(args)
    ws = cli.workspace()
    command, rest = (args[0], args[1:]) if args else ("status", [])
    try:
        if command == "show" and not rest:
            config = load_config(ws)
            print(json.dumps(snapshot(ws, config), indent=2, ensure_ascii=False))
        elif command == "setup":
            setup(ws, rest)
        elif command == "titles" and rest in (["on"], ["off"]):
            set_wall(ws, titles=rest == ["on"])
            print("Task titles are " + rest[0] + " for this screen.")
            push(ws)
        elif command == "view" and rest:
            set_view(ws, rest)
        elif command == "hours" and rest:
            set_hours(ws, rest)
        elif command == "status" and not rest:
            status(ws)
        elif command == "push" and rest in ([], ["--force"]):
            if not push(ws, force=bool(rest)):
                sys.exit(f"The screen didn't get that: {read_json(state_path(ws), {}).get('last_error')}")
        elif command == "off" and not rest:
            off(ws)
        else:
            sys.exit("Usage: theseus wall [show | setup <host> | titles on|off | view <name> | hours <from> <to> | status | push | off]")
    except WallError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
