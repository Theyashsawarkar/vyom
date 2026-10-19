<p align="center">
  <b>Vyom</b> (व्योम, "sky": the space everything sits in)<br>
  Beautiful, keyboard-driven panels for wlroots desktops (sway, Hyprland, river…).<br>
  The runtime behind <a href="https://github.com/Theyashsawarkar/vayu">Vayu</a>'s launcher and system panels; works on its own.
</p>

Vyom replaces wofi in Vayu. Instead of scripts piping text rows into a
generic list, each job is a **tool**: a small plugin with real layouts,
live data, previews, toggles and a key for everything. Vyom is what they
run in: one resident process with a shared panel, theme and plugin API, so
every tool opens instantly and looks the same.

**Each tool is its own repository**, so you install only the ones you want:

| Tool | | What it does |
|---|---|---|
| [dvara](https://github.com/Theyashsawarkar/dvara) | द्वार, gateway | app launcher: frequent apps first, app actions, open windows |
| [ganit](https://github.com/Theyashsawarkar/ganit) | गणित, mathematics | calculator: answers as you type, units, currency, history |
| [smriti](https://github.com/Theyashsawarkar/smriti) | स्मृति, memory | clipboard history: links, images, code told apart; pins |
| [bhava](https://github.com/Theyashsawarkar/bhava) | भाव, feeling | emoji: a grid, recents, skin tones; types it for you |
| [tarang](https://github.com/Theyashsawarkar/tarang) | तरंग, wave | Wi‑Fi with live signal, inline passwords, and the hotspot |
| [setu](https://github.com/Theyashsawarkar/setu) | सेतु, bridge | Bluetooth: devices with battery, discovery, pairing |
| [doot](https://github.com/Theyashsawarkar/doot) | दूत, messenger | your phone (KDE Connect): battery, send files, ring, browse |
| [patra](https://github.com/Theyashsawarkar/patra) | पात्र, vessel | Docker: containers by project, live CPU/memory, logs |
| [suchana](https://github.com/Theyashsawarkar/suchana) | सूचना, notice | notifications: on screen with actions, history, do not disturb |
| [raga](https://github.com/Theyashsawarkar/raga) | राग, melody | YouTube music (into MPD) and video (mpv) |
| [mudra](https://github.com/Theyashsawarkar/mudra) | मुद्रा, gesture | keybinding search by what it does; Enter runs it |
| [urja](https://github.com/Theyashsawarkar/urja) | ऊर्जा, energy | battery: charge, time left, health, power profile |
| [vishram](https://github.com/Theyashsawarkar/vishram) | विश्राम, rest | power menu: one letter each, countdown with cancel |
| [kendra](https://github.com/Theyashsawarkar/kendra) | केन्द्र, centre | quick settings: toggles, sliders, battery, lock, power |

## Install

Requirements: Python 3.11+, PyGObject (with pycairo, for tools that draw), GTK 4, [gtk4-layer-shell](https://github.com/wmww/gtk4-layer-shell),
a compositor with the layer-shell protocol (sway, Hyprland, river, Wayfire,
labwc…), and a [Nerd Font](https://www.nerdfonts.com) for the icons.

```sh
# Arch
sudo pacman -S --needed python-gobject python-cairo gtk4 gtk4-layer-shell ttf-jetbrains-mono-nerd

git clone https://github.com/Theyashsawarkar/vyom ~/.local/share/vyom/core
ln -s ~/.local/share/vyom/core/bin/vyom ~/.local/bin/vyom

# then the tools you want, e.g.
git clone https://github.com/Theyashsawarkar/dvara ~/.local/share/vyom/plugins/dvara
git clone https://github.com/Theyashsawarkar/ganit ~/.local/share/vyom/plugins/ganit
```

In your compositor (sway shown):

```sh
exec vyom daemon                      # start it in the background at login
bindsym $mod+d exec vyom dvara        # each tool on its own key; again closes it
bindsym $mod+c exec vyom ganit
layer_effects "vyom" {                # SwayFX: blurred glass behind every panel
    blur enable
    corner_radius 20
    shadows enable
}
```

## Usage

```
vyom <tool> [args]        open a tool (e.g. vyom tarang, vyom raga video); again closes it
vyom dmenu [-p PROMPT] [--markup] < lines
                          pick one line: printed on stdout, exit 1 on Esc (like wofi --dmenu)
vyom list                 installed tools, and why one is skipped
vyom daemon | reload | quit
vyom quick                quick settings (the kendra tool)
```

Vyom keeps one resident process (a GTK single-instance app). Once it's
running, `vyom <tool>` only sends it a D-Bus message, so a panel opens in
well under a tenth of a second. `vyom dmenu` makes any script's picker a
Vyom panel: `printf 'Accept\nReject\n' | vyom dmenu -p "Pair?"`.

Every panel: type to search, `Up`/`Down` (or `Ctrl+K`/`Ctrl+J`) move,
`Page Up`/`Page Down` jump, `Enter` runs, `Tab` switches to the next tool,
`Esc` closes. Each tool adds its own keys (shown in its footer and README).

## Configuration

`~/.config/vyom/config.toml`, all optional ([`examples/config.toml`](examples/config.toml)):

```toml
[vyom]
disabled = ["raga"]          # installed tools not to load
cycle = ["dvara", "ganit"]   # Tab order

[plugin.tarang]              # each tool's settings: see its README
hotspot_command = "vayu-hotspot"
```

`~/.config/vyom/style.css` loads last, to restyle anything.

## Writing a tool

A tool is a directory with a `plugin.toml` and a Python package of the
same name exporting a `Plugin` class:

```toml
# plugin.toml
name = "hello"
title = "Hello"
version = "0.1.0"
vyom = "0.2"
icon = "󰞅"          # Nerd Font glyph for the mode pill
color = "mauve"     # sky blue teal red peach mauve yellow green rose lavender
requires = []       # tools it needs; it's skipped (with the reason) without them
```

```python
# hello/__init__.py
from vyom import Hint, Plugin as Base, Row, Section, ui, util

class Plugin(Base):
    preview = True                       # a preview pane on the right
    hints = [Hint("↵", "greet")]

    def search(self, query):             # runs in a worker thread
        return [Section("People"), Row("World", "the usual", icon="󰞅", data="world")]

    def build_preview(self, row):        # main thread
        return ui.vbox(ui.title(f"Hello, {row.title}"), ui.meta("a preview"))

    def activate(self, row, mods):       # Enter; return True to close
        util.notify("Hello", row.data)
        return True
```

Layouts: `"list"` (rows, sections, preview), `"grid"` (cells, like the
emoji picker) and `"card"` (build the whole panel in `build_card()`). See
`vyom/plugin.py` for every hook (`header_extra`, `key`, `opened`,
`closed`, `live`, `anchor`…), `vyom/ui.py` for widgets, and any tool repo
for a worked example. Put it in `~/.local/share/vyom/plugins/hello` (or a
directory in `$VYOM_PLUGIN_PATH`) and `vyom reload`.

## License

MIT
