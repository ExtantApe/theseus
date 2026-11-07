#!/usr/bin/env python3
"""The only thing your Mac's key can do on this Pi: hand over one snapshot, or clear the screen. Anything that fails a check is refused, and the last good list stays."""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

RUN = Path(os.environ.get("THESEUS_WALL_RUN", "/run/theseus-wall"))
MOST_BYTES = 256 * 1024
SCHEMA = 1
PIECES = {"top", "list", "sectors", "due", "clock", "counts", "note", "status"}
GRIDS = {"landscape": (24, 14), "portrait": (14, 24)}
CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def check(snap):
    """The reason it's refused, or None."""
    if not isinstance(snap, dict) or snap.get("schema") != SCHEMA:
        return "unknown schema"
    if snap.get("mode") not in ("titles", "counts") or not isinstance(snap.get("generated_at"), str):
        return "not a snapshot"
    if not isinstance(snap.get("sections"), dict):
        return "no sections"
    for section in snap["sections"].values():
        if not isinstance(section, dict) or not is_int(section.get("open")):
            return "bad section"
        items = section.get("items", [])
        if not isinstance(items, list):
            return "bad items"
        if items and snap["mode"] == "counts":
            return "titles in counts mode"
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not is_int(item.get("number")):
                return "bad item"
    display = snap.get("display")
    if display is not None and not (isinstance(display, dict) and all(isinstance(display.get(k), str) and CLOCK.match(display[k]) for k in ("on", "off"))):
        return "bad hours"
    views = snap.get("views", [])
    if not isinstance(views, list) or (snap["mode"] == "titles" and not views):
        return "no views"
    for view in views:
        if not isinstance(view, dict) or not isinstance(view.get("name"), str) or not isinstance(view.get("layouts"), dict):
            return "bad view"
        for shape, layout in view["layouts"].items():
            if shape not in GRIDS or not isinstance(layout, (list, type(None))):
                return "bad layout"
            cols, rows = GRIDS[shape]
            for t in layout or []:
                if not isinstance(t, dict) or t.get("type") not in PIECES or not all(is_int(t.get(k)) for k in "xywh"):
                    return "bad piece"
                if t["x"] < 0 or t["y"] < 0 or t["w"] < 1 or t["h"] < 1 or t["x"] + t["w"] > cols or t["y"] + t["h"] > rows:
                    return "piece off the grid"
                if not isinstance(t.get("opts", {}), dict):
                    return "bad piece"
    return None


def main():
    command = os.environ.get("SSH_ORIGINAL_COMMAND", "receive").strip()
    target = RUN / "wall.json"
    if command == "clear":
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return 0
    if command != "receive":
        print("refused: this key can only deliver a snapshot", file=sys.stderr)
        return 2
    raw = sys.stdin.buffer.read(MOST_BYTES + 1)
    if len(raw) > MOST_BYTES:
        print("refused: too big", file=sys.stderr)
        return 3
    try:
        snap = json.loads(raw.decode())
    except ValueError:
        print("refused: not JSON", file=sys.stderr)
        return 3
    reason = check(snap)
    if reason:
        print(f"refused: {reason}", file=sys.stderr)
        return 3
    fd, tmp = tempfile.mkstemp(dir=RUN, prefix=".wall.")
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
    os.chmod(tmp, 0o644)  # the local web server runs as its own user
    os.replace(tmp, target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
