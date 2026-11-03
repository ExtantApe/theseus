---
description: Full fresh status: sync everything, process inbox, texts, calendar, email
---
Run a complete, fresh status update per engine/RULES.md §5. Re-run everything; never reuse an earlier briefing. Use only integrations enabled in config.json.
1. Sync per §3: Reminders (completed since `last_sync`), plus Skylight and ClickUp if enabled.
2. Process the Notes inbox (§4): `python3 engine/tools/notes.py inbox`.
3. `python3 engine/tools/notes.py master-read`. If `edited_by_user` is true, fold the edits into data/master.md first.
4. Texts: `python3 engine/tools/imsg.py --fresh missed`.
5. Calendar via `calendar_source` (today, plus tomorrow morning if it's evening).
6. Email via `email_source` (all accounts), plus the Slack email bridge if enabled (§10).
7. Auto-detect what's already done (§3).
8. Re-rank NOW and NEXT (data/priorities.md), update data/master.md, then `python3 engine/tools/notes.py master-publish`.
9. Reply with the §5 briefing (compact version if this came through a phone channel). Save `last_shown`.

Extra focus (optional): $ARGUMENTS

Bookends (engine/RULES.md §5 "📌 The pinned Today note"): start with the Today-note read-back, and end by republishing the Today note.
