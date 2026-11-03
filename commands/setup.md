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
4. **Email:** which apps they actually use. Explain the two options plainly:
   - *Connector* (e.g. Composio, or an official Gmail/Microsoft connector): reads their accounts directly. Best if they use the Gmail or Outlook apps or the web.
   - *Apple Mail*: reads Mail's local database, with no third party involved. Best if they already use Apple Mail, and only works while the Mail app runs.
   Set `email_source` and list each account in `email_accounts` with a friendly label.
5. **Calendar:** same choice (`calendar_source` "apple" reads every calendar synced into the Calendar app; "connector" reads and writes
   Google or Outlook directly). Ask which calendar should get new events by default, and whether certain kinds of events go to specific
   calendars (`calendar_routes`, e.g. side-business events → that business's Google calendar).
6. **Optional integrations**, each yes or no: texts (iMessage/SMS), Apple Notes inbox, iPhone alarms, Things 3 migration,
   Skylight (unofficial community connector, signs in with their Skylight password), ClickUp (official), and the Slack email bridge.
   Set `integrations.*`. Mention that anything can be turned on later.
7. **Notes inbox folder name** (default "Theseus") and the master list note title (default "★ Master List").
8. **Alarms policy**: are alarms only for waking up, or do they use them as task nudges too?
9. **Tone** for briefings (brief and direct, warm, playful) and anything else Theseus should know.

## 3. Wire up what they chose
- Connectors: give the exact `claude mcp add --scope user …` command from docs/SETUP.md for each one, and have them run `/mcp` to sign in.
- Run `bash <workspace>/engine/install.sh --check`. Walk them through every macOS
  permission prompt that fails (docs/SETUP.md §1).
- Offer scheduling: `bash <workspace>/engine/install.sh --schedule` (nightly brief + morning brief at their times).

## 4. Finish
Tell them to `cd <workspace> && claude` from now on (the rules load from there), then run `/migrate` to build their master list.
Show a 5-line summary of what's on, what's off, and where their private data lives.
