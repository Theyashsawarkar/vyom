"""~/.config/vyom/config.toml (all optional; examples/config.toml has every key).

  [vyom]
  disabled = ["raga"]            # plugins not to load
  cycle = ["dvara", "ganit"]     # Tab order between tools
  width = 900                    # every panel's size: all tools open at the same size
  height = 520
  scale = 1.25                   # times this (capped at 90% of the screen)
  opacity = 0.72                 # panel background: 1 solid, lower shows more of the blur

  [plugin.<name>]                # each plugin's own settings (its README)
"""
import os
import tomllib

PATH = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "vyom", "config.toml")


def load():
    try:
        with open(PATH, "rb") as f:
            conf = tomllib.load(f)
    except FileNotFoundError:
        conf = {}
    except tomllib.TOMLDecodeError as e:
        print(f"vyom: {PATH}: {e}; using defaults", flush=True)
        conf = {}
    conf.setdefault("vyom", {})
    conf.setdefault("plugin", {})
    return conf
