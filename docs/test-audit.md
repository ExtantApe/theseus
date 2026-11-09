# Test audit

How the tests line up with what Theseus promises. Redo it after every feature or fix, and at least every 14 days while the repo has commits.

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
