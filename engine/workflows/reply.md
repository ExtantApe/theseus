---
description: Draft a reply in their voice. Asks questions as if the person asked; never sends
argument-hint: <person or group name>
---
Draft a reply to: $ARGUMENTS. Follow engine/RULES.md §6 exactly.
1. `python3 engine/tools/imsg.py --fresh thread "$ARGUMENTS" --last 80` (if the name is ambiguous, run `imsg.py who` and ask which one).
2. Read data/voice.md, and how the user writes to this specific person in the thread.
3. Pull out the open points, then ask them as if the person just asked the user (≤ 5, quick-pick where natural).
4. Flag any stopping point where they should read the conversation himself, with exact pointers.
5. After they answers, compose the reply in their wording and save it to data/drafts/. Never send it.
