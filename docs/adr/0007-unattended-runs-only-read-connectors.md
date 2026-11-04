# 0007: Unattended runs read connectors and make only the updates a sync needs
**Status:** accepted · 2026-11-04

**Context:** Unattended runs can't answer permission prompts, so connectors were allowed whole. That let them send ClickUp messages and delete Skylight items, which breaks ADR 0002, and only the rules stopped them.

**Decision:** A PreToolUse hook (`engine/tools/send_guard.py`) runs on every MCP tool. It refuses anything that sends, allows plain reads from the connectors in `config.unattended_read_connectors`, and leaves the rest to the normal rules: a prompt in a live session, nothing in an unattended one. The workspace settings then allow, by exact name, the updates that keep ClickUp and Skylight in step with the list. It decides from the tool's name, treats anything not plainly a read as a write, and blocks the call if it can't decide.

**Consequences:** A check-off in the app reaches Reminders, ClickUp and Skylight on the next sync. Deleting still needs a person, and anything a run couldn't do appears under Needs attention. To turn one of these updates off, deny that exact tool in `.claude/settings.local.json`; sends stay refused either way. Names are a heuristic, so a badly named read may prompt, and that's the safe direction.
