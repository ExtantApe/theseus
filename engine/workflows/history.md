---
description: Is all of my message history on this Mac? Compare with iCloud
argument-hint: [iCloud message count from Settings]
---
Arguments: "$ARGUMENTS". Run `python3 engine/tools/imsg.py sync-status`, adding `--icloud-count N` if a number was given.
If no count was given, tell the user where to find it: iPhone Settings → [name] → iCloud → Messages (it shows "N messages"). Interpret the report plainly. If history looks incomplete, walk them through docs/SETUP.md → "Pull older history down", starting with the least disruptive step.
