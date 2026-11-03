---
description: Ingest your Notes inbox folder (and anything typed after the command) into the master list
argument-hint: [optional text to ingest directly]
---
Process the inbox per engine/RULES.md §4.
- Notes: `python3 engine/tools/notes.py inbox`. Handle every note, then `python3 engine/tools/notes.py processed --id <id> [--id …]`.
- Also ingest this text if given: $ARGUMENTS
Apply sync rules §3 for anything you created, publish the master note, and report in ≤ 8 lines: added / updated / completed / questions.

Bookends (engine/RULES.md §5 "📌 The pinned Today note"): start with the Today-note read-back, and end by republishing the Today note.
