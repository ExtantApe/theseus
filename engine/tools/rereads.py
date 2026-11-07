#!/usr/bin/env python3
"""
rereads.py: when a quiet sync should read connected services.

ClickUp and other connectors have limits, so frequent syncs don't read them every time. They're read at the times in
config.json "reread_times" (default noon and 4pm), and by /morning, /nightly and /refresh, which always read them.

  python3 engine/tools/rereads.py due    JSON: {"due": true/false, "last": "...", "next": "16:00"}
  python3 engine/tools/rereads.py done   record that they were just read

A missing or unreadable record counts as never read, so the worst case is one extra read.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

WS = Path(os.environ.get("THESEUS_HOME") or Path(__file__).resolve().parents[2])
RECORD = WS / "data" / "reread-state.json"
DEFAULT_TIMES = ["12:00", "16:00"]


def set_times(cfg: dict) -> list:
    """Sorted (hour, minute) pairs. Bad entries are ignored; if none are left, the defaults apply."""
    raw = cfg.get("reread_times")
    found = []
    for t in raw if isinstance(raw, list) else []:
        m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", t) if isinstance(t, str) else None
        if m:
            found.append((int(m.group(1)), int(m.group(2))))
    return sorted(set(found)) or [tuple(int(x) for x in t.split(":")) for t in DEFAULT_TIMES]


def is_due(times: list, last, now: dt.datetime) -> bool:
    """Due if never read, or if today's latest set time has passed since the last read."""
    if last is None:
        return True
    passed = [now.replace(hour=h, minute=m, second=0, microsecond=0) for h, m in times if (h, m) <= (now.hour, now.minute)]
    return bool(passed) and last < passed[-1]


def next_time(times: list, now: dt.datetime):
    later = [f"{h:02d}:{m:02d}" for h, m in times if (h, m) > (now.hour, now.minute)]
    return later[0] if later else None


def read_last():
    try:
        return dt.datetime.fromisoformat(json.loads(RECORD.read_text())["last"])
    except Exception:
        return None


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    now = dt.datetime.now()
    if cmd == "done":
        RECORD.parent.mkdir(parents=True, exist_ok=True)
        tmp = RECORD.with_name(f".{RECORD.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"last": now.isoformat(timespec="seconds")}))
        os.replace(tmp, RECORD)
    elif cmd == "due":
        try:
            cfg = json.loads((WS / "config.json").read_text())
        except Exception:
            cfg = {}
        times, last = set_times(cfg), read_last()
        print(json.dumps({"due": is_due(times, last, now), "last": last.isoformat(timespec="minutes") if last else None,
                          "next": next_time(times, now)}))
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
