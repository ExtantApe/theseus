# Theseus setup guide (macOS)

`/theseus:setup` walks you through all of this interactively. This page is the reference.

---

## 1. Install (about 15 minutes)

**Requirements:** a Mac (macOS 14+ recommended), [Claude Code](https://docs.claude.com/en/docs/claude-code/overview)
signed in with your own account, and Apple's developer tools (`xcode-select --install`, for Python and Swift).

**Install the plugin** (inside Claude Code):
```
/plugin marketplace add <owner>/theseus
/plugin install theseus@theseus
/theseus:setup
```
**Or install manually:** `git clone https://github.com/<owner>/theseus && cd theseus && ./install.sh`

**Permissions** (macOS will ask; `/theseus:doctor` re-checks):
| Permission | Why | Where |
|---|---|---|
| **Full Disk Access** | read Messages, Contacts, Apple Mail, Things (read-only snapshots) | System Settings → Privacy & Security → Full Disk Access → add your terminal app (Terminal, iTerm, Ghostty, VS Code…) **and `/bin/bash`** (⌘⇧G in the file picker) for scheduled runs. Quit and reopen the terminal. |
| Calendars, Reminders | read and create events and reminders | click **Allow** on the prompts (or Privacy & Security → Calendars / Reminders) |
| Automation → Notes | read your inbox folder, publish the master list | click **OK** on the prompt |

Only turn on what you use. Texts, Apple Mail and Things are optional.

## 2. Choose your email and calendar sources

Set during `/theseus:setup` (`email_source`, `calendar_source` in `config.json`):

| | Connector (e.g. Composio) | Apple apps |
|---|---|---|
| Best if you… | use Gmail, Google Calendar or Outlook directly (web or apps) | already use Apple Mail / Calendar with your accounts added |
| Multiple accounts | yes, list each one in `email_accounts` / `calendar_accounts` | yes, everything in System Settings → Internet Accounts |
| Writes events to | the exact account/calendar you route to (`calendar_routes`) | any calendar synced into the Calendar app |
| Data path | goes through the connector service | stays on your Mac |
| Catch | needs a connector account; your employer may block it | the Mail app must run to fetch new mail |

You can mix them, e.g. email via a connector and calendar via Apple.

**Composio:** from your Composio dashboard, copy the MCP URL and API key (use their Claude Code command if they show one):
```bash
claude mcp add --transport http --scope user composio "YOUR_COMPOSIO_MCP_URL" --header "X-API-Key: YOUR_KEY"
```
Then in Claude Code run `/mcp` and finish signing in to each Google or Microsoft account you want Theseus to read.

## 3. Optional add-ons

**ClickUp** (official connector; you sign in through ClickUp):
```bash
claude mcp add --transport http --scope user clickup https://mcp.clickup.com/mcp
```

**Skylight** (⚠️ an *unofficial* community connector built on Skylight's private API. It can break when Skylight
changes things, and it signs in with your Skylight email and password. Accounts that only use Google/Apple sign-in must set a
Skylight password first):
```bash
claude mcp add skylight --scope user -e SKYLIGHT_EMAIL=you@example.com -e SKYLIGHT_PASSWORD='…' -- npx -y skylight-mcp
```
For family events to show on the frame, turn on Skylight's two-way calendar sync (Skylight app → Sync Calendars) and
set `family_calendar` in config.json.

**Things 3 migration:** nothing to install. `/migrate` reads Things read-only. Things is never changed.

## 4. First run
```bash
cd ~/Theseus && claude
```
Run `/migrate`. Theseus gathers your reminders, old task notes and task apps, removes duplicates, proposes categories,
drafts NOW / NEXT / LATER / EVENTUALLY placement for your approval, and learns your texting voice. Then pin the
**★ Master List** note in Notes.

## 5. Schedule it

Your rhythm lives in `config.json → schedule`: **regimented** (fixed times) or **fluid** (varies; Theseus adapts), with separate groups
for weekdays, weekends or any days you like, plus single-day overrides. `python3 engine/tools/schedule.py --week` shows the result.
Example:
```json
"schedule": {"style": "regimented",
  "groups": [{"name": "Weekdays", "days": ["mon","tue","wed","thu","fri"], "wake": "06:00", "bed": "23:30"},
             {"name": "Weekends", "days": ["sat","sun"], "wake": "08:30", "bed": "01:00"}],
  "overrides": {"fri": {"bed": "01:30"}}, "flex_hours": 1.5, "adapt": true}
```
```bash
bash ~/Theseus/engine/install.sh --schedule
```
- **Nightly** (per day, ~2.5 h before that day's bed time): health check, full scan, and a **🌙 Tomorrow** section in your pinned **📌 Today** note (agenda,
  top 3, what's due, prep). If anything broke, a **⚠️ Needs attention** section explains the fix.
- **Morning** (per day, a few minutes before that day's wake time): fresh rescan, and 📌 Today is rebuilt for the new day.
- **📌 Today updates every time Theseus runs.** Pin it in Notes (swipe right → pin). If you can't reach Claude, it's all there.
  Type in **✍️ Jot here**, or change ☐ to **x** to check something off, and Theseus reads it back next run. (Notes' own checklist
  circles can't be read by scripts, so use the typed boxes.) Turn on `checks` if you want it refreshed through the day.
- **Frequent checks (optional):**
  `"checks": {"enabled": true, "every_minutes": 5, "min_minutes_between_claude_runs": 15, "only_while_awake": true, "skip_if_nothing_changed": true, "full_refresh_every_minutes": 60}`
  - Every `every_minutes` (1–60), a **local fingerprint** (`engine/tools/changes.py`, no Claude, typically under a second) checks
    texts (newest, unread and read activity), your Notes inbox and 📌 Today, reminders, today's calendar, alarms and Apple Mail.
  - **Claude runs only when something changed, and at most once per `min_minutes_between_claude_runs`.** Changes that arrive during
    that wait are remembered and handled on the next allowed run. A full refresh runs every `full_refresh_every_minutes` (that's when
    connector email like Gmail gets checked).
  - Checks pause outside that day's awake hours (wake → bed + `flex_hours`) and for 10 min around the morning and nightly runs.
  - The first activity after 4+ quiet hours triggers an immediate "you're up" refresh, which helps a lot with fluid schedules.
  - The Notes app isn't launched on every check: Theseus only asks Notes for details after the Notes database itself has changed.
  - `logs/checks.log` shows why each check ran, waited or skipped.
- **Apps it opens for you:** before each scheduled run, Theseus quietly opens anything listed in `ensure_apps` that isn't running
  (for example `["Claude"]` for the Claude desktop app). Apple Mail is opened automatically if you chose Apple Mail.
  The jobs themselves don't need any app open. They run Claude Code directly.
- Remove the schedule: `bash ~/Theseus/engine/install.sh --unschedule`

## 6. Everyday use
| Say / type | What happens |
|---|---|
| `/status` | full fresh re-run of everything, any time |
| `/add call the bank Friday 10am` | dictate anything; Theseus places it |
| `/add water the plants every other Saturday` | a repeating task: one Reminder that repeats, plus one ↻ item on your list |
| a note in your Notes inbox folder | ingested on the next run, then moved to Processed |
| `/next finished all except X, waiting on Alex, 45 min` (or plain words) | checks things off, parks X with the reason, picks what fits your time |
| `/texts` → "sprint" | who's waiting on a reply; knock out the easy ones |
| `/reply Sam` | Sam's open questions, asked as if Sam asked you; then a draft in your words. **Never sent.** |
| `/rank`, `/rank now` | quick "A or B?" prioritizing |
| `/review` | weekly cleanup and learning |
| `/thread-report Sam since 2021` | neutral, timestamped account of a long thread |
| `/text-research every mention of the lake house` | search and compile across your texts |
| `/sync-check 48210` | is all your message history on this Mac? |
| `/voice` | refresh your writing-voice profile |

**Placement hints (optional):** "now", "next week", "someday", "#Work", "remind me at 3", "groceries: eggs", "top".
Without a hint, Theseus decides from context. A note *titled* "NOW" or "Work" applies that hint to every line in it.

**From your phone:** start a Claude Code channel (e.g. the iMessage channel) **from your Theseus folder**, then text yourself
"status", "add …", or "what's next? 30 min".

## 6a. Reach Theseus from anywhere (on by default)
`install.sh --schedule` also keeps Claude Code's **Remote Control** server running in your Theseus folder (restarted automatically after a
crash, reboot or `--update`). Then:
1. On your phone, open the **Claude app → Code**. Your Mac shows up as a device (named "Theseus" by default; `remote_control.name` in config.json).
2. Tap it, pick your Theseus folder, and start a session. Each new session loads the latest rules, so start fresh rather than continuing an old chat.
3. Talk to it like normal: "status", "what's next, 20 min", "add …".
- Same on any computer at claude.ai/code.
- The Mac needs to be awake and online (see "Keep the Mac awake"). If it isn't, your 📌 Today and ★ Master List notes still work on the phone.
- Turn it off: set `"remote_control": {"enabled": false}` and run `engine/install.sh --unschedule`, then `--schedule` again. Logs: `logs/remote-control.log`.
- Needs a recent Claude Code (Remote Control server mode). If it fails, update Claude Code first.

## 6b. Text Theseus from your phone (optional)
Text yourself "status", "what's next, 20 min" or "add call the vet Friday", and Theseus answers in the same self-chat.
1. Install [Bun](https://bun.sh) (the channel plugin needs it): `curl -fsSL https://bun.sh/install | bash`
2. `bash ~/Theseus/engine/install.sh --channel`. It asks first, installs the official iMessage channel plugin, and keeps a Claude Code session
   running in your workspace while the Mac is awake (restarting after a crash or reboot, and once a day so it picks up rule updates).
3. Text yourself "status".
- It replies **only in your own self-chat**, never to anyone else. Add every number or email you text yourself from to `my_handles`.
- If it needs a permission it doesn't have, it tells you to approve it at the Mac. It doesn't skip permissions.
- Channels are a research preview in Claude Code. If it stops working after an update, Theseus notes it in your Today note.
- Remove it: `bash ~/Theseus/engine/install.sh --unschedule`. Logs: `~/Theseus/logs/channel.log`.

## 7. Is all my message history here?
1. iPhone → Settings → [your name] → iCloud → **Messages** shows how many messages are in iCloud (Mac: System Settings → [name] → iCloud → Messages).
2. `/sync-check <that number>` compares it with this Mac, and shows messages per year, empty months, and how far back your biggest conversations go.

If history looks incomplete, try these in order:
1. **Set "Keep Messages" to Forever** on iPhone and Mac. Do this first: 30-day or 1-year settings delete old messages everywhere.
2. Same Apple Account on both devices, with Messages in iCloud **on** for both. Make sure iCloud storage isn't full.
3. **Sync Now** on the iPhone (Settings → [name] → iCloud → Messages) while it's plugged in on Wi-Fi.
4. **Sync Now** on the Mac (Messages → Settings → iMessage). Leave it awake and plugged in, with Messages open, overnight, and re-run `/sync-check`.
5. Last resort, a full re-download: quit Messages, **back up `~/Library/Messages`**, move it aside, restart, and let it re-download.
   Mac-only history would then exist only in your backup. Theseus can still read it: `IMSG_CHAT_DB=/path/to/backup/chat.db`.

There's no official way to see an "undownloaded" count. Comparing the two counts is the most reliable signal.

## 8. Slack
**Option A: the official Slack connector** (Theseus reads Slack directly, with Claude Code's normal sign-in):
```bash
claude mcp add --transport http --scope user slack https://mcp.slack.com/mcp
```
Then run `/mcp` in Claude Code and sign in with Slack. Your workspace admin may need to approve the Slack MCP integration. Set `integrations.slack`
true and `slack_source` "mcp". Theseus only reads; it never posts, reacts or edits.

**Option B: the email bridge** (no Slack access). `/theseus:setup` asks which email provider receives your Slack notifications and gives you that
provider's exact filter or rule. The general steps:
1. **Slack** → Preferences → Notifications → *When I'm not active on desktop* → **Send me email notifications for mentions and
   direct messages**, every 15 minutes. Add keywords for the projects you care about. Turn off Slack's marketing emails.
2. **Folder and rule:** create a `Theseus/Slack Digest` folder (Outlook) or label (Gmail). Add a server-side rule or filter: from Slack's
   notification address (open one Slack email to check, e.g. `notification@slack.com`) → move or label it, **mark as read**,
   skip the inbox. Match only that address so Slack's security emails still reach you.
3. Turn on `integrations.slack_email_bridge` and set `slack_digest_folder`.
Each briefing then asks **"💬 Slack: did you get to these?"** Answer "1 3", "all", or "2 → task".
Slack only emails what you *haven't seen*, so anything you read live never reaches the bridge.
Work accounts may need IT approval for connectors, and your organization's data policy applies.

## 9. iPhone alarms (optional, Shortcuts, about 10 minutes)
Alarms don't sync between devices, so your iPhone saves its alarm list to iCloud Drive and Theseus reads it. Read-only.

**Build the Shortcut** (Shortcuts → **+**, name it **Alarms → Theseus**):
1. **Find Alarms** (older iOS: **Get All Alarms**), with no filters.
2. **Repeat with Each** item in Alarms.
3. Inside it, a **Text** action: `ALARM|`**Repeat Item › Time**`|`**Repeat Item › Name**`|`**Repeat Item › Repeat**`|`**Repeat Item › Is Enabled**
   (insert Repeat Item, tap the chip, pick the property. If **Is Enabled** isn't offered, leave that slot empty but keep the `|`).
4. After End Repeat: **Combine Text** (Repeat Results, with New Lines).
5. **Text**: line 1 `UPDATED|`**Current Date**, line 2 **Combined Text**.
6. **Save File** → Show More: Ask Where to Save **off**, Destination Path `theseus-alarms.txt`, Overwrite If File Exists **on**.
7. Run it once and allow access. Check it in Files → iCloud Drive → Shortcuts → `theseus-alarms.txt`.
   (If it errors on an alarm that repeats on only one day, that's a known Shortcuts bug: remove the Repeat property and keep the `||`.)

**Automate it** (Shortcuts → Automation → +):
- App → **Clock** → **Is Closed** → Run Immediately → *Alarms → Theseus* (notify off)
- Time of Day → 15 min before your evening brief (`python3 engine/tools/schedule.py` shows it), Daily → Run Immediately → *Alarms → Theseus*

Turn on `integrations.iphone_alarms`. **Apple Watch alarms never leave the watch.** Tell Theseus their times
("my watch alarm is 5:30 weekdays") and they're stored in `data/alarms-static.md`.
For tasks, say **"Hey Siri, remind me at 3 to…"** instead of setting an alarm. Reminders sync everywhere, and Theseus picks them up.

## 10a. For contributors: changes made from a workspace
Theseus can improve its own engine while it works in your workspace (`~/Theseus/engine`), for example a fix it needed right away. Every such
change, applied or only recommended, is logged in `~/Theseus/data/local-changes.md` (with a patch in `data/local-changes/` for applied
ones), so nothing is lost:
- Opening Claude Code in the source repo lists pending entries at session start (a SessionStart hook in the repo's `.claude/settings.json`).
- `install.sh` and `install.sh --update` refuse to run if a pending patch isn't in the source yet, so an update can't silently undo it.
  Apply the patch to the repo (or decide against it), move the entry to "Done upstream", then update. `--force` overrides.
- Theseus never edits the source repo or pushes without your yes.

## 10. What Theseus can and can't do
| ✅ Can | 🚫 Never |
|---|---|
| read texts, contacts, mail, notes, alarms, Things | send texts, emails, Slack messages or comments to anyone |
| create, complete and edit reminders; add calendar events | delete reminders, events or notes (it completes or archives; deleting a reminder asks you first) |
| add, complete and edit Skylight lists and chores, and ClickUp tasks when you ask | invent details in drafts (it asks you) |
| auto-detect things you already did | change your Messages or Mail databases (it reads snapshots) |
Every change is logged in `data/log.md`.

## Folder map
```
~/Theseus                     ← your private workspace (never shared)
├── CLAUDE.md                 loads engine/RULES.md + profile.md
├── profile.md, config.json   about you; your sources and settings
├── data/                     master list, priorities, voice, sync map, logs, drafts
├── briefings/ exports/ logs/ cache/
├── engine/                   rules, tools, workflows (replaced on update)
├── .claude/commands/         /status /add /next /inbox /texts /reply /rank /review /migrate …
└── bin/ek                    Calendar & Reminders bridge (built on install)
```

## 11. The optional Mac app (preview builds)
A native menu-bar app is planned. It's a window onto the same workspace: today's list, agenda, buttons for Status / What's next / Add,
and A-or-B ranking cards. Until it's signed and notarized by Apple, preview builds are **unsigned**:

- **Easiest: build it yourself.** Open the project in Xcode and press Run. Apps you build on your own Mac open normally.
- **Downloaded preview:** double-click it, and macOS will block it. Then go to **System Settings → Privacy & Security**, scroll to
  **Security**, and click **Open Anyway** next to the app's name. Confirm with your password. (On macOS 15+, right-click → Open no
  longer bypasses this, and the Open Anyway button only appears for about an hour after you try to open the app.)
- Only do this for builds from this repo's official releases. Never disable Gatekeeper system-wide.

**How the app talks to Claude** (you choose in its settings; same engine either way):
1. **"Use my Claude Code"**: the app starts your own installed `claude` in your Theseus folder, the same way the scheduled jobs do.
   It never sees, stores or handles your Claude login. Usage counts against your own plan, under Anthropic's terms for `claude -p`.
2. **"Use an API key"** (Anthropic's recommended route for apps): the app runs the same engine through Anthropic's Agent SDK with
   *your own* Claude Console API key, stored in your Mac's Keychain. Billed per use to you.
Anthropic's rules for third-party apps have been changing (see Anthropic's Claude Code "Legal and compliance" page and the help
article "Use the Claude Agent SDK with your Claude plan"). The app follows whatever they currently allow.
