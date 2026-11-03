#!/usr/bin/env python3
"""
mail.py: READ-ONLY access to Apple Mail across all your accounts (Google, Outlook/Exchange, iCloud…).

Reads a snapshot of Mail's local "Envelope Index" database. It never sends mail, never
marks anything read and never moves mail. Add your accounts in System Settings → Internet Accounts
(turn on Mail). The Mail app must run now and then to fetch new mail.

Commands
  doctor                      check access; list accounts and mailbox counts
  accounts                    accounts and their mailboxes
  inbox    [--days 3] [--unread] [--account X] [--limit 60]
  flagged  [--limit 50]
  folder   --name "Slack Digest" [--days 7] [--body]      mail in a named folder (any account)
  sent     [--to person@example.com | --to "Name"] [--since 2026-11-01] [--limit 50]
                                                           what you've sent (reply detection)
  replied  --to "address or name" --since 2026-11-01       yes/no: did you send them anything since?
  search   QUERY [--days 30] [--from X] [--limit 40]       subject/sender/summary search
  read     --id ROWID                                      full text of one message (from .emlx)
Output: JSON (add --text to read it yourself).
"""
from __future__ import annotations

import argparse
import datetime as dt
import email
import email.policy
import glob
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

WS = Path(os.environ.get("THESEUS_HOME") or Path(__file__).resolve().parents[2])
CACHE = WS / "cache"
MAIL_ROOT = Path(os.environ.get("THESEUS_MAIL_ROOT", Path.home() / "Library/Mail"))
ACCOUNTS_DB = Path.home() / "Library/Accounts/Accounts4.sqlite"
APPLE_EPOCH = 978307200


def die(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def mail_dir() -> Path:
    vs = sorted(MAIL_ROOT.glob("V[0-9]*"), key=lambda p: int(re.sub(r"\D", "", p.name) or 0))
    if not vs:
        die(f"No Apple Mail data under {MAIL_ROOT}. Add accounts in System Settings → Internet Accounts, "
            "open Mail once, and grant Full Disk Access to your terminal app.")
    return vs[-1]


def snapshot(src: Path, name: str, fresh: bool, max_age_min=5) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    dst = CACHE / name
    if dst.exists() and not fresh and time.time() - dst.stat().st_mtime < max_age_min * 60:
        return dst
    try:
        s = sqlite3.connect(src.as_uri() + "?mode=ro", uri=True, timeout=10)
        d = sqlite3.connect(str(dst)); s.backup(d); d.close(); s.close()
    except sqlite3.Error as e:
        die(f"Can't read {src} ({e}). Grant Full Disk Access to your terminal app (and /bin/bash for scheduled runs).")
    return dst


def ts(v) -> dt.datetime | None:
    if not v:
        return None
    v = float(v)
    if v > 1e11:
        v /= 1e9
    if v < 1_000_000_000:          # Apple epoch (seconds since 2001)
        v += APPLE_EPOCH
    return dt.datetime.fromtimestamp(v).astimezone()


def since_arg(s: str | None, days: int | None) -> float | None:
    if s:
        try:
            return dt.datetime.strptime(s, "%Y-%m-%d").timestamp()
        except ValueError:
            die("Use YYYY-MM-DD for --since")
    if days:
        return time.time() - days * 86400
    return None


class Mail:
    def __init__(self, fresh=False):
        self.dir = mail_dir()
        src = self.dir / "MailData" / "Envelope Index"
        if not src.exists():
            die(f"Mail database not found at {src}. Open the Mail app once so it builds it.")
        self.con = sqlite3.connect(str(snapshot(src, "mail-envelope.db", fresh)))
        self.con.row_factory = sqlite3.Row
        self.cols = {r[1] for r in self.con.execute("PRAGMA table_info(messages)")}
        self.tables = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.accounts = self._accounts(fresh)
        self._scale = None

    def _accounts(self, fresh) -> dict[str, str]:
        names: dict[str, str] = {}
        try:
            if ACCOUNTS_DB.exists():
                c = sqlite3.connect(str(snapshot(ACCOUNTS_DB, "accounts.db", fresh, 1440)))
                for ident, desc, user in c.execute("SELECT ZIDENTIFIER, ZACCOUNTDESCRIPTION, ZUSERNAME FROM ZACCOUNT"):
                    if ident:
                        names[ident.upper()] = desc or user or ident
        except Exception:
            pass
        cfg = WS / "config.json"
        if cfg.exists():
            try:
                for k, v in (json.loads(cfg.read_text()).get("mail_account_labels") or {}).items():
                    names[k.upper()] = v
            except Exception:
                pass
        return names

    def mailbox_label(self, url: str) -> tuple[str, str]:
        """'imap://UUID/INBOX' → ('Work Gmail', 'INBOX')"""
        m = re.match(r"^[a-z]+://([^/]+)/(.*)$", url or "")
        if not m:
            return ("?", url or "?")
        acct = self.accounts.get(m.group(1).upper(), m.group(1)[:8])
        from urllib.parse import unquote
        box = unquote(m.group(2))
        return (acct, box)

    def query(self, where: str, args: list, order="m.date_received DESC", limit=60):
        summary = "su.summary" if "summaries" in self.tables and "summary" in self.cols else "NULL"
        join_su = "LEFT JOIN summaries su ON su.ROWID = m.summary" if summary != "NULL" else ""
        flagged = "m.flagged" if "flagged" in self.cols else "0"
        deleted = "AND m.deleted = 0" if "deleted" in self.cols else ""
        q = f"""SELECT m.ROWID AS id, s.subject AS subject, a.address AS from_addr, a.comment AS from_name,
                       m.date_received AS received, m.date_sent AS sent, m.read AS read, {flagged} AS flagged,
                       mb.url AS mailbox, {summary} AS summary
                FROM messages m
                LEFT JOIN subjects s ON s.ROWID = m.subject
                LEFT JOIN addresses a ON a.ROWID = m.sender
                LEFT JOIN mailboxes mb ON mb.ROWID = m.mailbox
                {join_su}
                WHERE 1=1 {deleted} AND {where}
                ORDER BY {order} LIMIT ?"""
        rows = self.con.execute(q, args + [limit]).fetchall()
        return [self.row(r) for r in rows]

    def row(self, r) -> dict:
        acct, box = self.mailbox_label(r["mailbox"])
        rec = ts(r["received"]) or ts(r["sent"])
        return {"id": r["id"], "date": rec.isoformat() if rec else None,
                "from": (f'{r["from_name"]} <{r["from_addr"]}>' if r["from_name"] else r["from_addr"]),
                "subject": r["subject"] or "(no subject)", "account": acct, "mailbox": box,
                "read": bool(r["read"]), "flagged": bool(r["flagged"]),
                "snippet": re.sub(r"\s+", " ", (r["summary"] or ""))[:300] or None}

    def date_param(self, unix: float) -> float:
        if self._scale is None:
            mx = self.con.execute("SELECT MAX(date_received) FROM messages").fetchone()[0] or 0
            self._scale = "apple" if mx < 1_000_000_000 else "unix"
        return unix - APPLE_EPOCH if self._scale == "apple" else unix

    def recipients_of(self, msg_ids: list[int]) -> dict[int, list[str]]:
        out: dict[int, list[str]] = {}
        if "recipients" not in self.tables or not msg_ids:
            return out
        for i in range(0, len(msg_ids), 500):
            chunk = msg_ids[i:i + 500]
            for mid, addr, name in self.con.execute(
                    f"SELECT r.message, a.address, a.comment FROM recipients r JOIN addresses a ON a.ROWID=r.address "
                    f"WHERE r.message IN ({','.join('?' * len(chunk))})", chunk):
                out.setdefault(mid, []).append(f"{name} <{addr}>" if name else addr)
        return out


def emit(data, text: bool, title=""):
    if not text:
        print(json.dumps(data, indent=1, ensure_ascii=False))
        return
    if title:
        print(f"# {title}\n")
    for m in data if isinstance(data, list) else [data]:
        if "subject" in m:
            flags = ("🔵" if not m.get("read") else "  ") + ("🚩" if m.get("flagged") else "")
            print(f"{flags} {m['date'][:16] if m.get('date') else ''} · {m['account']}/{m['mailbox']} · id {m['id']}")
            print(f"   {m['from']} — {m['subject']}")
            if m.get("to"):
                print(f"   to: {', '.join(m['to'][:4])}")
            if m.get("snippet"):
                print(f"   {m['snippet'][:200]}")
            if m.get("body"):
                print("\n" + m["body"] + "\n")
        else:
            print(json.dumps(m, indent=1, ensure_ascii=False))


SENT_RE = r"(sent|sent items|sent mail|sent messages|\[gmail\]/sent mail)"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fresh", action="store_true")
    p.add_argument("--text", action="store_true", help="human-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor"); sub.add_parser("accounts")
    s = sub.add_parser("inbox"); s.add_argument("--days", type=int, default=3); s.add_argument("--unread", action="store_true")
    s.add_argument("--account"); s.add_argument("--limit", type=int, default=60)
    s = sub.add_parser("flagged"); s.add_argument("--limit", type=int, default=50)
    s = sub.add_parser("folder"); s.add_argument("--name", required=True); s.add_argument("--days", type=int, default=7)
    s.add_argument("--body", action="store_true"); s.add_argument("--limit", type=int, default=80)
    s = sub.add_parser("sent"); s.add_argument("--to"); s.add_argument("--since"); s.add_argument("--days", type=int, default=7)
    s.add_argument("--limit", type=int, default=50)
    s = sub.add_parser("replied"); s.add_argument("--to", required=True); s.add_argument("--since", required=True)
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--days", type=int, default=30)
    s.add_argument("--from", dest="sender"); s.add_argument("--limit", type=int, default=40)
    s = sub.add_parser("read"); s.add_argument("--id", type=int, required=True)
    a = p.parse_args()
    m = Mail(fresh=a.fresh)

    def mailbox_ids(pattern: str) -> list[int]:
        rx = re.compile(pattern, re.I)
        ids = []
        for rid, url in m.con.execute("SELECT ROWID, url FROM mailboxes"):
            acct, box = m.mailbox_label(url)
            if rx.search(box.split("/")[-1]) or rx.fullmatch(box):
                ids.append(rid)
        return ids

    if a.cmd in ("doctor", "accounts"):
        rows = m.con.execute("SELECT mb.ROWID, mb.url, COUNT(msg.ROWID) FROM mailboxes mb "
                             "LEFT JOIN messages msg ON msg.mailbox = mb.ROWID GROUP BY mb.ROWID").fetchall()
        accts: dict[str, list] = {}
        for rid, url, n in rows:
            acct, box = m.mailbox_label(url)
            accts.setdefault(acct, []).append({"mailbox": box, "messages": n})
        newest = ts(m.con.execute("SELECT MAX(date_received) FROM messages").fetchone()[0])
        out = {"ok": True, "mail_dir": str(m.dir), "accounts": {k: sorted(v, key=lambda x: -x["messages"])
               for k, v in accts.items()}, "newest_message": newest.isoformat() if newest else None,
               "newest_age_hours": round((time.time() - newest.timestamp()) / 3600, 1) if newest else None}
        if a.cmd == "doctor":
            out["accounts"] = {k: f"{len(v)} mailboxes, {sum(x['messages'] for x in v):,} messages" for k, v in accts.items()}
            if out["newest_age_hours"] and out["newest_age_hours"] > 24:
                out["warning"] = "No new mail in 24h+: is the Mail app running and online?"
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return

    if a.cmd == "inbox":
        ids = mailbox_ids(r"^inbox$")
        if not ids:
            die("No INBOX mailboxes found.")
        where = f"m.mailbox IN ({','.join(map(str, ids))}) AND m.date_received >= ?"
        args = [m.date_param(since_arg(None, a.days))]
        if a.unread:
            where += " AND m.read = 0"
        res = m.query(where, args, limit=a.limit)
        if a.account:
            res = [r for r in res if a.account.lower() in r["account"].lower()]
        emit(res, a.text, f"Inbox — last {a.days} days")
    elif a.cmd == "flagged":
        emit(m.query("m.flagged = 1" if "flagged" in m.cols else "0", [], limit=a.limit), a.text, "Flagged")
    elif a.cmd == "folder":
        ids = mailbox_ids(rf"^{re.escape(a.name)}$|{re.escape(a.name)}$")
        if not ids:
            die(f"No mailbox named '{a.name}'. Run `mail.py accounts` to see names.")
        res = m.query(f"m.mailbox IN ({','.join(map(str, ids))}) AND m.date_received >= ?",
                      [m.date_param(since_arg(None, a.days))], limit=a.limit)
        if a.body:
            for r in res:
                r["body"] = read_body(m.dir, r["id"])[:4000]
        emit(res, a.text, f"Folder {a.name}")
    elif a.cmd in ("sent", "replied"):
        ids = mailbox_ids(SENT_RE)
        if not ids:
            die("No Sent mailboxes found.")
        since = since_arg(a.since, getattr(a, "days", None))
        res = m.query(f"m.mailbox IN ({','.join(map(str, ids))}) AND COALESCE(m.date_sent, m.date_received) >= ?",
                      [m.date_param(since)], order="COALESCE(m.date_sent, m.date_received) DESC",
                      limit=getattr(a, "limit", 500))
        rec = m.recipients_of([r["id"] for r in res])
        for r in res:
            r["to"] = rec.get(r["id"], [])
        if a.to:
            needle = a.to.lower()
            res = [r for r in res if any(needle in t.lower() for t in r["to"])]
        if a.cmd == "replied":
            print(json.dumps({"to": a.to, "since": a.since, "sent_since": bool(res), "count": len(res),
                              "latest": res[0] if res else None}, indent=1, ensure_ascii=False))
        else:
            emit(res, a.text, "Sent")
    elif a.cmd == "search":
        like = f"%{a.query}%"
        where = ("(s.subject LIKE ? OR a.address LIKE ? OR a.comment LIKE ?"
                 + (" OR su.summary LIKE ?)" if "summaries" in m.tables else ")") + " AND m.date_received >= ?")
        args = [like, like, like] + ([like] if "summaries" in m.tables else []) + [m.date_param(since_arg(None, a.days))]
        res = m.query(where, args, limit=a.limit)
        if a.sender:
            res = [r for r in res if a.sender.lower() in (r["from"] or "").lower()]
        emit(res, a.text, f"Search: {a.query}")
    elif a.cmd == "read":
        meta = m.query("m.ROWID = ?", [a.id], limit=1)
        if not meta:
            die("No such message id.")
        meta[0]["body"] = read_body(m.dir, a.id)
        emit(meta[0], a.text)


def read_body(mdir: Path, rowid: int) -> str:
    hits = glob.glob(str(mdir / "**" / f"{rowid}.emlx"), recursive=True) + \
           glob.glob(str(mdir / "**" / f"{rowid}.partial.emlx"), recursive=True)
    if not hits:
        return "(body not downloaded on this Mac — only the summary is available)"
    raw = Path(hits[0]).read_bytes()
    nl = raw.find(b"\n")
    try:
        n = int(raw[:nl].strip())
        raw = raw[nl + 1: nl + 1 + n]
    except ValueError:
        pass
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    if part.get_content_type() == "text/html":
        text = re.sub(r"<(script|style).*?</\1>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        import html as _h
        text = _h.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


if __name__ == "__main__":
    main()
