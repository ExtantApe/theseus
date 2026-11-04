# Compliance assumptions (checked monthly by /compliance-check)

Theseus is designed around these assumptions. Each one cites the rule it depends on. If a source changes,
`/compliance-check` re-reads it, compares it against this list, and proposes changes. It never edits the engine on its own.

| # | Assumption | Source |
|---|---|---|
| A1 | Theseus runs inside each user's *own* Claude Code, signed in through Anthropic's own flow. It never collects, stores or forwards Claude credentials or tokens. | Claude Code "Legal and compliance" → Authentication and credential use: https://code.claude.com/docs/en/legal-and-compliance |
| A2 | Scheduled runs use `claude -p` on the user's own plan, at an ordinary individual level: 2 runs/day by default. Frequent checks are opt-in. The local fingerprint can run every few minutes (no Claude involved). Claude itself runs only when something changed, at most once per `min_minutes_between_claude_runs` (default 15), and only while awake by default. | Same page (usage limits assume ordinary, individual use); help article "Use the Claude Agent SDK with your Claude plan": https://support.claude.com/en/articles/15036540 |
| A3 | Any future app either launches the user's own Claude Code, or uses the user's *own* API key via the Agent SDK. It never offers Claude.ai login and never routes requests through a subscription on users' behalf. | Legal and compliance page; Agent SDK overview |
| A4 | Name and branding: "Theseus" contains no Anthropic marks. Text may say it "works with Claude Code" in plain words, plus a non-affiliation notice. No Anthropic or Claude logos. | Legal and compliance → name and logo; Trademark Guidelines: https://www.anthropic.com/legal/trademark-guidelines |
| A5 | Uses stay within Anthropic's Usage Policy: personal productivity, never sends messages as the user, no impersonation, no surveillance of others, privacy-protective handling of third parties' messages. | Usage Policy: https://www.anthropic.com/legal/aup |
| A6 | Free, MIT-licensed, no resale of Claude access, no paid tier. | Consumer Terms: https://www.anthropic.com/legal/consumer-terms ; Commercial Terms: https://www.anthropic.com/legal/commercial-terms |
| A10 | Unattended runs only read connectors. A hook refuses anything that sends, whoever or whatever asks, and changing anything else needs a person unless the user allows that exact tool. Recheck that Claude Code still blocks on hook exit 2, and that hook "allow" and "deny" decisions work as `send_guard.py` assumes. | Claude Code docs → Hooks |
| A9 | Phone access uses Claude Code's own Remote Control feature on the user's own machine and account. Theseus only keeps it running. | Claude Code docs → Remote Control |
| A8 | The optional iMessage channel uses Claude Code's official channels feature and plugin (a research preview), on the user's own plan, replying only in their own self-chat. Flags or allowlist behavior may change, so re-check them monthly. | Claude Code docs → Channels |
| A7 | Plugin distribution through a GitHub marketplace, following Claude Code's plugin rules. | Claude Code docs → Plugins / Plugin marketplaces |

Third-party services follow their own terms (Composio, ClickUp, Skylight's unofficial API, Slack, Apple). The monthly check flags
obvious problems there too, but only Anthropic's rules are tracked in detail.
