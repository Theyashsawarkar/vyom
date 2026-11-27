# 11. Often-used panels stay warm

**Status:** Accepted (changes when ADR 10 applies)  
**Date:** 2026-11-27

## Context

ADR 10 let every hidden panel go of its surface after 30 s: 90 MB less graphics memory, but every opening after a pause made a new surface. Measured in a headless sway (Intel, GTK 4.24 Vulkan): a kept panel reopens in 3-16 ms, a released one in 15-40 ms, with 100-150 ms spikes now and then; the launcher, released after the warm-up, opened in 66 ms instead of 14. For the panels opened many times a day that is the wrong trade: the desktop must feel instant, and a little memory that buys that isn't wasted.

## Decision

A hidden panel keeps its surface unless it is rarely used and has been hidden a long time:

- never released: the warm-up's panel (the launcher), the panels in `[vyom] keep`, a tool with `keep = true` in its `[plugin.<name>]` (`keep = false` there lets even an often-used one go), and any panel opened `[vyom] keep_often` times (default 5) in the last week. Vyom counts openings in `vyom-uses.json` in its state folder, written at idle after a panel hides, never on the way to a frame.
- the rest let go after `[vyom] release_after` seconds hidden: default 600 (10 minutes), so a tool used in a burst never pays; `false` keeps every surface.
- a kept panel sets no timer at all, so it costs no wakeups.

## Consequences

- The panels on your keys open from a kept surface every time (launcher 10-17 ms instead of 36-66 ms). Each kept panel holds its buffers, about 10 MB of graphics memory.
- A rarely used tool still gives its memory back, once it has been hidden ten minutes; opening it then takes 10-25 ms more.
- The first week (or after the state file is gone) every panel but the launcher counts as rare until it has been opened 5 times; `keep` names the ones that matter from the start.
