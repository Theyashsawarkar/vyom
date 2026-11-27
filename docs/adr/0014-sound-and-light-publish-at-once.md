# 14. Sound and light are published at once, with the output's kind

**Status:** Accepted (changes ADR 12)  
**Date:** 2026-11-28

## Context

ADR 12 publishes each source at most four times a second, so a burst (a Wi-Fi scan starting) wakes no one change by change. Two other programs still followed the sound server and the backlight on their own because that limit and the summary didn't serve them: Vayu's bar ran its own `pactl subscribe` and two `pactl` runs per volume step (its sound icon needs to know earbuds from a TV, which the summary left out), and ekatva ran `pactl subscribe` and `udevadm monitor` while a phone shows its media panel. A volume step woke three readers of the sound server (Vyom's `wpctl`, the bar's two `pactl` runs), and a scroll through Vyom would have shown on the bar up to 250 ms late.

## Decision

- Each source says how often it may be published (`Source.publish_every`, 0.25 s by default). The volume publishes at once (0): its own reads, one at a time, already pace it at a step per ~10 ms. The backlight publishes at most every 50 ms (a held key steps it ~30 times a second; the first and the last step go out at once).
- The volume is read with `pactl -f json list sinks` (one run per step; `pactl get-default-sink` beside it only when the server says the default may have changed) instead of `wpctl`, and its summary carries what a bar needs to draw the output: `sink`, `device`, `volume` (the channels' average), `muted`, `bus`, `api`, `form_factor`, `port`. `{"sink": ""}` means there is no output; `null`, that nothing follows the sound server (no `pactl`, or not read yet). A `pactl` without JSON (before 16) is read the plain way.
- When `pactl subscribe` ends, the volume is read again at once (no output while the server is away) and followed again after 3, 6, 9... s, up to a minute, never giving up (it gave up after five tries).

## Consequences

- One `pactl subscribe` on the desktop instead of two (three while a phone watches its media panel), and one `pactl` run per volume step instead of three. Measured headless (fake `pactl` at its real ~9 ms, waybar on its signal): a step reaches Vayu's bar in 21-22 ms median through Vyom, against 22 ms when the bar asked `pactl` itself.
- Programs that follow `dev.vayu.Vyom.State` wake on every volume step (they did on their own watchers anyway) and on up to 20 backlight steps a second while a key is held.
- Readers keep their own watcher as a fallback for when Vyom isn't running or is older: a `volume` without `sink` is from before this change.
