---
description: One-time migration of existing reminders, task apps and old task notes into the master list
---
One-time setup. Be thorough, and ask before changing or completing anything in Reminders.
1. Gather, from whatever is enabled:
   - `bin/ek lists` and `bin/ek reminders --completed-since 60d`
   - Things 3 (if `things_migration`): `python3 engine/tools/things_export.py`, then read exports/things/*.md
   - Old task notes: `python3 engine/tools/notes.py folders`, then ask which notes are old task lists (or `notes.py find --query …`) and read them
   - Skylight lists and chores; ClickUp spaces and assignments
2. Dedupe across sources by meaning. Keep the most detailed version and note all sources.
3. Propose **categories** (≤ 10, based on profile.md: work, each side business or project by name, Home, Finance, Health…) in data/categories.md. Wait for approval.
4. Draft NOW / NEXT / LATER / EVENTUALLY / WAITING placement as a compact table. Batch your questions.
5. After approval, write data/master.md with ids and data/sync-map.json, then publish the master note.
6. Propose a Reminders cleanup (what becomes master-only, which lists to merge). Do nothing until the user says yes.
7. Leave other task apps untouched. The user archives them when ready.
8. Alarms (if `iphone_alarms`): `python3 engine/tools/alarms.py --text`. Add "Talk over" items per §7c. Ask about Apple Watch alarm times and record them in data/alarms-static.md.
9. Build data/voice.md from `python3 engine/tools/imsg.py style --limit 80`.
