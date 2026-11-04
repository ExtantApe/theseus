# Changelog

## Unreleased
- New identity: an Athenian ship in ivory on Aegean blue, a monochrome menu bar icon that follows light and dark mode, and matching colors in the app.
- **Theseus for Mac is available** from Releases, built automatically. Every push now runs CI: leak check, script and Python checks, and an app build.
- **Ariadne is a separate tool** (ADR 0005). Theseus doesn't move files. With `integrations.ariadne` on, a check-in offers a filing pass when `ariadne count` passes `checkin_offers.unfiled`.
- **Theseus.app (M1 scaffold):** menu bar app in `apps/desktop` that hosts Remote Control, change checks and morning/nightly runs under one set of macOS permissions; Today / Services / Permissions views; "Take over hosting". `run-job.sh` stands down when `scheduler_host` is `app`. See ADR 0006.
- **Remote Control now runs in a Terminal window by default** (`remote_control.host: "terminal"`), kept open by a background watchdog.
  Terminal is then the app in charge, so phone sessions get its permissions, like command-line runs. `"background"` and a future `"app"` mode remain.
- **Remote Control server fixes**: input held open with a FIFO (it quit on "end of input" under launchd), a clean stop on restart (no leftover
  server blocking the next one with "already served"), and leftovers stopped before starting.
- **Texts and Mail inside Claude Code sessions**: when macOS blocks direct reads there, the tools fall back to saved copies, which the
  5-minute checks (running from /bin/bash, which has access) refresh whenever texts or mail change.
- `--schedule` now also (1) allows your connected MCP servers in scheduled runs via `.claude/settings.local.json` (Slack excluded, since it can
  post), and (2) runs `--grant`: a one-off background job that makes macOS ask for Calendar, Reminders and Notes access *for the background jobs*,
  which don't inherit Terminal's permissions. Removed invalid `Write(...)` permission rules (Edit rules cover all file edits).
- README: "Lightly opinionated": a fresh install starts blank and learns the person; the only fixed requirement is a Mac that stays on.
- **Always reachable**: `--schedule` now also keeps a Claude Code **Remote Control** server running in the workspace (`remote_control`, on by
  default; `--remote` installs it alone). The Mac appears in the Claude app's Code tab, so a fresh Theseus session can be started from anywhere.
  It restarts after crashes, reboots and `--update`, and nightly and morning health checks flag it in the Today note if it's down.
- **Text Theseus from your phone** (optional): `engine/install.sh --channel` keeps an iMessage channel session running in the workspace
  (official plugin; self-chat only; restarts after crashes and daily for new rules; removed by `--unschedule`). Setup step, docs §6b, compliance A8.
- `repeating_tasks_in_master` (default true): set false to keep repeating Reminders out of the master list; they still show under ⏰ when due.
  `lists_outside_master` keeps whole Reminders lists out.
- `extra_sections`: add your own master list sections (e.g. 💬 COMMUNICATIONS after NOW). Existing unknown sections are never dropped.
- Groceries by store (`grocery_reminders_list` as a list, mapped to Skylight sections), optional chore ⇄ Reminder sync (`chore_reminder_sync`,
  `data/chore-map.json`), and a rule for changing a chore's schedule without erasing its history.
- **Backlog check-in offers** (RULES §7d): one optional, timed "Got 5 minutes?" offer when a backlog builds up, at natural moments only,
  with yes / later / not today / never answers, and learning when the user likes to tidy. Thresholds in `config.checkin_offers`.
- **README rewritten**: who it's for, how it tailors itself, bubble-sort ranking up front, every command, how to start, roadmap, and an
  integrations table with one service per line (email and calendar listed separately per provider), with links and support status.
- **MCP vs Composio** explained: use either, or both, per service. Email and calendar accounts each carry their own `source`.
- **Slack, two ways**: the official Slack MCP connector (Claude Code sign-in, read-only use) or the email bridge. Setup asks which provider gets
  the notifications and gives step-by-step filters for Gmail/Google Workspace, Outlook/Microsoft 365 and iCloud.
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
