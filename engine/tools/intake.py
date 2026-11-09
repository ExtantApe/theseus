#!/usr/bin/env python3
"""
intake.py: items other tools hand Theseus (data/intake/<tool>.jsonl). Nothing joins the master list without the user's yes.

Each tool only appends, one JSON object per line:
  {"id": "console-…", "created": "<ISO 8601>", "title": "…", "owner_is_me": true,
   "meeting": {"title": "…", "date": "YYYY-MM-DD"},
   "context": "…", "due": "YYYY-MM-DD", "category": "#…", "link": "…"}      (last four optional)
A later line with the same id and "status": "done" or "cancelled" updates the item.

  pending              new items waiting for the user's yes, numbered, plus lines that were skipped and why
  accept ID --task tNNNN   the user said yes and the item is now that master task
  decline ID           the user said no
  updates              accepted items whose tool later marked them done or cancelled, not yet carried to the list
  applied ID           that update has been carried to the list

Decisions live in data/intake-state.json. This tool never writes to the tools' files.
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

WS = Path(os.environ.get("THESEUS_HOME") or Path(__file__).resolve().parents[2])
INTAKE = WS / "data/intake"
STATE = WS / "data/intake-state.json"
REQUIRED = ("id", "created", "title", "owner_is_me", "meeting")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"items": {}}


def save_state(state):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False) + "\n")
    os.replace(tmp, STATE)


def read_items():
    """Fold every tool's lines by id: the first full line is the item, later status lines update it."""
    items, skipped = {}, []
    for path in sorted(INTAKE.glob("*.jsonl")) if INTAKE.exists() else []:
        source = path.stem
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            where = f"{path.name}:{n}"
            try:
                obj = json.loads(line)
            except ValueError:
                skipped.append({"line": where, "why": "not JSON"})
                continue
            if not isinstance(obj, dict) or not isinstance(obj.get("id"), str) or not obj["id"]:
                skipped.append({"line": where, "why": "no id"})
                continue
            key = f"{source}:{obj['id']}"
            status = obj.get("status")
            if status in ("done", "cancelled"):
                if key in items:
                    items[key]["status"] = status
                    items[key]["status_line"] = where
                else:
                    skipped.append({"line": where, "why": f"{status} for an id not seen yet"})
                continue
            if status is not None:
                skipped.append({"line": where, "why": f"unknown status {status!r}"})
                continue
            if key in items:
                continue   # same id again: the first one stands
            missing = [f for f in REQUIRED if f not in obj or obj[f] in (None, "")]
            if missing:
                skipped.append({"line": where, "why": "missing " + ", ".join(missing)})
                continue
            if obj["owner_is_me"] is not True:
                continue   # someone else's action item
            if obj.get("due") and not DATE.match(str(obj["due"])):
                obj = {**obj, "due_raw": obj["due"], "due": None}
            items[key] = {"key": key, "source": source, "line": where, "status": "open",
                          **{k: obj.get(k) for k in ("id", "created", "title", "context", "due", "due_raw",
                                                    "category", "meeting", "link")}}
    return items, skipped


def pending():
    items, skipped = read_items()
    decided = load_state()["items"]
    new = [i for k, i in items.items() if k not in decided and i["status"] == "open"]
    new.sort(key=lambda i: str(i["created"]))
    for n, i in enumerate(new, 1):
        i["n"] = n
    print(json.dumps({"pending": new, "skipped": skipped}, indent=1, ensure_ascii=False))


def decide(key, decision, task=None):
    items, _ = read_items()
    if key not in items:
        sys.exit(f"no intake item {key!r} (use the key from `pending`, e.g. console:console-123)")
    state = load_state()
    if key in state["items"]:
        sys.exit(f"{key} was already {state['items'][key]['decision']}")
    entry = {"decision": decision, "at": dt.datetime.now().isoformat(timespec="seconds"),
             "title": items[key]["title"]}
    if task:
        entry["task"] = task
    state["items"][key] = entry
    save_state(state)
    print(json.dumps({key: entry}, ensure_ascii=False))


def updates():
    items, _ = read_items()
    state = load_state()["items"]
    out = [{"key": k, "task": d.get("task"), "title": d["title"], "status": items[k]["status"]}
           for k, d in state.items()
           if d["decision"] == "accepted" and k in items and items[k]["status"] != "open" and not d.get("applied")]
    print(json.dumps({"updates": out}, indent=1, ensure_ascii=False))


def applied(key):
    state = load_state()
    if key not in state["items"]:
        sys.exit(f"no decision recorded for {key!r}")
    state["items"][key]["applied"] = dt.datetime.now().isoformat(timespec="seconds")
    save_state(state)
    print(json.dumps({key: state["items"][key]}, ensure_ascii=False))


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd, rest = argv[0], argv[1:]
    if cmd == "pending" and not rest:
        return pending()
    if cmd == "updates" and not rest:
        return updates()
    if cmd == "accept" and len(rest) == 3 and rest[1] == "--task" and re.match(r"^t\d{4,}$", rest[2]):
        return decide(rest[0], "accepted", rest[2])
    if cmd == "decline" and len(rest) == 1:
        return decide(rest[0], "declined")
    if cmd == "applied" and len(rest) == 1:
        return applied(rest[0])
    sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
