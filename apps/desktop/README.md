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
pnpm --filter theseus-desktop icons    # makes the icon set from app-icon.png
pnpm app:dev                           # run it in development
pnpm app:build                         # → apps/desktop/src-tauri/target/release/bundle/macos/Theseus.app
```

Copy `Theseus.app` into `/Applications`, and grant permissions after moving it. Macs identify an unsigned app by its exact build, so a rebuild may ask for them again.

## Switch over

1. Open Theseus. A ship icon appears in the menu bar. Choose **Open Theseus**.
2. **Permissions** tab: open each pane and add Theseus (Full Disk Access, Calendars, Reminders, Automation → Notes). Click
   **Check access**. Everything should show ✓.
3. **Services** tab: **Take over hosting**. This:
   - sets `remote_control.host` and `scheduler_host` to `"app"` in `config.json`
   - stops the `com.theseus.*` launch agents and moves their plists to `data/archive/launchagents/`
   - closes the Terminal Remote Control window
4. Turn on **Open at Login** for Theseus (System Settings → General → Login Items).
5. Make sure the **Claude desktop app isn't also serving `~/Theseus` with Remote Control**. Only one copy can, so the other
   one keeps failing.

Changed your mind? **Hand back to Terminal**, then `bash ~/Theseus/engine/install.sh --schedule`.

## What it runs

| Job | When | How |
|---|---|---|
| Remote Control | Always (unless paused) | `script -q /dev/null claude remote-control --name <name>`, restarted with backoff |
| Change check | Every `checks.every_minutes` | `engine/tools/changes.py`; a sync runs only when it exits 0 |
| Morning / nightly | Times from `engine/tools/schedule.py` | `claude -p` with the workflow prompt, once per day |
| Status | Menu bar → **Run status now** | `claude -p` status workflow |

Only one Claude job runs at a time. Output goes to `logs/app-<job>-<time>.out`, plus `logs/app.log`, `logs/checks.log` and
`logs/remote-control.log`.

## Not yet

Apple signing and automatic updates (an unsigned app would need its permissions granted again after each update anyway), an in-app list editor, notifications from inside the app (briefings still reach you through the pinned Today note and the Claude app), and the M6 wall view. Releases: [RELEASING.md](../../RELEASING.md).
