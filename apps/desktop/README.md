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

Copy `Theseus.app` into `/Applications`, and grant permissions after moving it. Macs identify an unsigned app by its exact build, so a rebuild may ask for them again.

## Switch over

1. Open Theseus. A ship icon appears in the menu bar. Choose **Open Theseus**.
2. **Setup**: click **Allow…** for Calendars, Reminders and Notes, and choose Allow in each macOS dialog. Full Disk Access is the one macOS never asks about: open Settings, click +, and choose Theseus.
3. Still in **Setup**: **Run from this app…**. This:
   - sets `remote_control.host` and `scheduler_host` to `"app"` in `config.json`
   - stops the `com.theseus.*` launch agents and moves their plists to `data/archive/launchagents/`
   - closes the Terminal Remote Control window
4. Turn on **Open at Login** for Theseus (System Settings → General → Login Items).
5. Make sure the **Claude desktop app isn't also serving `~/Theseus` with Remote Control**. Only one copy can, so the other
   one keeps failing.

Changed your mind? **Hand back to Terminal** puts the background jobs and the Terminal window back.

Remote Control can take a few minutes to return after switching, because the old server has to let go of the folder. The app says so and retries by itself.

## What it runs

| Job | When | How |
|---|---|---|
| Remote Control | Always (unless paused) | `script -q /dev/null claude remote-control --name <name>`, restarted with backoff |
| Change check | Every `checks.every_minutes` | `engine/tools/changes.py`; a sync runs only when it exits 0 |
| Morning / nightly | Times from `engine/tools/schedule.py` | `claude -p` with the workflow prompt, once per day |
| Status | Menu bar → **Run status now** | `claude -p` status workflow |

Only one Claude job runs at a time. Output goes to `logs/app-<job>-<time>.out`, plus `logs/app.log`, `logs/checks.log` and
`logs/remote-control.log`.

## Your list

The List page and the Now and Communication blocks on Today edit `data/master.md` directly. Drag to reorder or move between sections, double-click to rename, or switch to Markdown. It saves as you go, with undo and redo (⌘Z, ⇧⌘Z). A check-off waits three seconds so you can change your mind, then moves to Done.

What you do is logged in `data/app-edits.jsonl`, and the next sync carries it to Reminders, Skylight and ClickUp and treats your drags as your own ranking. An hourly copy of the list goes in `data/archive`.

## Not yet

Apple signing and automatic updates (an unsigned app would need its permissions granted again after each update anyway), notifications from inside the app (briefings still reach you through the pinned Today note and the Claude app), and the M6 wall view. Releases: [RELEASING.md](../../RELEASING.md).
