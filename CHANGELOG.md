# Changelog

Newest first. Releases are tags (`vX.Y.Z`).

## v0.1.1 -- 2026-10-19

- `vyom daemon` builds the panels right away, so the first `vyom quick`
  after login is as fast as the rest (it took ~600 ms while the tile
  checks ran on first use).
- The Wi-Fi tile reads NetworkManager's cached scan (`--rescan no`):
  without it the network name could take seconds to appear.

## v0.1.0 -- 2026-10-19

- First release: **quick settings**. A layer-shell panel under the bar's
  top-right corner with a header (greeting, uptime, battery with time
  to full / left, lock and power buttons), eight tiles (Wi-Fi, Bluetooth,
  hotspot, Do not disturb, caffeine, dark theme, new wallpaper, power
  profile) and volume / brightness sliders.
- One resident GTK process; `vyom quick` toggles it over D-Bus
  (org.gtk.Actions), measured at ~95 ms to open and ~60 ms to close from
  the key press, most of it the launcher's Python start.
- Tiles refresh in background threads after the panel shows, so slow
  tools never hold it up. Tiles whose tool or hardware is missing are
  left out (no Bluetooth controller, backlight, battery, power-profiles).
- Built-ins use nmcli, bluetoothctl, makoctl, gsettings, powerprofilesctl,
  wpctl and brightnessctl; any tile can be driven by your own commands in
  ~/.config/vyom/config.toml (examples/config.toml).
- The panel fills its layer surface exactly so SwayFX's
  `layer_effects "vyom"` blur and corner radius line up with it.
