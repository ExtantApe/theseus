# ADR 0004: Schedules are per day and can be fluid
**Status:** accepted · 2026-11-03
**Decision:** `config.schedule` has day groups (weekdays, weekends or any days), single-day overrides, a regimented/fluid style,
flex hours and adaptive learning. Morning and nightly runs are scheduled per weekday. The first activity after a long quiet stretch triggers a refresh.
**Why:** people's lives differ by day and by person. Fixed 6am/9pm assumptions fail for shift workers, parents and weekends.
