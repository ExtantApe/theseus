#!/usr/bin/env python3
"""
send_guard.py: holds Theseus to "never sends" for every connector, in every session.

A Claude Code PreToolUse hook on all MCP tools (engine/templates/settings.json). It reads the pending call on stdin and decides by the tool's name:
  - anything that sends, posts or messages someone: refused, always
  - a plain read from a connector listed in config.json → unattended_read_connectors: allowed, so unattended runs can read
  - everything else goes to the normal permission rules: you're asked in a live session, and an unattended run can't do it
Composio runs many actions through one tool, so each action is checked, and deleting through it is refused too.

If this script can't decide (bad input, a crash), it exits 2, which blocks the call. Only exit 2 blocks; a plain crash wouldn't.
Names are read for what they could do, not what they probably do: a read word anywhere isn't enough if any other word says it writes.
"""
import json
import os
import re
import sys
from pathlib import Path

SEND = {"SEND", "SENDS", "REPLY", "REPLIES", "FORWARD", "POST", "PUBLISH", "SHARE", "INVITE", "NOTIFY", "BROADCAST", "ANNOUNCE", "DM"}
DESTROY = {"DELETE", "DELETES", "TRASH", "REMOVE", "REMOVES", "ARCHIVE", "PURGE", "ERASE", "DESTROY", "WIPE", "CLEAR"}
READ = {"FETCH", "GET", "LIST", "SEARCH", "FIND", "READ", "QUERY", "LOOKUP", "RETRIEVE", "VIEW", "FILTER", "HEALTHCHECK", "DESCRIBE", "COUNT"}
WRITE = {"CREATE", "UPDATE", "ADD", "SET", "INSERT", "PATCH", "PUT", "MOVE", "MODIFY", "EDIT", "UPSERT", "MERGE", "MARK", "DRAFT", "WRITE", "SAVE", "RENAME",
         "COPY", "UPLOAD", "IMPORT", "TRANSFER", "SUBSCRIBE", "UNSUBSCRIBE", "ENROLL", "ASSIGN", "APPROVE", "REJECT", "CANCEL", "COMPLETE", "CLOSE", "OPEN",
         "START", "STOP", "RUN", "EXECUTE", "TRIGGER", "ENABLE", "DISABLE", "PAY", "CHARGE", "REFUND", "RESET", "REVOKE", "GRANT", "BLOCK", "BAN", "KICK",
         "JOIN", "LEAVE", "PIN", "UNPIN", "STAR", "LIKE", "REACT", "SYNC", "REDEEM", "PLAN", "GENERATE", "LINK", "UNLINK", "SCHEDULE", "BOOK", "OR", "AND", "THEN"}
# Writing any of these reaches another person, so it counts as sending. Saving a draft doesn't.
PEOPLE = {"COMMENT", "COMMENTS", "MESSAGE", "MESSAGES", "CHAT", "EMAIL", "EMAILS", "MAIL", "SMS", "TEXT"}
COMPOSIO_SHELLS = ("COMPOSIO_REMOTE_BASH_TOOL", "COMPOSIO_REMOTE_WORKBENCH", "COMPOSIO_PROXY_EXECUTE")
# The iMessage channel's own reply tool. RULES §5b limits it to the self-chat you're texting from.
EXEMPT_SERVERS = ("plugin_imessage",)


def classify(name: str) -> str:
    """send | destroy | read | write. Anything not plainly a read is a write."""
    words = {w for w in re.split(r"[^A-Z0-9]+", name.upper()) if w}
    if words & SEND:
        return "send"
    if words & DESTROY:
        return "destroy"
    if words & READ and not words & WRITE:
        return "read"
    if words & PEOPLE and "DRAFT" not in words:
        return "send"
    return "write"


def decide(decision: str, reason: str):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision, "permissionDecisionReason": reason}}))
    sys.exit(0)


def read_connectors() -> list:
    try:
        root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".")
        return list(json.loads((root / "config.json").read_text()).get("unattended_read_connectors") or [])
    except (OSError, ValueError, TypeError):
        return []


def composio(tool: str, call: dict):
    if any(tool.endswith(s) for s in COMPOSIO_SHELLS):
        decide("ask", "This Composio tool can do anything, so Theseus asks first.")
    if not tool.endswith("COMPOSIO_MULTI_EXECUTE_TOOL"):
        return
    actions = call["tool_input"]["tools"]
    if not actions:
        raise ValueError("no actions to check")
    unknown = []
    for item in actions:
        slug = str(item["tool_slug"]).upper()
        kind = classify(slug)
        if kind in ("send", "destroy"):
            decide("deny", f"Theseus never sends or deletes on your behalf: {slug} refused. Draft it for the user instead.")
        if kind != "read":
            unknown.append(slug)
    if unknown:
        decide("ask", "Not a plain read, so Theseus asks first: " + ", ".join(unknown))


def main():
    call = json.load(sys.stdin)
    tool = call["tool_name"]
    parts = tool.split("__")
    if len(parts) < 3 or parts[0] != "mcp":
        return
    server, name = parts[1], "__".join(parts[2:])
    if server.startswith(EXEMPT_SERVERS):
        return
    if "COMPOSIO_" in name:
        return composio(tool, call)
    kind = classify(name)
    if kind == "send":
        decide("deny", f"Theseus never sends anything on your behalf: {name} refused. Draft it for the user instead.")
    if kind == "read" and server in read_connectors():
        decide("allow", "A plain read from a connected service.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:   # can't tell what this call does, so it doesn't happen
        print(f"Theseus's send guard couldn't check this call, so it's blocked: {e!r}", file=sys.stderr)
        sys.exit(2)
