#!/usr/bin/env python3
"""
app_edits.py: hands what the user did in Theseus.app to a sync, without losing anything done meanwhile.

  take   move data/app-edits.jsonl aside and print its events. The app starts a new file, so anything done from now on waits for the next sync.
         A batch left by a run that died is included.
  done   the batch has been carried out: file it in data/archive/app-edits-YYYY-MM.jsonl
"""
import datetime as dt
import json
import os
import sys
import uuid
from pathlib import Path

WS = Path(os.environ.get("THESEUS_HOME") or Path(__file__).resolve().parents[2])
LIVE = WS / "data/app-edits.jsonl"


def batches():
    return sorted((WS / "data").glob("app-edits.processing-*.jsonl"))


def take():
    if LIVE.exists() and LIVE.stat().st_size:
        os.replace(LIVE, WS / "data" / f"app-edits.processing-{dt.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.jsonl")
    events = []
    for p in batches():
        for line in p.read_text().splitlines():
            try:
                if line.strip():
                    events.append(json.loads(line))
            except ValueError:
                pass   # a torn last line from a crash
    print(json.dumps({"events": events}, indent=1, ensure_ascii=False))


def done():
    done_count = 0
    if batches():
        archive = WS / "data/archive" / f"app-edits-{dt.date.today():%Y-%m}.jsonl"
        archive.parent.mkdir(parents=True, exist_ok=True)
        for p in batches():
            with open(archive, "a") as f:
                f.write(p.read_text())
            p.unlink()
            done_count += 1
    print(json.dumps({"filed_batches": done_count}))


if __name__ == "__main__":
    {"take": take, "done": done}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
