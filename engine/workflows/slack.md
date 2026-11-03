---
description: Process Slack notification emails and run the "did you get to these?" check-in
argument-hint: [your answers, e.g. "1 3 done, 2 → task"]
---
Follow engine/RULES.md §10 (Slack email bridge). Only if `slack_email_bridge` is enabled.
- If answers are given ("$ARGUMENTS"), apply them to data/slack-items.json first, and create master tasks for any "→ task" items.
- Read new mail in `slack_digest_folder` via `email_source`, split it into items, and merge with open items (skip `seen_ids`).
- Show the numbered check-in list (open items only) and how to answer. Keep it short.
