# Changelog

Newest first. Releases are tags (`vX.Y.Z`).

## v0.4.0 -- 2026-10-24

- **Numbered tabs.** Every tab shows its number (1..9, 0 for the tenth), so
  `Ctrl+<number>` goes there without counting tabs.
- **`Ctrl+Tab` / `Ctrl+Shift+Tab`** cycle the tabs (next / previous,
  wrapping), in every tool with tabs, alongside `Ctrl+H` / `Ctrl+L`. The
  footer's hint says `Ctrl+Tab tabs`.
- **`Shift+Tab`** opens the previous tool, as `Tab` opens the next one.
- **Key caps in the theme's colours**: footers and hints (and any tool using
  `ui.keycap_markup`) take the theme's surface and text colours from the
  loaded stylesheets; they were Catppuccin Mocha's in every theme.
  `vyom.panel.KEYCAP` has them for tools that draw their own.
- Inactive tab labels are brighter (the theme's subtext, not overlay):
  easier to read over a bright wallpaper.

## v0.3.2 -- 2026-10-24

- **Logs go to the journal, with tracebacks.** `vyom` starts the daemon as
  your `vyom.service` if you have one, else as a transient unit
  (`systemd-run`): `journalctl --user -u vyom -u vyom-daemon`. Only without
  systemd does it write `~/.local/state/vyom/daemon.log`, now kept under
  1 MB (it grew forever). A plugin that fails to load, a search() or
  background job that raises, and any exception nobody caught (a GTK
  callback, a thread) are logged with their traceback, not one line or
  nothing. Each line carries its level, so `journalctl -p warning` finds
  them.
- `vyom/log.py`: the setup, standard library only. A tool logs with
  `logging.getLogger("vyom.<name>")`, no import from Vyom needed.
  `VYOM_DEBUG=1` (or `vyom daemon --debug`) adds debug messages, among them
  every command `util.run` ran that failed, with its exit code and stderr.
- A broken config.toml is a warning in the log (it was printed to stdout).
- The README, CONTRIBUTING, agent notes and the bug report form point to
  the journal; agent notes say to test in a headless sway, never on the
  user's own desktop.

## v0.3.1 -- 2026-10-24

- **Apps started from Vyom no longer inherit `LD_PRELOAD`.** `vyom daemon`
  re-runs itself with gtk4-layer-shell preloaded (it has to load before
  GTK), and kept it in its environment: every app, terminal and command a
  tool launched preloaded it too, and so did everything those started (a
  terminal's tmux server, then every shell, hook and script inside it).
  Each such process loaded GTK 4's 114 libraries at start: ~35 ms instead
  of ~1 ms for a plain command, an interactive zsh 0.61 s instead of 0.24 s.
  Vyom now takes it back out once it's loaded (any other preload you had
  stays). A tmux server or shell started before this keeps it until
  restarted (`tmux set-environment -gu LD_PRELOAD` clears it for new panes).

## v0.3.0 -- 2026-10-24

- **Tabs are part of the panel**, with one set of keys in every tool: a tool
  lists `tabs = [(key, label)]` and the panel draws them in the search bar.
  `Ctrl+H` / `Ctrl+L` switch to the previous / next tab (wrapping, vim's
  left/right beside `Ctrl+K` / `Ctrl+J`), `Ctrl+1..9` and `Ctrl+0` pick one
  by number, the footer shows `Ctrl+H/L tabs`, and each tab's tooltip its
  number. Tools get `self.tab`, `tab_changed()`, `select_tab()` and
  `set_tabs()`, and lose their own tab buttons, keys and CSS (ADR 6).
  bhava, mudra, raga, smriti, tarang and ganit use it from their next release.
- The README lists every panel's keys in a table.
- Tool directories with a dot in the name are skipped: while `kosha link`
  runs your checkout of a tool, kosha keeps the release as
  `<name>.kosha-release` next to it, and Vyom listed both in `vyom list` and
  loaded the release's style.css on top of the checkout's.

## v0.2.9 -- 2026-10-21

- **Themes**: `[vyom] css = [...]` loads more stylesheets after everything
  else, e.g. [varna](https://github.com/Theyashsawarkar/varna)'s colours.
  The panel background and the selection, focus and border colours are now
  named (`@base`, `@crust`, and a new `@accent`, mauve by default) instead
  of fixed hex codes, so a theme that redefines the names recolours all of Vyom.

## v0.2.8 -- 2026-10-21

- A website (GitHub Pages, https://theyashsawarkar.github.io/vyom/): the README as a home page, the
  changelog, and architecture decision records (`docs/adr/`), built from these files by
  `scripts/build-site.py`; CI checks the site is up to date.

## v0.2.7 -- 2026-10-21

- Documentation for open source: a logo and banner, a full README (features,
  install, usage, configuration, troubleshooting, the whole Vyom family),
  CONTRIBUTING, SECURITY and CODE_OF_CONDUCT, issue and pull request
  templates, and CI (compiles, checks the version has a changelog entry).

## v0.2.6 -- 2026-10-19

- Cards (power menu, battery, quick settings) keep the tool's own width
  and are as tall as their content; the shared size is for search tools.
- `[vyom] opacity` (default 0.72, was a fixed 0.82): how much of the
  blurred desktop shows through every panel.

## v0.2.5 -- 2026-10-19

- Every panel opens at the same size: `[vyom] width` x `height` (default
  900 x 520, times `scale`), so switching tools never jumps. A tool's own
  `width`/`height` now only apply to an anchored panel (kendra). Card
  tools fill the panel; `ui.spacer()` pushes a footer to the bottom.

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
