---
description: An unbiased outside read on how the user communicates in one conversation, only when asked
argument-hint: <person or group> [since YYYY or YYYY-MM-DD] [focus, e.g. "how I handle disagreements"]
---
Give the user an honest outside read on their communication with: $ARGUMENTS. Run this only when the user asks for it. Follow engine/RULES.md §6 and §9. Keep it private: answer here, and save it only if they ask.

The user is the subject. The other person's messages are context for how the user comes across, so this isn't a profile of them.

## Gather
1. `python3 engine/tools/imsg.py sync-status`: note any gaps in the history.
2. `python3 engine/tools/imsg.py stats "<person>"`: volume, balance, reply times and how they changed.
3. `python3 engine/tools/imsg.py thread-notes-list`: if this person has thread notes, read them, but don't update them here.
4. `python3 engine/tools/imsg.py export "<person>" --split month` (add `--since` if given), then read from the files. For a long history, tell the user how many messages it is and ask before reading them all, or offer the last 18 months. Never skip a period silently.

## Stay unbiased
The person asking is the person being assessed, so the pull is toward flattering them or taking their side. Resist it.
- Hold both people to the same standard. If a behavior counts against one, it counts against the other.
- Back every claim with dated quotes `[YYYY-MM-DD HH:MM, Sender]`, and look for counterexamples before you state a pattern. Report the ones you find. If the evidence is thin, say so or leave it out.
- Say the uncomfortable thing plainly and kindly. Don't invent a flaw to seem balanced, or soften a real one into nothing.
- Don't rule on who's right. Don't diagnose either person or use labels like "narcissist", "avoidant" or "toxic". Don't state the other person's feelings or motives as fact. Offer them as possible readings, including the most charitable one.
- If the messages suggest threats, abuse, or someone in danger, say that first and plainly, and point to appropriate support instead of treating it as a style question.

## Report
Lead with the answer. Leave out any section with nothing real in it.
1. **The short version:** three sentences or fewer.
2. **How you come across:** clarity, warmth, directness, humor, and how it shifts with the subject or over time.
3. **The dynamic:** who starts conversations and carries them, who asks and who answers, whether questions and plans get followed through, and what happens after tension.
4. **What's working:** specific strengths, with examples.
5. **What may not be landing:** specific patterns, with examples and how the other person might reasonably read them.
6. **What you might not have noticed:** small recurring patterns that are easy to miss from the inside.
7. **What this can't see:** calls, time together, anything outside this thread, and gaps in the history. Say how much that limits the conclusions.

Offer suggestions only if they ask. If they do, give one or two small, concrete things to try. Never draft or send a message to the person as part of this.
