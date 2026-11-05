---
description: Re-read Anthropic's current rules, compare them with how Theseus works, and propose changes if needed
argument-hint: [--force to re-check even if nothing changed]
---
Follow engine/RULES.md §11 "Compliance check". Steps:
1. Read docs/COMPLIANCE.md (the assumptions A1–A7 and their source URLs).
2. Fetch each Anthropic source with WebFetch (if a URL moved, say so in the report when this is an unattended run, which can't search; otherwise use WebSearch to find the current page on an anthropic.com, claude.com or
   claude.ai domain). For each page, extract only the passages relevant to the assumptions and record a short fingerprint
   (title, last-updated date if shown, and a 1–2 line summary of each relevant rule) in data/compliance/<YYYY-MM-DD>.md.
3. Compare with the previous file in data/compliance/. For every assumption, report one of:
   ✅ still holds · ⚠️ wording changed but it still holds (explain) · ❌ conflicts or is uncertain (quote ≤ 1 short sentence, explain).
4. For each ❌, propose the smallest concrete change (which engine file and what to change, or a setting such as turning off
   hourly sync). **Do not edit the engine or docs yourself.** Write the proposal to data/compliance/proposals.md and ask the user.
   If the user maintains the public repo, also draft a CHANGELOG line and a note for users.
5. Put one line in the Today note: "⚖️ Compliance (monthly): all clear", or "⚖️ Compliance: N items need a look (see /compliance)".
6. Update `data/state.json → compliance_last_checked`. Log it in data/log.md.
Never present this as legal advice. When something is genuinely ambiguous, say so and suggest asking Anthropic directly.
Extra: $ARGUMENTS
