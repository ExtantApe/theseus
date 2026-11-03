# ADR 0001: Engine and workspace are separate
**Status:** accepted · 2026-11-03
**Decision:** All shareable logic (rules, tools, workflows, templates) lives in `engine/`. Everything personal lives in the user's
workspace (profile, config, data) and is never overwritten by updates or included in the repo.
**Why:** people can share and update Theseus without leaking anyone's life, and the plugin and app can use one engine.
**Consequences:** a leak check guards commits. New personal state always goes under the workspace, never under `engine/`.
