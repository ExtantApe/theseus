# Theseus
### Live your life better. Theseus does the organizing; you do the living.

**Free and open source, always.** No subscription, no paid tier, no data collection.

Theseus helps you run your life. It doesn't run it for you. A private personal assistant that runs in **Claude Code on your Mac**. It keeps one prioritized list of
everything you have to do, briefs you every night and morning, tells you who's waiting on a reply, and drafts those
replies in your own voice. **It never sends anything for you.**

> Named after Claude Shannon's *Theseus*, the 1950 mechanical mouse that learned its way through a maze.
> This one learns its way through yours.

---

## What it does
- **One list.** NOW / NEXT / LATER / EVENTUALLY, categorized and ranked. It lives in Apple Notes, so it's on every device.
- **Dictate anywhere.** Type or speak into a Notes folder, `/add` in Claude Code, or ask Siri to "remind me…". Theseus files it,
  and makes a Reminder only when a nudge is actually needed.
- **A pinned 📌 Today note** that's always current: your top tasks, agenda, who's waiting on you, and in the evening a 🌙 Tomorrow
  section (agenda, top 3, what to prep tonight). It works with no connection to Claude. Jot in it or check things off,
  and Theseus reads your edits back on its next run.
- **Notices what you already did.** Replied to the text? Sent the email? Checked off the reminder? It closes the task
  (and asks when it isn't sure).
- **"What's next?"** "Finished everything except X because Y, I have 45 minutes." It updates the list and picks what fits.
- **Learns how you prioritize** with quick "A or B?" questions, efficient bubble-sort style.
- **Texts:** who's waiting on you, reply sprints, and drafts built by asking *you* the other person's questions
  ("Sam's asking: are you still coming Saturday?"). It never fills in blanks and tells you when to read the thread yourself.
- **Thread reports:** neutral, timestamped accounts of long or multi-year conversations.
- **Optional:** Skylight (chores and groceries), ClickUp, a Slack email bridge, iPhone alarms, Things 3 migration.

## Privacy model
- **Your data stays in your workspace** (`~/Theseus`): profile, config, master list, drafts, exports. The engine (this repo)
  contains no personal data, and updates never touch your files.
- Messages, Mail, Contacts and Things are read **read-only from snapshots**. Nothing is modified.
- Sending tools are **blocked** in the workspace settings. Every change Theseus makes is logged.
- You choose your sources: email and calendar through a connector (e.g. Composio) **or** Apple Mail / Calendar.
- Theseus uses **your own Claude Code account**. It never asks for or handles your Anthropic login.

## Requirements
macOS 14+, Claude Code, Apple developer tools (`xcode-select --install`). An iPhone is optional (texts, alarms).

## Install
In Claude Code:
```
/plugin marketplace add <owner>/theseus
/plugin install theseus@theseus
/theseus:setup
```
or `git clone https://github.com/<owner>/theseus && cd theseus && ./install.sh`.
Full guide: [docs/SETUP.md](docs/SETUP.md).

## Integrations
| | Type | Status |
|---|---|---|
| Apple Reminders, Calendar, Notes, Messages, Contacts, Mail | built in (local) | core / optional |
| Email and calendar via Composio or other MCP connectors | connector | optional |
| ClickUp | official connector | optional |
| Skylight | ⚠️ unofficial community connector | optional, use at your own risk |
| Things 3 | read-only import | optional, one-time |
| iPhone alarms | Shortcuts → iCloud Drive file | optional |
| Slack | email-notification bridge (no Slack access) | optional |

## Contributing
Run `scripts/leak-check.sh` before every commit (`scripts/install-hooks.sh` makes it automatic). It blocks
commits that contain anything from your private terms list, plus phone numbers and real-looking emails.

---
**Independent project. Not affiliated with, endorsed by, or sponsored by Anthropic.**
Claude and Claude Code are trademarks of Anthropic, PBC. Skylight, ClickUp, Composio, Things and Slack are trademarks of their
respective owners. MIT licensed. Provided as is, with no warranty.
