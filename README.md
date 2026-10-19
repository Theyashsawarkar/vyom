<p align="center">
  <b>Vyom</b> (व्योम, "sky")<br>
  Beautiful, keyboard-driven system panels for wlroots desktops (sway, Hyprland, river…).<br>
  Part of <a href="https://github.com/Theyashsawarkar/vayu">Vayu</a>; works on its own.
</p>

Vyom is replacing wofi in Vayu: instead of thirteen scripts that pipe text
rows into a generic list, one resident app with real panels: toggles,
sliders, live state, previews and a key for everything. It's being built
in stages; **v0.1 ships quick settings**. The app launcher, calculator,
clipboard, emoji, Wi‑Fi, Bluetooth, phone, Docker, notifications, music,
keybindings, battery and power modes follow (the [design](#roadmap)).

## Quick settings

A panel under the bar's top-right corner:

- **Header:** a greeting, uptime and battery (time to full / left), lock
  and power-menu buttons.
- **Tiles**, two per row, each on/off with what it's doing underneath:
  Wi‑Fi (network name), Bluetooth (connected device), hotspot (devices
  connected), Do not disturb, caffeine, dark theme, new wallpaper, power
  profile. Right click or `Shift+Enter` opens a tile's details (e.g. the
  Wi‑Fi list).
- **Sliders:** volume (click the speaker to mute) and screen brightness.
- Opens instantly with the last state, then refreshes every tile in the
  background, so a slow `bluetoothctl` never delays it.
- Anything your machine doesn't have (no Bluetooth controller, no
  backlight, no battery, no power-profiles-daemon) simply isn't shown.

| Key | Action |
|---|---|
| Arrows | move between tiles and sliders |
| `Enter` / `Space` | toggle the focused tile |
| `Shift+Enter` | open the focused tile's details |
| `Esc` | close (so does running `vyom quick` again) |

## Install

Requirements: Python 3.11+, PyGObject, GTK 4, [gtk4-layer-shell](https://github.com/wmww/gtk4-layer-shell),
and a compositor with the layer-shell protocol (sway, Hyprland, river,
Wayfire, labwc…). The tiles use what's there: NetworkManager (`nmcli`),
BlueZ (`bluetoothctl`), mako (`makoctl`), `gsettings`, `powerprofilesctl`,
WirePlumber (`wpctl`), `brightnessctl`. A [Nerd Font](https://www.nerdfonts.com)
draws the icons.

```sh
# Arch
sudo pacman -S --needed python-gobject gtk4 gtk4-layer-shell ttf-jetbrains-mono-nerd

git clone https://github.com/Theyashsawarkar/vyom ~/.local/share/vyom
ln -s ~/.local/share/vyom/bin/vyom ~/.local/bin/vyom
```

Then in your compositor and bar (sway shown):

```sh
# ~/.config/sway/config
exec vyom daemon                      # start it in the background at login
bindsym $mod+q exec vyom quick        # open / close quick settings
layer_effects "vyom" {                # SwayFX: blurred glass behind it
    blur enable
    corner_radius 20
    shadows enable
}
```

```jsonc
// waybar: a button for it
"custom/quick": { "format": "󰒓", "tooltip-format": "Quick settings", "on-click": "vyom quick" }
```

## Usage

```
vyom quick          open / close quick settings
vyom daemon         start Vyom in the background
vyom reload         re-read ~/.config/vyom/config.toml
vyom quit           stop it
vyom --version
```

Vyom keeps one resident process (a GTK single-instance app). Once it's
running, `vyom quick` only sends it a D-Bus message, so the panel opens in
well under a tenth of a second.

## Configuration

Everything is optional; [`examples/config.toml`](examples/config.toml)
lists every key. The main ones:

```toml
[quick]
tiles = ["wifi", "bluetooth", "hotspot", "dnd", "caffeine", "theme", "wallpaper", "power-profile"]
lock = "swaylock"
power = "wlogout"

[quick.tile.wifi]
open = "nm-connection-editor"          # right click / Shift+Enter

# Drive any tile with your own commands:
[quick.tile.caffeine]
status = "systemctl --user is-active swayidle.service"
on_when = "^inactive$"
on = "systemctl --user stop swayidle.service"
off = "systemctl --user start swayidle.service"
```

## Roadmap

From the [design review](https://github.com/Theyashsawarkar/vayu) (now vs then for every wofi use):

1. **v0.1:** quick settings ✓
2. Apps, calculator, clipboard, emoji (the everyday ones)
3. Wi‑Fi, Bluetooth, phone, Docker, battery (the bar's pickers)
4. Notifications, music & video, keybindings, dialogs, power menu

## License

MIT
