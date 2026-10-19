"""The plugin API. Every Vyom tool (dvara, ganit, smriti, tarang...) is its
own repository containing one Python package with a `Plugin` class that
subclasses `vyom.Plugin`, plus a `plugin.toml`:

    name = "ganit"
    title = "Calculator"
    description = "..."
    version = "0.1.0"
    vyom = "0.2"          # minimum Vyom version
    requires = ["qalc"]   # tools it needs (it's skipped, with a reason, without them)

Plugins are found in $XDG_DATA_HOME/vyom/plugins/<name>/ (a clone of the
plugin's repo) and in every directory of $VYOM_PLUGIN_PATH.

Layouts:
  "list"  a search box over rows (optionally a preview pane on the right)
  "grid"  a search box over a grid of cells (emoji)
  "card"  the plugin builds the whole content (battery, power menu, dialogs)

The panel calls search() in a worker thread (never touch widgets there)
and everything else on the GTK main loop. Long work in activate() goes
through self.background(work, then).
"""
from dataclasses import dataclass
from typing import Any


@dataclass
class Row:
    title: str
    subtitle: str = ""
    icon: Any = ""              # a Nerd Font glyph, a Gio.Icon, or an image path
    color: str = "mauve"        # tile color: sky blue teal red peach mauve yellow green rose lavender
    meta: str = ""              # right-aligned text (a shortcut, a size, an age)
    data: Any = None            # anything the plugin wants back in activate()
    markup: bool = False        # title/subtitle use Pango markup
    dim: bool = False           # greyed out (e.g. a stopped container)
    badge: str = ""             # a small colored chip after the title
    badge_color: str = ""


@dataclass
class Section:
    title: str


@dataclass
class Hint:
    keys: str
    what: str


class Plugin:
    # identity (plugin.toml gives defaults; a class attribute wins)
    name = ""
    title = ""
    icon = ""                   # Nerd Font glyph for the mode pill
    color = "mauve"

    layout = "list"             # list | grid | card
    placeholder = "Search…"
    width = 720                 # only for an anchored panel (see anchor); every centered
    height = 480                # panel is [vyom] width x height, so they all match
    preview = False             # a preview pane on the right
    preview_width = 300
    grid_columns = 8            # grid layout
    live = 0                    # seconds: re-run search() this often while open
    debounce = 40               # ms between a keystroke and search()
    keep_query = False          # keep the typed text between openings
    hints = []                  # Hint(keys, what) for the footer

    def __init__(self, vyom, conf):
        self.vyom = vyom         # the application (self.vyom.close(), .open(name))
        self.conf = conf or {}   # [plugin.<name>] from ~/.config/vyom/config.toml
        self.panel = None        # set by the panel
        self.args = []

    # ---- lifecycle
    def available(self):
        """(ok, reason). Checked once at load; requires in plugin.toml are
        checked before this."""
        return True, ""

    def opened(self, args):
        """The panel is about to show (args: from `vyom <name> ...`)."""
        self.args = args

    def closed(self):
        pass

    # ---- list / grid
    def search(self, query):
        """Rows and Sections for `query`. Runs in a worker thread."""
        return []

    def activate(self, row, mods):
        """Enter on a row. mods: set of "shift", "ctrl", "alt". Return True
        to close the panel."""
        return True

    def build_preview(self, row):
        """A widget for the preview pane (main thread), or None."""
        return None

    def header_extra(self):
        """A widget at the right end of the search bar (a switch, tabs)."""
        return None

    def key(self, name, row, mods):
        """Any other key (e.g. "d" with ctrl for Ctrl+D). Return True when
        handled."""
        return False

    # ---- card
    def build_card(self):
        """The whole content for layout = "card" (main thread)."""
        return None

    # ---- helpers for plugins
    def refresh(self):
        """Re-run search() with the current text (call from anywhere)."""
        if self.panel:
            self.panel.refresh_soon()

    def background(self, work, then=None):
        if self.panel:
            self.panel.background(work, then)

    def close(self):
        self.vyom.close_all()

    def set_status(self, text):
        """A line of status in the footer (e.g. "connecting…")."""
        if self.panel:
            self.panel.set_status(text)
