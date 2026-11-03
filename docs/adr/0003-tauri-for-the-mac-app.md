# ADR 0003: The Mac app uses Tauri 2, with a Swift sidecar for EventKit
**Status:** proposed · 2026-11-03
**Decision:** Build Theseus.app with Tauri 2 + React/TypeScript (the maintainer's existing stack and release pipeline from OnePedigree for Mac),
shipping the `ek` Swift helper as a sidecar for Calendar and Reminders.
**Alternatives:** SwiftUI (more native, but a second stack); Electron (heavier).
**Consequences:** reuse desktop.yml (universal DMG, signed updates, latest.json). Native-only needs go into small sidecars.
