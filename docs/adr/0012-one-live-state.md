# 12. One live state, followed by signals

**Status:** Accepted  
**Date:** 2026-11-27

## Context

The panels that show the system asked for it on every opening: quick settings (kendra) ran about 26 commands in 0.45 s (nmcli, bluetoothctl, powerprofilesctl at 170 ms each, wpctl, brightnessctl, status scripts), the battery panel (urja) ran `powerprofilesctl` three times on the main loop (0.5-0.9 s to its first frame), Wi-Fi (tarang) and Bluetooth (setu) a dozen each before their lists filled. Every daemon involved already says when something changes (NetworkManager, BlueZ and UPower on D-Bus, power-profiles-daemon, the sound server's subscribe, the kernel's backlight uevents, systemd, GSettings), and the bar and scripts asked the same questions again on their own.

## Decision

`vyom/live.py` follows each source once, for the daemon's whole life, by those signals: one `GDBusObjectManagerClient` for NetworkManager; BlueZ followed narrowly (every object once, then only the adapter's and your paired or connected devices' changes; everything only while a panel watches, so another program's scan, which reports every stranger's signal many times a second, wakes nobody), proxies for UPower, power-profiles-daemon and systemd user units, `pactl subscribe` for the default output, GUdev for the backlight, `Gio.Settings` for the colour scheme. Nothing polls. A snapshot is worked out again only after a change; `live.get(name)` is a copy of it (safe from a search thread), `live.watch(name, fn)` tells an open panel at idle, several changes coming as one call.

Tools read it with a fallback, so they work with an older Vyom (`try: from vyom import live`), and keep doing their actions (connect, toggle) the way they did.

The daemon publishes a summary of each source for other programs, from one owner: `dev.vayu.Vyom.State` at `/dev/vayu/Vyom/State` on Vyom's bus name (a JSON string property per source, `PropertiesChanged`, `Get(name)`) and `$XDG_RUNTIME_DIR/vayu/state/<name>.json`, replaced by an atomic rename only when its contents change. What a scan changes many times a second (signal levels of networks and devices you aren't on) is left out of the summary, and a source is published at most four times a second, so a burst wakes no one. A (re)started Vyom writes everything fresh.

The one helper process, `pactl subscribe`, dies with Vyom whatever way it goes (`PR_SET_PDEATHSIG`, through `setpriv` or a child setup) and is stopped on shutdown.

## Consequences

- Panels open on the current state: no command on the way to the first frame.
- Vyom wakes only when the system changes (on a laptop on Wi-Fi, a few times a minute: NetworkManager's own updates).
- WirePlumber's library (Wp 0.5) would avoid the `pactl` process; it isn't used yet because it can only be tested against a running PipeWire, and tests must never reach the user's own.
- A source whose daemon isn't running is `None` (or `{"running": false}`): tools then ask the old way, which also explains what's wrong.
