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
    chips: Any = None           # [(text, color)] or [text]: chips at the right ("Open", "5 GHz")
    level: int = -1             # 0..4 signal bars at the right (-1: none)
    level_text: str = ""        # the level in a word ("Good"), next to the bars
    level_color: str = ""       # green / yellow / red: what the level means


@dataclass
class Section:
    title: str
    count: Any = ""             # shown quietly after the title ("Saved 2")
    note: str = ""              # right-aligned ("strongest first", "Enter connects")


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
    width = 720                 # only for a card or an anchored panel; every list/grid
    height = 480                # panel is [vyom] width x height, so they all match
    preview = False             # a preview pane on the right
    preview_width = 300
    grid_columns = 8            # grid layout
    live = 0                    # seconds: re-run search() this often while open
    debounce = 40               # ms between a keystroke and search()
    keep_query = False          # keep the typed text between openings
    hints = []                  # Hint(keys, what) for the footer (tab_hints() per tab)
    # Tabs: [(key, label)] or [(key, label, tooltip)], a tool's main kinds. The
    # panel draws them in the top bar (a card too) and switches them with Tab /
    # Shift+Tab, Ctrl+H / Ctrl+L and Ctrl+1..9, Ctrl+0 (by number), the same in
    # every tool. `tab` is the current key; tab_changed() runs on a switch (a
    # card's: call self.panel.rebuild_card()).
    tabs = []
    tab = ""
    tab_class = "tab"           # css class of the tab buttons (bhava: glyphs)
    tabs_in_rail = False        # build_rail() shows the tabs: the top bar's tab buttons hide
    # Vim keys (ADR 0008), opt-in: NORMAL / INSERT modes, counts, Space as
    # the leader, ? help, Space Space palette. The tool's keys are data:
    # keys(tab) returns vyom.keys.Bind objects; a Bind's action is a string
    # "verb:arg" (the panel calls self.v_<verb>(count, arg), or its own
    # c_<verb>: close, help, palette, fullscreen, refresh, tab, insert,
    # normal, search, down, up, top, bottom, activate, focus, adjust, press,
    # moved, nop) or a callable(count, arg).
    modal = False
    start_mode = "normal"       # "insert" for search-first tools, or {tab: mode}; [plugin.x] start_mode overrides
    vim_counts = True           # digits are counts (5j); an exact digit bind still wins
    card_cursor = True          # a card's j/k/h/l/Enter move and press its controls
    key_groups = {}             # {" c": "container"}: names for the tool's own Space groups
    insert_hints = [Hint("Esc", "normal mode")]

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

    def build_strip(self):
        """The status strip above the list (main thread), or None: what's
        going on before the list (tarang: the network you're on). Rebuilt
        after every search, or now with self.panel.refresh_strip()."""
        return None

    def header_extra(self):
        """A widget at the right end of the search bar (a switch, tabs)."""
        return None

    def build_rail(self):
        """A side rail left of the results (bhava's categories), built once per
        panel; list and grid layouts. None: no rail."""
        return None

    def key(self, name, row, mods):
        """Any other key (e.g. "d" with ctrl for Ctrl+D). Return True when
        handled."""
        return False

    # ---- tabs
    def tab_changed(self, key):
        """The user switched to tab `key` (self.tab is already set)."""
        self.refresh()

    def select_tab(self, key):
        """Switch to a tab from the tool (e.g. `vyom raga video`)."""
        if self.panel and getattr(self.panel, "tab_buttons", None):
            self.panel.select_tab(key)
        elif key != self.tab:
            self.tab = key
            self.tab_changed(key)

    def set_tabs(self, tabs, current=None):
        """Replace the tabs (mudra's depend on what it found)."""
        self.tabs = list(tabs)
        keys = [t[0] for t in self.tabs]
        self.tab = current if current in keys else self.tab if self.tab in keys else (keys[0] if keys else "")
        if self.panel:
            self.panel.build_tabs()

    # ---- vim keys (modal = True)
    def keys(self, tab):
        """[vyom.keys.Bind] for this tab (both modes; Bind.mode says which).
        A bind with the same keys as one of the panel's replaces it."""
        return []

    def editables(self):
        """A card's text boxes: they take typing only in INSERT mode."""
        return []

    def insert_target(self):
        """The box a card's INSERT mode types into."""
        boxes = self.editables()
        return boxes[0] if boxes else None

    def keys_to_widget(self):
        """True while every key should go straight to GTK (a dropdown's open
        list): the panel's keys step aside."""
        return False

    def wants_all_keys(self):
        """True while the tool must see every key first, even in the middle
        of a sequence or a count (vishram's countdown: any key cancels it).
        Core drops what was half-typed and calls key() before anything else."""
        return False

    def mode_changed(self, mode):
        """NORMAL <-> INSERT happened ("normal" / "insert")."""

    def escape(self):
        """Esc in NORMAL mode with nothing pending: return True when the tool
        used it (unpick a line); else the panel clears the search, then closes."""
        return False

    def mode_hints(self, mode):
        """The footer's keys in this mode: tab_hints() in NORMAL, insert_hints
        in INSERT."""
        return self.tab_hints() if mode == "normal" else self.insert_hints

    def vim_mode(self):
        """"normal" or "insert" ("insert" for a tool that isn't modal)."""
        m = getattr(self.panel, "modal", None) if self.panel else None
        return m.mode if m is not None else "insert"

    def set_vim_mode(self, mode):
        m = getattr(self.panel, "modal", None) if self.panel else None
        if m is not None:
            m.set_mode(mode)

    def confirm(self, question, action):
        """Ask before something that can't be undone: y runs action(), any
        other key keeps things as they are. Works in every tool."""
        if self.panel:
            self.panel.vim.confirm(question, action)

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

    def tab_hints(self):
        """The footer's keys for the tab you're on: `hints` unless a tool
        overrides it. The panel redraws them on every tab switch;
        self.panel.refresh_hints() redraws them any other time."""
        return self.hints

    def set_status(self, text, kind=None, clear_after=None):
        """A line of status in the footer (e.g. "connecting…"); kind "ok" or
        "bad" colours it. It takes the footer keys' place while it shows;
        clear_after (seconds) clears a passing note by itself."""
        if self.panel:
            self.panel.set_status(text, kind, clear_after)
