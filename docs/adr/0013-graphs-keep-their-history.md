# 13. Graphs keep their history in the live state

**Status:** Accepted (extends ADR 12)  
**Date:** 2026-11-27

## Context

Quick settings' Wi-Fi chart (kendra) and the Wi-Fi panel's speed graph (tarang) sampled the card's byte counters only while they were open, so they started empty on every opening and filled while you watched, although Vyom runs all the time. The battery graph (urja) took its own samples inside the panel's tool and asked UPower for its record over the last 3 hours, which comes back empty when the charge hasn't moved for that long (UPower leaves out the point before the window), so after a restart of Vyom it showed almost nothing. The desktop must feel instant, but waste nothing: no needless wakeups, no programs spawned.

## Decision

`vyom/live.py` keeps two histories next to the live state, started with it by the daemon:

- **net**: the byte counters (`/sys/class/net/<dev>/statistics/{rx,tx}_bytes`, two small reads, no command) of every device NetworkManager has connected (ethernet, Wi-Fi), every 2 s on a `timeout_add_seconds` timer (it wakes together with Vyom's other whole-second timers), every second while a panel draws the graph by the second (`live.watch("net", fn, fast=True)`). The last minute (the longest any panel draws) is kept as raw readings, 64 per device. `live.history("net", dev, step, window)` turns them into speeds in bins of any step: between two readings the speed is the bytes over the time, spread over the bins it covers, so 2 s readings fill a 1 s graph evenly. Times are CLOCK_BOOTTIME; two readings more than 6 s apart (a suspend, a disconnect) or a counter that went back (the driver reloaded) count as nothing moved, never a spike. With nothing connected the timer is removed: nothing wakes.
- **battery**: UPower's own charge record for the laptop battery (`GetHistory`, the whole record: a few hundred points), read once; then every change of percentage or charging that the battery source's signals bring. upowerd writes its record to disk anyway, so a restart of Vyom loses nothing and costs no file of ours. `live.history("battery", seconds)` returns the window and the point before it.

Neither is put in the state files or pushed with `PropertiesChanged`: readings every 2 s would wake every program that follows the state. `dev.vayu.Vyom.State.History(name)` returns one as JSON when asked. Sources gain `hooks` (told at once of every change) for the histories to follow NetworkManager and UPower without a watcher's snapshot copy.

Docker (patra) stays out: following container stats all along would cost dockerd about 0.2% of a core per running container (streaming stats, measured with three idle containers: 0.75% against 0.10% idle) and a wakeup a second per container, for a panel opened rarely; patra instead keeps its last readings in its own resident tool and reads Docker's socket only while it's open.

## Consequences

Measured in a headless session (sway + Vyom with kendra, tarang, urja and patra; 120 s, no panel open after start-up, on Wi-Fi):

- Vyom idle: 0.91 context switches a second before, 1.23 after (+0.3/s: the 2 s timer); CPU 0.08-0.10% of a core either way; resident memory the same within noise (each device's minute is about 11 kB of Python objects, the battery's day of points well under 100 kB). After a panel that asked for fast readings closes, the timer goes back to 2 s.
- kendra and tarang open with the last minute drawn; tarang's graph moves by the second as before. A `history("net")` call costs about 45 µs.
- Without NetworkManager there's no net history (`None`): the tools sample as before. Tools keep their own sampler for an older Vyom.
