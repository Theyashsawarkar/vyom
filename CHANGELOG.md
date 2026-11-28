# Changelog

Newest first. Releases are tags (`vX.Y.Z`).

## v0.12.0 -- 2026-11-28

- **Every connection in the live state** (ADR 16): `live.get("wifi")["connections"]` lists every active connection, whatever it runs over (Wi-Fi, Ethernet, a phone over USB, mobile broadband, Bluetooth, VPN, WireGuard), with its kind and label, interface, addresses, gateway, DNS, link speed and duplex, MAC, operator and APN, the VPN's server and what it rides on; the primary one (`primary`, NetworkManager's PrimaryConnection) first, a VPN after its connection. Docker's bridges, loopback and other plumbing are left out. From the objects Vyom already follows: no command, no new signal.
- **The net history keeps every connected device**, not only Ethernet and Wi-Fi (`wwan0`, `bnep0`, `wg0`, a phone's `usb0`), so a graph of any connection opens full; `history("net")` without a device is the primary connection's.
- `Panel.set_mode(icon, title)`: a tool changes its mode pill while it shows (tarang reads "Network" on a cable).
- `VYOM_SYS_NET` points the network counters, speed and duplex reads at other files (headless tests with a fake NetworkManager).

## v0.11.0 -- 2026-11-28

- **A key opens a panel ~30 ms sooner**: `vyom <tool>` sends its one D-Bus call (busctl) before Python imports anything else, instead of importing json, subprocess and tempfile and running busctl and then gdbus: 47-50 ms from the key to Vyom, now 18-24 (measured headless). Anything else, or a Vyom that doesn't answer, takes the full path as before.
- **Typing searches at once**: the first keystroke after a pause searches right away instead of after a 40 ms timer, keystrokes typed while a search runs are one search after it, and the results go in before the next frame (they waited for idle time). Launcher: a key to its results on screen went from 60-95 ms to 17-47 ms. A tool with a longer `debounce` (raga's yt-dlp) still waits for a pause.
- **Long lists stay quick**: a list builds widgets for its first 60 rows, and more as you scroll or move toward the end (`G` builds them all); GTK lays out and draws every row a list holds, so the 400-row keybinding list cost 130 ms a frame. Results identical to what's on screen (reopening with an empty search, a live refresh that found nothing new) keep their widgets. Keybindings: reopening 54-81 ms -> 12-24 ms, after a long hide 137-185 -> 38-52.
- **Every kept panel is warm from the start**: after the launcher, each panel that keeps its surface (`keep`, `keep_often`) is drawn once off screen, one after another while idle, so its first opening is as quick as the next: emoji 54-75 -> 11-14 ms, quick settings 82-87 -> 13-16, calculator 40-47 -> 10-11, clipboard 17-22 -> 5-10, launcher 62 -> 16-20. A panel shown for a warm-up has `panel.warming` set (a tool can skip work only a person needs).
- **Volume and brightness keys in one call** (ADR 15, `dev.vayu.Vyom.Osd.Step` at `/dev/vayu/Vyom/Osd`): Vyom works out the step from the level it follows, shows the slider at once and applies it behind it (one `pactl` at a time, bursts stacked; logind's `SetBrightness`, else `brightnessctl`). A key to the slider on screen: volume 46-80 -> 14-24 ms, brightness 22-55 -> 10-33 (with Vayu's scripts calling it first).
- **Footer key caps have round corners**: each is its own label (`.hint-cap`), not a Pango background, which can only be a square box.

- Website: pranali joins the family list in the footer; the site builder passes ruff.
- **Sound and light are published at once** (ADR 14): the volume source is published as soon as it changes (was at most four times a second), the backlight up to 20 times a second, so a bar or a phone following `dev.vayu.Vyom.State` keeps up with your scrolling. Each source says how often it may be published (`Source.publish_every`).
- **The volume says what the output is**: it's read with `pactl -f json list sinks` (one run per step; the default's name only when the server changed), and its state adds `sink`, `bus`, `api`, `form_factor` and `port` to `device`, `volume` and `muted`, so Vayu's bar can draw earbuds, a speaker or a TV from it instead of following the sound server itself. `{"sink": ""}`: no output. A `pactl` older than 16 (no JSON) is read the plain way.
- The volume source follows the sound server again after it goes away for good (3, 6, 9... s, up to a minute), instead of giving up after five tries, and shows no output while it's away.
- CI installs PyGObject with GTK 4, cairo and gtk4-layer-shell from apt (and runs the system Python) so the tests that import GTK run there too; they failed on GitHub with `No module named 'gi'` since they were added.

## v0.10.0 -- 2026-11-27

- **Graphs open with their history drawn** (ADR 13, `live.history`). The live state keeps the network speed of every connected device (its byte counters in sysfs, read every 2 s for the daemon's whole life, every second while a panel draws them by the second; the last minute kept, about 10 kB a device) and the laptop battery's charge (UPower's own record, read once, then every change its signals bring). Quick settings' Wi-Fi chart and the Wi-Fi panel's speed graph open on the whole last minute instead of starting empty; the battery graph is whole after Vyom restarts. `live.history("net", dev, step, window)` gives speeds in bins of any step (2 s readings fill 1 s bins evenly; a suspend, a disconnect or a counter that goes back is 0, never a spike), `live.watch("net", fn, fast=False)` each new reading; with nothing connected there is no timer. The readings are not in the state files or pushed on D-Bus (they'd wake every program following them): `dev.vayu.Vyom.State.History(name)` returns one as JSON when asked. Measured: Vyom idle went from 0.91 to 1.23 wakeups a second, CPU unchanged at 0.1% of a core (ADR 13).
- `Source.hooks`: functions told at once of a source's every change (what the histories follow).

## v0.9.1 -- 2026-11-27

- A command a panel starts in the background (`bluetoothctl scan off` when setu hides) is collected as soon as it exits instead of staying a zombie until Vyom next started a process.

## v0.9.0 -- 2026-11-27

- **One live state for every panel** (ADR 12, `vyom.live`). Wi-Fi and the hotspot (NetworkManager), Bluetooth and device batteries (BlueZ), the battery (UPower), the power profile, the volume, the backlight, systemd user units and the colour scheme are followed for the daemon's whole life by the signals their daemons send anyway; nothing polls. `live.get(name)` is the current state at once, `live.watch(name, fn)` keeps an open panel current. Quick settings, Wi-Fi, Bluetooth and battery read it, so they open without running a command. Other programs get the same on D-Bus (`dev.vayu.Vyom.State` at `/dev/vayu/Vyom/State`) and in `$XDG_RUNTIME_DIR/vayu/state/<name>.json`, written only when it changes. `[vyom] live = false` doesn't publish it.
- **Panels you use often stay warm** (ADR 11, changes ADR 10). A hidden panel keeps its surface, so reopening it is instant; only a rarely used one lets go of it (its buffers in graphics memory, about 10 MB), after 10 minutes hidden (`[vyom] release_after`, default 600; `false`: never). Never released: the launcher, the panels in `[vyom] keep`, a tool with `keep = true` in its section, and any panel opened `[vyom] keep_often` times (default 5) in the last week. The launcher no longer lets go after the warm-up (it reopened in 36-66 ms; now 10-17).
- **Less memory for rarely used panels** (ADR 10): a released panel unrealizes (its widgets and the tool's data stay; its window on the compositor and its buffers in graphics memory go) and the C heap is trimmed. Opening it again takes 10-25 ms more.
- **The heap is trimmed after start-up**: after a Mesa update, the driver compiles its shaders inside Vyom and the C heap stayed at 140 MB; now it goes back to about 20 MB. `util.trim_memory()` does it (glibc's `malloc_trim`, under a millisecond), for a tool that frees a lot too (a notification's popup closing).
- A row's right-hand text can carry a colour that means something (`Row.meta_color`: green, yellow, red, peach), for a battery level in a list (setu).
- Section notes ("Enter connects", "closest first") are a step brighter, so they stay readable over a light wallpaper.
- New screenshots in the Spatial look, taken with made-up demo data (WebP, sharp on high-density screens).
- Section labels, the which-key title and the every-key sheet are in sentence case, not all caps (Spatial: no all-caps labels).
- The website, closer to Vayu's own: the tool's screenshot blurred behind the page, a centred hero with the logo and the verse, the page you're on as the white pill, glass "On this page" and footer panels, releases as cards. No glow behind the logo, no coloured line beside the verse.
- **Spatial look** (Vayu's new design): panels are graphite glass with a lit top edge and 28 px corners (SwayFX's `layer_effects "vyom"` corner radius should match; ADR 9); where you are is brighter glass with a light rim instead of an accent frame and left bar; search bar, tabs, buttons, chips, segmented controls, sliders and progress bars are pills; colour stays for meaning only. The fallback colours (without varna) are Vayu's Spatial palette.
- The website has Vayu's Spatial look: graphite glass, a floating navigation bar, near-white for links and the main button, and the tool's own colour only as its signature (the logo's glow, the shloka's line, the release dots). No more all-caps labels.

## v0.8.0 -- 2026-11-17

- **The pointer says what's clickable**: a hand over buttons, switches, tabs and rows that open, a text beam over text boxes, in every panel (GTK left it an arrow everywhere).
- **One box, not two, in a card's text boxes.** The card cursor ringed the focused widget, and in a text box that's the text inside it: a second ring inside the box's own border. Now the box itself carries the cursor (`vk-cursor` on the entry), so a tool can light its border.

## v0.7.4 -- 2026-11-14

- **Vyom exits when there's no display yet**, instead of running with no screen. D-Bus can start it before the session's environment is ready (akashvani, the notification server, is D-Bus activated by the first notification): it came up with no display, built no panels and held on until the session restarted it. Now it logs why and exits, and its unit or the session starts it again once there's a display.
- **The first opening is as quick as the rest.** After `vyom daemon` starts, the launcher (or the first tool, without dvara) is shown once where it can't be seen or used (off the screen, on the bottom layer, taking no keys) and hidden after its first frame. GTK does most of its one-time work on a window's first frame, not when it's built: the first Super+d took 0.6 s and every later one 10-20 ms; now the first is 19 ms too (headless sway, measured). `[vyom] warm_up = false` turns it off. The warm-up runs one idle step at a time, so a key pressed during it is served first.
- **`Plugin.prewarm()`**, optional: a tool fills the caches its first opening would wait for (dvara: its app list and icons), once, while Vyom is idle after it starts. `ui.warm_icons(icons, sizes)` loads Gio.Icons into GTK's icon cache at the sizes a panel draws them.
- **Apps a panel opens get their own systemd scope** (`app-vyom-<name>-<pid>.scope` in `app.slice`, like a desktop shell's). `util.spawn` and the new `util.adopt(pid, name)` move the process there. Before, an app opened from a panel lived in `vyom.service`: its memory counted as Vyom's (1.2 GB with a browser open), and stopping or restarting Vyom killed it.
- The log says how long building the panels and the warm-up took, and how long a panel took to its first frame (info when over 150 ms, else debug), so a slow opening shows in `journalctl --user -u vyom`.

## v0.7.3 -- 2026-11-09

- **A card panel is one piece of glass** (power menu, quick settings, battery). GTK's theme filled anything called `.card` with its solid `card_bg_color`, so the body was an opaque slate box above a see-through footer. Inside a panel a card has no fill now, and a card panel wears the footer's dark tint all over (`layout-card`), the footer only a line above it.

## v0.7.2 -- 2026-11-09

- **In a grid, `Ctrl+H` / `Ctrl+L` move left / right** (as `Ctrl+J` / `Ctrl+K` move down / up), in insert and normal mode: in bhava's emoji grid they switched the category instead. Tabs stay on `H` / `L` and `Tab`; list and card panels keep `Ctrl+H` / `Ctrl+L` for tabs.

## v0.7.1 -- 2026-11-09

- **The footer never widens a card.** The key hints reported their full width as the footer's natural width, so a card grew to fit every hint (kendra was about 700 px wide for 420 asked). They now ask for no width: the card's own width decides, and hints that don't fit are left out whole, as promised. The footer's gaps are 12 px (were 16), so a little more fits.

## v0.7.0 -- 2026-11-09

- **Core does what tools did themselves:** `Space u p` shows or hides the preview (each tool remembers it); a modal card marks the focused control (`vk-cursor`, an accent ring), since GTK's focus ring doesn't show in a layer-shell panel; `Plugin.build_rail()` gives a side rail a slot (`tabs_in_rail` hides the top tab bar). smriti, bhava, mudra, akashvani, patra, urja and vishram drop their own copies.
- **The footer never widens the panel:** the tool's keys are clipped instead, a status message takes their place while it shows, and core's passing notes clear themselves after a few seconds (`set_status(…, clear_after=)`). On a small card the which-key strip, help and palette fit the card's width.
- **Keys typed before the results arrive wait for them:** `4j` typed the moment a panel opens (or while a search runs) moves once the list is there, instead of nothing.
- `keys.py` 1.0.2: Ctrl+`<` and Ctrl+`>` (`<C-<>`, `<C->>`) are one key each; before, they split into five and a bare `<` could wait forever behind them.
- `Plugin.wants_all_keys()`: while a tool says it's busy (vishram's countdown), core drops a half-typed key, an open palette, help or confirm, and gives the next key to the tool's `key()` first, so any key can cancel.
- The palette keeps one height while you filter (6 rows on a small card, 10 elsewhere, with "1–6 of 20" when there are more), so it never spills over a card's footer.
- Footer keys never cut a hint in half: the ones that don't fit are left out whole, from the end (urja's "h / l change", kendra's "Enter toggle" were clipped mid-word).
- `keys.py` 1.0.1: a bare `<` is its own key (it used to wait forever, read as the start of `<CR>`); only real key names in angle brackets are one token. `vendor-keys.sh --help` prints usage instead of writing a file named `--help`.
- **Vim keys, for every tool that wants them** ([ADR 8](docs/adr/0008-vim-keys-in-the-panel.md)).
  A tool sets `modal = True` and declares its keys as data (`keys(tab)` returning
  `vyom.keys.Bind`s); the panel gives it NORMAL and INSERT modes, counts (`5j`),
  sequences (`gg`, `dd`), `Space` as the leader with a which-key strip, `?` help, a
  `Space Space` palette of every action, a `y`-only `confirm()`, a mode pill in the
  footer, and a cursor for cards (`j`/`k` between controls, `h`/`l` a slider,
  `Enter` toggles). The same core keys in every such tool: `j`/`k`, `gg`/`G`,
  `Ctrl+d`/`Ctrl+u`, `H`/`L` tabs, `/`, `i`, `q`, `Esc`, `Space t`, `Space u f`
  fullscreen, `Space r`. Space groups keep one meaning across tools (`y` copy,
  `d` delete, `o` open outside…). Tools that don't opt in keep their keys exactly.
- **`vyom/keys.py`**: the keys engine in pure Python (no GTK), so Vayu's other Python
  tools share it; `scripts/vendor-keys.sh` copies it into one with a version and hash
  header (`--check` finds a stale copy). Tests: `python3 -m unittest discover tests`.
- **Space never presses a focused button on a card**, in any tool: GTK's default
  made Space in the power menu lock the screen. `Enter` does.
- `set_status(text, kind)`: `"ok"` or `"bad"` colours the message. New optional hooks:
  `keys`, `editables`, `insert_target`, `escape`, `mode_changed`, `mode_hints`,
  `keys_to_widget`, `confirm`, `vim_mode`, `set_vim_mode`.
- README: tabs are shown by name (no number since v0.6.3), as it now says.
- Fixed before release: `Tab` / `Shift+Tab` in a modal card's INSERT mode switch tabs (as `Ctrl+H` / `Ctrl+L` do), instead of taking the focus out of the box, after which typing went nowhere (ganit).
- Fixed before release: `Shift+Enter` / `Ctrl+Enter` typed before the results arrive wait for them, like `Enter`, so they never act on the row that was there a moment ago.
- Fixed before release: the `Space Space` palette resizes as it fills or filters (its rows spilled out of its frame on a big card).
- Fixed before release: a rebuilt card's text box always gets its click-to-type (a freed box's `id()` could be reused, and the new box was skipped).

## v0.6.3 -- 2026-11-08

- **Tabs show just their name**, no number before it. `Ctrl+1..9` still switches to the
  first to the ninth, and each tab's tooltip says which key it is.

## v0.6.2 -- 2026-11-08

- **The footer's keys can follow the tab** (or a mode): a tool returns them from
  `tab_hints()` and the panel redraws them on every tab switch
  (`self.panel.refresh_hints()` any other time). tarang and bhava drop their own footer
  rewiring.
- **A status message has room.** While `set_status()` shows one, it takes the place of
  the tool's key hints (Tab, F11 and Esc stay), so "Ctrl+Backspace again removes it ·
  Esc keeps it" is no longer cut to a few letters; its tooltip has the whole text.
- **`ui.switch()` doesn't warn in a header.** It hides GTK's two tiny on/off images
  (they logged a baselines warning), can't take focus, takes a tooltip, and keeps its
  handler as `.handler` for setting the state from code.

## v0.6.1 -- 2026-11-07

- Sliders and progress bars no longer log "GtkGizmo reported min width -2" (GTK's -1px
  margin, left over once their border is gone).
- Row titles keep the text colour without a theme (they could render black).

## v0.6.0 -- 2026-11-07

- **One look for every tool.** The selected row has a 2px accent frame and a bar on its
  left edge, easy to see even on a dim screen; rows are taller with larger text; chips
  have an outline in their colour; the current tab is underlined in the accent.
- **A status strip** (`build_strip()`) above a tool's list: what's connected, what's
  playing, what needs you, before you read the list.
- **Rows can carry coloured chips and signal bars with a word** (`chips`, `level`,
  `level_text`, `level_color`); sections can show a count and a note.
- **Shared building blocks** in `vyom.ui`: `hero`, `ring`, `bars`, `meter`, `steps`,
  `notice`, `segmented`, `section`, `soft`, `chips`, `keycap`, and buttons that show their
  key. Drawn widgets take the theme's colours. ADR 0007.

## v0.5.0 -- 2026-11-06

- **F11 makes any tool fullscreen**, and again back; each tool remembers it for next time. A small gap is left at the screen's edges, so the corners stay round.
- **Tab switches a tool's own tabs**, its main kinds (ganit's Calculate and Convert,
  tarang's Networks and Hotspot), like Ctrl+1..9 and Ctrl+H/L, in every tool and every
  layout. Tab no longer jumps to another Vyom tool, and `[vyom] cycle` is gone. In a
  tool without tabs, Tab does nothing in a list and moves between controls in a card.
- **Card tools can have tabs** (`tabs` on the plugin, `self.panel.rebuild_card()` in
  `tab_changed`), shown at the top right like a list's; ganit 0.3.0 uses them.
- Every corner is rounded: the website's callouts.
- A logo and a shloka at the top of the README and the website: every Vayu tool has them now.

## v0.4.2 -- 2026-11-02

- **Tools could silently lose what lives in `~/.local/bin`.** A user service's
  PATH often lacks it, so a tool that looks there found nothing: mudra showed
  only Sway's keys. Vyom now adds it to its own PATH when it starts.

## v0.4.1 -- 2026-10-24

- **Quick settings (and any card panel) came up empty after a reload.**
  `vyom reload` (which a theme change runs) rebuilds the panels, but a
  plugin that keeps its card, like kendra, handed back a card still inside
  the old panel; GTK refused to move it ("gtk_box_append: assertion …
  failed") and the new panel opened empty. A panel now lets go of its card
  before it's destroyed, and takes the card from wherever it still is.

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
