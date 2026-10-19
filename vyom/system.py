"""What the quick settings tiles and sliders read and change.

Every tile has a generic built-in (NetworkManager, BlueZ, mako, gsettings,
power-profiles-daemon...) and can be pointed at your own commands in
~/.config/vyom/config.toml instead (see examples/config.toml). A tile
whose tool isn't installed, or whose hardware isn't there (no Bluetooth
controller, no backlight, no battery), simply isn't shown.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import time


def expand(cmd):
    return os.path.expanduser(os.path.expandvars(cmd))


def run(cmd, timeout=4):
    """Runs a command (a string goes through the shell, a list doesn't).
    Returns (exit code, stdout stripped); a missing tool or a timeout is
    (127, "")."""
    try:
        r = subprocess.run(expand(cmd) if isinstance(cmd, str) else cmd, shell=isinstance(cmd, str),
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def spawn(cmd):
    """Starts a command and returns at once (pickers, the power menu)."""
    subprocess.Popen(expand(cmd), shell=True, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def have(tool):
    return shutil.which(expand(tool).split()[0]) is not None


# ------------------------------------------------------------------ tiles
class Tile:
    """A toggle. status() returns (on, subtitle); on is True/False, or None
    for a tile that only does something (no on/off state)."""
    key = title = icon = ""
    color = "mauve"

    def __init__(self, conf=None):
        self.conf = conf or {}
        self.open_cmd = self.conf.get("open")

    def available(self):
        return True

    def status(self):
        return None, ""

    def toggle(self, on):
        pass


class CommandTile(Tile):
    """A tile driven by your own commands (config.toml):
      status   prints the state; on when its output matches on_when (regex)
      toggle   one command for both directions, or on / off for each
      subtitle_on / subtitle_off   what the tile says under its title
    A tile with only `run` is an action (e.g. fetch a new wallpaper)."""

    def __init__(self, key, conf, defaults):
        super().__init__(conf)
        self.key = key
        self.title = conf.get("title", defaults.get("title", key))
        self.icon = conf.get("icon", defaults.get("icon", ""))
        self.color = conf.get("color", defaults.get("color", "mauve"))

    def available(self):
        cmds = [self.conf.get(k) for k in ("status", "toggle", "on", "off", "run") if self.conf.get(k)]
        return bool(cmds) and all(have(c) for c in cmds)

    def status(self):
        if "run" in self.conf and "status" not in self.conf:
            return None, self.conf.get("subtitle", "")
        _, out = run(self.conf["status"])
        on = re.search(self.conf.get("on_when", r"^(on|yes|true|active|enabled|1)$"), out, re.M) is not None
        return on, self.conf.get("subtitle_on" if on else "subtitle_off", "on" if on else "off")

    def toggle(self, on):
        if "run" in self.conf and "status" not in self.conf:
            spawn(self.conf["run"])
        elif "toggle" in self.conf:
            run(self.conf["toggle"], timeout=15)
        else:
            run(self.conf["on" if on else "off"], timeout=15)


class Wifi(Tile):
    key, title, icon, color = "wifi", "Wi‑Fi", "\U000f05a9", "sky"

    def available(self):
        return have("nmcli") and "wifi" in run("nmcli -t -f TYPE device")[1].split()

    def status(self):
        on = run("nmcli radio wifi")[1] == "enabled"
        if not on:
            return False, "off"
        ssid = next((l.split(":", 1)[1] for l in run("nmcli -t -f ACTIVE,SSID device wifi")[1].splitlines()
                     if l.startswith("yes:")), "")
        if ssid:
            return True, ssid
        wired = "ethernet:connected" in run("nmcli -t -f TYPE,STATE device")[1]
        return True, "on · ethernet in use" if wired else "on · not connected"

    def toggle(self, on):
        run(["nmcli", "radio", "wifi", "on" if on else "off"])


class Bluetooth(Tile):
    key, title, icon, color = "bluetooth", "Bluetooth", "\U000f00af", "blue"

    def available(self):
        return have("bluetoothctl") and "Controller" in run("bluetoothctl show")[1]

    def status(self):
        on = "Powered: yes" in run("bluetoothctl show")[1]
        if not on:
            return False, "off"
        names = [l.split(" ", 2)[2] for l in run("bluetoothctl devices Connected")[1].splitlines()
                 if l.startswith("Device ")]
        return True, ", ".join(names) if names else "on"

    def toggle(self, on):
        run(["bluetoothctl", "power", "on" if on else "off"], timeout=8)


class Hotspot(Tile):
    """Through vayu-hotspot (Vayu's hotspot command) or a command of yours
    with the same `status --json` / `on` / `off` interface."""
    key, title, icon, color = "hotspot", "Hotspot", "\U000f0003", "teal"

    def __init__(self, conf=None):
        super().__init__(conf)
        self.cmd = expand(self.conf.get("command", "vayu-hotspot"))

    def available(self):
        return have(self.cmd) or os.access(self.cmd, os.X_OK)

    def status(self):
        rc, out = run([self.cmd, "status", "--json"])
        try:
            st = json.loads(out) if rc == 0 else None
        except ValueError:
            st = None
        if not st:
            return False, "unavailable"
        if st["on"]:
            n = st["client_count"]
            return True, f"{st['ssid']} · {n} connected"
        return False, "off"

    def toggle(self, on):
        run([self.cmd, "on" if on else "off"], timeout=25)


class DoNotDisturb(Tile):
    key, title, icon, color = "dnd", "Do not disturb", "\U000f009b", "red"

    def available(self):
        return have("makoctl")

    def status(self):
        on = "do-not-disturb" in run("makoctl mode")[1].split()
        return on, "notifications held" if on else "off"

    def toggle(self, on):
        run(["makoctl", "mode", "-a" if on else "-r", "do-not-disturb"])


class DarkTheme(Tile):
    key, title, icon, color = "theme", "Dark theme", "\U000f0594", "mauve"
    schema = ["org.gnome.desktop.interface", "color-scheme"]

    def available(self):
        return have("gsettings")

    def status(self):
        on = "dark" in run(["gsettings", "get", *self.schema])[1]
        return on, "on" if on else "light"

    def toggle(self, on):
        run(["gsettings", "set", *self.schema, "prefer-dark" if on else "default"])


class PowerProfile(Tile):
    """Cycles power-saver -> balanced -> performance (those this machine
    offers: performance needs CPU support)."""
    key, title, icon, color = "power-profile", "Power", "\U000f0241", "green"

    def available(self):
        return have("powerprofilesctl") and run("powerprofilesctl get")[0] == 0

    def profiles(self):
        found = re.findall(r"^\s*\*?\s*([a-z-]+):\s*$", run("powerprofilesctl list")[1], re.M)
        order = ["power-saver", "balanced", "performance"]
        return [p for p in order if p in found] or order[:2]

    def status(self):
        p = run("powerprofilesctl get")[1]
        return p != "balanced", p.replace("-", " ").capitalize()

    def toggle(self, on):
        ps, cur = self.profiles(), run("powerprofilesctl get")[1]
        nxt = ps[(ps.index(cur) + 1) % len(ps)] if cur in ps else ps[0]
        run(["powerprofilesctl", "set", nxt])


BUILTIN = {t.key: t for t in (Wifi, Bluetooth, Hotspot, DoNotDisturb, DarkTheme, PowerProfile)}
# Defaults for tiles that only exist through your commands.
COMMAND_DEFAULTS = {
    "caffeine": {"title": "Caffeine", "icon": "\U000f0176", "color": "peach"},
    "wallpaper": {"title": "New wallpaper", "icon": "\U000f02e9", "color": "yellow"},
}


def make_tile(key, conf):
    """A built-in tile, unless config.toml gives it commands: then those
    drive it, keeping the built-in's title, icon and color."""
    if key in BUILTIN and not any(k in conf for k in ("status", "toggle", "on", "off", "run")):
        return BUILTIN[key](conf)
    b = BUILTIN.get(key)
    defaults = {"title": b.title, "icon": b.icon, "color": b.color} if b else COMMAND_DEFAULTS.get(key, {})
    return CommandTile(key, conf, defaults)


# ---------------------------------------------------------------- sliders
class Volume:
    icon, icon_muted = "\U000f057e", "\U000f0581"

    def available(self):
        return have("wpctl") and run("wpctl get-volume @DEFAULT_AUDIO_SINK@")[0] == 0

    def get(self):
        out = run("wpctl get-volume @DEFAULT_AUDIO_SINK@")[1]
        m = re.search(r"([\d.]+)", out)
        return round(float(m.group(1)) * 100) if m else 0, "MUTED" in out

    def set(self, pct):
        run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{pct / 100:.2f}"])

    def toggle_mute(self):
        run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])


class Brightness:
    icon = "\U000f00e0"

    def available(self):
        return have("brightnessctl") and bool(glob.glob("/sys/class/backlight/*"))

    def get(self):
        out = run("brightnessctl -m -c backlight")[1].split(",")
        return (int(out[3].rstrip("%")) if len(out) > 3 else 0), False

    def set(self, pct):
        run(["brightnessctl", "-q", "-c", "backlight", "set", f"{max(pct, 1)}%"])


# ----------------------------------------------------------------- header
def battery():
    """(percent, charging, time left text) of the first battery, or None."""
    for d in sorted(glob.glob("/sys/class/power_supply/*")):
        try:
            if open(f"{d}/type").read().strip() != "Battery":
                continue
            pct = int(open(f"{d}/capacity").read())
            status = open(f"{d}/status").read().strip()
        except (OSError, ValueError):
            continue
        left = ""
        try:
            now = int(open(f"{d}/energy_now").read())
            rate = int(open(f"{d}/power_now").read())
            full = int(open(f"{d}/energy_full").read())
            if rate > 0:
                h = (full - now) / rate if status == "Charging" else now / rate
                left = f"{int(h)} h {int(h % 1 * 60):02d}"
        except (OSError, ValueError):
            pass
        return pct, status in ("Charging", "Full"), left
    return None


def uptime():
    try:
        s = float(open("/proc/uptime").read().split()[0])
    except OSError:
        return ""
    h, m = int(s // 3600), int(s % 3600 // 60)
    return f"up {h} h {m} min" if h else f"up {m} min"


def user_name():
    import pwd
    p = pwd.getpwuid(os.getuid())
    full = p.pw_gecos.split(",")[0].strip()
    return (full.split()[0] if full else p.pw_name).capitalize()


def greeting():
    h = time.localtime().tm_hour
    return "Good morning" if h < 12 else "Good afternoon" if h < 17 else "Good evening"
