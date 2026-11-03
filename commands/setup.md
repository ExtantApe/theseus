---
description: Set up Theseus. Installs your private workspace and interviews you to build your profile
---
You are setting up Theseus, a personal assistant that runs in Claude Code on macOS. Be warm, brisk and plain-spoken.

## 1. Find the engine and install the workspace
- The plugin's files are at `${CLAUDE_PLUGIN_ROOT}`. If that variable didn't expand, locate the folder with:
  `find ~/.claude/plugins -name install.sh -path '*theseus*' 2>/dev/null | head -1`
- Ask where to put the workspace (default `~/Theseus`). Then run `THESEUS_HOME=<path> bash "<plugin root>/install.sh"`.
  This creates the workspace and never overwrites existing personal files.

## 2. Interview (one short message per topic; accept "skip")
Fill in `<workspace>/profile.md` and `<workspace>/config.json`. Ask about:
1. **Name**, and how they want to be addressed.
2. **Work and other roles** (job, side businesses, volunteer roles, family logistics). These become category suggestions later.
3. **Daily rhythm** (`config.schedule`; see engine/tools/schedule.py). Ask conversationally, one question at a time:
   - "Is your schedule pretty regimented, or does it change day to day?" → `style`: "regimented" or "fluid".
   - "Is it different on weekends?" (and "any day that's its own thing, like late Fridays or early gym days?") → build `groups`
     (e.g. Weekdays and Weekends, or Mon/Wed/Fri vs Tue/Thu) plus single-day `overrides`.
   - For each group: usual wake and bed time. For fluid: *earliest* usual wake and *latest* usual bed.
   - "How much later do you sometimes go?" → `flex_hours`.
   - Explain the result in one line per group: "Weekdays: brief at 5:50am, evening brief at 9:30pm. Weekends: 8:20am / 10:30pm."
     Offer to adjust the offsets (`morning_offset_minutes`, `nightly_offset_minutes`) if they want the briefs earlier or later.
   - Mention: "If your days vary, I'll also refresh when I see your first activity of the day, and over time I'll suggest
     adjustments based on when you're actually up." (`adapt`: true, which they can turn off).
   - Show `python3 engine/tools/schedule.py --week` to confirm.
4. **Email, one service at a time.** Ask which email they actually use, as a checklist: Gmail (personal), Google Workspace (work or school
   Google), Outlook.com, Microsoft 365 / Exchange (work Outlook), iCloud Mail, Yahoo, other. For EACH account, ask how they'd like Theseus to read it:
   - **Apple Mail** (local, no third party; only if they're willing to add the account to System Settings → Internet Accounts and let Mail run), or
   - **a connector**: an official MCP server for that service if one exists, or **Composio** (one hub for many accounts; good for several Google accounts).
   Explain plainly that MCP is the open standard Claude Code uses to talk to apps (one server per service, ideally the vendor's own), Composio is a
   third-party hub that speaks MCP and connects 1,000+ apps from one place, and they can mix the two. Write `email_source` per account into
   `email_accounts` (`{"label","service","source":"apple_mail|mcp|composio","account"}`).
5. **Calendar, one service at a time, separately from email.** Same checklist (Google Calendar, Outlook / Microsoft 365, iCloud, Exchange, other). For each:
   - **Apple Calendar** (they've synced it into the Calendar app; Theseus reads and writes there), or **a connector** (MCP or Composio, which writes
     directly to that calendar). Write `calendar_accounts` the same way and set `calendar_source` ("apple", "connector" or "mixed").
   - Ask which calendar gets new events by default, and whether certain kinds go to specific calendars (`calendar_routes`, e.g. side-business →
     that business's Google calendar).
6. **Slack** (if they use it). Ask: "Do you want Theseus to read Slack directly, or only through Slack's notification emails?"
   - **Directly (official Slack connector):** `claude mcp add --transport http --scope user slack https://mcp.slack.com/mcp`, then `/mcp` to sign in
     with Slack. Mention that their workspace admin may need to approve it. Set `integrations.slack` true and `slack_source` "mcp".
   - **Email bridge (no Slack access):** set `integrations.slack_email_bridge` true and `slack_source` "email". Then, one question at a time:
     a) "Which email address does Slack send notifications to?" → find that account in `email_accounts` (add it if missing; it must be readable).
     b) "Is that Gmail / Google Workspace, Outlook / Microsoft 365, iCloud, or something else?" Then give ONLY that provider's steps:
        - **Gmail / Google Workspace:** Gmail on the web → search `from:(notification@slack.com OR notification@slack-mail.com)` → ⋮ / "Show search
          options" → **Create filter** → ✓ Skip the Inbox (Archive it), ✓ Mark as read, ✓ Apply the label → New label `Theseus/Slack Digest` →
          ✓ Also apply filter to matching conversations → Create. Set `slack_digest_folder` to `Theseus/Slack Digest`.
        - **Outlook / Microsoft 365:** create the folder `Theseus` → `Slack Digest` (top level, not inside Inbox). Then Outlook on the web (works for
          the Mac app too, and runs on the server): Settings → Mail → Rules → **+ Add new rule** → name `Slack → Theseus` → condition *From* the Slack
          notification address → actions **Move to** `Theseus/Slack Digest` and **Mark as read** → ✓ Stop processing more rules → Save → Run rule now.
        - **iCloud Mail:** icloud.com/mail → ⚙︎ Settings → Rules → Add a rule → *From* the Slack address → **Move to** a `Slack Digest` folder.
          (iCloud rules can't mark as read; tell them the folder doesn't badge on most devices, or offer Apple Mail with a local rule.)
        - **Other:** ask whether their provider has server-side filters or rules; if not, suggest forwarding Slack notifications to an account that does.
     c) Ask them to open one Slack notification email and confirm the sender address, then adjust the filter.
     d) Slack itself: Preferences → Notifications → *When I'm not active on desktop* → ✓ **Send me email notifications for mentions and direct
        messages** → every 15 minutes. Add keywords for what they care about, and turn off Slack's marketing emails.
     e) Confirm: "Send yourself a test DM from a colleague, or wait 15 minutes, and I'll check the folder." Then read it once to prove it works.
   - **Neither:** leave both off.
   Either way: Theseus never posts to Slack.
7. **Optional integrations**, each yes or no: texts (iMessage/SMS), Apple Notes inbox, iPhone alarms, Things 3 migration,
   Skylight (unofficial community connector, signs in with their Skylight password), ClickUp (official MCP connector).
   Set `integrations.*`. Mention that anything can be turned on later.
8. **Reach Theseus from your phone (Remote Control, on by default).** Explain: the scheduled setup keeps a Remote Control server running, so the
   Mac appears in the Claude app's Code tab and they can start a fresh Theseus session from anywhere. Ask what to call it (`remote_control.name`,
   default "Theseus"). Make sure the Claude app on their phone is signed in to the same account. After `--schedule`, have them open the Code tab and
   try "status". If they'd rather not, set `remote_control.enabled` to false.
   **Text Theseus from your phone (optional extra, iMessage channel).** Ask: "Want to text Theseus by messaging yourself?" If yes:
   - Explain: a Claude Code session stays running in the workspace while the Mac is awake, and it only ever replies in your own self-chat.
     Channels are a research preview, so this may change.
   - Check Bun (`bun --version`; if it's missing: `curl -fsSL https://bun.sh/install | bash`) and Full Disk Access (already needed for texts).
   - Make sure every handle they text themselves from is in `my_handles`, so the self-chat never shows up as a text waiting.
   - Run `bash <workspace>/engine/install.sh --channel` (it asks for a yes, installs the plugin and the background session) and have them text
     "status" to test it. Point out `engine/install.sh --unschedule` to remove it.
9. **Notes inbox folder name** (default "Theseus") and the master list note title (default "★ Master List").
10. **Alarms policy**: are alarms only for waking up, or do they use them as task nudges too?
11. **Tone** for briefings (brief and direct, warm, playful) and anything else Theseus should know.

## 3. Wire up what they chose
- Connectors: give the exact `claude mcp add --scope user …` command from docs/SETUP.md for each one, and have them run `/mcp` to sign in.
- Run `bash <workspace>/engine/install.sh --check`. Walk them through every macOS
  permission prompt that fails (docs/SETUP.md §1).
- Offer scheduling: `bash <workspace>/engine/install.sh --schedule` (nightly brief + morning brief at their times).

## 4. Finish
Tell them to `cd <workspace> && claude` from now on (the rules load from there), then run `/migrate` to build their master list.
Show a 5-line summary of what's on, what's off, and where their private data lives.
