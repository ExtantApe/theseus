#!/usr/bin/env python3
"""
send_guard.py: holds Theseus to "never sends" for Composio, which can both read and send through one tool.

A Claude Code PreToolUse hook (engine/templates/settings.json). It reads the pending call on stdin and:
  - refuses anything that sends, posts or deletes, always
  - lets plain reads through to the normal permission rules
  - asks about anything else. With no one to answer (an unattended run), asking means it doesn't happen.
"""
import json
import re
import sys

NEVER = re.compile(r"(^|_)(SEND|REPLY|FORWARD|POST|PUBLISH|SHARE|INVITE|DELETE|TRASH|REMOVE|ARCHIVE)(_|$)")
READ = re.compile(r"(^|_)(FETCH|GET|LIST|SEARCH|FIND|READ|QUERY|LOOKUP|RETRIEVE|VIEW)(_|$)")
SHELLS = ("COMPOSIO_REMOTE_BASH_TOOL", "COMPOSIO_REMOTE_WORKBENCH", "COMPOSIO_PROXY_EXECUTE")


def decide(decision, reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision, "permissionDecisionReason": reason}}))
    sys.exit(0)


def main():
    try:
        call = json.load(sys.stdin)
    except ValueError:
        decide("ask", "Theseus couldn't read this call, so it's asking first.")
    tool = call.get("tool_name", "")
    if any(tool.endswith(s) for s in SHELLS):
        decide("ask", "This Composio tool can do anything, so Theseus asks first.")
    if not tool.endswith("COMPOSIO_MULTI_EXECUTE_TOOL"):
        return
    unknown = []
    for item in call.get("tool_input", {}).get("tools", []):
        slug = str(item.get("tool_slug", "")).upper()
        if NEVER.search(slug):
            decide("deny", f"Theseus never sends or deletes on your behalf: {slug} refused. Draft it for the user instead.")
        if not READ.search(slug):
            unknown.append(slug)
    if unknown:
        decide("ask", "Not a plain read, so Theseus asks first: " + ", ".join(unknown))


if __name__ == "__main__":
    main()
