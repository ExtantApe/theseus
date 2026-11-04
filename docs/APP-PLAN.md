# Theseus.app: plan for a single shipped package

> **Where this stands (0.5.0):** the menu bar app ships and hosts everything, with Today, List, Activity and Setup pages. The sections below are the plan as first written. Where they differ from what shipped, ADR 0006 and `apps/desktop/README.md` describe what exists: the app hosts jobs itself rather than through its own LaunchAgent, a small watchdog agent keeps it open, the engine is installed separately rather than bundled, and releases carry a self-signed certificate.

**Goal:** one download, `Theseus.dmg`, that gives anyone the whole thing: the app, the engine, setup, scheduling and updates.
No Terminal, no Xcode, no copying folders around. The Claude Code plugin stays available as an alternative install of the
*same engine* for people who live in Claude Code.

**Principles (unchanged from the engine):**
1. Theseus helps you live your life. It doesn't live it for you. It never sends anything on your behalf.
2. Your data stays in *your* workspace on *your* Mac.
3. It never sees, stores or handles your Claude login. It follows Anthropic's rules (docs/COMPLIANCE.md, checked monthly).
4. Free and open source, always.

---

## 0. Stack decision: Tauri 2 (same as OnePedigree for Mac)
The maintainer's existing Mac app (OnePedigree, `apps/desktop`) already uses **Tauri 2 + React/TypeScript + pnpm**, with a GitHub Actions workflow
(`desktop.yml`) that builds a **universal DMG** on a `desktop-v*` tag, signs **updates** with a minisign key, publishes `latest.json` for the
built-in updater, and ships unsigned until Apple notarization is added. Theseus.app reuses that whole pipeline:

| Piece | Choice | Why |
|---|---|---|
| App shell, UI | Tauri 2, React + TypeScript (Vite), pnpm workspace | known stack; small binary; same release flow |
| Menu bar | Tauri tray icon + popover window | built in |
| Background checks | the app's LaunchAgent (via `tauri-plugin-autostart` or a small helper) running the engine's check job | no hand-written plists |
| Calendar & Reminders | the `ek` Swift helper shipped as a Tauri **sidecar** (`bundle.externalBin`) | EventKit needs native code; permissions attach to the app |
| Engine tools | bundled as resources; Python sidecar in phase 1, Swift/Rust ports later | ship now, slim down later |
| Settings and state | workspace files are the source of truth; `tauri-plugin-store` only for app-only prefs | engine and plugin stay compatible |
| Updates | `tauri-plugin-updater` + `latest.json` on GitHub Releases (copy desktop.yml) | already proven in OnePedigree |
| Repo practice | "one description everywhere" (package.json → GitHub), lockstep versions, CHANGELOG, ADRs in `docs/adr` | matches OneTaxonomy and OnePedigree |

(SwiftUI would be the alternative: more native APIs, but a second stack to maintain. Tauri plus a tiny Swift sidecar gets the native
bits where they matter.)

## 1. What ships inside the app

```
Theseus.app/
├── Contents/MacOS/Theseus            Tauri app (menu bar + window)
├── Contents/MacOS/ek                 Swift sidecar: EventKit (Calendar, Reminders)
└── Contents/Resources/
    ├── engine/                       RULES.md, workflows/, tools/, templates/  ← same files as the plugin
    ├── docs/                         SETUP, COMPLIANCE, CREDITS
    └── python/                       bundled standalone Python runtime (phase 1 only; see §4)
```
- **The engine is identical to the plugin's.** The repo stays the single source of truth, and the app build copies `engine/` in.
  An app update = an engine update. The app runs `install.sh --update` logic natively, and personal files are never touched.
- **The workspace stays where it is** (`~/Theseus` by default). The app is a window onto it. Plugin users and app users can switch freely.

## 2. How the app talks to Claude (user picks in Settings → Claude)

| Mode | How | Billing | Notes |
|---|---|---|---|
| **Use my Claude Code** (default) | The app launches the user's own installed `claude` CLI in the workspace (same as the scheduled jobs). Sign-in happens in Claude Code's own flow, in Terminal. | user's own plan | The app never touches credentials. If Claude Code isn't installed, the app links to Anthropic's official installer (it doesn't bundle Claude Code). |
| **Use an API key** | Same CLI or Agent SDK, with the user's own Anthropic API key from the macOS Keychain passed as an environment variable. | user's own API account, pay per use | Anthropic's recommended route for developer-built apps. |

Both modes run the **same commands** (`/status`, `/next`, …) against the same workspace, so the engine code doesn't change.
The monthly compliance check covers the app too. If Anthropic's rules change, the affected mode is disabled with an explanation.

## 3. Screens

**Menu bar (always there):** a small popover
- "📌 Today": top 3 NOW items with check circles (checking one writes to the master list and syncs out on the next run), next event, who's waiting
- **What's next?** button with a quick time picker (15 / 30 / 60 min / until next event)
- **Add** field with a dictation mic → goes through the same placement rules as `/add`
- Status line: "Last sync 2:14 · next check 2:19 · ✅ all services"

**Main window (sidebar):**
1. **Today**: agenda timeline, NOW list, texts waiting, "Did you already…?" confirmations (one tap), 🌙 Tomorrow in the evening
2. **List**: NOW / NEXT / LATER / EVENTUALLY / WAITING columns, filter by category, **drag to reorder** (recorded as ranking evidence)
3. **Rank**: A-or-B cards (bubble-sort style, binary insertion for new items), with "why?" chips that turn into rules
4. **Replies**: people waiting on you. Opens the *as-if-they-asked* questionnaire as a native form (quick-pick buttons and dictation),
   then shows the draft in your voice with **Copy** and **Open in Messages** buttons. The app never sends.
5. **Threads**: pick a person → neutral report, stats, search (wraps `imsg.py`)
6. **Settings**: Profile · Schedule (visual weekday/weekend editor, regimented or fluid) · Sources (email, calendar, connectors) ·
   Integrations · Checks (frequency, cooldown) · Notes names · Privacy (what's read, export or delete my workspace) · Claude mode ·
   Compliance (last check, findings) · Logs

**First-run wizard** (replaces `/theseus:setup` for app users; same questions and the same config output):
Welcome → Claude Code installed and signed in (or API key) → workspace location → profile and schedule → sources and connectors →
permissions (each with a "why", a deep-link button to the right System Settings pane, and a live ✅ when granted) →
iPhone Shortcut instructions (optional) → `/migrate` (shown as a guided review screen) → done.

## 4. Native pieces that remove setup friction
- **EventKit natively in Swift:** Calendar and Reminders permissions belong to Theseus.app, so no `swiftc`/Xcode is needed. `ek` becomes
  a small command-line target inside the app bundle that the engine calls.
- **Permissions owned by the app** (Full Disk Access, Automation → Notes, Calendars, Reminders) instead of Terminal and /bin/bash.
  Much easier to explain, and revocable in one place.
- **Background agent** (the app's LaunchAgent): runs the 5-minute fingerprint checks and the per-day morning and nightly runs.
  This replaces the hand-written LaunchAgent plists and shows up in System Settings → General → Login Items as "Theseus".
- **Python:** macOS no longer ships a ready Python without the developer tools. Phase 1 bundles a standalone Python runtime
  (python-build-standalone, permissive license) for the tools. Phase 3 ports the hot paths (fingerprint, Messages, Notes, Mail readers)
  to Swift and drops Python.
- **Notes access** through the app's own Automation permission. The Today note can also be shown natively in the app.

## 5. Shipping
- **One repo, one release:** GitHub Releases attach `Theseus.dmg` (the app with the engine inside) plus the plugin marketplace files
  (for Claude Code users). Same version number for both.
- **Before notarization:** unsigned builds with clear "Open Anyway" instructions (docs/SETUP.md §11), or build from source in Xcode.
- **Later (optional):** an Apple Developer ID for signing and notarization ($99/yr). Only if enough people want one-click installs.
- **Updates:** Tauri updater + `latest.json` on GitHub Releases, signed with the updater key (as in OnePedigree). Engine-only updates can ship without a new app binary.
- **Uninstall:** Settings → "Remove Theseus" unregisters the agent and leaves the workspace in place (or exports, then deletes it, if the user chooses).

## 6. Milestones
| | Scope | Done when |
|---|---|---|
| **M0** (done) | Engine + plugin (v0.4) on the maintainer's Mac | 2 weeks of daily use; Today note, checks and migration feel right |
| **M1** (shipped: menu bar app hosting everything, ADR 0006. Still to come: popover, bundled engine) | Menu-bar app: read-only Today popover, Add, What's next, "Use my Claude Code" mode, bundled engine | app replaces Terminal for daily use |
| **M2** (partly: the app owns permissions and hosts the schedule. Still to come: native EventKit) | Background agent (app LaunchAgent) replaces the launchd scripts; native EventKit; permissions owned by the app | no Terminal needed after install |
| **M3** (partly: List with drag and undo shipped. Still to come: Rank, Replies, Settings) | Main window: List (drag-rank), Rank cards, Replies questionnaire, Settings with the Schedule editor | full feature parity with the plugin |
| **M4** | First-run wizard, unsigned DMG release, docs, a 5-person private beta | a non-technical friend installs it alone |
| **M6** | **Command center**: a wall or desk display served by the Mac on the home network (Raspberry Pi in browser kiosk mode, or a MagicMirror² module reading `wall.json`); landscape and portrait layouts; wall-safe by default; last snapshot shown if the Mac sleeps | glanceable all day, nothing private visible to passers-by |
| **M7** | **Voice and family (optional)**: on-Pi wake word and fixed commands ("show the family", "show <name>", "in detail", "back"); "in detail" needs confirmation on the person's watch or phone and expires in ~30 s; per-person opt-in profiles; a Family view (week, chores, groceries, dinner, countdowns) for homes without Skylight | a household can share one wall, with each person in control of their own data |
| **M5** | API-key mode, auto-updates, Swift ports of tools (drop Python), optional notarization, public release | public 1.0 |

## 6b. Data rules to keep now (so M6 and M7 drop in later)
- Each person = their own workspace and profile. A household layer only combines what each person marks shareable.
- Every item gets a `visibility`: `private` (never on a wall) · `wall-safe` (title-less summary, counts) · `wall-detail` (full title, only after confirmation).
- Message content, email and private contacts are never wall-visible, at any level.
- Voice is never authentication. Sensitive views need a second factor from that person.

## 7. Risks and open questions
- **Anthropic's rules for third-party apps are evolving.** Keep the "Use my Claude Code" mode minimal (launch the user's own CLI, never
  intermediate credentials), keep API-key mode available, re-check monthly, and consider asking Anthropic for a read before public 1.0.
- **Full Disk Access is a big ask.** The wizard explains exactly what's read and why, and texts/Mail/Things stay optional.
- **Unofficial connectors** (Skylight) stay clearly labeled and off by default.
- **Apple Notes scripting limits** (checklist state is unreadable, locked notes) → the native Today view in the app sidesteps them.
- **Mac App Store?** Probably not: sandboxing blocks reading Messages and other apps' data. Direct download only.
- **Name check:** run a trademark search on "Theseus" in the productivity-software class before 1.0.
