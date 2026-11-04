#!/usr/bin/env python3
"""
imsg.py — READ-ONLY toolkit for macOS Messages (iMessage + SMS/RCS).

It never writes to your real Messages database and has no ability to send.
It works from a snapshot copy of ~/Library/Messages/chat.db (taken with
SQLite's backup API, so the WAL file is included) and matches phone
numbers / emails to names from your Contacts database.

Subcommands
  doctor        check permissions, paths, contacts, and your own handles
  sync-status   how complete is the local history? (compare to iCloud count)
  chats         list recent conversations
  missed        conversations where someone is waiting on you
  thread        last N messages with one person/group (for drafting replies)
  export        full transcript (md / csv / jsonl), optional split by month/year
  search        keyword / regex search across everything or one person
  stats         volume, response times, silences for one conversation
  style         sample of YOUR sent messages + habits (to learn your voice)
  who           resolve a name/number to conversations

Run `python3 imsg.py <cmd> -h` for options. Python 3.9+ stdlib only.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import platform
import re
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HOME = Path.home()
WS = Path(os.environ.get("THESEUS_HOME") or Path(__file__).resolve().parents[2])   # ~/Theseus (workspace)
CACHE = WS / "cache"
EXPORTS = WS / "exports"
CONFIG_PATH = WS / "config.json"
CHAT_DB = Path(os.environ.get("IMSG_CHAT_DB", HOME / "Library/Messages/chat.db"))
AB_DIR = Path(os.environ.get("IMSG_AB_DIR", HOME / "Library/Application Support/AddressBook"))
APPLE_EPOCH = 978307200  # 2001-01-01 UTC

REACTIONS = {2000: "loved", 2001: "liked", 2002: "disliked", 2003: "laughed at",
             2004: "emphasized", 2005: "questioned", 2006: "reacted to", 2007: "stickered"}
AUTOMATED_RE = re.compile(
    r"(verification code|security code|your code is|\bOTP\b|reply stop|text stop|"
    r"msg ?& ?data rates|unsubscribe|do not reply|no-reply|noreply|one-time (pass)?code|"
    r"appointment reminder|your order|has shipped|delivery|tracking)", re.I)

# ----------------------------------------------------------------- utilities

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception as e:  # noqa
            print(f"warning: config.json unreadable ({e}); using defaults", file=sys.stderr)
    return {}


def die_access(err: Exception, what: str):
    print(f"""
ERROR: could not read {what}: {err}

This almost always means Full Disk Access is missing.
Fix: System Settings → Privacy & Security → Full Disk Access →
     turn ON the app you run Claude Code in (Terminal, iTerm, Ghostty,
     VS Code...). For the scheduled morning job also add /bin/bash
     (press ⌘⇧G in the file picker and type /bin/bash).
Then fully quit and reopen that app.
""", file=sys.stderr)
    sys.exit(2)


def snapshot(src: Path, dst: Path, max_age_min: float, fresh: bool) -> Path:
    """Copy a live SQLite db (incl. WAL) to dst via the backup API, read-only."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not fresh and (time.time() - dst.stat().st_mtime) < max_age_min * 60:
        return dst
    tmp = dst.with_suffix(".tmp")
    try:
        if not src.exists():          # may itself raise PermissionError when macOS blocks the folder
            raise sqlite3.OperationalError(f"{src} not found")
        s = sqlite3.connect(src.as_uri() + "?mode=ro", uri=True, timeout=10)
        d = sqlite3.connect(str(tmp))
        s.backup(d)
        d.close(); s.close()
        os.replace(tmp, dst)
    except (sqlite3.Error, OSError) as e:
        if tmp.exists():
            tmp.unlink()
        if dst.exists():
            # No direct access here (e.g. inside a Claude Code session without Full Disk Access): fall back to the copy the
            # background checks keep fresh.
            age = (time.time() - dst.stat().st_mtime) / 60
            print(f"note: using the saved copy of {src.name} from {age:.0f} min ago (no direct access: {e}). "
                  f"The background checks refresh it every few minutes.", file=sys.stderr)
            return dst
        die_access(e, str(src))
    return dst


def apple_dt(v) -> dt.datetime | None:
    if not v:
        return None
    v = int(v)
    secs = v / 1e9 if abs(v) > 1e11 else v
    return dt.datetime.fromtimestamp(secs + APPLE_EPOCH).astimezone()


def to_apple(d: dt.datetime) -> int:
    return int((d.timestamp() - APPLE_EPOCH) * 1e9)


def parse_date(s: str | None, end=False) -> dt.datetime | None:
    if not s:
        return None
    s = s.strip().lower()
    now = dt.datetime.now().astimezone()
    m = re.fullmatch(r"(\d+)\s*([dwmy])", s)  # 7d, 2w, 6m, 3y  (relative)
    if m:
        n, u = int(m.group(1)), m.group(2)
        days = {"d": 1, "w": 7, "m": 30.44, "y": 365.25}[u] * n
        return now - dt.timedelta(days=days)
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            d = dt.datetime.strptime(s, fmt).astimezone()
            if end:
                if fmt == "%Y":
                    d = d.replace(year=d.year + 1)
                elif fmt == "%Y-%m":
                    d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
                else:
                    d = d + dt.timedelta(days=1)
            return d
        except ValueError:
            pass
    sys.exit(f"Could not parse date '{s}'. Use YYYY-MM-DD, YYYY-MM, YYYY, or 7d/2w/6m/3y.")


def decode_attributed_body(blob: bytes | None) -> str | None:
    """Extract plain text from the NSAttributedString 'typedstream' blob."""
    if not blob:
        return None
    try:
        i = blob.find(b"NSString")
        if i < 0:
            return None
        j = blob.find(b"\x2b", i + 8)          # '+' marks the C-string payload
        if j < 0 or j - i > 20:
            return None
        j += 1
        n = blob[j]
        if n == 0x81:
            length, start = int.from_bytes(blob[j + 1:j + 3], "little"), j + 3
        elif n == 0x82:
            length, start = int.from_bytes(blob[j + 1:j + 5], "little"), j + 5
        else:
            length, start = n, j + 1
        txt = blob[start:start + length].decode("utf-8", errors="replace")
        return txt.replace("￼", "").strip() or None   # strip attachment placeholder
    except Exception:
        return None


def norm_handle(h: str | None) -> str:
    if not h:
        return ""
    h = h.strip()
    if "@" in h:
        return h.lower()
    digits = re.sub(r"\D", "", h)
    if len(digits) >= 10:
        return digits[-10:]
    return digits or h.lower()


def pretty_handle(h: str) -> str:
    d = re.sub(r"\D", "", h or "")
    if "@" not in (h or "") and len(d) in (10, 11):
        d = d[-10:]
        return f"({d[:3]}) {d[3:6]}-{d[6:]}"
    return h or "?"


def is_shortcode(h: str) -> bool:
    d = re.sub(r"\D", "", h or "")
    return "@" not in (h or "") and 3 <= len(d) <= 6


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "conversation"


def fmt_age(d: dt.datetime) -> str:
    secs = (dt.datetime.now().astimezone() - d).total_seconds()
    if secs < 3600:
        return f"{int(secs // 60)}m"
    if secs < 86400:
        return f"{int(secs // 3600)}h"
    return f"{int(secs // 86400)}d"

# ------------------------------------------------------------------ contacts

class Contacts:
    def __init__(self, fresh=False, max_age=60):
        self.by_key: dict[str, str] = {}
        cfg = load_config()
        dbs = []
        if AB_DIR.exists():
            dbs = sorted(AB_DIR.glob("AddressBook-v22.abcddb")) + \
                  sorted(AB_DIR.glob("Sources/*/AddressBook-v22.abcddb"))
        for n, src in enumerate(dbs):
            try:
                snap = snapshot(src, CACHE / f"contacts-{n}.db", max_age, fresh)
                self._load(snap)
            except SystemExit:
                raise
            except Exception as e:  # noqa
                print(f"warning: skipped contacts db {src}: {e}", file=sys.stderr)
        for k, v in (cfg.get("contact_overrides") or {}).items():
            self.by_key[norm_handle(k)] = v
        self.source_count = len(dbs)

    def _load(self, path: Path):
        con = sqlite3.connect(str(path))
        names = {}
        for pk, first, last, nick, org in con.execute(
                "SELECT Z_PK, ZFIRSTNAME, ZLASTNAME, ZNICKNAME, ZORGANIZATION FROM ZABCDRECORD"):
            full = " ".join(x for x in (first, last) if x) or nick or org
            if full:
                names[pk] = full.strip()
        for owner, num in con.execute("SELECT ZOWNER, ZFULLNUMBER FROM ZABCDPHONENUMBER"):
            if owner in names and num:
                self.by_key.setdefault(norm_handle(num), names[owner])
        for owner, addr in con.execute("SELECT ZOWNER, ZADDRESS FROM ZABCDEMAILADDRESS"):
            if owner in names and addr:
                self.by_key.setdefault(norm_handle(addr), names[owner])
        con.close()

    def name(self, handle: str | None) -> str | None:
        return self.by_key.get(norm_handle(handle or ""))

    def label(self, handle: str | None) -> str:
        return self.name(handle) or pretty_handle(handle or "")

# ---------------------------------------------------------------- database

class Messages:
    def __init__(self, fresh=False, max_age=5, contacts_fresh=False):
        self.db_path = snapshot(CHAT_DB, CACHE / "chat-snapshot.db", max_age, fresh)
        self.con = sqlite3.connect(str(self.db_path))
        self.con.row_factory = sqlite3.Row
        self.mcols = {r[1] for r in self.con.execute("PRAGMA table_info(message)")}
        self.ccols = {r[1] for r in self.con.execute("PRAGMA table_info(chat)")}
        self.contacts = Contacts(fresh=contacts_fresh)
        self.cfg = load_config()
        self.my_handles = self._my_handles()
        self._convs = None

    # --- identity
    def _my_handles(self) -> set[str]:
        hs = {norm_handle(h) for h in self.cfg.get("my_handles", [])}
        if "destination_caller_id" in self.mcols:
            for (h,) in self.con.execute(
                    "SELECT DISTINCT destination_caller_id FROM message "
                    "WHERE is_from_me=1 AND destination_caller_id IS NOT NULL"):
                hs.add(norm_handle(h))
        if "account" in self.mcols:
            for (a,) in self.con.execute("SELECT DISTINCT account FROM message WHERE account IS NOT NULL"):
                if len(a) > 2 and a[1] == ":":
                    hs.add(norm_handle(a[2:]))
        hs.discard("")
        return hs

    # --- conversations (merges a person's iMessage/SMS/email threads)
    def conversations(self) -> list[dict]:
        if self._convs is not None:
            return self._convs
        parts = defaultdict(list)
        for chat_id, h in self.con.execute(
                "SELECT chj.chat_id, h.id FROM chat_handle_join chj JOIN handle h ON h.ROWID=chj.handle_id"):
            parts[chat_id].append(h)
        stats = {r[0]: (r[1], r[2]) for r in self.con.execute(
            "SELECT cmj.chat_id, COUNT(*), MAX(m.date) FROM chat_message_join cmj "
            "JOIN message m ON m.ROWID=cmj.message_id GROUP BY cmj.chat_id")}
        style_col = "style" if "style" in self.ccols else "NULL"
        groups: dict[str, dict] = {}
        for r in self.con.execute(
                f"SELECT ROWID, chat_identifier, display_name, {style_col} AS style, service_name FROM chat"):
            cid = r["ROWID"]
            p = parts.get(cid, [])
            is_group = (r["style"] == 43) or len(p) > 1 or (r["chat_identifier"] or "").startswith("chat")
            if is_group:
                key = f"group:{cid}"
                names = [self.contacts.label(x) for x in p]
                label = r["display_name"] or ", ".join(names[:4]) + (" +" + str(len(names) - 4) if len(names) > 4 else "")
            else:
                h = p[0] if p else r["chat_identifier"]
                nm = self.contacts.name(h)
                key = f"person:{nm.lower()}" if nm else f"handle:{norm_handle(h)}"
                label = nm or pretty_handle(h)
                names = [label]
            g = groups.setdefault(key, {"key": key, "label": label, "chat_ids": [], "is_group": is_group,
                                        "participants": names, "handles": set(), "count": 0,
                                        "last": None, "services": set(), "identifiers": []})
            g["chat_ids"].append(cid)
            g["handles"].update(norm_handle(x) for x in (p or [r["chat_identifier"]]))
            g["services"].add(r["service_name"] or "?")
            g["identifiers"].append(r["chat_identifier"])
            cnt, last = stats.get(cid, (0, None))
            g["count"] += cnt
            if last and (g["last"] is None or last > g["last"]):
                g["last"] = last
        out = []
        for g in groups.values():
            g["self_chat"] = (not g["is_group"]) and bool(g["handles"]) and g["handles"] <= self.my_handles
            g["automated"] = (not g["is_group"]) and any(is_shortcode(i or "") or "noreply" in (i or "").lower()
                                                         for i in g["identifiers"])
            g["last_dt"] = apple_dt(g["last"])
            g["handles"] = sorted(g["handles"])
            g["services"] = sorted(g["services"])
            out.append(g)
        out.sort(key=lambda g: g["last"] or 0, reverse=True)
        self._convs = out
        return out

    def resolve(self, who: str) -> list[dict]:
        convs = self.conversations()
        w = who.strip()
        if w.isdigit() and any(w == str(c) for g in convs for c in g["chat_ids"]) and len(w) < 7:
            return [g for g in convs if int(w) in g["chat_ids"]]
        nh = norm_handle(w)
        exact = [g for g in convs if g["label"].lower() == w.lower() or (nh and nh in g["handles"])]
        if exact:
            return exact
        wl = w.lower()
        return [g for g in convs if wl in g["label"].lower()
                or any(wl in p.lower() for p in g["participants"])]

    def pick(self, who: str) -> dict:
        m = self.resolve(who)
        if not m:
            sys.exit(f"No conversation matches '{who}'. Try `imsg.py who \"{who}\"` or `imsg.py chats`.")
        if len(m) > 1:
            exact = [g for g in m if g["label"].lower() == who.lower()]
            if len(exact) == 1:
                return exact[0]
            people = [g for g in m if not g["is_group"] and who.lower() in g["label"].lower()]
            if len(people) == 1:          # "Sam" → Sam Rivera, not a group Sam is in
                return people[0]
            print(f"'{who}' matches {len(m)} conversations — rerun with the exact label or chat id:", file=sys.stderr)
            for g in m[:25]:
                print(f"  - {g['label']!r}  (chat ids {','.join(map(str, g['chat_ids']))}, "
                      f"{g['count']} msgs, last {g['last_dt']:%Y-%m-%d})" if g['last_dt'] else
                      f"  - {g['label']!r} (chat ids {g['chat_ids']})", file=sys.stderr)
            sys.exit(3)
        return m[0]

    # --- messages
    def messages(self, chat_ids, since=None, until=None, include_reactions=True) -> list[dict]:
        opt = lambda c: f"m.{c}" if c in self.mcols else f"NULL AS {c}"  # noqa
        q = f"""SELECT m.ROWID AS rowid, m.guid, m.text, m.attributedBody, m.is_from_me, m.date,
                   m.is_read, h.id AS sender, m.associated_message_type AS atype,
                   m.associated_message_guid AS aguid, m.item_type, m.cache_has_attachments,
                   m.service, {opt('date_edited')}, {opt('date_retracted')},
                   {opt('thread_originator_guid')}, {opt('associated_message_emoji')},
                   {opt('is_audio_message')}, cmj.chat_id
                FROM chat_message_join cmj JOIN message m ON m.ROWID = cmj.message_id
                LEFT JOIN handle h ON h.ROWID = m.handle_id
                WHERE cmj.chat_id IN ({','.join('?' * len(chat_ids))})"""
        args = list(chat_ids)
        if since:
            q += " AND m.date >= ?"; args.append(self._date_arg(since))
        if until:
            q += " AND m.date < ?"; args.append(self._date_arg(until))
        q += " ORDER BY m.date, m.ROWID"
        rows = self.con.execute(q, args).fetchall()
        atts = self._attachments([r["rowid"] for r in rows if r["cache_has_attachments"]])
        out, seen = [], set()
        for r in rows:
            if r["guid"] in seen:      # same message can appear in merged chats
                continue
            seen.add(r["guid"])
            atype = r["atype"] or 0
            if not include_reactions and atype:
                continue
            text = r["text"] or decode_attributed_body(r["attributedBody"])
            d = {
                "id": r["rowid"], "guid": r["guid"], "when": apple_dt(r["date"]),
                "from_me": bool(r["is_from_me"]),
                "sender": "Me" if r["is_from_me"] else self.contacts.label(r["sender"]),
                "sender_handle": r["sender"], "text": text or "",
                "attachments": atts.get(r["rowid"], []),
                "is_read": bool(r["is_read"]), "service": r["service"],
                "edited": bool(r["date_edited"]), "unsent": bool(r["date_retracted"]),
                "reply_to": r["thread_originator_guid"], "item_type": r["item_type"] or 0,
                "reaction": None, "reaction_target": None, "chat_id": r["chat_id"],
                "audio": bool(r["is_audio_message"]),
            }
            if atype:
                base = atype - 1000 if atype >= 3000 else atype
                verb = REACTIONS.get(base, f"reaction({atype})")
                if r["associated_message_emoji"]:
                    verb = f"reacted {r['associated_message_emoji']} to"
                d["reaction"] = ("removed: " if atype >= 3000 else "") + verb
                g = r["aguid"] or ""
                d["reaction_target"] = g.split("/")[-1] if "/" in g else g
            out.append(d)
        return out

    def _date_arg(self, d: dt.datetime):
        # chat.db stores ns on modern macOS; detect scale from data
        mx = self.con.execute("SELECT MAX(date) FROM message").fetchone()[0] or 0
        return to_apple(d) if mx > 1e11 else int(d.timestamp() - APPLE_EPOCH)

    def _attachments(self, ids) -> dict[int, list[str]]:
        res = defaultdict(list)
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            if not chunk:
                continue
            for mid, name, fn, mime in self.con.execute(
                    f"SELECT maj.message_id, a.transfer_name, a.filename, a.mime_type "
                    f"FROM message_attachment_join maj JOIN attachment a ON a.ROWID=maj.attachment_id "
                    f"WHERE maj.message_id IN ({','.join('?' * len(chunk))})", chunk):
                res[mid].append(name or (Path(fn).name if fn else None) or mime or "file")
        return res

# ---------------------------------------------------------------- rendering

def is_real(m: dict) -> bool:
    return not m["reaction"] and m["item_type"] == 0 and (m["text"] or m["attachments"])


def render_line(m: dict, by_guid: dict | None = None, show_date=False) -> str:
    ts = m["when"].strftime("%Y-%m-%d %H:%M" if show_date else "%H:%M") if m["when"] else "????"
    if m["reaction"]:
        tgt = (by_guid or {}).get(m["reaction_target"])
        snippet = f' "{tgt["text"][:60]}"' if tgt and tgt["text"] else ""
        return f"{ts}  _{m['sender']} {m['reaction']}{snippet}_"
    if m["item_type"] != 0:
        return f"{ts}  _[system event: {m['text'] or 'group change'}]_"
    body = m["text"].replace("\n", " ⏎ ") if m["text"] else ""
    if m["attachments"]:
        body += ("  " if body else "") + " ".join(f"[📎 {a}]" for a in m["attachments"])
    if m["audio"] and not body:
        body = "[🎤 audio message]"
    flags = []
    if m["edited"]:
        flags.append("edited")
    if m["unsent"]:
        flags.append("unsent")
        body = body or "[message unsent]"
    if m["reply_to"]:
        tgt = (by_guid or {}).get(m["reply_to"])
        flags.append(f'reply to "{tgt["text"][:40]}"' if tgt and tgt["text"] else "threaded reply")
    if m["service"] and m["service"] not in ("iMessage",):
        flags.append(m["service"])
    fl = f"  _({'; '.join(flags)})_" if flags else ""
    return f"{ts}  **{m['sender']}:** {body}{fl}"


def write_markdown(msgs, title, path: Path, meta: dict):
    by_guid = {m["guid"]: m for m in msgs}
    lines = [f"# {title}", ""]
    for k, v in meta.items():
        lines.append(f"- **{k}:** {v}")
    lines.append("")
    day = None
    for m in msgs:
        d = m["when"].date() if m["when"] else None
        if d != day:
            day = d
            lines += ["", f"## {d:%Y-%m-%d (%a)}" if d else "## (no date)", ""]
        lines.append(render_line(m, by_guid) + "  ")
    path.write_text("\n".join(lines) + "\n")


def msg_record(m: dict) -> dict:
    return {"timestamp": m["when"].isoformat() if m["when"] else None, "sender": m["sender"],
            "from_me": m["from_me"], "text": m["text"], "attachments": m["attachments"],
            "reaction": m["reaction"], "reaction_target_guid": m["reaction_target"],
            "edited": m["edited"], "unsent": m["unsent"], "reply_to_guid": m["reply_to"],
            "service": m["service"], "guid": m["guid"]}

# ---------------------------------------------------------------- commands

def cmd_doctor(a):
    print(f"Python {platform.python_version()} · macOS {platform.mac_ver()[0] or 'unknown'}")
    print(f"Workspace: {WS}")
    print(f"Messages DB: {CHAT_DB} (exists: {CHAT_DB.exists()})")
    db = Messages(fresh=True, contacts_fresh=True)
    n = db.con.execute("SELECT COUNT(*) FROM message").fetchone()[0]
    print(f"✅ Messages readable — {n:,} message rows in snapshot")
    print(f"✅ Contacts: {len(db.contacts.by_key):,} phone/email entries from {db.contacts.source_count} address book(s)")
    if not db.contacts.by_key:
        print("   ⚠️  No contacts found — names will show as numbers. Check Contacts is syncing to this Mac.")
    print(f"Your handles (auto-detected): {', '.join(sorted(db.my_handles)) or 'none'}")
    print("   (add any missing ones to config.json → my_handles so your self-chat is excluded)")
    latest = apple_dt(db.con.execute("SELECT MAX(date) FROM message").fetchone()[0])
    if latest:
        print(f"Newest message: {latest:%Y-%m-%d %H:%M} ({fmt_age(latest)} ago)")


def cmd_sync_status(a):
    db = Messages(fresh=True)
    c = db.con
    total = c.execute("SELECT COUNT(*) FROM message").fetchone()[0]
    reactions = c.execute("SELECT COUNT(*) FROM message WHERE associated_message_type != 0").fetchone()[0]
    system = c.execute("SELECT COUNT(*) FROM message WHERE item_type != 0").fetchone()[0]
    real = total - reactions - system
    lo, hi = c.execute("SELECT MIN(date), MAX(date) FROM message WHERE date > 0").fetchone()
    lo, hi = apple_dt(lo), apple_dt(hi)
    print("# Message history completeness report\n")
    print(f"- Total rows: **{total:,}**  (real messages {real:,} · reactions {reactions:,} · system events {system:,})")
    if lo:
        print(f"- Oldest message on this Mac: **{lo:%Y-%m-%d}**")
        print(f"- Newest message on this Mac: **{hi:%Y-%m-%d %H:%M}** ({fmt_age(hi)} ago)")
        if (dt.datetime.now().astimezone() - hi).days >= 1:
            print("  - ⚠️ Nothing new in 24h+ — sync may be stalled (or it's just quiet). Try Sync Now.")
    if a.icloud_count:
        diff = a.icloud_count - total
        pct = 100 * total / a.icloud_count if a.icloud_count else 0
        print(f"\n## vs iCloud\n- iCloud says **{a.icloud_count:,}** · this Mac has **{total:,}** rows ({pct:.1f}%)")
        if pct >= 98 or abs(diff) <= 25:
            print("- ✅ Counts match closely — your Mac very likely has everything iCloud has.")
        elif diff > 0:
            print(f"- ⚠️ About **{diff:,}** fewer here than iCloud reports → history is likely still "
                  "downloading or stuck. See docs/SETUP.md → 'Is all my message history here?'.")
        else:
            print("- This Mac has MORE than iCloud reports — usually fine (local-only or pre-iCloud history).")
        print("  _Apple doesn't document exactly what its count includes; treat small differences as noise._")
    else:
        print("\n> To compare with the server: iPhone → Settings → [your name] → iCloud → Messages "
              "(or Mac: System Settings → [your name] → iCloud → Messages) shows the number of messages "
              "in iCloud. Rerun with `--icloud-count N`.")
    # per-year histogram
    print("\n## Messages per year")
    per_year = Counter()
    per_month = Counter()
    scale = 1e9 if (c.execute("SELECT MAX(date) FROM message").fetchone()[0] or 0) > 1e11 else 1
    for (d,) in c.execute("SELECT date FROM message WHERE date > 0 AND associated_message_type = 0"):
        t = dt.datetime.fromtimestamp(d / scale + APPLE_EPOCH)
        per_year[t.year] += 1
        per_month[(t.year, t.month)] += 1
    mx = max(per_year.values()) if per_year else 1
    for y in sorted(per_year):
        print(f"- {y}: {per_year[y]:>7,} {'█' * max(1, int(30 * per_year[y] / mx))}")
    # gaps
    if per_month:
        months = sorted(per_month)
        y, m = months[0]
        gaps = []
        while (y, m) <= months[-1]:
            if per_month.get((y, m), 0) == 0:
                gaps.append(f"{y}-{m:02d}")
            m += 1
            if m == 13:
                y, m = y + 1, 1
        if gaps:
            print(f"\n## Empty months inside your history ({len(gaps)})\n" + ", ".join(gaps[:60]))
            print("_Isolated empty months can be real; long runs usually mean history never downloaded._")
    # biggest conversations' oldest dates
    print("\n## Top conversations — earliest message held locally")
    for g in sorted([g for g in db.conversations() if not g["automated"]], key=lambda g: -g["count"])[:15]:
        first = c.execute(f"SELECT MIN(m.date) FROM chat_message_join cmj JOIN message m ON m.ROWID=cmj.message_id "
                          f"WHERE cmj.chat_id IN ({','.join('?' * len(g['chat_ids']))}) AND m.date>0",
                          g["chat_ids"]).fetchone()[0]
        f = apple_dt(first)
        print(f"- {g['label']}: {g['count']:,} msgs since {f:%Y-%m-%d}" if f else f"- {g['label']}: {g['count']:,}")
    print("_If a long-running relationship starts suspiciously recently, older history for it is missing._")
    if "ck_sync_state" in db.mcols:
        dist = c.execute("SELECT ck_sync_state, COUNT(*) FROM message GROUP BY 1 ORDER BY 2 DESC").fetchall()
        print("\n## Diagnostic: ck_sync_state distribution (undocumented by Apple)")
        print(", ".join(f"{s}: {n:,}" for s, n in dist))
        print("_Typically almost all rows share one value once fully synced; a large second group can indicate "
              "rows still pending upload/download. Treat as a hint, not proof._")


def cmd_chats(a):
    db = Messages(fresh=a.fresh)
    since = parse_date(a.since) if a.since else None
    rows = []
    for g in db.conversations():
        if g["self_chat"] or (g["automated"] and not a.all):
            continue
        if since and (not g["last_dt"] or g["last_dt"] < since):
            continue
        rows.append(g)
        if len(rows) >= a.limit:
            break
    if a.json:
        print(json.dumps([{k: (v.isoformat() if isinstance(v, dt.datetime) else v) for k, v in g.items()
                           if k != "last"} for g in rows], indent=1, default=str))
        return
    for g in rows:
        kind = "👥" if g["is_group"] else "👤"
        last = f"{g['last_dt']:%Y-%m-%d %H:%M}" if g["last_dt"] else "—"
        print(f"{kind} {g['label']}  · {g['count']:,} msgs · last {last} · {'/'.join(g['services'])} "
              f"· chat ids {','.join(map(str, g['chat_ids']))}")


def cmd_missed(a):
    db = Messages(fresh=a.fresh)
    since = parse_date(f"{a.days}d")
    ignore = {norm_handle(h) for h in db.cfg.get("ignore_handles", [])}
    items = []
    for g in db.conversations():
        if g["self_chat"] or not g["last_dt"] or g["last_dt"] < since:
            continue
        if set(g["handles"]) & ignore:
            continue
        if g["is_group"] and not a.groups:
            continue
        msgs = db.messages(g["chat_ids"], since=since - dt.timedelta(days=30))
        real = [m for m in msgs if is_real(m)]
        if not real or real[-1]["from_me"]:
            continue
        trailing = []
        for m in reversed(real):
            if m["from_me"]:
                break
            trailing.append(m)
        trailing.reverse()
        last_mine = next((m for m in reversed(real) if m["from_me"]), None)
        after = [m for m in msgs if m["when"] and m["when"] > trailing[0]["when"]]
        reacted_only = any(m["from_me"] and m["reaction"] for m in after)
        text_blob = " ".join(m["text"] for m in trailing)
        automated = g["automated"] or bool(AUTOMATED_RE.search(text_blob))
        if automated and not a.all:
            continue
        unread = sum(1 for m in trailing if not m["is_read"])
        items.append({
            "conversation": g["label"], "is_group": g["is_group"], "chat_ids": g["chat_ids"],
            "waiting_since": trailing[0]["when"], "waiting": fmt_age(trailing[0]["when"]),
            "count": len(trailing), "unread": unread, "question": "?" in text_blob,
            "reacted_only": reacted_only, "automated": automated,
            "their_messages": trailing[-a.show:],
            "my_last": last_mine, "by_guid": {m["guid"]: m for m in msgs},
        })
    items.sort(key=lambda x: (x["automated"], x["is_group"], not x["question"], x["waiting_since"]))
    if a.json:
        out = []
        for it in items:
            out.append({k: v for k, v in it.items() if k not in ("by_guid",)})
            out[-1]["waiting_since"] = it["waiting_since"].isoformat()
            out[-1]["their_messages"] = [msg_record(m) for m in it["their_messages"]]
            out[-1]["my_last"] = msg_record(it["my_last"]) if it["my_last"] else None
        print(json.dumps(out, indent=1, default=str))
        return
    print(f"# Waiting on you — last {a.days} days ({len(items)} conversation{'s' if len(items) != 1 else ''})\n")
    if not items:
        print("Inbox zero on texts. 🎉")
    for it in items:
        tags = []
        if it["question"]:
            tags.append("❓ question")
        if it["unread"]:
            tags.append(f"🔵 {it['unread']} unread")
        if it["reacted_only"]:
            tags.append("👍 you reacted but didn't reply")
        if it["is_group"]:
            tags.append("👥 group")
        if it["automated"]:
            tags.append("🤖 automated")
        print(f"## {it['conversation']} — waiting {it['waiting']}  {' · '.join(tags)}")
        if it["my_last"]:
            print(f"> you last said ({it['my_last']['when']:%m/%d}): {it['my_last']['text'][:140]}")
        for m in it["their_messages"]:
            line = render_line(m, it["by_guid"], show_date=True)
            print("- " + (line[:400] + " …[truncated]" if len(line) > 400 else line))
        print()


def cmd_thread(a):
    db = Messages(fresh=a.fresh)
    g = db.pick(a.who)
    msgs = db.messages(g["chat_ids"], since=parse_date(a.since) if a.since else None,
                       include_reactions=not a.no_reactions)
    msgs = msgs[-a.last:]
    by_guid = {m["guid"]: m for m in msgs}
    print(f"# {g['label']} — last {len(msgs)} messages\n")
    for m in msgs:
        print(render_line(m, by_guid, show_date=True))


def cmd_export(a):
    db = Messages(fresh=a.fresh)
    g = db.pick(a.who)
    since, until = parse_date(a.since), parse_date(a.until, end=True)
    msgs = db.messages(g["chat_ids"], since, until, include_reactions=not a.no_reactions)
    if not msgs:
        sys.exit("No messages in that range.")
    outdir = Path(a.out) if a.out else EXPORTS / slug(g["label"])
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    meta = {
        "Conversation": g["label"],
        "Participants": ", ".join(["Me"] + g["participants"]),
        "Source threads merged": f"{len(g['chat_ids'])} ({', '.join(g['identifiers'])}; services {'/'.join(g['services'])})",
        "Range": f"{msgs[0]['when']:%Y-%m-%d %H:%M} → {msgs[-1]['when']:%Y-%m-%d %H:%M}",
        "Messages": f"{len(msgs):,} (incl. reactions)" if not a.no_reactions else f"{len(msgs):,}",
        "Exported": f"{dt.datetime.now():%Y-%m-%d %H:%M} from a read-only snapshot of chat.db",
        "Note": "Times are local. Only messages present on this Mac are included — run sync-status to check completeness.",
    }
    buckets = defaultdict(list)
    for m in msgs:
        key = "all" if a.split == "none" else (f"{m['when']:%Y}" if a.split == "year" else f"{m['when']:%Y-%m}")
        buckets[key].append(m)
    files = []
    for key, ms in sorted(buckets.items()):
        base = outdir / (f"{slug(g['label'])}_{key}" if a.split != "none" else f"{slug(g['label'])}_{stamp}")
        if a.format == "md":
            p = base.with_suffix(".md")
            write_markdown(ms, f"{g['label']} — {key}" if key != "all" else g["label"], p, meta)
        elif a.format == "jsonl":
            p = base.with_suffix(".jsonl")
            with p.open("w") as f:
                for m in ms:
                    f.write(json.dumps(msg_record(m), ensure_ascii=False) + "\n")
        else:
            p = base.with_suffix(".csv")
            with p.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(msg_record(ms[0]).keys()))
                w.writeheader()
                for m in ms:
                    r = msg_record(m)
                    r["attachments"] = "; ".join(r["attachments"])
                    w.writerow(r)
        files.append((p, len(ms)))
    if a.split != "none":
        idx = outdir / "INDEX.md"
        idx.write_text(f"# {g['label']} — export index\n\n" + "\n".join(f"- **{k}:** {v}" for k, v in meta.items())
                       + "\n\n| Period | Messages | File |\n|---|---:|---|\n"
                       + "\n".join(f"| {p.stem.split('_')[-1]} | {n:,} | {p.name} |" for p, n in files) + "\n")
        files.insert(0, (idx, 0))
    print(f"Exported {len(msgs):,} messages for '{g['label']}' → {outdir}")
    for p, n in files:
        print(f"  {p.name}" + (f"  ({n:,})" if n else ""))


def cmd_search(a):
    db = Messages(fresh=a.fresh)
    since, until = parse_date(a.since), parse_date(a.until, end=True)
    pat = re.compile(a.query if a.regex else re.escape(a.query), re.I)
    convs = [db.pick(a.who)] if a.who else [g for g in db.conversations() if not g["automated"] or a.all]
    total = 0
    for g in convs:
        if since and g["last_dt"] and g["last_dt"] < since:
            continue
        msgs = db.messages(g["chat_ids"], since, until, include_reactions=False)
        by_guid = {m["guid"]: m for m in msgs}
        hits = [i for i, m in enumerate(msgs) if pat.search(m["text"] or "")
                or any(pat.search(x) for x in m["attachments"])]
        if a.from_me:
            hits = [i for i in hits if msgs[i]["from_me"]]
        if a.from_them:
            hits = [i for i in hits if not msgs[i]["from_me"]]
        if not hits:
            continue
        print(f"\n## {g['label']} — {len(hits)} match{'es' if len(hits) != 1 else ''}")
        shown = set()
        for i in hits:
            if total >= a.limit:
                print(f"\n…stopped at --limit {a.limit}. Narrow with --who/--since or raise --limit.")
                return
            lo, hi = max(0, i - a.context), min(len(msgs), i + a.context + 1)
            if a.context:
                print("---")
            for j in range(lo, hi):
                if j in shown:
                    continue
                shown.add(j)
                print(("» " if j == i else "  ") + render_line(msgs[j], by_guid, show_date=True))
            total += 1
    if total == 0:
        print("No matches.")


def cmd_stats(a):
    db = Messages(fresh=a.fresh)
    g = db.pick(a.who)
    msgs = [m for m in db.messages(g["chat_ids"], parse_date(a.since), parse_date(a.until, end=True),
                                   include_reactions=True)]
    real = [m for m in msgs if is_real(m)]
    if not real:
        sys.exit("No messages.")
    print(f"# Stats — {g['label']}\n")
    print(f"- Range: {real[0]['when']:%Y-%m-%d} → {real[-1]['when']:%Y-%m-%d} "
          f"({(real[-1]['when'] - real[0]['when']).days:,} days)")
    print(f"- Messages: {len(real):,} · reactions: {len(msgs) - len(real):,}")
    by_sender = Counter(m["sender"] for m in real)
    words = Counter()
    for m in real:
        words[m["sender"]] += len(m["text"].split())
    print("\n| Sender | Messages | Share | Words | Avg words/msg |\n|---|---:|---:|---:|---:|")
    for s, n in by_sender.most_common():
        print(f"| {s} | {n:,} | {100 * n / len(real):.0f}% | {words[s]:,} | {words[s] / n:.1f} |")
    # response times (first message after the other side spoke; ignore gaps > 7 days)
    resp = defaultdict(list)
    for prev, cur in zip(real, real[1:]):
        if prev["sender"] != cur["sender"]:
            gap = (cur["when"] - prev["when"]).total_seconds()
            if 0 < gap < 7 * 86400:
                resp[cur["sender"]].append(gap / 60)
    if resp:
        print("\n**Median reply time** (replies within 7 days):")
        for s, v in resp.items():
            med = statistics.median(v)
            print(f"- {s}: {med:.0f} min" if med < 120 else f"- {s}: {med / 60:.1f} h")
    # per month
    pm = defaultdict(Counter)
    for m in real:
        pm[m["when"].strftime("%Y-%m")][m["sender"]] += 1
    senders = [s for s, _ in by_sender.most_common(6)]
    print("\n## Per month\n| Month | " + " | ".join(senders) + " | Total |\n|---|" + "---:|" * (len(senders) + 1))
    for mo in sorted(pm):
        print(f"| {mo} | " + " | ".join(str(pm[mo][s]) for s in senders) + f" | {sum(pm[mo].values())} |")
    # silences
    gaps = sorted(((b["when"] - a_["when"], a_, b) for a_, b in zip(real, real[1:])), key=lambda x: -x[0])[:5]
    print("\n## Longest silences")
    for gap, x, y in gaps:
        print(f"- {gap.days} days: {x['when']:%Y-%m-%d} → {y['when']:%Y-%m-%d} (broken by {y['sender']})")


def cmd_style(a):
    db = Messages(fresh=a.fresh)
    convs = [db.pick(a.who)] if a.who else [g for g in db.conversations()
                                             if not g["automated"] and not g["self_chat"]][:40]
    mine = []
    for g in convs:
        for m in db.messages(g["chat_ids"], parse_date(a.since or "18m"), include_reactions=False):
            if m["from_me"] and m["text"] and not m["attachments"]:
                mine.append((g["label"], m))
    mine.sort(key=lambda x: x[1]["when"])
    sample = mine[-a.limit:]
    texts = [m["text"] for _, m in mine]
    if not texts:
        sys.exit("No sent messages found.")
    emoji_re = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
    starts_lower = sum(1 for t in texts if t[:1].islower()) / len(texts)
    ends_period = sum(1 for t in texts if t.rstrip().endswith(".")) / len(texts)
    ends_excl = sum(1 for t in texts if t.rstrip().endswith("!")) / len(texts)
    emojis = Counter(e for t in texts for e in emoji_re.findall(t))
    openers = Counter(" ".join(t.split()[:2]).lower() for t in texts if len(t.split()) >= 2)
    lol = Counter(w.lower() for t in texts for w in re.findall(r"\b(lol|lmao|haha+|omg|ty|thx|np|yep|yup|nope|gotcha|sounds good|for sure|totally)\b", t, re.I))
    print(f"# Your texting style — {len(texts):,} sent messages analysed"
          + (f" (with {convs[0]['label']})" if a.who else " (recent conversations)") + "\n")
    print(f"- Median length: {statistics.median(len(t.split()) for t in texts):.0f} words")
    print(f"- Starts lowercase: {starts_lower:.0%} · ends with '.': {ends_period:.0%} · ends with '!': {ends_excl:.0%}")
    print(f"- Messages with emoji: {sum(1 for t in texts if emoji_re.search(t)) / len(texts):.0%}; "
          f"top: {' '.join(e for e, _ in emojis.most_common(10)) or '—'}")
    print(f"- Frequent fillers: {', '.join(f'{w} ({n})' for w, n in lol.most_common(10)) or '—'}")
    print(f"- Common openers: {', '.join(f'“{w}”' for w, _ in openers.most_common(12))}")
    print(f"\n## {len(sample)} most recent examples (verbatim)\n")
    for label, m in sample:
        print(f"- [{m['when']:%Y-%m-%d} → {label}] {m['text']}")


def cmd_who(a):
    db = Messages(fresh=a.fresh)
    for g in db.resolve(a.who)[:30]:
        last = f"{g['last_dt']:%Y-%m-%d}" if g["last_dt"] else "—"
        print(f"{'👥' if g['is_group'] else '👤'} {g['label']} · {g['count']:,} msgs · last {last} · "
              f"handles {', '.join(g['handles'])} · chat ids {','.join(map(str, g['chat_ids']))}")

# --------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fresh", action="store_true", help="force a new snapshot (default: reuse if <5 min old)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    s = sub.add_parser("sync-status"); s.add_argument("--icloud-count", type=int); s.set_defaults(fn=cmd_sync_status)

    s = sub.add_parser("chats"); s.add_argument("--limit", type=int, default=40); s.add_argument("--since")
    s.add_argument("--all", action="store_true", help="include automated/short-code senders")
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_chats)

    s = sub.add_parser("missed"); s.add_argument("--days", type=int, default=load_config().get("missed_days", 7))
    s.add_argument("--groups", action="store_true", help="include group chats")
    s.add_argument("--all", action="store_true", help="include automated messages (codes, deliveries…)")
    s.add_argument("--show", type=int, default=4, help="max of their messages to show per conversation")
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_missed)

    s = sub.add_parser("thread"); s.add_argument("who"); s.add_argument("--last", type=int, default=40)
    s.add_argument("--since"); s.add_argument("--no-reactions", action="store_true"); s.set_defaults(fn=cmd_thread)

    s = sub.add_parser("export"); s.add_argument("who"); s.add_argument("--since"); s.add_argument("--until")
    s.add_argument("--format", choices=["md", "csv", "jsonl"], default="md")
    s.add_argument("--split", choices=["none", "month", "year"], default="none")
    s.add_argument("--out"); s.add_argument("--no-reactions", action="store_true"); s.set_defaults(fn=cmd_export)

    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--who"); s.add_argument("--regex", action="store_true")
    s.add_argument("--since"); s.add_argument("--until"); s.add_argument("--context", type=int, default=0)
    s.add_argument("--limit", type=int, default=150); s.add_argument("--all", action="store_true")
    s.add_argument("--from-me", action="store_true"); s.add_argument("--from-them", action="store_true")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("stats"); s.add_argument("who"); s.add_argument("--since"); s.add_argument("--until"); s.set_defaults(fn=cmd_stats)
    s = sub.add_parser("style"); s.add_argument("--who"); s.add_argument("--since"); s.add_argument("--limit", type=int, default=60)
    s.set_defaults(fn=cmd_style)
    s = sub.add_parser("who"); s.add_argument("who"); s.set_defaults(fn=cmd_who)

    a = p.parse_args()
    for sp in ("fresh",):
        setattr(a, sp, getattr(a, sp, False))
    a.fn(a)


if __name__ == "__main__":
    main()
