#!/usr/bin/env python3
"""
notes.py: Apple Notes bridge for Theseus (via JavaScript for Automation).

Commands (JSON output unless noted)
  inbox                         notes waiting in the inbox folder (config: notes_inbox_folder, default "Theseus")
  processed --id ID [--id ID]   move notes into "<inbox>/Processed" (created if missing)
  folders                       list every folder (account/path) with note counts
  folder --path "Work/Lists"    read all notes in any folder (migration of old lists)
  find --query "groceries"      notes whose title contains text (all folders)
  read --id ID                  one note's full text
  master-read                   current text of the Master List note + whether YOU edited it
  master-publish [--file data/master.md] [--force]
                                render the markdown master list into the pinned note
  publish --title "📌 Today" --file data/today.md
                                create/update any Theseus-owned note by title (kept in state)
  note-read --title "📌 Today"  current text of a Theseus-owned note + whether YOU edited it since
                                Theseus last wrote it (so your edits can be read back in)

Nothing is ever deleted. Locked notes are skipped (never unlocked).
Config (config.json): notes_account, notes_inbox_folder, notes_processed_subfolder,
master_note_title, master_note_folder.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(os.environ.get("THESEUS_HOME") or Path(__file__).resolve().parents[2])   # ~/Theseus (workspace)
STATE = WS / "data" / "state.json"
CFG = json.loads((WS / "config.json").read_text()) if (WS / "config.json").exists() else {}
ACCOUNT = CFG.get("notes_account", "iCloud")
INBOX = CFG.get("notes_inbox_folder", "Theseus")
PROCESSED = CFG.get("notes_processed_subfolder", "Processed")
MASTER_TITLE = CFG.get("master_note_title", "★ Master List")
MASTER_FOLDER = CFG.get("master_note_folder", "Notes")

JXA = r"""
function run(argv) {
  const req = JSON.parse(argv[0]);
  const Notes = Application('Notes');
  function account() {
    try { const a = Notes.accounts.byName(req.account); a.name(); return a; }
    catch (e) { return Notes.defaultAccount(); }
  }
  // Only "that note doesn't exist" means missing. A slow or busy Notes must not look like a deleted note.
  function notFound(e) { return e.errorNumber === -1728 || /\(-1728\)/.test(String(e)); }
  function child(container, name) {
    try { const f = container.folders.byName(name); f.name(); return f; } catch (e) { return null; }
  }
  function folderAt(path, create) {
    let cur = account();
    for (const part of path.split('/').filter(Boolean)) {
      let f = child(cur, part);
      if (!f) {
        if (!create) throw new Error('Folder not found: ' + path);
        Notes.make({ new: 'folder', withProperties: { name: part }, at: cur });
        f = child(cur, part);
      }
      cur = f;
    }
    return cur;
  }
  function info(n, withBody) {
    const when = n.modificationDate();
    const o = { id: n.id(), title: n.name(), modified: when.toISOString(), modified_ms: when.getTime(),
                created: n.creationDate().toISOString(), locked: false };
    try { o.locked = n.passwordProtected(); } catch (e) {}
    if (withBody && !o.locked) { try { o.text = n.plaintext(); } catch (e) { o.text = null; o.error = String(e); } }
    try { o.folder = n.container().name(); } catch (e) {}
    return o;
  }
  function notesIn(folder, withBody) {
    const out = []; const ns = folder.notes();
    for (const n of ns) out.push(info(n, withBody));
    return out;
  }
  function walk(container, prefix, out) {
    for (const f of container.folders()) {
      const p = prefix ? prefix + '/' + f.name() : f.name();
      let c = 0; try { c = f.notes.length; } catch (e) {}
      out.push({ path: p, notes: c, id: f.id() });
      walk(f, p, out);
    }
    return out;
  }
  const r = req;
  switch (r.cmd) {
    case 'inbox': return JSON.stringify(notesIn(folderAt(r.inbox, true), true));
    case 'folder': return JSON.stringify(notesIn(folderAt(r.path, false), true));
    case 'folders': {
      const out = [];
      for (const a of Notes.accounts()) { const rows = walk(a, '', []); rows.forEach(x => x.account = a.name()); out.push(...rows); }
      return JSON.stringify(out);
    }
    case 'find': {
      const q = r.query.toLowerCase(); const out = [];
      const ns = Notes.notes(); const names = Notes.notes.name();
      for (let i = 0; i < names.length; i++) if ((names[i] || '').toLowerCase().includes(q)) out.push(info(ns[i], false));
      return JSON.stringify(out);
    }
    case 'read': return JSON.stringify(info(Notes.notes.byId(r.id), true));
    case 'processed': {
      const dest = folderAt(r.inbox + '/' + r.processed, true); const moved = [];
      for (const id of r.ids) { const n = Notes.notes.byId(id); n.name(); Notes.move(n, { to: dest }); moved.push(id); }
      return JSON.stringify({ moved: moved, to: r.inbox + '/' + r.processed });
    }
    case 'get': {
      try { const n = Notes.notes.byId(r.id); return JSON.stringify(info(n, true)); }
      catch (e) { if (notFound(e)) return JSON.stringify({ missing: true }); throw e; }
    }
    case 'upsert': {
      let n = null;
      if (r.id) { try { n = Notes.notes.byId(r.id); n.name(); } catch (e) { if (!notFound(e)) throw e; n = null; } }
      if (!n) {
        const folder = folderAt(r.folder, true);
        n = Notes.make({ new: 'note', withProperties: { body: r.html }, at: folder });
      } else {
        n.body = r.html;
      }
      return JSON.stringify(info(n, true));
    }
  }
  throw new Error('unknown cmd ' + r.cmd);
}
"""


def jxa(req: dict):
    req.setdefault("account", ACCOUNT)
    try:
        p = subprocess.run(["osascript", "-l", "JavaScript", "-e", JXA, json.dumps(req)],
                           capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        sys.exit("Notes didn't answer within 3 minutes. Nothing was changed; try again later.")
    if p.returncode != 0:
        err = p.stderr.strip()
        if "-1743" in err or "Not authorized" in err:
            sys.exit("Notes access denied. System Settings → Privacy & Security → Automation → "
                     "your terminal app → enable 'Notes'. Then rerun.")
        sys.exit(f"Notes error: {err}")
    return json.loads(p.stdout or "null")


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(s: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STATE.parent, prefix=".state.")
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(s, indent=1))
    os.replace(tmp, STATE)


def record(key: str, rec: dict):
    """The app and Claude both publish notes, so this rereads under a lock: neither can undo what the other just recorded."""
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE.parent / ".state.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        st = load_state()
        st[key] = rec
        save_state(st)


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def h(t: str) -> str:
    return hashlib.sha256(norm(t).encode()).hexdigest()[:16]

# -------------------------------------------------------- markdown → Notes HTML

ID_TOKEN = re.compile(r"\s*·?\s*\b(?:id|was):[\w-]+")
COMMENT = re.compile(r"<!--.*?-->", re.S)


def inline(t: str) -> str:
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])_(.+?)_(?![\w*])", r"<i>\1</i>", t)
    return t


def md_to_html(md: str) -> str:
    md = COMMENT.sub("", md)
    out, in_list = [], False
    for raw in md.splitlines():
        line = ID_TOKEN.sub("", raw.rstrip())
        m_item = re.match(r"^(\s*)[-*]\s+(\[( |x|X)\]\s+)?(.*)$", line)
        if m_item:
            if not in_list:
                out.append("<ul>"); in_list = True
            box = ""
            if m_item.group(2):
                box = "☑︎ " if m_item.group(3).lower() == "x" else "☐ "
            indent = len(m_item.group(1)) // 2
            pad = "&nbsp;&nbsp;&nbsp;&nbsp;" * indent
            body = inline(m_item.group(4))
            if box == "☑︎ ":
                body = f"<strike>{body}</strike>"
            out.append(f"<li>{pad}{box}{body}</li>")
            continue
        if in_list:
            out.append("</ul>"); in_list = False
        m_h = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m_h:
            lvl = len(m_h.group(1))
            out.append(f"<h{lvl}>{inline(m_h.group(2))}</h{lvl}>")
        elif line.strip() in ("---", "***"):
            out.append("<div><br></div>")
        elif not line.strip():
            out.append("<div><br></div>")
        else:
            out.append(f"<div>{inline(line)}</div>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)

# ------------------------------------------------------------------ commands

COUNTS = re.compile(r"^_Updated [^\n]*_$", re.M)
SECTION = re.compile(r"^##\s+\W*(NOW|NEXT|LATER|EVENTUALLY)\b", re.I)


def fresh_counts(md: str) -> str:
    """The list's "_Updated · 4 NOW · 9 NEXT_" line, recounted, because the app can publish between syncs."""
    if not COUNTS.search(md):
        return md
    counts, cur = {}, None
    for line in md.splitlines():
        if line.startswith("## "):
            m = SECTION.match(line)
            cur = m.group(1).upper() if m else None
            if cur:
                counts.setdefault(cur, 0)
        elif cur and re.match(r"^- \[ \]", line):
            counts[cur] += 1
    now = dt.datetime.now()
    when = f"{now:%a} {now.month}/{now.day} {now.hour % 12 or 12}:{now:%M}{'am' if now.hour < 12 else 'pm'}"
    parts = [when] + [f"{counts[k]} {k}" for k in ("NOW", "NEXT", "LATER", "EVENTUALLY") if k in counts]
    return COUNTS.sub(lambda _: "_Updated " + " · ".join(parts) + "_", md, count=1)


def upsert(key: str, title: str, md: str, folder: str, force: bool) -> dict:
    rec = load_state().get(key, {})
    if rec.get("id") and not force:
        cur = jxa({"cmd": "get", "id": rec["id"]})
        if not cur.get("missing") and cur.get("text") is not None and h(cur["text"]) != rec.get("hash"):
            print(json.dumps({"conflict": True, "message":
                  f"'{title}' was edited in Notes since Theseus last wrote it. Reconcile those edits "
                  f"into the source file first (or rerun with --force to overwrite).",
                  "current_text": cur["text"]}, indent=1, ensure_ascii=False))
            sys.exit(4)
    body_md = md if md.lstrip().startswith("# ") else f"# {title}\n\n{md}"
    res = jxa({"cmd": "upsert", "id": rec.get("id"), "folder": folder, "html": md_to_html(body_md)})
    record(key, {"id": res["id"], "hash": h(res.get("text", "")), "title": title, "folder": folder, "modified_ms": res.get("modified_ms")})
    return {"published": True, "title": res["title"], "id": res["id"], "folder": res.get("folder")}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inbox")
    s = sub.add_parser("processed"); s.add_argument("--id", action="append", required=True)
    sub.add_parser("folders")
    s = sub.add_parser("folder"); s.add_argument("--path", required=True)
    s = sub.add_parser("find"); s.add_argument("--query", required=True)
    s = sub.add_parser("read"); s.add_argument("--id", required=True)
    sub.add_parser("master-read")
    s = sub.add_parser("master-publish"); s.add_argument("--file", default=str(WS / "data/master.md"))
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("note-read"); s.add_argument("--title", required=True)
    s = sub.add_parser("publish"); s.add_argument("--title", required=True); s.add_argument("--file", required=True)
    s.add_argument("--folder", default=MASTER_FOLDER); s.add_argument("--force", action="store_true")
    a = p.parse_args()

    if a.cmd == "inbox":
        notes = jxa({"cmd": "inbox", "inbox": INBOX})   # direct children only; Processed/ is a subfolder
        print(json.dumps(notes, indent=1, ensure_ascii=False))
    elif a.cmd == "processed":
        print(json.dumps(jxa({"cmd": "processed", "ids": a.id, "inbox": INBOX, "processed": PROCESSED}), indent=1))
    elif a.cmd == "folders":
        print(json.dumps(jxa({"cmd": "folders"}), indent=1, ensure_ascii=False))
    elif a.cmd == "folder":
        print(json.dumps(jxa({"cmd": "folder", "path": a.path}), indent=1, ensure_ascii=False))
    elif a.cmd == "find":
        print(json.dumps(jxa({"cmd": "find", "query": a.query}), indent=1, ensure_ascii=False))
    elif a.cmd == "read":
        print(json.dumps(jxa({"cmd": "read", "id": a.id}), indent=1, ensure_ascii=False))
    elif a.cmd in ("master-read", "note-read"):
        rec = load_state().get("master" if a.cmd == "master-read" else "note:" + a.title, {})
        if not rec.get("id"):
            print(json.dumps({"exists": False}))
            return
        cur = jxa({"cmd": "get", "id": rec["id"]})
        if cur.get("missing"):
            print(json.dumps({"exists": False, "note": "this note was deleted; the next publish recreates it"}))
            return
        print(json.dumps({"exists": True, "edited_by_user": h(cur.get("text", "")) != rec.get("hash"),
                          "text": cur.get("text")}, indent=1, ensure_ascii=False))
    elif a.cmd == "master-publish":
        md = fresh_counts(Path(a.file).read_text())
        print(json.dumps(upsert("master", MASTER_TITLE, md, MASTER_FOLDER, a.force), indent=1, ensure_ascii=False))
    elif a.cmd == "publish":
        md = Path(a.file).read_text()
        print(json.dumps(upsert("note:" + a.title, a.title, md, a.folder, a.force), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
