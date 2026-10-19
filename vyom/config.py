"""~/.config/vyom/config.toml (all optional; examples/config.toml has every key)."""
import os
import tomllib

PATH = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "vyom", "config.toml")

DEFAULT_TILES = ["wifi", "bluetooth", "hotspot", "dnd", "caffeine", "theme", "wallpaper", "power-profile"]


def load():
    try:
        with open(PATH, "rb") as f:
            conf = tomllib.load(f)
    except FileNotFoundError:
        conf = {}
    except tomllib.TOMLDecodeError as e:
        print(f"vyom: {PATH}: {e}; using defaults", flush=True)
        conf = {}
    quick = conf.setdefault("quick", {})
    quick.setdefault("tiles", DEFAULT_TILES)
    quick.setdefault("tile", {})
    quick.setdefault("lock", "loginctl lock-session")
    return conf
