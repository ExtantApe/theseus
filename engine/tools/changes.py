#!/usr/bin/env python3
"""
changes.py: cheap, local "did anything change?" gate for frequent checks. It does NOT call Claude.

Computes a small fingerprint per source and compares it with the last run's (data/check-state.json).
Exit code 0 = run Claude (something changed, or a full refresh is due, and the cooldown has passed).
Exit code 10 = skip (nothing changed, outside awake hours, near the morning/nightly run, or cooling down; changes seen during the
cooldown are remembered and handled on the next allowed run).

Sources (only enabled integrations): texts (newest message id), Notes inbox + pinned Today note (modification dates),
Reminders and today's Calendar (content hash via bin/ek), iPhone alarms file (mtime), Apple Mail (newest message id), things done in Theseus.app.
Email via connectors can't be checked locally, so it's covered by the periodic full refresh.

A change stays on the books until the run it started has finished: the host calls --ack after a successful sync. If that run fails, or never
starts because something else was running, the change is handled by the next one instead of waiting for the hourly refresh.

Usage: python3 engine/tools/changes.py [--explain] [--force] | --ack
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

WS = Path(os.environ.get("THESEUS_HOME") or Path(__file__).resolve().parents[2])
STATE = WS / "data" / "check-state.json"
HOME = Path.home()


def cfg() -> dict:
    try:
        return json.loads((WS / "config.json").read_text())
    except Exception:
        return {}


def on(c, name) -> bool:
    return bool((c.get("integrations") or {}).get(name))


def sql_scalar(path: Path, q: str):
    try:
        con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        v = con.execute(q).fetchone()[0]
        con.close()
        return v
    except Exception as e:
        return f"err:{type(e).__name__}"


def run(cmd: list[str], timeout=60) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=WS)
        return p.stdout if p.returncode == 0 else f"err:{p.returncode}"
    except Exception as e:
        return f"err:{type(e).__name__}"


def h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def write_json(path: Path, obj):
    """Whole or not at all: several programs read these files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=1))
    os.replace(tmp, path)


NOTES_JXA = r"""
function run(argv){const r=JSON.parse(argv[0]);const N=Application('Notes');let out=[];
 try{const a=N.accounts.byName(r.account);const f=a.folders.byName(r.inbox);
   out.push('inbox:'+f.notes.length+':'+f.notes.modificationDate().map(d=>d.getTime()).join(','));}catch(e){out.push('inbox:none');}
 if(r.today_id){try{const t=N.notes.byId(r.today_id).modificationDate().getTime();out.push('today:'+(t===r.today_written?'as-written':t));}catch(e){out.push('today:none');}}
 return out.join('|');}
"""


def fingerprint(c: dict, prev_state: dict, extra: dict) -> dict[str, str]:
    fp: dict[str, str] = {}
    if on(c, "texts"):
        db = Path(os.environ.get("IMSG_CHAT_DB", HOME / "Library/Messages/chat.db"))
        # newest message + how many are unread + latest read time: catches new texts, and texts you read or answered on your phone
        parts = [str(sql_scalar(db, "SELECT MAX(ROWID) FROM message")),
                 str(sql_scalar(db, "SELECT SUM(CASE WHEN is_read=0 AND is_from_me=0 THEN 1 ELSE 0 END) FROM message")),
                 str(sql_scalar(db, "SELECT MAX(date_read) FROM message"))]     # each part independent: a missing column can't blank the rest
        fp["texts"] = h(":".join(parts))
    if on(c, "notes"):
        # Cheap first: has the Notes database changed at all? Only then ask Notes (precise check) whether the
        # inbox folder or the Today note changed. This way the Notes app isn't launched every few minutes.
        store = HOME / "Library/Group Containers/group.com.apple.notes"
        mt = max((p.stat().st_mtime for p in store.glob("NoteStore.sqlite*")), default=0)
        prev_fp = (prev_state.get("fp") or {})
        if prev_fp.get("notes") and prev_state.get("notes_store_mtime") == mt:
            fp["notes"] = prev_fp["notes"]
        else:
            today_id = written = None
            try:
                st = json.loads((WS / "data/state.json").read_text())
                rec = st.get("note:" + c.get("today_note_title", "📌 Today")) or {}
                today_id, written = rec.get("id"), rec.get("modified_ms")
            except Exception:
                pass
            # Theseus's own publish changes the note's date. notes.py records that date, so only someone else's edit counts as a change.
            req = json.dumps({"account": c.get("notes_account", "iCloud"), "inbox": c.get("notes_inbox_folder", "Theseus"),
                              "today_id": today_id, "today_written": written})
            seen = run(["osascript", "-l", "JavaScript", "-e", NOTES_JXA, req])
            # Notes being slow isn't a change.
            fp["notes"] = prev_fp["notes"] if seen.startswith("err:") and prev_fp.get("notes") else h(seen)
        extra["notes_store_mtime"] = mt
    ek = WS / "bin/ek"
    if on(c, "reminders") and ek.exists():
        out = run([str(ek), "reminders", "--completed-since", "1d"])
        try:  # ignore volatile fields; keep ids, titles, due, completion
            items = sorted((r["id"], r["title"], str(r["due"]), r["completed"], r["list"]) for r in json.loads(out))
            fp["reminders"] = h(json.dumps(items))
        except Exception:
            fp["reminders"] = h(out)
    if on(c, "calendar") and c.get("calendar_source", "apple") == "apple" and ek.exists():
        out = run([str(ek), "events", "--from", "today", "--to", "tomorrow"])
        try:
            fp["calendar"] = h(json.dumps(sorted((e["id"], e["title"], e["start"], e["end"]) for e in json.loads(out))))
        except Exception:
            fp["calendar"] = h(out)
    if on(c, "iphone_alarms"):
        p = HOME / "Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents" / c.get("alarms_file", "theseus-alarms.txt")
        fp["alarms"] = str(int(p.stat().st_mtime)) if p.exists() else "none"
    if on(c, "email") and c.get("email_source") == "apple_mail":
        root = Path(os.environ.get("THESEUS_MAIL_ROOT", HOME / "Library/Mail"))
        vs = sorted(root.glob("V[0-9]*"))
        if vs:
            fp["mail"] = str(sql_scalar(vs[-1] / "MailData/Envelope Index", "SELECT MAX(ROWID) FROM messages"))
    # Things done in Theseus.app wait for a sync to reach Reminders and the rest. The sync empties this file.
    edits = [WS / "data" / "app-edits.jsonl", *sorted((WS / "data").glob("app-edits.processing-*.jsonl"))]
    size = sum(p.stat().st_size for p in edits if p.exists())
    if size:
        fp["app"] = h(str(size))
    return fp


sys.path.insert(0, str(Path(__file__).resolve().parent))
import schedule as sched  # noqa: E402


def in_window(c: dict, chk: dict) -> tuple[bool, str]:
    """Awake window (per day of the week) and quiet zones around today's morning and nightly runs."""
    import datetime as _dt
    now = _dt.datetime.now()
    t = now.hour * 60 + now.minute
    p = sched.day_plan(c, now.date())
    for k in ("morning_run", "nightly_run"):
        b = sched.mins(p[k])
        if min(abs(t - b), 1440 - abs(t - b)) < 10:
            return False, f"within 10 min of the {k.split('_')[0]} run"
    if not chk.get("only_while_awake", True):
        return True, ""
    return (True, "") if sched.is_awake(c, now) else (False, "outside awake hours")


def log_rhythm(c: dict, now: float, changed: list[str]):
    """For adaptive schedules: remember the first and last activity per day (data/rhythm.json, last 60 days)."""
    if not (sched.normalize(c).get("adapt", True) and changed):
        return
    import datetime as _dt
    p = WS / "data" / "rhythm.json"
    try:
        r = json.loads(p.read_text())
    except Exception:
        r = {}
    t = _dt.datetime.fromtimestamp(now)
    day = (t - _dt.timedelta(hours=4)).date().isoformat()   # activity before 4am counts toward the previous day
    rec = r.setdefault(day, {"first": t.strftime("%H:%M"), "last": t.strftime("%H:%M")})
    rec["last"] = t.strftime("%H:%M")
    for k in sorted(r)[:-60]:
        r.pop(k)
    write_json(p, r)


def refresh_copies(c: dict, changed: list[str]):
    """This check runs from /bin/bash, which has Full Disk Access. Claude Code sessions may not, so they read the saved copies
    in cache/. Refresh them whenever texts or mail changed, and at least every 30 minutes."""
    jobs = []
    snap = WS / "cache" / "chat-snapshot.db"
    stale = not snap.exists() or time.time() - snap.stat().st_mtime > 1800
    if on(c, "texts") and ("texts" in changed or stale):
        jobs.append([sys.executable, str(WS / "engine/tools/imsg.py"), "--fresh", "doctor"])
    if on(c, "email") and c.get("email_source") == "apple_mail" and "mail" in changed:
        jobs.append([sys.executable, str(WS / "engine/tools/mail.py"), "--fresh", "doctor"])
    for cmd in jobs:
        try:
            subprocess.run(cmd, cwd=WS, capture_output=True, timeout=120)
        except Exception:
            pass


def ack():
    """The last sync finished, so what it was started for has been handled."""
    try:
        st = json.loads(STATE.read_text())
    except Exception:
        return
    st["claimed"] = []
    st["last_full"] = time.time()   # any finished sync is a full refresh
    write_json(STATE, st)


def main():
    if "--ack" in sys.argv:
        return ack()
    explain = "--explain" in sys.argv
    force = "--force" in sys.argv
    c = cfg()
    chk = c.get("checks") or {}
    ok, why = in_window(c, chk)
    if not ok and not force:
        print(why)
        sys.exit(10)
    full_every = int(chk.get("full_refresh_every_minutes", 60)) * 60
    cooldown = int(chk.get("min_minutes_between_claude_runs", 15)) * 60
    try:
        prev = json.loads(STATE.read_text())
    except Exception:
        prev = {}
    now = time.time()
    extra: dict = {}
    fp = fingerprint(c, prev, extra)
    changed = sorted(k for k in fp if fp[k] != (prev.get("fp") or {}).get(k))
    claimed = prev.get("claimed", [])                                  # given to a run that hasn't finished (or that failed)
    pending = sorted(set(prev.get("pending", [])) | set(changed))      # seen, and not yet given to a run
    waiting = sorted(set(pending) | set(claimed))
    full_due = now - prev.get("last_full", 0) >= full_every
    cooled = now - prev.get("last_claude", 0) >= cooldown
    want = force or bool(waiting) or full_due or not chk.get("skip_if_nothing_changed", True)
    quiet_hours = (now - prev.get("last_activity", now)) / 3600
    first_activity = bool(changed) and quiet_hours >= 4          # first sign of life after a long quiet stretch
    run_claude = force or first_activity or (want and cooled)
    if run_claude:
        reason = ("forced" if force else
                  f"first activity after {quiet_hours:.0f}h quiet (you're up): " + ", ".join(waiting) if first_activity else
                  "changed: " + ", ".join(waiting) if waiting else "full refresh due")
    elif want:
        reason = f"waiting (cooldown): {', '.join(waiting) or 'full refresh'}"
    else:
        reason = "nothing changed"
    write_json(STATE, {
        "fp": fp, "last_check": now, "last_reason": reason, **extra,
        "pending": [] if run_claude else pending,
        "claimed": waiting if run_claude else claimed,
        "last_claude": now if run_claude else prev.get("last_claude", 0),
        "last_full": prev.get("last_full", 0),
        "last_activity": now if changed else prev.get("last_activity", now),
    })
    log_rhythm(c, now, changed)
    refresh_copies(c, changed)
    if explain:
        print(json.dumps({"run_claude": run_claude, "reason": reason, "changed_now": changed,
                          "fingerprint": fp}, indent=1))
    else:
        print(reason)
    sys.exit(0 if run_claude else 10)


if __name__ == "__main__":
    main()
