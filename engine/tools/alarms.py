#!/usr/bin/env python3
"""
alarms.py: read the iPhone alarm list that the "Alarms → Theseus" Shortcut saves to iCloud Drive.

The Shortcut writes one line per alarm to  iCloud Drive/Shortcuts/theseus-alarms.txt (config: alarms_file) :
    ALARM|<time>|<label>|<repeat>|<enabled>
and a first line  UPDATED|<date/time>

Usage:
  python3 tools/alarms.py            JSON: alarms + freshness + tomorrow's active alarms
  python3 tools/alarms.py --text     human-readable list
Read-only. Apple Watch alarms are NOT included (they never leave the watch).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

SHORTCUTS_DIR = Path.home() / "Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents"
WS = Path(os.environ.get("THESEUS_HOME") or Path(__file__).resolve().parents[2])
try:
    _name = json.loads((WS / "config.json").read_text()).get("alarms_file", "theseus-alarms.txt")
except Exception:
    _name = "theseus-alarms.txt"
PATH = Path(os.environ.get("ALARMS_FILE") or (SHORTCUTS_DIR / _name))
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
SHORT = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def parse_time(s: str) -> str | None:
    """Accepts '6:45 AM', '06:45', 'Jan 1, 2001 at 6:45 AM', '2001-01-01T06:45:00-07:00' → 'HH:MM'."""
    s = s.strip()
    m = re.search(r"T(\d{1,2}):(\d{2})", s)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = re.search(r"(\d{1,2}):(\d{2})\s*([AaPp])\.?\s*[Mm]?", s)
    if m:
        h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
        return f"{h:02d}:{m.group(2)}"
    m = re.search(r"(\d{1,2}):(\d{2})", s)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def parse_repeat(s: str) -> list[int] | None:
    """None = one-off ('Never' / empty). Otherwise weekday numbers (Mon=0)."""
    t = s.strip().lower()
    if not t or t in ("never", "none", "no"):
        return None
    if "every day" in t or "daily" in t:
        return list(range(7))
    if "weekday" in t:
        return [0, 1, 2, 3, 4]
    if "weekend" in t:
        return [5, 6]
    found = set()
    for i, d in enumerate(DAYS):
        if d in t:
            found.add(i)
    for k, i in SHORT.items():
        if re.search(rf"\b{k}\b", t):
            found.add(i)
    return sorted(found) or None


def parse_bool(s: str) -> bool | None:
    t = s.strip().lower()
    if t in ("yes", "true", "1", "on", "enabled"):
        return True
    if t in ("no", "false", "0", "off", "disabled"):
        return False
    return None  # Shortcut couldn't provide it


def load():
    if not PATH.exists():
        return {"ok": False, "error": f"No alarm file at {PATH}. Set up the 'Alarms → Theseus' Shortcut (docs/SETUP.md, iPhone alarms).",
                "alarms": []}
    raw = PATH.read_text(errors="replace")
    alarms, updated = [], None
    for line in raw.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if parts[0].upper() == "UPDATED" and len(parts) > 1:
            updated = parts[1]
        elif parts[0].upper() == "ALARM" and len(parts) >= 3:
            parts += [""] * (5 - len(parts))
            t = parse_time(parts[1])
            label = parts[2]
            if label and parse_time(label) == t and len(label) <= 9:
                label = ""          # Shortcuts uses the time as the name when there's no label
            alarms.append({"time": t, "time_raw": parts[1], "label": label or None,
                           "repeat_raw": parts[3], "repeat_days": parse_repeat(parts[3]),
                           "enabled": parse_bool(parts[4])})
    age_h = (dt.datetime.now().timestamp() - PATH.stat().st_mtime) / 3600
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).weekday()
    active_tomorrow = [a for a in alarms if a["enabled"] is not False and
                       (a["repeat_days"] is None or tomorrow in a["repeat_days"])]
    return {"ok": True, "file": str(PATH), "updated": updated, "file_age_hours": round(age_h, 1),
            "stale": age_h > 30, "count": len(alarms), "alarms": sorted(alarms, key=lambda a: a["time"] or ""),
            "active_tomorrow": sorted(active_tomorrow, key=lambda a: a["time"] or ""),
            "note": "one-off alarms (no repeat) are assumed to be for the next occurrence"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", action="store_true")
    a = ap.parse_args()
    d = load()
    if not a.text:
        print(json.dumps(d, indent=1, ensure_ascii=False))
        return
    if not d["ok"]:
        sys.exit(d["error"])
    print(f"iPhone alarms ({d['count']}) · file updated {d['file_age_hours']}h ago" + ("  ⚠️ STALE" if d["stale"] else ""))
    for x in d["alarms"]:
        state = {True: "on ", False: "off", None: " ? "}[x["enabled"]]
        rep = x["repeat_raw"] or "Never"
        print(f"  [{state}] {x['time']}  {x['label'] or '(no label)'}  · {rep}")


if __name__ == "__main__":
    main()
