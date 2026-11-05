#!/usr/bin/env python3
"""The theseus command: the same workspace, rules and send guard as the app, from Terminal."""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SEP = " · "
ITEM = re.compile(r"^- \[( |x|X)\] (.*)$")


def fail(message, code=1):
    print(message, file=sys.stderr)
    sys.exit(code)


def workspace():
    """THESEUS_HOME if set, and nothing else then. Otherwise the workspace this copy of the engine lives in, then wherever the installer said, then the default."""
    home = os.environ.get("THESEUS_HOME")
    if home:
        # Someone asked for this workspace by name, so never quietly change the real list instead.
        if (Path(home) / "config.json").exists():
            return Path(home)
        fail(f"THESEUS_HOME is set to {home}, but there's no Theseus workspace there, so nothing changed.")
    candidates = []
    candidates.append(Path(__file__).resolve().parents[2])
    pointer = Path.home() / "Library/Application Support/Theseus/workspace"
    if pointer.exists():
        candidates.append(Path(pointer.read_text().strip()))
    candidates.append(Path.home() / "Theseus")
    for ws in candidates:
        if (ws / "config.json").exists():
            return ws
    fail("Can't find your Theseus workspace. Run ./install.sh from your copy of Theseus, or set THESEUS_HOME.")


def claude():
    extra = [str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin"]
    path = os.pathsep.join([os.environ.get("PATH", "")] + extra)
    found = shutil.which("claude", path=path)
    return found or fail("This needs Claude Code, and I can't find it. Install it from https://claude.com/claude-code")


def section_title(heading):
    return re.sub(r"^[^\w]+", "", re.sub(r"^##\s*", "", heading)).split(":")[0].strip()


def is_done(key):
    return re.match(r"(done|completed?|finished)\b", key) is not None


def sections(text):
    """[(title, heading line index, end line index)], the same way the app reads the file."""
    lines = text.split("\n")
    heads = [i for i, line in enumerate(lines) if line.startswith("## ")]
    return [(section_title(lines[h]), h, heads[n + 1] if n + 1 < len(heads) else len(lines)) for n, h in enumerate(heads)]


def open_items(lines):
    """What's still to do: not checked off, and not a repeating item that's done for now."""
    for line in lines:
        m = ITEM.match(line)
        if m and m.group(1) == " ":
            parts = [p.strip() for p in m.group(2).split(SEP)]
            if not any(re.match(r"done for now\b", p) for p in parts[1:]):
                yield parts


def read_master(ws):
    path = ws / "data/master.md"
    if not path.exists():
        fail(f"There's no list yet at {path}.")
    return path.read_text()


def job_holder(ws):
    """The process running a job right now (app, schedule or this command), if any."""
    try:
        pid = int((ws / "data/.job.lock").read_text().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def status(ws):
    text = read_master(ws)
    lines = text.split("\n")
    version = (ws / "engine/VERSION").read_text().strip() if (ws / "engine/VERSION").exists() else "unknown"
    print(f"Theseus {version} · {ws}")
    counts = [f"{sum(1 for _ in open_items(lines[h + 1:e]))} {title}" for title, h, e in sections(text) if not is_done(title.lower())]
    print("List: " + (SEP.join(counts) or "no sections yet"))
    try:
        state = json.loads((ws / "data/state.json").read_text())
    except (OSError, ValueError):
        state = {}
    print("Last sync: " + str(state.get("last_sync") or "not yet"))
    config = json.loads((ws / "config.json").read_text())
    app_open = subprocess.run(["/usr/bin/pgrep", "-x", "theseus"], capture_output=True).returncode == 0
    if config.get("scheduler_host") == "app":
        print("Schedule: run by the app" + ("" if app_open else ", which isn't open, so nothing runs until you open it"))
    else:
        print("Schedule: run by background jobs, until the app has its permissions" + (" (the app is open)" if app_open else ""))
    print("Running now: a job" if job_holder(ws) else "Running now: nothing")


def next_up(ws, args):
    if len(args) > 1 or (args and not args[0].isdigit()):
        fail('Usage: theseus next [how many]. For a recommendation, ask: theseus "what should I do next? I have 30 minutes"', 2)
    limit = int(args[0]) if args else 5
    text = read_master(ws)
    lines = text.split("\n")
    found = sections(text)
    now = next((s for s in found if s[0].lower() == "now"), None) or next((s for s in found if not is_done(s[0].lower())), None)
    if not now:
        fail("Your list has no sections yet.")
    todo = list(open_items(lines[now[1] + 1:now[2]]))
    if not todo:
        print(f"Nothing left in {now[0]}.")
        return
    for n, parts in enumerate(todo[:limit], 1):
        due = next((p for p in parts[1:] if re.match(r"due\b", p)), "")
        print(f"{n}. {parts[0]}" + (f" · {due}" if due else ""))
    if len(todo) > limit:
        print(f"…and {len(todo) - limit} more in {now[0]}.")


def save_master(ws, before, lines, event):
    """Saves the list and tells the next sync what changed. False if something else just saved, so the caller starts over on what it saved."""
    path = ws / "data/master.md"
    now = dt.datetime.now()
    archive = ws / "data/archive"
    archive.mkdir(parents=True, exist_ok=True)
    backup = archive / f"master-app-{now:%Y-%m-%d-%H}.md"
    if not backup.exists():
        backup.write_text(before)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".master.md.")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines))
    # Last look before the swap, the same as the app.
    if path.read_text() != before:
        os.unlink(tmp)
        return False
    os.replace(tmp, path)
    with open(ws / "data/app-edits.jsonl", "a") as f:
        f.write(json.dumps({**event, "time": f"{now:%Y-%m-%d %H:%M}"}, ensure_ascii=False) + "\n")
    return True


def add(ws, args):
    to = None
    if "--to" in args:
        at = args.index("--to")
        if at + 1 >= len(args):
            fail('Usage: theseus add "text" [--to section]', 2)
        to = args[at + 1].lower()
        args = args[:at] + args[at + 2:]
    # The same clean-up as adding in the app: " · " separates a line's parts, so a title can't contain one.
    title = re.sub(r"\s*·\s*", " - ", " ".join(args)).replace("\n", " ").strip()
    if not title:
        fail('Usage: theseus add "text" [--to section]', 2)
    for _ in range(3):
        before = read_master(ws)
        found = [s for s in sections(before) if not is_done(s[0].lower())]
        if to:
            hits = [s for s in found if s[0].lower() == to] or [s for s in found if s[0].lower().startswith(to)]
            if len(hits) != 1:
                fail(f'No section called "{to}". You have: ' + ", ".join(s[0] for s in found))
        else:
            hits = [s for s in found if s[0].lower() == "next"] or found[:1]
            if not hits:
                fail("Your list has no sections yet.")
        name, heading, end = hits[0]
        lines = before.split("\n")
        at = end
        while at > heading + 1 and not lines[at - 1].strip():   # ahead of the section's trailing blank lines
            at -= 1
        lines.insert(at, f"- [ ] {title} · #Inbox")
        if not save_master(ws, before, lines, {"action": "add", "id": None, "title": title, "to": name.lower()}):
            continue
        print(f"Added to {name}: {title}")
        print("The next sync gives it a category and carries it to your other lists.")
        return
    fail("The list kept changing while I tried to add that, so nothing was added. Try again in a moment.")


def with_segment(parts, segment):
    """Adds a segment just before the id, the same as the app."""
    at = next((i for i, p in enumerate(parts) if p.startswith("id:")), len(parts))
    return parts[:at] + [segment] + parts[at:]


def open_matches(text, query):
    """Items still to do that match an id or part of a title. An exact title beats a partial one."""
    lines = text.split("\n")
    hits = []
    for title, heading, end in sections(text):
        if is_done(title.lower()):
            continue
        for i in range(heading + 1, end):
            m = ITEM.match(lines[i])
            if not m or m.group(1) != " ":
                continue
            parts = [p.strip() for p in m.group(2).split(SEP)]
            if any(re.match(r"done for now\b", p) for p in parts[1:]):
                continue
            hits.append({"line": i, "section": title, "parts": parts})
    q = query.lower()
    by_id = [h for h in hits if f"id:{q}" in (p.lower() for p in h["parts"])]
    exact = [h for h in hits if h["parts"][0].lower() == q]
    return by_id or exact or [h for h in hits if q in h["parts"][0].lower()]


def done(ws, args):
    query = " ".join(args).strip()
    if not query:
        fail('Usage: theseus done "part of the title"', 2)
    for _ in range(3):
        before = read_master(ws)
        hits = open_matches(before, query)
        if not hits:
            fail(f'Nothing still to do matches "{query}".')
        if len(hits) > 1:
            names = "\n".join(f"  {h['parts'][0]} ({h['section']})" for h in hits[:10])
            fail(f'"{query}" matches {len(hits)} items, so nothing changed. Use more of the title:\n{names}', 3)
        hit = hits[0]
        lines = before.split("\n")
        at, parts, now = hit["line"], hit["parts"], dt.datetime.now()
        stamp = f"{now.month}/{now.day}"
        id_ = next((p[3:] for p in parts if p.startswith("id:")), None)
        repeating = any(p.startswith("↻") for p in parts[1:])
        if repeating:
            lines[at] = "- [ ] " + SEP.join(with_segment(parts, f"done for now {stamp}"))
        else:
            end = at + 1
            while end < len(lines) and lines[end].startswith(("  ", "\t")):   # its notes go with it
                end += 1
            was = hit["section"].lower().replace(" ", "-")
            moved = ["- [x] " + SEP.join(with_segment(with_segment(parts, f"done {stamp}"), f"was:{was}"))] + lines[at + 1:end]
            del lines[at:end]
            rest = "\n".join(lines)
            target = next((s for s in sections(rest) if is_done(s[0].lower())), None)
            if target:
                _, heading, stop = target
                first = next((i for i in range(heading + 1, stop) if ITEM.match(lines[i])), None)
                lines[(first if first is not None else heading + 1):0] = moved
            else:
                while lines and not lines[-1].strip():
                    lines.pop()
                lines += ["", "## ✅ DONE"] + moved + [""]
        if not save_master(ws, before, lines, {"action": "complete", "id": id_, "title": parts[0], "repeating": repeating}):
            continue
        print(f"Done: {parts[0]}" + (" (repeats, so it's done for now)" if repeating else ""))
        print("The next sync carries it to your other lists.")
        return
    fail("The list kept changing while I tried to check that off, so nothing changed. Try again in a moment.")


def today(ws):
    path = ws / "data/today.md"
    if not path.exists():
        fail('There\'s no Today note yet. It\'s built by the next sync, or run: theseus sync')
    print(path.read_text().rstrip())


def texts(ws, args):
    """Who's waiting on you, straight from the local message tool."""
    sys.exit(subprocess.call(["/usr/bin/python3", str(ws / "engine/tools/imsg.py"), "missed", *args], cwd=ws, env={**os.environ, "THESEUS_HOME": str(ws)}))


def run_job(ws, job):
    print(f"Running {job}. This usually takes a few minutes, and the result prints here when it's done.", flush=True)
    env = {**os.environ, "THESEUS_HOME": str(ws), "THESEUS_MANUAL": "1"}
    sys.exit(subprocess.call(["/bin/bash", str(ws / "engine/scheduled/run-job.sh"), job], cwd=ws, env=env))


def ask(ws, question):
    prompt = (f'The user asked this at the command line: "{question}". Answer briefly and follow engine/RULES.md. If it\'s something to do or remember, add it to the list. '
              "Never send anything. This run can't ask follow-up questions, so make the sensible choice and say what you did.")
    sys.exit(subprocess.call([claude(), "-p", prompt, "--output-format", "text"], cwd=ws, stdin=subprocess.DEVNULL, env={**os.environ, "THESEUS_HOME": str(ws)}))


def main():
    args = sys.argv[1:]
    if args and args[0] in ("help", "--help", "-h"):
        print((Path(__file__).resolve().parents[1] / "commands.txt").read_text().rstrip())
        return
    ws = workspace()
    if not args:
        path = claude()
        os.chdir(ws)
        os.environ["THESEUS_HOME"] = str(ws)
        os.execv(path, [path])
    command, rest = args[0], args[1:]
    if command in ("sync", "morning") and not rest:
        run_job(ws, command)
    elif command == "status" and not rest:
        status(ws)
    elif command == "next":
        next_up(ws, rest)
    elif command == "add":
        add(ws, rest)
    elif command == "done":
        done(ws, rest)
    elif command == "today" and not rest:
        today(ws)
    elif command == "texts":
        texts(ws, rest)
    elif command in ("version", "--version") and not rest:
        print((ws / "engine/VERSION").read_text().strip())
    elif len(args) == 1 and not re.search(r"\s", command):
        # A mistyped command shouldn't spend your Claude plan on a one-word "question".
        fail(f'I don\'t know the command "{command}". To ask something, use a whole question in quotes. See: theseus help', 2)
    else:
        ask(ws, " ".join(args))


if __name__ == "__main__":
    main()
