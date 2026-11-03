---
description: Quiet sync of Reminders ⇄ master list ⇄ connected apps (no briefing)
---
Run only the sync rules in engine/RULES.md §3 and inbox processing §4. Publish the master note if anything changed.
Output: one line per change, or "No changes." This may run unattended hourly, so never wait for input.

Bookends (engine/RULES.md §5 "📌 The pinned Today note"): start with the Today-note read-back, and end by republishing the Today note.
