---
name: trading-day
description: Start the trading day - run a full trading cycle per CLAUDE.md, which also schedules the rest of the day's cycles and the exit loop.
disable-model-invocation: true
---

Run a trading cycle per CLAUDE.md.

This is the cycle that starts the day: finish with full-cycle step 10 so the remaining cycles and the
self-paced exit loop are scheduled. Outside market hours, step 10 just schedules the next morning's cycle.
