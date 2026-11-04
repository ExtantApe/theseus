# 0006: Theseus.app hosts Remote Control and the schedule

**Status:** accepted · 2026-11-03

## Context

macOS grants privacy permissions to the *responsible process*. Runs started from Terminal inherit Terminal's Full Disk Access,
so the command line worked. launchd jobs have no such parent: `bash` and `claude` are each checked on their own, and the
Claude Code binary can't easily be added to Full Disk Access. Scheduled runs and the background Remote Control server couldn't
read Messages, Calendars or Notes, and fell back to saved copies. The Terminal-window host (option 1) works, but it depends
on a window staying open.

## Decision

The Mac app (Tauri, see 0003) becomes the responsible process. It starts Remote Control, the change checks and the
morning/nightly/sync runs as its own children, so a single grant to Theseus.app covers all of them. Hosting is chosen in
`config.json`:

- `remote_control.host`: `app` | `terminal` | `background`
- `scheduler_host`: `app` | `launchd`

`run-job.sh` exits early when `scheduler_host` is `app`, so the two hosts never both run a job. "Take over" in the app sets
both keys and sets the launch agents aside. Nothing is deleted, so you can switch back.

## Consequences

- One permission prompt per kind, granted to an app users recognize.
- The app has to be running. Open at Login covers that, and the launchd path stays available for headless setups.
- The engine stays app-agnostic. The app only edits those two config keys.
