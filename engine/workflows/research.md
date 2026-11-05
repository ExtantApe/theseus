---
description: Search texts for topics or patterns across people and time; compile findings
argument-hint: <what to look for, e.g. "every time anyone mentioned the lake house since 2023">
---
Research request: $ARGUMENTS
1. Plan the search terms (synonyms, names, misspellings). Use `imsg.py search` with --regex, --since, --who and --context 3 as needed. Iterate.
2. For pattern questions, use `imsg.py stats` and exports. Compute with code rather than estimating.
3. Write findings to exports/research/<slug>-<date>.md: method, terms used, timestamped evidence, counts, caveats (run sync-status for completeness).
4. Give the user a short answer first, then the file location.
