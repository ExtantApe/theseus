# Theseus for Mac

A menu bar app that **hosts** Theseus. Remote Control, the change checks, and the morning/nightly/sync runs all start from
Theseus.app. So you grant Full Disk Access, Calendars, Reminders and Notes **once, to Theseus.app**, and everything inherits it.
That replaces the Terminal window and the launchd jobs, which each had to be granted separately (and often couldn't be).

The engine doesn't change: rules, tools and workflows stay in your workspace (`~/Theseus`, or `$THESEUS_HOME`).

## Build (first time)

Needs Rust (`curl https://sh.rustup.rs -sSf | sh`), Node 20+, pnpm, and Xcode Command Line Tools.

```bash
cd ~/Code/theseus
pnpm install
pnpm --filter theseus-desktop icons    # makes the icon set from brand/icon-1024.png
pnpm app:dev                           # run it in development
pnpm app:build                         # → apps/desktop/src-tauri/target/release/bundle/macos/Theseus.app
```

Copy `Theseus.app` into `/Applications`, and grant permissions after moving it. Your own builds are signed ad hoc, so each one asks for permissions again. Releases are signed with a stable certificate and keep them ([RELEASING.md](../../RELEASING.md)). To change the app without losing permissions, use a release.

## Getting started

Open Theseus. That's all it needs to run: you don't have to open Claude or Terminal.

1. A ship icon appears in the menu bar. Until its permissions are in place, the window opens by itself.
2. **Setup**: click **Allow…** for Calendars, Reminders and Notes, and choose Allow in each macOS dialog. Full Disk Access is the one macOS never asks about: open Settings, click +, and choose Theseus.
3. Once it can read Messages, Calendars and Reminders, Theseus moves everything into the app by itself, within a minute. **Run from this app…** does the same right away. Either way, it:
   - sets `remote_control.host` and `scheduler_host` to `"app"` in `config.json`, so the old jobs stand down even if something below fails
   - stops the `com.theseus.*` launch agents and moves their plists to `data/archive/launchagents/`. The iMessage channel, if you use it, stays as it is
   - closes the Terminal Remote Control window and stops the server serving this workspace, and no other project's
   - adds a small launch agent, `com.theseus.watchdog`, that opens Theseus at login and reopens it after a crash. Quitting from the menu bar keeps it closed until you open it or restart
4. Make sure the **Claude desktop app isn't also serving `~/Theseus` with Remote Control**. Only one copy can, so the other
   one keeps failing.

Changed your mind? **Hand back to Terminal** puts the background jobs and the Terminal window back, removes the watchdog, and stops the app taking over again (`auto_host: false` in `config.json`) until you choose **Run from this app…**.

Remote Control can take a few minutes to return after switching, because the old server has to let go of the folder. The app says so and retries by itself.

## What it runs

| Job | When | How |
|---|---|---|
| Remote Control | Always (unless paused) | `script -q /dev/null claude remote-control --name <name>`, restarted with backoff |
| Change check | Every `checks.every_minutes` | `engine/tools/changes.py`; a sync runs only when it exits 0 |
| Morning / nightly | Times from `engine/tools/schedule.py due` | `claude -p` with the prompt in `engine/scheduled/prompts.json`, once per day. A run missed while the Mac slept happens when it wakes, within 5 hours for the morning and 3 for the evening |
| Status | Menu bar → **Run status now** | `claude -p` status workflow |

Only one Claude job runs at a time, and one that runs past `job_time_limit_minutes` (default 45) is stopped. A change counts as handled only when its sync finishes, so a failed run is retried. Output goes to `logs/app-<job>-<time>.out`, plus `logs/app.log`, `logs/checks.log` and
`logs/remote-control.log`.

## Your list

The List page and the Now and Communication blocks on Today edit `data/master.md` directly. Drag to reorder or move between sections, double-click to rename, or switch to Markdown. It saves as you go, with undo and redo (⌘Z, ⇧⌘Z). A check-off waits three seconds so you can change your mind, then moves to Done.

What you do is logged in `data/app-edits.jsonl` when it's saved, including what you type in the Markdown view, and the next sync carries it to Reminders and treats your drags as your own ranking. It carries it to Skylight and ClickUp too. An hourly copy of the list goes in `data/archive` for 14 days. If a sync lands while you're typing, what you typed is saved there too.

## Not yet

Apple notarization and automatic updates, notifications from inside the app (briefings still reach you through the pinned Today note and the Claude app), and the M6 wall view. Releases: [RELEASING.md](../../RELEASING.md).
