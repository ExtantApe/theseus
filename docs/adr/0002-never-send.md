# ADR 0002: Theseus never sends on the user's behalf
**Status:** accepted · 2026-11-03
**Decision:** No messages, emails, Slack posts, comments or invites to other people, ever. Drafts only. `engine/tools/send_guard.py` refuses anything that sends, on every connector and in every session; a few known sending tools are also denied by name in the workspace settings. If the guard can't decide, the call is blocked.
**Why:** Theseus helps people live their lives; it doesn't live their lives for them. Trust is the product.
**Consequences:** features like "auto-reply" are out of scope. The app offers Copy and "Open in Messages", never Send.
