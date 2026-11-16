#!/usr/bin/env python3
"""
eta.py: leave-by times for the day's events that have a place, from Apple Maps travel times (K660).

  python3 engine/tools/eta.py day [--date YYYY-MM-DD] [--json]

It reads the day's events from every calendar on this Mac (bin/ek events, which includes every account the Calendar app
has), skips all-day, declined and online events and ones with no place, and asks Apple Maps how long the trip takes
when arriving at the event's start. Apple predicts traffic for that time (tested 2026-11-15: the same 23 km route took
34 minutes arriving at a weekday rush hour and 19 minutes early on a Sunday).

config.json:
  "eta_from": where trips start, an address or "LAT,LON". Required; without it nothing is looked up.
  "eta_transport": "car" (default), "walk" or "transit".
  "eta_buffer_minutes": added to the travel time for parking and walking in (default 10).
  "eta_daily_lookups": the most Apple Maps lookups a day (default 12).

Each event is looked up once a day, and again in the two hours before it if the last answer is over an hour old, so
traffic is fresh when it matters. Answers are kept in data/eta-cache.json. The starting point and event places go only
to Apple, through MapKit. Limits: every trip starts from "eta_from", not from the event before.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

WS = Path(os.environ.get("THESEUS_HOME") or Path(__file__).resolve().parents[2])
CACHE = WS / "data" / "eta-cache.json"
ONLINE = re.compile(r"(https?://|zoom\.us|meet\.google|teams\.microsoft|webex|facetime|\bonline\b|\bvirtual\b|\bphone\b|\bcall\b)", re.I)
DECLINED = 3  # EKParticipantStatus.declined


def load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def ek(*args):
    p = subprocess.run([str(WS / "bin/ek"), *args], capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip()[:200])
    return json.loads(p.stdout or "null")


def needs_trip(e: dict, origin: str) -> str | None:
    """Why an event needs no trip, or None if it does."""
    loc = (e.get("location") or "").strip()
    if e.get("all_day"):
        return "all day"
    if e.get("my_status") == DECLINED:
        return "declined"
    if not loc and not e.get("geo"):
        return "no place"
    if loc and ONLINE.search(loc):
        return "online"
    if loc and origin and loc.lower() == origin.strip().lower():
        return "at the starting point"
    return None


def key(e: dict, transport: str) -> str:
    where = json.dumps(e.get("geo")) if e.get("geo") else (e.get("location") or "").strip().lower()
    return hashlib.sha1(f"{where}|{e.get('start')}|{transport}".encode()).hexdigest()[:16]


def due(entry: dict | None, start: dt.datetime, now: dt.datetime) -> bool:
    """Look up again? Never looked up today, or within two hours of the start with an answer over an hour old."""
    if not entry:
        return True
    asked = dt.datetime.fromisoformat(entry["at"])
    return dt.timedelta(0) <= start - now <= dt.timedelta(hours=2) and now - asked > dt.timedelta(hours=1)


def lookup_args(e: dict, origin: str, transport: str) -> list[str]:
    args = ["eta"]
    args += ["--from-geo", origin] if re.fullmatch(r"\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*", origin) else ["--from", origin]
    geo = e.get("geo")
    args += ["--to-geo", f"{geo['lat']},{geo['lon']}"] if geo else ["--to", e["location"].strip()]
    start = dt.datetime.fromisoformat(e["start"])
    args += ["--arrive", start.strftime("%Y-%m-%d %H:%M"), "--transport", transport]
    return args


def plan(day: dt.date, cfg: dict, now: dt.datetime | None = None, ask=ek) -> dict:
    now = now or dt.datetime.now().astimezone()
    origin = (cfg.get("eta_from") or "").strip()
    if not origin:
        return {"trips": [], "note": 'Set "eta_from" in config.json (an address or LAT,LON) for leave-by times.'}
    transport = cfg.get("eta_transport") or "car"
    buffer = int(cfg.get("eta_buffer_minutes", 10))
    limit = int(cfg.get("eta_daily_lookups", 12))
    cache = load(CACHE, {})
    today = now.date().isoformat()
    if cache.get("day") != today:
        cache = {"day": today, "lookups": 0, "entries": {}}
    events = ask("events", "--from", day.isoformat(), "--to", (day + dt.timedelta(days=1)).isoformat()) or []
    trips, notes = [], []
    for e in events:
        if needs_trip(e, origin):
            continue
        start = dt.datetime.fromisoformat(e["start"])
        if start < now:
            continue
        k = key(e, transport)
        entry = cache["entries"].get(k)
        if due(entry, start, now):
            if cache["lookups"] >= limit:
                notes.append(f"Reached today's {limit} Apple Maps lookups; '{e.get('title')}' uses an older answer or none.")
            else:
                cache["lookups"] += 1
                try:
                    got = ask(*lookup_args(e, origin, transport))
                    entry = {"minutes": int(got["minutes"]), "at": now.isoformat(timespec="minutes")}
                    cache["entries"][k] = entry
                except (RuntimeError, KeyError, TypeError, ValueError) as err:
                    notes.append(f"No travel time for '{e.get('title')}': {err}")
        if not entry:
            continue
        leave = start - dt.timedelta(minutes=entry["minutes"] + buffer)
        trips.append({"title": e.get("title") or "", "start": e["start"], "location": e.get("location") or "",
                      "minutes": entry["minutes"], "buffer": buffer, "leave_by": leave.isoformat(timespec="minutes"),
                      "checked": entry["at"], "late": leave < now})
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1))
    return {"trips": trips, "note": " ".join(notes) or None, "transport": transport}


def text(result: dict) -> str:
    lines = []
    for t in result["trips"]:
        leave = dt.datetime.fromisoformat(t["leave_by"])
        when = leave.strftime("%-I:%M %p").lower()
        lines.append(f"{'⚠️ Leave now' if t['late'] else 'Leave by ' + when} for {t['title']} "
                     f"({t['minutes']} min {result.get('transport', 'car')} + {t['buffer']})")
    if result.get("note"):
        lines.append(result["note"])
    return "\n".join(lines) or "No trips today."


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] != "day":
        print(__doc__)
        return 0 if len(argv) < 2 or argv[1] in ("-h", "--help") else 2
    day = dt.date.today()
    if "--date" in argv:
        day = dt.date.fromisoformat(argv[argv.index("--date") + 1])
    result = plan(day, load(WS / "config.json", {}))
    print(json.dumps(result, indent=1, ensure_ascii=False) if "--json" in argv else text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
