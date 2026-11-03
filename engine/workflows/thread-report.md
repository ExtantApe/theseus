---
description: Neutral, timestamped account of a long text thread (multi-year OK)
argument-hint: <person> [since YYYY or YYYY-MM-DD] [focus topic]
---
Build a neutral account of the text history with: $ARGUMENTS. Follow engine/RULES.md §9.
1. `python3 engine/tools/imsg.py sync-status`: note completeness caveats.
2. `python3 engine/tools/imsg.py stats "<person>"`: get the shape of the thread.
3. `python3 engine/tools/imsg.py export "<person>" --split month` (add --since/--until if given). Read INDEX.md.
4. Summarize month by month into exports/<slug>/summaries/ with citations [YYYY-MM-DD HH:MM, Sender]. Don't skip periods.
5. Write the final report to exports/<slug>/REPORT.md: scope, completeness note, timeline of key events, a section per topic (if focus given), direct quotes, and an "Interpretation" section only if the user asked for one.
6. Tell the user where it is, and give the 5-line summary.
