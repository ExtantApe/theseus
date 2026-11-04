# 0005: Filing lives in its own tool, Ariadne
**Status:** accepted · 2026-11-03

**Context:** File and Notes organizing was built as a module in the engine. It moves real files on an occasional rhythm, while Theseus runs constantly and mostly reads and drafts. Its rules loaded on every run, including background syncs that only ever counted.

**Decision:** Ariadne is a separate repo, data folder and Mac app. Theseus's side is one optional check-in row, one note in the rules and one setup step, all behind `integrations.ariadne`. It calls `ariadne count`, and `ariadne rules` when the user asks to file. Theseus's settings allow only those two commands, so nothing here can approve or move anything.

**Why not one app:** separate permissions aren't the reason, since Theseus.app needs Full Disk Access anyway. The reasons are risk and purpose: Ariadne is useful without an assistant, and Theseus stays free of file-moving rules.
