#!/usr/bin/env python3
"""
skylight_sync.py: keeps chores and groceries in step between Skylight and Reminders, without Claude (D212).

  python3 engine/tools/skylight_sync.py run [--dry-run]   one pass (the LaunchAgent runs this every 2 minutes)
  python3 engine/tools/skylight_sync.py status            what the last pass did, and any alert
  python3 engine/tools/skylight_sync.py install           print the LaunchAgent install command
  python3 engine/tools/skylight_sync.py uninstall         print the command that removes it

It does nothing unless config.json has "skylight_sync": "tool". Then the Claude syncs leave chores and groceries to it
(RULES §3.5 and §3.6).

What it syncs, and how:
- Groceries: the Skylight grocery list and one Reminders list per store (config "grocery_reminders_list"). A store is
  a section of the Skylight list (or as mapped in "grocery_store_sections"). Items are linked by id once matched;
  the first match is by normalized title and store, ignoring quantities. A Skylight item with no section goes to the
  first store and gets that section.
- Chores: only the links in data/chore-map.json. A Reminders occurrence and a Skylight occurrence match by the
  reminder's current due date, never by "the next open one". A link with several chores completes its reminder
  only once all of them are done in Skylight.

The rules, all covered by tests:
- A change on one side since the last pass is copied to the other.
- If both sides changed in opposite ways, done beats not-done.
- If both sides renamed an item, the newer edit wins when both sides say when they changed. Otherwise both are kept
  and the conflict is listed for the owner.
- Deletions never cross (RULES 0.4): an item gone from one side is unlinked and logged, and the other copy stays.
- Nothing new is dated on a kid's chore, no chore series is changed, and no chore is created. Those are listed.

The Skylight login is read from the Keychain (service "Theseus Skylight", account = the login email) and handed to
skylight-mcp in its environment. It is never written to disk or to a log. skylight-mcp keeps its own token in
data/.skylight-tokens.json (0600), apart from the one Claude Code's connector uses.

Every write goes to data/log.md. Each pass adds one short line to logs/skylight-sync.log. Problems that need a person
(an expired login, a conflict) are kept in data/skylight-sync.json under "alerts", and the next Claude run shows them.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

WS = Path(os.environ.get("THESEUS_HOME") or Path(__file__).resolve().parents[2])
STATE = WS / "data" / "skylight-sync.json"
TOKENS = WS / "data" / ".skylight-tokens.json"
CHORE_MAP = WS / "data" / "chore-map.json"
LOG = WS / "logs" / "skylight-sync.log"
WRITE_LOG = WS / "data" / "log.md"
LOCK = WS / "data" / ".skylight-sync.lock"
KEYCHAIN_SERVICE = "Theseus Skylight"
AGENT = "com.theseus.skylight-sync"
MCP_COMMAND = ["npx", "-y", "skylight-mcp@1.7.0"]
CHORE_DAYS_BACK, CHORE_DAYS_AHEAD = 7, 7
DONE_WORDS = {"complete", "completed", "done", "checked"}


# ---------------------------------------------------------------- matching

_QTY = re.compile(r"^\s*(\d+(\.\d+)?\s*(x|×)?\s+|x\s*\d+\s+)|(\s+(x|×)\s*\d+|\s*\(\s*\d+\s*\)|\s+\d+\s*(x|×))\s*$", re.I)


def norm(title: str) -> str:
    """A title for matching: case, spacing, curly quotes and a leading or trailing quantity don't count."""
    t = unicodedata.normalize("NFKC", title or "").replace("’", "'").replace("‘", "'").strip().lower()
    prev = None
    while prev != t:
        prev, t = t, _QTY.sub(" ", t).strip()
    return re.sub(r"\s+", " ", t)


def local_date(stamp) -> str | None:
    """The local calendar date of an ISO time, or the date itself if it's already YYYY-MM-DD."""
    if not stamp:
        return None
    s = str(stamp)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d.astimezone() if d.tzinfo else d).date().isoformat()


def when(stamp) -> float | None:
    if not stamp:
        return None
    try:
        return dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def is_done(status) -> bool:
    return str(status or "").strip().lower() in DONE_WORDS


# ---------------------------------------------------------------- groceries

def stores(cfg: dict) -> list[str]:
    raw = cfg.get("grocery_reminders_list") or "Groceries"
    return [raw] if isinstance(raw, str) else [s for s in raw if isinstance(s, str) and s]


def section_for(cfg: dict, store: str) -> str:
    return (cfg.get("grocery_store_sections") or {}).get(store, store)


def store_for(cfg: dict, section) -> str | None:
    """The store a Skylight section belongs to, or None for no section. A section that isn't a store is None too."""
    if not section:
        return None
    for st in stores(cfg):
        if norm(section_for(cfg, st)) == norm(section):
            return st
    return None


def plan_groceries(cfg: dict, links: list[dict], sky: list[dict], rems: list[dict], orphans: list[str] | None = None):
    """
    What to do so the two grocery lists agree.

    sky:  [{"id", "label", "done", "section", "updated"}]   the Skylight grocery list
    rems: [{"id", "title", "done", "list", "modified"}]     reminders in the store lists, open and recently completed
    links: the last pass's links, [{"sky", "rem", "store", "label", "title", "sky_done", "rem_done"}]

    orphans: ids of items whose other copy was deleted. They stay single: re-creating the deleted copy would undo
    the person's delete.

    Returns (actions, links, notes, orphans). Actions are tuples for apply(). New links for items still to be created
    carry "pending": the action index that will create the missing side.
    """
    shops = stores(cfg)
    first = shops[0]
    by_sky = {s["id"]: s for s in sky}
    by_rem = {r["id"]: r for r in rems if r.get("list") in shops}
    actions, notes, kept = [], [], []
    alive = set(by_sky) | set(by_rem)
    single = {o for o in (orphans or []) if o in alive}

    for ln in links:
        s, r = by_sky.get(ln["sky"]), by_rem.get(ln["rem"])
        if s is None or r is None:
            gone, other = ("Skylight", "Reminders") if s is None else ("Reminders", "Skylight")
            settled = ln.get("sky_done") and ln.get("rem_done")
            if not settled and not (s is None and r is None):
                notes.append(f"'{ln['title']}' is gone from {gone}; the {other} copy was left alone (deletions never cross)")
            single.add(ln["rem"] if s is None else ln["sky"])
            continue
        new = dict(ln)
        # Done or not: a change on one side is copied; opposite changes on both sides go to done.
        ds, dr = s["done"] != ln["sky_done"], r["done"] != ln["rem_done"]
        if s["done"] != r["done"]:
            if ds and not dr:
                actions.append(("rem_done", r["id"], s["done"]))
                r = {**r, "done": s["done"]}
            elif dr and not ds:
                actions.append(("sky_done", s["id"], r["done"]))
                s = {**s, "done": r["done"]}
            else:  # both changed, or out of step from an earlier failure: done beats not-done
                if not s["done"]:
                    actions.append(("sky_done", s["id"], True))
                    s = {**s, "done": True}
                else:
                    actions.append(("rem_done", r["id"], True))
                    r = {**r, "done": True}
        # Titles: one side's edit is copied; edits on both sides go to the newer, if both sides say when.
        cs, cr = s["label"] != ln["label"], r["title"] != ln["title"]
        if s["label"] != r["title"]:
            if cs and not cr:
                actions.append(("rem_title", r["id"], s["label"]))
                r = {**r, "title": s["label"]}
            elif cr and not cs:
                actions.append(("sky_label", s["id"], r["title"]))
                s = {**s, "label": r["title"]}
            elif cs and cr:
                ts, tr = when(s.get("updated")), when(r.get("modified"))
                if ts is not None and tr is not None:
                    if ts >= tr:
                        actions.append(("rem_title", r["id"], s["label"]))
                        r = {**r, "title": s["label"]}
                    else:
                        actions.append(("sky_label", s["id"], r["title"]))
                        s = {**s, "label": r["title"]}
                else:
                    notes.append(f"Renamed on both sides: Skylight '{s['label']}', Reminders '{r['title']}'. Both kept; pick one")
        # Store: a Skylight section change moves the reminder; a reminder moved to another store sets the section.
        sky_store = store_for(cfg, s.get("section"))
        if r["list"] != ln["store"] and sky_store == ln["store"]:
            actions.append(("sky_section", s["id"], section_for(cfg, r["list"])))
            new["store"] = r["list"]
        elif sky_store and sky_store != ln["store"] and r["list"] == ln["store"]:
            actions.append(("rem_list", r["id"], sky_store))
            new["store"] = sky_store
        new.update(label=s["label"], title=r["title"], sky_done=s["done"], rem_done=r["done"])
        kept.append(new)

    linked_sky = {ln["sky"] for ln in kept}
    linked_rem = {ln["rem"] for ln in kept}
    open_rems = [r for r in by_rem.values() if r["id"] not in linked_rem and r["id"] not in single and not r["done"]]

    for s in sky:
        if s["id"] in linked_sky or s["id"] in single or s["done"]:
            continue
        store = store_for(cfg, s.get("section"))
        if store is None:
            store = first
            actions.append(("sky_section", s["id"], section_for(cfg, first)))
        match = next((r for r in open_rems if r["list"] == store and norm(r["title"]) == norm(s["label"])), None)
        if match:
            open_rems.remove(match)
            kept.append({"sky": s["id"], "rem": match["id"], "store": store, "label": s["label"], "title": match["title"],
                         "sky_done": False, "rem_done": False})
        else:
            actions.append(("rem_add", store, s["label"]))
            kept.append({"sky": s["id"], "rem": None, "store": store, "label": s["label"], "title": s["label"],
                         "sky_done": False, "rem_done": False, "pending": len(actions) - 1})
        linked_sky.add(s["id"])

    for r in open_rems:
        actions.append(("sky_add", r["title"], section_for(cfg, r["list"])))
        kept.append({"sky": None, "rem": r["id"], "store": r["list"], "label": r["title"], "title": r["title"],
                     "sky_done": False, "rem_done": False, "pending": len(actions) - 1})
    return actions, kept, notes, sorted(single)


# ---------------------------------------------------------------- chores

def occurrences(rows: list[dict]) -> dict:
    """{(chore id, YYYY-MM-DD): done} from skylight_list_chores rows."""
    out = {}
    for row in rows:
        day = local_date(row.get("start") or row.get("date") or row.get("instance_date"))
        cid = str(row.get("chore_id") or row.get("recurring_chore_id") or row.get("id") or "")
        if cid and day:
            out[(cid, day)] = is_done(row.get("status")) or bool(row.get("completed"))
    return out


def plan_chores(chore_map: dict, rems: dict, occ: dict, seen: dict):
    """
    What to do for each chore-map link.

    rems: {reminder id: {"id", "title", "done", "due", "recurring"}}   the linked reminders
    occ:  {(chore id, date): done}                                    Skylight occurrences in the read window
    seen: {reminder id: {"due": date, "done": bool}}                  the last pass

    Returns (actions, seen, notes).
    """
    actions, notes, new_seen = [], [], {}
    for ln in chore_map.get("links", []):
        rid = ln.get("reminder") or ln.get("reminder_id")
        chores = [str(c) for c in ln.get("chores") or ln.get("chore_ids") or []]
        r = rems.get(rid)
        if not rid or not chores:
            continue
        if r is None:
            notes.append(f"Chore '{ln.get('title', rid)}' has no reminder any more; the Skylight chore was left alone")
            continue
        due, last = local_date(r.get("due")), seen.get(rid) or {}
        # Reminders → Skylight. A repeating reminder that moved on was done for the date it had; a one-off that was
        # ticked was done for its date. Only that date's Skylight occurrences are completed.
        done_on = None
        if r.get("recurring") and last.get("due") and due and due > last["due"]:
            done_on = last["due"]
        elif not r.get("recurring") and r["done"] and not last.get("done"):
            done_on = due
        if done_on:
            for c in chores:
                if occ.get((c, done_on)) is False:
                    actions.append(("chore_done", c, done_on))
                    occ = {**occ, (c, done_on): True}
        # Skylight → Reminders: every linked chore is done for the reminder's current date.
        elif due and not r["done"]:
            states = [occ.get((c, due)) for c in chores]
            if states and all(st is True for st in states):
                actions.append(("rem_done", rid, True))
                if not r.get("recurring"):
                    r = {**r, "done": True}
        new_seen[rid] = {"due": due, "done": r["done"]}
    return actions, new_seen, notes


# ---------------------------------------------------------------- the outside world

class SyncError(Exception):
    """A problem that stops the pass and needs a person, such as a login that has expired."""


def keychain_login() -> dict:
    """SKYLIGHT_EMAIL and SKYLIGHT_PASSWORD from the Keychain. The values are never printed."""
    meta = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE], capture_output=True, text=True)
    if meta.returncode != 0:
        raise SyncError(f"No Skylight login in the Keychain (service \"{KEYCHAIN_SERVICE}\"). Add it with the command in docs/SETUP.md.")
    m = re.search(r'"acct"<blob>="([^"]*)"', meta.stdout)
    pw = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True, text=True)
    if not m or pw.returncode != 0 or not pw.stdout.strip():
        raise SyncError("The Skylight Keychain item has no account or password.")
    return {"SKYLIGHT_EMAIL": m.group(1), "SKYLIGHT_PASSWORD": pw.stdout.rstrip("\n")}


class Skylight:
    """skylight-mcp over stdio: plain JSON-RPC, no Claude. Login, refresh and retries are skylight-mcp's own code."""

    def __init__(self, command=None, env=None):
        TOKENS.parent.mkdir(parents=True, exist_ok=True)
        full_env = {**os.environ, **(env or {}), "SKYLIGHT_TOKEN_FILE": str(TOKENS), "MCP_CONFIRM_MODE": "token"}
        self.p = subprocess.Popen(command or MCP_COMMAND, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, env=full_env, cwd=WS)
        self.n = 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "theseus-skylight-sync", "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def _rpc(self, method, params):
        self.n += 1
        self._send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise SyncError("skylight-mcp stopped without answering")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise SyncError(f"skylight-mcp: {msg['error'].get('message', 'error')}")
                return msg.get("result") or {}

    def call(self, tool, **args):
        res = self._rpc("tools/call", {"name": tool, "arguments": args})
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            low = text.lower()
            if any(w in low for w in ("login", "challenge", "unauthor", "401", "credential", "missing:")):
                raise SyncError("Skylight needs you to sign in again (run /login-skylight, or see docs/SETUP.md).")
            raise SyncError(f"Skylight {tool} failed: {text[:200]}")
        try:
            return json.loads(text)
        except ValueError:
            return text

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()
        finally:
            self.p.stdout.close()


def ek(*args) -> object:
    p = subprocess.run([str(WS / "bin/ek"), *args], capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise SyncError(f"bin/ek {args[0]} failed: {(p.stderr or p.stdout).strip()[:200]}")
    return json.loads(p.stdout or "null")


# ---------------------------------------------------------------- state, logs, alerts

def load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save_state(state: dict):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False))
    tmp.replace(STATE)


def write_log(action: str, what: str, why: str = "skylight sync"):
    WRITE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with WRITE_LOG.open("a") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M} · {action} · {what} · {why}\n")


def pass_log(line: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {line}\n")
    try:
        if LOG.stat().st_size > 2_000_000:
            keep = LOG.read_bytes()[-500_000:]
            LOG.write_bytes(keep[keep.find(b"\n") + 1:])
    except OSError:
        pass


def add_alerts(state: dict, texts: list[str]):
    have = {a["text"] for a in state.setdefault("alerts", [])}
    for t in texts:
        if t not in have:
            state["alerts"].append({"at": dt.datetime.now().isoformat(timespec="minutes"), "text": t})
            have.add(t)
    state["alerts"] = state["alerts"][-30:]


# ---------------------------------------------------------------- one pass

def read_sky_groceries(sk: Skylight, cfg: dict):
    want = norm(cfg.get("skylight_grocery_list") or "Grocery List")
    lists = sk.call("skylight_list_lists")
    lists = lists if isinstance(lists, list) else []
    found = next((l for l in lists if norm(l.get("label") or l.get("name") or "") in (want, norm("Grocery List"), norm("Grocery"))), None)
    if not found:
        raise SyncError(f"No Skylight list called \"{cfg.get('skylight_grocery_list') or 'Grocery List'}\"")
    rows = sk.call("skylight_get_list_items", listId=str(found["id"]))
    rows = rows if isinstance(rows, list) else []
    items = [{"id": str(r["id"]), "label": r.get("label") or "", "done": is_done(r.get("status")),
              "section": r.get("section"), "updated": r.get("updated_at") or r.get("updatedAt")} for r in rows if r.get("id")]
    return str(found["id"]), items


def read_rems(lists: list[str] | None, days: int = 30) -> list[dict]:
    """Open reminders plus those completed in the last `days`. No lists means every list."""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = ek("reminders", *(["--list", ",".join(lists)] if lists else []), "--completed-since", since)
    return [{"id": r["id"], "title": r.get("title") or "", "done": bool(r.get("completed")), "list": r.get("list"),
             "modified": r.get("modified"), "due": r.get("due"), "recurring": bool(r.get("recurring"))} for r in rows or []]


def apply(actions, sk: Skylight | None, list_id: str | None, links: list[dict], dry: bool) -> list[str]:
    """Carries out the actions, logs each write, and fills in the ids of items it created."""
    done = []
    for i, a in enumerate(actions):
        kind = a[0]
        desc = f"{kind} {' · '.join(str(x) for x in a[1:])}"
        if dry:
            done.append(desc)
            continue
        if kind == "rem_done":
            ek("complete" if a[2] else "uncomplete", "--id", a[1])
        elif kind == "rem_title":
            ek("update", "--id", a[1], "--title", a[2])
        elif kind == "rem_list":
            ek("update", "--id", a[1], "--list", a[2])
        elif kind == "rem_add":
            made = ek("add-reminder", "--title", a[2], "--list", a[1])
            for ln in links:
                if ln.get("pending") == i:
                    ln["rem"] = made["id"]
                    ln.pop("pending")
        elif kind == "sky_done":
            sk.call("skylight_update_list_item", listId=list_id, itemId=a[1], checked=bool(a[2]))
        elif kind == "sky_label":
            sk.call("skylight_update_list_item", listId=list_id, itemId=a[1], label=a[2])
        elif kind == "sky_section":
            sk.call("skylight_update_list_item", listId=list_id, itemId=a[1], section=a[2])
        elif kind == "sky_add":
            made = sk.call("skylight_add_list_item", listId=list_id, label=a[1])
            new_id = str(made.get("id")) if isinstance(made, dict) and made.get("id") else None
            if new_id:
                sk.call("skylight_update_list_item", listId=list_id, itemId=new_id, section=a[2])
            for ln in links:
                if ln.get("pending") == i:
                    ln["sky"] = new_id
                    ln.pop("pending")
        elif kind == "chore_done":
            sk.call("skylight_complete_chore_instance", id=a[1], instance_date=a[2])
        write_log(kind.replace("_", " "), " · ".join(str(x) for x in a[1:]))
        done.append(desc)
    return done


def run(dry: bool = False) -> int:
    cfg = load(WS / "config.json", {})
    if cfg.get("skylight_sync") != "tool":
        print('skylight sync is off (config.json "skylight_sync" is not "tool")')
        return 0
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    lock = LOCK.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0  # the previous pass is still running
    state = load(STATE, {})
    if state.get("stopped") and not dry:
        pass_log(f"stopped: {state['stopped']}")
        return 1
    started = time.time()
    sk = None
    try:
        sk = Skylight(env=keychain_login())
        list_id, sky = read_sky_groceries(sk, cfg)
        shops = stores(cfg)
        rems = read_rems(shops)
        g_actions, g_links, g_notes, g_single = plan_groceries(cfg, [l for l in state.get("grocery_links", []) if l.get("sky") and l.get("rem")],
                                                               sky, rems, state.get("grocery_single", []))
        chore_map = load(CHORE_MAP, {"links": []})
        today = dt.date.today()
        rows = sk.call("skylight_list_chores", after=(today - dt.timedelta(days=CHORE_DAYS_BACK)).isoformat(),
                       before=(today + dt.timedelta(days=CHORE_DAYS_AHEAD)).isoformat())
        occ = occurrences(rows if isinstance(rows, list) else [])
        linked = {ln.get("reminder") or ln.get("reminder_id") for ln in chore_map.get("links", [])}
        # The linked reminders can sit in any list ("Kids" today, maybe one per kid later), so every list is read.
        chore_rems = {r["id"]: r for r in read_rems(None, days=CHORE_DAYS_BACK) if r["id"] in linked}
        c_actions, c_seen, c_notes = plan_chores(chore_map, chore_rems, occ, state.get("chore_seen", {}))
        did = apply(g_actions, sk, list_id, g_links, dry) + apply(c_actions, sk, list_id, [], dry)
        if dry:
            print(json.dumps({"would_do": did, "notes": g_notes + c_notes}, indent=1, ensure_ascii=False))
            return 0
        state.update(grocery_links=[l for l in g_links if l.get("sky") and l.get("rem")], grocery_single=g_single, chore_seen=c_seen,
                     last_pass=dt.datetime.now().isoformat(timespec="seconds"), last_changes=len(did))
        add_alerts(state, g_notes + c_notes)
        save_state(state)
        pass_log(f"ok in {time.time() - started:.1f}s: {len(did)} change(s)")
        return 0
    except SyncError as e:
        msg = str(e)
        if "sign in" in msg or "Keychain" in msg:
            state["stopped"] = msg  # don't keep knocking on the login; a person has to act
        add_alerts(state, [msg])
        if not dry:
            save_state(state)
        pass_log(f"error: {msg}")
        print(msg, file=sys.stderr)
        return 1
    finally:
        if sk:
            sk.close()


def agent_plist(python: str = "/usr/bin/python3") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{AGENT}</string>
  <key>ProgramArguments</key><array><string>{python}</string><string>{WS / 'engine/tools/skylight_sync.py'}</string><string>run</string></array>
  <key>WorkingDirectory</key><string>{WS}</string>
  <key>EnvironmentVariables</key><dict><key>THESEUS_HOME</key><string>{WS}</string><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StartInterval</key><integer>120</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>{LOG}</string>
  <key>StandardErrorPath</key><string>{LOG}</string>
</dict></plist>
"""


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "help"
    if cmd == "run":
        return run(dry="--dry-run" in argv)
    if cmd == "status":
        st = load(STATE, {})
        print(json.dumps({k: st.get(k) for k in ("last_pass", "last_changes", "stopped", "alerts")}, indent=1, ensure_ascii=False))
        return 0
    if cmd == "resume":
        st = load(STATE, {})
        st.pop("stopped", None)
        save_state(st)
        print("The next pass will try again.")
        return 0
    if cmd in ("install", "uninstall"):
        path = Path.home() / "Library/LaunchAgents" / f"{AGENT}.plist"
        dom = f"gui/{os.getuid()}"
        if cmd == "install":
            out = WS / "data" / f"{AGENT}.plist"
            out.write_text(agent_plist())
            print(f"cp '{out}' '{path}' && launchctl bootstrap {dom} '{path}'")
        else:
            print(f"launchctl bootout {dom} '{path}'; rm -f '{path}'")
        return 0
    print(__doc__)
    return 0 if cmd in ("help", "-h", "--help") else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
