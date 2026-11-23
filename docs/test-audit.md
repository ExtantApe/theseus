# Test audit

How the tests line up with what Theseus promises. Redo it after every feature or fix, and at least every 14 days while the repo has commits.

## 2026-11-22 · Skylight sync, leave-by times, Quit and the Dock

| Promise | Proved by |
| --- | --- |
| The Skylight sync matches, links, copies done and renames, moves sections, and never deletes (D212) | `tests/test_skylight_sync.py`: the grocery, chore and client classes, including "no plan ever deletes" |
| New grocery items reuse the Skylight section's own spelling | `test_a_new_item_reuses_the_skylight_section_as_spelled_there` |
| While the sync is off it does nothing, and a dry run works then and writes nothing | **Added:** `OffSwitchAndDryRun`: a real pass never opens Skylight or saves state; a dry run reads, lists what it would do, and reaches neither Skylight's writes, Reminders, the change log nor the state file |
| Leave-by times come from Apple Maps travel times, starting from the home address on the owner's card | `tests/test_eta.py` |
| Quit stops the whole process tree Remote Control started, TERM then KILL, with an 8-second backstop | the macOS test in `src-tauri` where the child ignores HUP and TERM |
| Every way out leaves the watchdog marker; Theseus stays in the Dock | the marker and Dock unit tests in `src-tauri/src/lib.rs` |
| The window has a standard menu bar with Quit | the cargo tests for the menu contents and ids |

Gaps skipped: clicking the menu bar icon's Quit, and a real Remote Control session, need the owner's screen and login (both noted in their commits). A dry run still creates the sync's lock file, and logs a line if it fails; neither holds user data, so that's left as is. Release-only commits (0.6.2) change version numbers, which the version check already covers.

## 2026-11-09 · the Impact view

| Promise | Proved by |
| --- | --- |
| The order is low effort/high impact, high/high, low/low, high/low, unrated last; effort comes from the size estimate | `focus.test.ts`: sizes become minutes, tier order, bucket order |
| Focus holds each category's top item, high impact first, then urgency, then section | `focus.test.ts`: focus ranking, due dates across a new year |
| Five per bucket; a finished item stays in place and the next joins only when asked | `focus.test.ts` slots; e2e "stays in its place", "waits to be asked for", "Add puts it at the bottom" |
| The user's rating is marked as theirs and replaces Claude's; clicking again takes it off | `focus.test.ts` setImpact; e2e rating checks |
| Dragging or Move up/down changes only the view; another bucket changes only the category | e2e "reorders the view only", "leaves the list file alone"; `focus.test.ts` setCategory keeps the item's place |
| Opening the view changes nothing, and the List view is unchanged | e2e "opening the view changes nothing", "the List view is still there"; the earlier e2e checks still pass |
| Waiting On, Projects and Done never appear | `focus.test.ts` candidates; e2e "waiting items are left out" |
| The phone note doesn't show `impact:` fields | `test_list_counts_are_recounted_and_ids_hidden` |

Skipped: keyboard-only drag replacement is the native `<select>` ("Move…"), so its screen-reader behavior is the browser's; the e2e test drives it by value. Claude's rating during /morning and /weekly isn't built yet (waits for the owner's yes), so it has no tests.

## 2026-11-09 · first audit

What exists: `tests/test_engine.py` (134 tests, stdlib, run by `scripts/ci-checks.sh`), `apps/desktop/src/*.test.ts` (22, `node --test`), 2 Rust tests in the desktop app, the desktop and wall end-to-end runs in CI (`apps/desktop/e2e/ui.mjs`, `apps/wall/e2e.mjs`), and `apps/wall/sim/test_connection.py`. CI also runs the leak check, syntax checks for every script and tool, `swiftc -typecheck` on `ek.swift`, and the shared-file check.

### Always covered (security, data loss, privacy, fail-closed checks)

| Promise | Proved by |
| --- | --- |
| Nothing is sent without the user; connectors can read but not send, delete or change things in unattended runs | `Guard` (send_guard: sends and deletes refused, one bad action refuses the batch, empty batch blocked, fails closed, works from any folder, settings run the guard on every connector, unattended runs can sync but not send) |
| The iMessage channel answers only the user's own self-chat | `test_the_imessage_channel_can_answer_you`, `…_cannot_reach_anyone_else`, `…_needs_your_handles` |
| Personal databases (Messages, Mail, Things) are only read, through a copy | **new** `PersonalDataReadOnly`: every live database is opened `mode=ro`; no reader runs SQL that writes or can send; a snapshot leaves the source byte for byte |
| No copies of personal data stay behind | `test_a_run_leaves_no_copies_of_personal_databases_behind`, `test_a_run_clears_its_hidden_temp_exports` |
| Secrets are off limits; what runs read is data, not instructions | `test_secrets_are_off_limits_everywhere`, `test_runs_are_told_what_they_read_is_data`, `test_both_hosts_keep_runs_off_the_web_and_out_of_settings` |
| The wall display sends only what the user chose, and the Pi only accepts it | `WallDisplay` and `WallReceive` (only the list is read, notes and ids stay behind, Done and Communications never appear, titles off sends no titles, a bad list sends nothing, the key can do nothing but deliver or clear, host identity changes are never accepted) |
| The master list is never lost or half written | app-edits batches (`test_a_change_survives_a_run_that_never_finished`, `test_a_batch_from_a_dead_run_comes_back`), `test_state_is_never_half_written`, desktop `master.test.ts` round trips, undo refusing when the list changed |
| An install never overwrites the user's local engine changes | **new** `LocalChangesGuard`: a patch the source lacks stops the install, a missing patch file stops it, an applied patch lets it through, entries without a patch don't block, the session note says the file is data |
| Items other tools hand Theseus join the list only with the user's yes | **new** `Intake`: only open items for the user are offered, a non-date due is never used, nothing joins without a decision and each is decided once, a later done line reaches its task once, the tool's file is never written |

### Gaps added in this audit
- `engine/tools/local_changes.py` had no tests, though `guard` is the check that keeps an install from overwriting local changes. Added `LocalChangesGuard` (5 tests).
- Read-only access to personal databases was true in the code but unproven. Added `PersonalDataReadOnly` (3 tests).
- `engine/tools/intake.py` is new (the Console intake, decided 2026-11-08). Added with `Intake` (6 tests). It isn't wired into the workflows yet.

### Gaps skipped, and why
- `alarms.py` (reads a file a Shortcut writes; no writes, nothing sent) and `things_export.py` (one-time migration). Their read-only side is covered by `PersonalDataReadOnly`; parsing details aren't worth a test until they change.
- `ek.swift` beyond the type check: it needs real Reminders and Calendar access, so it can't run in CI. Its writes go through the send guard's rules and the workflows' logging.
- `mail.py` and `imsg.py` output formatting: covered where it matters (search windows, contacts fallback, seen marks); the rest is presentation.
- Framework internals of the desktop app (Tauri, Svelte) and trivial getters.

### Next audit
By 2026-11-23, or with the next feature or fix, whichever comes first. Check then: the intake wiring once the workflows use it.
