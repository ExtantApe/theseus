#!/usr/bin/env python3
"""
schedule.py: the user's daily rhythm (config.json → "schedule"), per day of the week.

  "schedule": {
    "style": "regimented",            # "regimented" (fixed times) or "fluid" (varies day to day; Theseus adapts)
    "groups": [
      {"name": "Weekdays", "days": ["mon","tue","wed","thu","fri"], "wake": "06:00", "bed": "00:00"},
      {"name": "Weekends", "days": ["sat","sun"],                   "wake": "08:00", "bed": "01:00"}
    ],
    "overrides": {"fri": {"bed": "02:00"}},   # optional single-day tweaks
    "flex_hours": 2,                        # how much later than usual they sometimes wake or sleep
    "morning_offset_minutes": -10,          # morning run relative to wake (fluid: relative to the EARLIEST wake)
    "nightly_offset_minutes": -150,         # nightly run relative to bed
    "adapt": true                           # learn actual wake/bed from activity (data/rhythm.json)
  }

For a fluid schedule, "wake"/"bed" mean the EARLIEST usual wake and the LATEST usual bed. The morning run lands at the earliest
time, and a "you're up" refresh happens on the first activity of the day (see changes.py).
Older configs with wake_time/bed_time/sleep_flex_hours still work.

CLI:  python3 engine/tools/schedule.py            today and tomorrow, as JSON
      python3 engine/tools/schedule.py --week     all 7 days
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

WS = Path(os.environ.get("THESEUS_HOME") or Path(__file__).resolve().parents[2])
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def load_cfg() -> dict:
    try:
        return json.loads((WS / "config.json").read_text())
    except Exception:
        return {}


def mins(hhmm: str) -> int:
    h, m = (int(x) for x in hhmm.split(":"))
    return (h * 60 + m) % 1440


def hhmm(m: int) -> str:
    m %= 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def normalize(c: dict) -> dict:
    s = c.get("schedule")
    if not s:   # legacy keys
        s = {"style": "regimented",
             "groups": [{"name": "Every day", "days": DAYS, "wake": c.get("wake_time", "07:00"),
                         "bed": c.get("bed_time", "23:00")}],
             "flex_hours": c.get("sleep_flex_hours", 1)}
        if c.get("morning_time"):
            s["morning_fixed"] = c["morning_time"]
        if c.get("nightly_time"):
            s["nightly_fixed"] = c["nightly_time"]
    s.setdefault("style", "regimented")
    s.setdefault("flex_hours", 1)
    s.setdefault("morning_offset_minutes", -10)
    s.setdefault("nightly_offset_minutes", -150)
    s.setdefault("overrides", {})
    return s


def day_plan(c: dict, d: dt.date) -> dict:
    s = normalize(c)
    key = DAYS[d.weekday()]
    wake, bed, group = "07:00", "23:00", None
    for g in s.get("groups", []):
        if key in g.get("days", []):
            wake, bed, group = g.get("wake", wake), g.get("bed", bed), g.get("name")
            break
    o = s["overrides"].get(key, {})
    wake, bed = o.get("wake", wake), o.get("bed", bed)
    w, b = mins(wake), mins(bed)
    flex = int(float(s["flex_hours"]) * 60)
    morning = mins(s["morning_fixed"]) if s.get("morning_fixed") else (w + s["morning_offset_minutes"]) % 1440
    nightly = mins(s["nightly_fixed"]) if s.get("nightly_fixed") else (b + s["nightly_offset_minutes"]) % 1440
    return {"date": d.isoformat(), "day": key, "group": group, "style": s["style"], "wake": hhmm(w), "bed": hhmm(b),
            "awake_until": hhmm(b + flex), "morning_run": hhmm(morning), "nightly_run": hhmm(nightly),
            "tonight_cutoff": hhmm(b - 60), "first_thing": hhmm(w + 20)}


def is_awake(c: dict, now: dt.datetime | None = None) -> bool:
    """True if `now` falls in today's awake window, or in last night's window if it runs past midnight."""
    now = now or dt.datetime.now()
    t = now.hour * 60 + now.minute
    for d, base in ((now.date(), 0), (now.date() - dt.timedelta(days=1), -1440)):
        p = day_plan(c, d)
        start = mins(p["wake"]) + base
        end = mins(p["awake_until"]) + base
        if end <= start:
            end += 1440
        if start <= t <= end:
            return True
    return False


# How long a missed briefing is still worth running, in hours. launchd runs a missed job when the Mac wakes; Theseus.app does the same with this.
CATCH_UP_HOURS = {"morning": 5, "nightly": 3}


def scheduled_at(c: dict, d: dt.date, job: str) -> dt.datetime:
    """When this day's run really happens. An evening run set after midnight belongs to the next calendar day."""
    p = day_plan(c, d)
    m = mins(p[f"{job}_run"])
    at = dt.datetime.combine(d, dt.time(m // 60, m % 60))
    return at + dt.timedelta(days=1) if job == "nightly" and m < mins(p["wake"]) else at


def already_ran(ws: Path, job: str, at: dt.datetime) -> bool:
    """Whichever host ran it left a log named with the start time, so this survives restarts and a change of host."""
    for pattern in (f"{job}-*.out", f"app-{job}-*.out"):
        for f in (ws / "logs").glob(pattern):
            m = re.search(r"\d{4}-\d{2}-\d{2}_\d{4}$", f.stem)
            if m and dt.datetime.strptime(m.group(), "%Y-%m-%d_%H%M") >= at:
                return True
    return False


def due(c: dict, ws: Path, now: dt.datetime | None = None) -> str | None:
    """The briefing that should run now, if any. Only the most recent one counts: waking at 6am runs the morning, not last night's prep too."""
    now = now or dt.datetime.now()
    found = []
    for job, hours in CATCH_UP_HOURS.items():
        for d in (now.date(), now.date() - dt.timedelta(days=1)):
            at = scheduled_at(c, d, job)
            if at <= now <= at + dt.timedelta(hours=hours):
                found.append((at, job))
    if not found:
        return None
    at, job = max(found)
    return None if already_ran(ws, job, at) else job


def runs_for_launchd(c: dict) -> dict[str, list[dict]]:
    """StartCalendarInterval entries per job, with launchd weekdays (0 = Sunday)."""
    out = {"morning": [], "nightly": []}
    base = dt.date(2024, 1, 1)   # a Monday
    for i in range(7):
        p = day_plan(c, base + dt.timedelta(days=i))
        wd = (i + 1) % 7
        for job, k in (("morning", "morning_run"), ("nightly", "nightly_run")):
            m = mins(p[k])
            day = wd
            if job == "nightly" and m < mins(p["wake"]):   # the evening run falls after midnight → it belongs to the next calendar day
                day = (wd + 1) % 7
            out[job].append({"Weekday": day, "Hour": m // 60, "Minute": m % 60})
    for job in out:   # collapse to a daily entry when every day is the same
        times = {(e["Hour"], e["Minute"]) for e in out[job]}
        if len(times) == 1:
            h, m = times.pop()
            out[job] = [{"Hour": h, "Minute": m}]
    return out


def main():
    c = load_cfg()
    if "due" in sys.argv:
        print(json.dumps({"due": due(c, Path(os.environ.get("THESEUS_HOME") or Path(__file__).resolve().parents[2]))}))
        return
    today = dt.date.today()
    n = 7 if "--week" in sys.argv else 2
    print(json.dumps({"style": normalize(c)["style"], "awake_now": is_awake(c),
                      "days": [day_plan(c, today + dt.timedelta(days=i)) for i in range(n)]}, indent=1))


if __name__ == "__main__":
    main()
