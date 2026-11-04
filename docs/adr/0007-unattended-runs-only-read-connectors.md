# 0007: Unattended runs only read connectors
**Status:** accepted · 2026-11-04

**Context:** Unattended runs can't answer permission prompts, so connectors were allowed whole. That let them send ClickUp messages and delete Skylight items, which breaks ADR 0002, and only the rules stopped them.

**Decision:** A PreToolUse hook (`engine/tools/send_guard.py`) runs on every MCP tool. It refuses anything that sends, allows plain reads from the connectors in `config.unattended_read_connectors`, and leaves the rest to the normal rules: a prompt in a live session, nothing in an unattended one. It decides from the tool's name, treats anything not plainly a read as a write, and blocks the call if it can't decide.

**Consequences:** A check-off in the app reaches Reminders on the next sync, but ClickUp and Skylight changes wait for a live session and appear under Needs attention. To let one through unattended, allow that exact tool in `.claude/settings.local.json`; sends stay refused either way. Names are a heuristic, so a badly named read may prompt, and that's the safe direction.
