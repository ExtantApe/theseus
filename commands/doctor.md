---
description: Check that every Theseus service is reachable, and explain how to fix anything that isn't
---
Run `THESEUS_HOME=<workspace, default ~/Theseus> bash <workspace>/engine/install.sh --check`.
Also do a cheap read from each enabled connector (email and calendar accounts, Skylight, ClickUp).
Report one line per service (✅/⚠️) with the exact fix for each failure (docs/SETUP.md).
