# Changelog

Newest first. Releases are tags (`vX.Y.Z`).

## v0.2.4 -- 2026-10-19

- Footer key hints show the keys as key caps with their names (Ctrl+Enter,
  Shift+Enter, Esc) instead of symbols (⌃↵, ⇧↵): `vyom.ui.hint_label()` and
  `keycap_markup()` for tools that build their own footer.

## v0.2.3 -- 2026-10-19

- Fixed: moving down a long list stopped scrolling once the selection left
  the visible part. Rows were measured against the scrolled window's
  Viewport (only the visible area), so a row below it looked visible.
  They're measured against the list itself now.

## v0.2.2 -- 2026-10-19

- Bigger panels: every tool's size times `[vyom] scale` (default 1.25), never
  more than 90% of the screen, so it adapts to smaller displays. The
  preview column scales with it.

## v0.2.1 -- 2026-10-19

- `vyom dmenu` panels are dialog-sized (640x340) instead of launcher-sized:
  they usually hold a handful of choices (Accept / Reject, Update now / Later).

## v0.2.0 -- 2026-10-19

Vyom is now the runtime for a family of tools, each in its own
repository (dvara, ganit, smriti, bhava, tarang, setu, doot, patra,
suchana, raga, mudra, urja, vishram, kendra): together they replace wofi
(and nwg-bar) in Vayu.

- A plugin API (vyom/plugin.py): a tool is a directory with plugin.toml and
  a package exporting `Plugin`, found in ~/.local/share/vyom/plugins/ and
  $VYOM_PLUGIN_PATH. A tool whose `requires` are missing, or whose
  `available()` says no, is skipped with the reason (`vyom list`); one that
  fails to load doesn't stop the rest.
- One shared panel (vyom/panel.py): a centered (or anchored) layer-shell
  window with a mode pill, the query, rows with icon tiles (Nerd Font
  glyphs, theme icons or images), sections, badges, a grid layout, an
  optional fixed-width preview pane, a card layout, and key hints in the
  footer. Searches run in a worker thread with stale results dropped;
  `live` refreshes while open.
- Keys everywhere: Up/Down or Ctrl+K/J, Page Up/Down, Enter (with Shift /
  Ctrl variants per tool), Tab to the next tool, Esc (the tool sees it
  first, e.g. to cancel a password prompt).
- `vyom dmenu`: any script's picker as a Vyom panel (stdin lines, the pick
  on stdout, exit 1 on Esc; Shift+Enter returns what you typed). Killed
  while waiting, it closes its panel.
- `vyom <tool> [args]` starts the daemon if needed (logs to
  ~/.local/state/vyom/daemon.log); the same call again closes the panel.
  Every panel is built when the daemon starts, so even the first open is
  instant.
- vyom.ui (building blocks for previews and cards) and vyom.util (run,
  spawn, copy, type, notify, state files, fuzzy matching with a strict
  substring mode for big lists).
- Quick settings moved out into its own tool, kendra. Install layout:
  Vyom in ~/.local/share/vyom/core, tools in ~/.local/share/vyom/plugins.

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
