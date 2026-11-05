---
description: Take deep, neutral notes on how the user and one person talk, reading only messages not covered yet
argument-hint: <person or group name>
---
Keep thread notes for: $ARGUMENTS. Run this only when the user asks for it. Never start it from a scheduled run, a sync or another workflow.

The notes are an observer's detailed record of how the user and this person interact. They should capture the essence of the conversation, closely enough to catch nuances the user may not have noticed, and let Theseus get back up to speed without rereading the thread. Theseus isn't acting as the user here.

1. `python3 engine/tools/imsg.py --fresh thread-notes "$ARGUMENTS"`. If the name is ambiguous, run `imsg.py who` and ask which one. If it reports 0 new messages, you're done: the check is already logged.
2. Before the first read of a thread, run `imsg.py stats "$ARGUMENTS"` for its shape. If more than about 600 messages are left, tell the user the count and ask before reading them all, or offer the last 18 months with `--since 18m`. Notes are only as deep as what's been read, so say how much is covered.
3. Compare the current notes with the new messages. Add what's new, refine what they change, and correct what they contradict. Keep what still holds. If they show nothing new, leave the notes alone: don't pad them.
4. Save the file named in the output, as long as it needs to be, with these sections. Leave out any with nothing real to say.
   - First line `# <name>`.
   - **Coverage:** the dates and how many messages these notes are based on, and any gaps.
   - **How each of them writes:** length, rhythm, punctuation, emoji, reactions and vocabulary, for both people, and how the user differs here from data/voice.md.
   - **Shared language:** nicknames, running jokes and references, with what they refer to.
   - **The rhythm:** who starts, who carries, reply speed, times of day, silences and how they end.
   - **Recurring subjects:** what they keep coming back to, what gets planned, and whether plans happen.
   - **How hard moments go:** disagreement, bad news, apologies and repair, and who moves first.
   - **What's changed:** how any of this has shifted over time, with dates.
   - **Small things:** patterns easy to miss from the inside, like a word that only appears when plans are about to change, or questions that often go unanswered.
   - **Reading between the lines:** possible meanings, kept here and nowhere else. Label each as a possible reading with how sure you are, what it's based on, and another way to read it.
   - **Examples:** short verbatim quotes that show the patterns above.
5. Everything except "Reading between the lines" is what actually happened. Cite it with `[YYYY-MM-DD, Sender]` where it matters. Don't take sides or judge either person, and don't state feelings or motives as fact.
6. Mention a private subject, like health or money, only as far as it shapes how they talk. Never record codes, passwords or account numbers.
7. Always record the check, even if nothing changed: `python3 engine/tools/imsg.py thread-notes-mark "$ARGUMENTS" --result updated` or `--result unchanged`.
8. If messages are left and the user agreed to read them, repeat from step 1.

Thread notes stay in `data/thread-notes/`. Never paste them into a draft, a shared list or a message to someone else. For an opinion on how the user communicates, that's `/mirror`.
