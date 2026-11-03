---
description: Update the Theseus engine in your workspace (your profile, config and data are untouched)
---
Locate the plugin files (`${CLAUDE_PLUGIN_ROOT}`, or `find ~/.claude/plugins -name install.sh -path '*theseus*' | head -1`).
Ask for the workspace path if `~/Theseus` doesn't exist. Run `THESEUS_HOME=<workspace> bash "<plugin root>/install.sh" --update`.
Then summarize what changed by comparing `<plugin root>/CHANGELOG.md` with the previous version, if present.
