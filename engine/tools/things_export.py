#!/usr/bin/env python3
"""
things_export.py — one-time, READ-ONLY export of Things 3 for migration.

Reads Things' local database (snapshot copy; Things is never modified) and writes
  exports/things/things-open.md     everything still open, grouped Area → Project → Heading
  exports/things/things-open.json   same, structured (for Theseus to sort)
  exports/things/things-recent-done.md   completed in the last N days (context on your habits)

Usage: python3 tools/things_export.py [--done-days 60]
Needs Full Disk Access for the terminal app (same as Messages).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

WS = Path(os.environ.get("THESEUS_HOME") or Path(__file__).resolve().parents[2])   # ~/Theseus (workspace)
OUT = WS / "exports" / "things"
CACHE = WS / "cache"
GC = Path(os.environ.get("THINGS_GROUP_CONTAINER",
                         Path.home() / "Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac"))
START = {0: "Inbox", 1: "Anytime", 2: "Someday"}


def find_db() -> Path:
    pats = [str(GC / "ThingsData-*/Things Database.thingsdatabase/main.sqlite"),
            str(GC / "Things Database.thingsdatabase/main.sqlite")]
    hits = [Path(h) for p in pats for h in glob.glob(p)]
    if not hits:
        sys.exit(f"Things database not found under {GC}. Is Things 3 installed on this Mac and opened once?")
    return max(hits, key=lambda x: x.stat().st_mtime)


def snapshot(src: Path) -> sqlite3.Connection:
    CACHE.mkdir(parents=True, exist_ok=True)
    dst = CACHE / "things-snapshot.db"
    try:
        s = sqlite3.connect(src.as_uri() + "?mode=ro", uri=True)
        d = sqlite3.connect(str(dst)); s.backup(d); s.close()
    except sqlite3.Error as e:
        sys.exit(f"Could not read Things DB ({e}). Grant Full Disk Access to your terminal app.")
    d.row_factory = sqlite3.Row
    return d


def things_date(v):
    """Things stores dates either packed (y<<16|m<<12|d<<7) or as unix seconds."""
    if v in (None, 0, ""):
        return None
    v = int(v)
    if v < 200_000_000:
        y, m, d = v >> 16, (v >> 12) & 0xF, (v >> 7) & 0x1F
        try:
            return dt.date(y, m, d)
        except ValueError:
            return None
    return dt.datetime.fromtimestamp(v).date()


def ts(v):
    return dt.datetime.fromtimestamp(float(v)) if v else None


def cols(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--done-days", type=int, default=60)
    a = ap.parse_args()
    con = snapshot(find_db())
    tc = cols(con, "TMTask")
    q = lambda c, alias=None: (c if c in tc else "NULL") + f" AS {alias or c}"  # noqa
    rows = con.execute(f"""SELECT uuid, title, {q('notes')}, type, status, trashed, {q('start')},
        {q('startDate')}, {q('deadline')}, {q('area')}, {q('project')}, {q('heading')},
        {q('creationDate')}, {q('stopDate')}, {q('"index"', 'idx')}, {q('todayIndex')}
        FROM TMTask WHERE trashed = 0""").fetchall()
    areas = {r["uuid"]: r["title"] for r in con.execute("SELECT uuid, title FROM TMArea")}
    tags = defaultdict(list)
    try:
        for t_uuid, title in con.execute(
                "SELECT tt.tasks, t.title FROM TMTaskTag tt JOIN TMTag t ON t.uuid = tt.tags"):
            tags[t_uuid].append(title)
    except sqlite3.Error:
        pass
    checklist = defaultdict(list)
    try:
        for r in con.execute('SELECT task, title, status FROM TMChecklistItem ORDER BY "index"'):
            checklist[r["task"]].append({"title": r["title"], "done": r["status"] == 3})
    except sqlite3.Error:
        pass

    by_id = {r["uuid"]: r for r in rows}
    today = dt.date.today()

    def bucket(r):
        sd = things_date(r["startDate"])
        if r["start"] == 0:
            return "Inbox"
        if r["start"] == 2:
            return "Someday"
        if sd and sd <= today:
            return "Today"
        if sd and sd > today:
            return f"Upcoming ({sd:%Y-%m-%d})"
        return "Anytime"

    def item(r):
        proj = by_id.get(r["project"]) if r["project"] else None
        head = by_id.get(r["heading"]) if r["heading"] else None
        if head and not proj and head["project"]:
            proj = by_id.get(head["project"])
        area_id = r["area"] or (proj["area"] if proj else None)
        return {
            "id": r["uuid"], "title": r["title"], "notes": (r["notes"] or "").strip(),
            "area": areas.get(area_id) if area_id else None,
            "project": proj["title"] if proj else None, "heading": head["title"] if head else None,
            "when": bucket(r), "deadline": str(things_date(r["deadline"]) or "") or None,
            "tags": tags.get(r["uuid"], []), "checklist": checklist.get(r["uuid"], []),
            "created": ts(r["creationDate"]).isoformat() if r["creationDate"] else None,
            "completed": ts(r["stopDate"]).isoformat() if r["stopDate"] else None,
        }

    todos = [r for r in rows if r["type"] == 0]
    open_items = [item(r) for r in todos if r["status"] == 0]
    cutoff = dt.datetime.now() - dt.timedelta(days=a.done_days)
    done_items = [item(r) for r in todos if r["status"] == 3 and r["stopDate"] and ts(r["stopDate"]) >= cutoff]
    open_projects = [r["title"] for r in rows if r["type"] == 1 and r["status"] == 0]

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "things-open.json").write_text(json.dumps(
        {"exported": dt.datetime.now().isoformat(), "open_projects": open_projects,
         "areas": sorted(set(areas.values())), "items": open_items}, indent=1, ensure_ascii=False))

    grouped = defaultdict(lambda: defaultdict(list))
    for it in open_items:
        grouped[it["area"] or "(no area)"][it["project"] or "(loose to-dos)"].append(it)
    lines = [f"# Things — open items ({len(open_items)})", f"_Exported {dt.datetime.now():%Y-%m-%d %H:%M}_", ""]
    for area in sorted(grouped):
        lines.append(f"## {area}")
        for proj in sorted(grouped[area]):
            lines.append(f"### {proj}")
            for it in grouped[area][proj]:
                meta = [it["when"]]
                if it["deadline"]:
                    meta.append(f"deadline {it['deadline']}")
                if it["heading"]:
                    meta.append(f"under '{it['heading']}'")
                if it["tags"]:
                    meta.append("tags " + ", ".join(it["tags"]))
                lines.append(f"- [ ] {it['title']}  _({'; '.join(meta)})_")
                if it["notes"]:
                    lines.append("  - notes: " + it["notes"].replace("\n", " ⏎ ")[:400])
                for c in it["checklist"]:
                    lines.append(f"  - [{'x' if c['done'] else ' '}] {c['title']}")
            lines.append("")
    (OUT / "things-open.md").write_text("\n".join(lines))
    done_lines = [f"# Things — completed in last {a.done_days} days ({len(done_items)})", ""]
    for it in sorted(done_items, key=lambda x: x["completed"] or ""):
        done_lines.append(f"- {it['completed'][:10]} · {it['title']} · {it['area'] or ''} {('/ ' + it['project']) if it['project'] else ''}")
    (OUT / "things-recent-done.md").write_text("\n".join(done_lines) + "\n")
    print(f"Things export: {len(open_items)} open to-dos, {len(open_projects)} open projects, "
          f"{len(areas)} areas, {len(done_items)} completed in last {a.done_days}d → {OUT}")


if __name__ == "__main__":
    main()
