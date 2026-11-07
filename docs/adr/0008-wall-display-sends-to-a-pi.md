# 0008: The wall display is a Pi your Mac sends to
**Status:** accepted · 2026-11-06

**Context:** M6 planned a wall display served by the Mac, showing no titles by default. Designing it in detail showed two problems. Serving means the Mac listens on the home network for anyone who asks, and the screen goes blank when the Mac sleeps. A to-do display with no titles also can't do its one job.

**Decision:** The Mac sends a filtered `wall.json` to the Pi over SSH, and opens no port. Its key can only deliver or clear, enforced with a forced command on the Pi. The filter reads only `data/master.md`, sends only the sections a view uses, and never sends Communications or Done. Titles are the person's choice for each screen, and stay off until they choose. The builder will be a page in Theseus.app, and the Pi and screen code live in `apps/wall`. There's no second Mac app: unlike Ariadne (0005), a display has no use without the list, and its risks are the same as the app's.

**Consequences:** Part of the list now sits on a second device, in its memory only, and the manifesto names that as an exception. The Pi's list goes stale when the Mac sleeps, so the screen says how old it is. Delivery starts as a launch agent and moves into the app with the builder, because a network reach from a launch agent can't be taken for granted on every macOS version. The Pi can't ask for anything: there's no path from it back to the list, and any later change to that needs its own decision. Active hours sleep the screen and, where the TV answers, the TV itself.
