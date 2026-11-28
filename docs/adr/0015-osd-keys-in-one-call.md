# 15. Volume and brightness keys in one call

**Status:** Accepted  
**Date:** 2026-11-28

## Context

A volume or brightness key ran a shell script per press (Vayu's `volume_osd.sh`): `pactl` five times, `grep`, `head`, `flock`, `notify-send`, about 11 processes and 40-80 ms before the slider showed, each press, and more while a touchpad's scroll sent a burst. Vyom already follows both levels (ADR 12) and draws the slider (akashvani, a tool in the same process).

## Decision

- `dev.vayu.Vyom.Osd.Step(s) -> b` at `/dev/vayu/Vyom/Osd` on the daemon's own connection: `volume +N`, `volume -N`, `volume mute-toggle`, `brightness +N`, `brightness -N` (percent).
- The new level is worked out from the level Vyom knows (its own last request while one is on its way, so a burst stacks on it), clamped to 0-100; 0% mutes, any step unmutes. The slider is asked for at once, as a desktop notification with the `value` hint and the synchronous tag the script used, so it looks the same in any notification server.
- Then the change is applied behind it: one `pactl set-sink-volume` (and `set-sink-mute` only when the mute changes), never two at once (presses during one are one more after it, from the latest level); the backlight through logind's `Session.SetBrightness` for our graphical session (`$XDG_SESSION_ID`, else the user's display session), with `brightnessctl set` when logind can't.
- It answers `false` when it doesn't know the level (no sound server, no backlight): the caller does it its own way. A script keeps its old path as that fallback, and for an older Vyom.

## Consequences

- A key press is the script's shell and one `busctl`, then one `pactl` (none for the backlight) inside Vyom: measured headless, the slider is on screen 14-24 ms after the key (was 46-80) for the volume and 10-33 ms (22-55) for brightness.
- The slider shows the level asked for before the sound server confirms it; if the server refuses (an output that can't go that loud), the bar, which follows the server, shows the truth.
- Vyom's notifications for the slider carry the app name "Vyom".
