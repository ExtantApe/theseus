# Changelog

## Unreleased
- **Repeating reminders**: `ek add-reminder` and `ek update` take `--recur "<RRULE>"`, `ek update` takes `--clear-recur`, and reminder output
  includes `recurrence`.
- Repeating tasks in the rules: one repeating Reminder plus one `↻` master item; completing an occurrence keeps the item and advances its due date
  instead of moving it to DONE. A plain-language → RRULE table, and a confirmation the first time.
- `recurrence` in reminder output is now built from the rule's own fields (stable across macOS versions); safer BYSETPOS parsing.
- `install.sh` flags work in any order (`--force --update` == `--update --force`).
- docs/SETUP.md §10a explains the local-changes handoff for contributors.
- **Local changes handoff**: `data/local-changes.md` records engine changes made or recommended in a workspace (`engine/tools/local_changes.py`).
  A SessionStart hook in this repo lists pending entries, and `install` and `--update` stop if a pending patch isn't in the source (`--force` overrides).

## 0.4.0
- **Flexible schedules**: regimented or fluid, weekday/weekend (or any) day groups, single-day overrides, flex hours. Morning and nightly runs
  are scheduled per day (including evening runs after midnight). A "you're up" refresh fires on the first activity after 4+ quiet hours, and
  weekly rhythm learning suggests schedule tweaks. Setup now asks about all of this. (`engine/tools/schedule.py`)
- **docs/APP-PLAN.md**: plan for Theseus.app as a single shipped package (Tauri 2, same engine), milestones M0–M5.
- Architecture decision records in `docs/adr`.

## 0.3.1
- Local checks can run every few minutes (default 5). Claude is rate-limited (`min_minutes_between_claude_runs`, default 15), and changes
  seen during the wait are queued. Awake hours are enforced in the check itself. The Notes app is no longer launched on every check.

## 0.3.0
- **Configurable frequent checks** (`checks` in config.json; default every 30 min while awake, opt-in). A local change test
  (`engine/tools/changes.py`) runs first, and Claude only runs if texts, notes, reminders, calendar, alarms or mail changed, or a full refresh is due.
  Replaces `hourly_sync`.

## 0.2.0
- 📌 Pinned **Today** note, republished on every run. It works offline, and your edits (✍️ Jot here, ☐→x, reordering) are read back.
  🌙 Tomorrow is now a section of it instead of a separate note.
- Philosophy written into the rules: Theseus helps you live your life; it doesn't live it for you.
- Docs: running unsigned preview builds of the planned Mac app; the two ways an app can talk to Claude.
- CREDITS.md and the borrowing policy.
- Monthly **compliance check**: re-reads Anthropic's rules against docs/COMPLIANCE.md and proposes changes (it never edits on its own).
- README: free and open source, always.
- Scheduled runs quietly open any apps listed in `ensure_apps` (plus Apple Mail when it's the email source).

## 0.1.0
- First public version: master list (NOW/NEXT/LATER/EVENTUALLY), Notes inbox, nightly "🌙 Tomorrow" and morning "☀️ Today" briefings,
  texts-waiting, as-if-they-asked reply drafting, pairwise ranking, "what's next?" check-ins, auto-detection of done items,
  thread reports, iPhone alarms via Shortcuts, Things 3 migration, optional Skylight / ClickUp / Slack email bridge.
- Email and calendar from connectors (e.g. Composio) or Apple Mail / Calendar, chosen per user.
