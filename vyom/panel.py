"""The window every plugin shows in: a centered layer-shell panel with a
search bar (mode pill, query, an optional widget), a list or grid of
results, an optional preview pane, and a footer of key hints.

Keys (all panels): type to search, Up/Down (or Ctrl+J/K) move, Page
Up/Down jump, Enter activates, Shift/Ctrl+Enter are a row's other actions
(the plugin says which in its hints), Esc closes. A tool's tabs (its main
kinds: Calculate and Convert, Networks and Hotspot) switch with Tab /
Shift+Tab, Ctrl+1..9 and Ctrl+H / Ctrl+L, the same in every tool.

A tool with `modal = True` has vim keys instead (modal.py, ADR 0008):
NORMAL and INSERT modes, Space as the leader, ? help. Space never presses
a focused button on a card, modal or not.
"""
import logging
import os
import re
import threading

from gi.repository import Gdk, Gio, GLib, Graphene, Gsk, Gtk, Gtk4LayerShell as LayerShell, Pango

from . import util
from .modal import Modal
from .plugin import Row, Section

# keybind: Vyom/every panel | Up / Down | Move to the previous / next result
# keybind: Vyom/every panel | Ctrl+K / Ctrl+J | Move to the previous / next result
# keybind: Vyom/every panel | Page Up / Page Down | Jump a page of results
# keybind: Vyom/every panel | Enter | Open or run the selected result
# keybind: Vyom/every panel | Tab / Shift+Tab | Switch to the next / previous tab (tools with tabs; wraps around)
# keybind: Vyom/every panel | Ctrl+H / Ctrl+L | Switch to the previous / next tab (tools with tabs)
# keybind: Vyom/every panel | Ctrl+1..9 | Switch to the first..ninth tab (Ctrl+0: the tenth; its tooltip says which)
# keybind: Vyom/every panel | F11 | Toggle fullscreen (each tool remembers it)
# keybind: Vyom/every panel | Esc | Close the panel

FULL_GAP = 14   # fullscreen: the gap left at each edge of the screen, in pixels

MODS = {"shift": Gdk.ModifierType.SHIFT_MASK, "ctrl": Gdk.ModifierType.CONTROL_MASK,
        "alt": Gdk.ModifierType.ALT_MASK}


def mods_of(state):
    return {name for name, mask in MODS.items() if state & mask}


def label(text, *classes, markup=False, **kw):
    w = Gtk.Label(**kw)
    if markup:
        w.set_markup(text)
    else:
        w.set_label(text)
    for c in classes:
        w.add_css_class(c)
    return w


def icon_widget(icon, size=18):
    """A Nerd Font glyph, a Gio.Icon, or an image file, as a widget."""
    if isinstance(icon, Gio.Icon):
        img = Gtk.Image.new_from_gicon(icon)
        img.set_pixel_size(size + 10)
        return img
    if isinstance(icon, str) and icon.startswith("/") and os.path.exists(icon):
        pic = Gtk.Picture.new_for_filename(icon)
        pic.set_content_fit(Gtk.ContentFit.COVER)
        pic.set_size_request(size + 14, size + 14)
        return pic
    return label(icon or "", "glyph")


# Key cap colours (Pango can't read CSS colours): the theme's surface0 and
# subtext1, set by the app from the loaded stylesheets (a theme's
# @define-color), Catppuccin Mocha's until then.
KEYCAP = {"bg": "#313244", "fg": "#bac2de", "dim": "#7f849c"}


def set_keycap_colours(css_text):
    """Takes the last @define-color of surface0 / subtext1 / overlay1 in the
    loaded CSS (a theme loads after the defaults, so it wins)."""
    for name, key in (("surface0", "bg"), ("subtext1", "fg"), ("overlay1", "dim")):
        found = re.findall(rf"@define-color\s+{name}\s+(#[0-9a-fA-F]{{6}})\s*;", css_text)
        if found:
            KEYCAP[key] = found[-1]


def keycap_markup(keys):
    """'Ctrl+Enter' as a key cap (Pango), for footers and hints."""
    return (f"<span background='{KEYCAP['bg']}' foreground='{KEYCAP['fg']}' font_family='JetBrainsMono Nerd Font'> "
            + GLib.markup_escape_text(keys) + " </span>")


def hint_label(keys, what):
    """A footer hint: the keys as a key cap, then what they do."""
    return label(f"{keycap_markup(keys)} {GLib.markup_escape_text(what)}", "hint", markup=True)


class HintRow(Gtk.Widget):
    """The footer's keys in a row that never widens the panel and never cuts
    a hint in half: hints that don't fit are left out whole, from the end."""
    __gtype_name__ = "VyomHintRow"

    def __init__(self, spacing=16):
        super().__init__()
        self.spacing = spacing

    def append(self, child):
        child.set_parent(self)

    def remove(self, child):
        child.unparent()

    def kids(self):
        c = self.get_first_child()
        while c is not None:
            yield c
            c = c.get_next_sibling()

    def do_measure(self, orientation, for_size):
        kids = [c for c in self.kids() if c.get_visible()]
        if orientation == Gtk.Orientation.HORIZONTAL:
            nat = sum(c.measure(orientation, -1)[1] for c in kids) + self.spacing * max(0, len(kids) - 1)
            return 0, nat, -1, -1     # minimum 0: the footer gives it what's left
        sizes = [c.measure(orientation, -1) for c in kids] or [(0, 0, -1, -1)]
        return max(m[0] for m in sizes), max(m[1] for m in sizes), -1, -1

    def do_size_allocate(self, width, height, baseline):
        x, fits = 0, True
        for c in self.kids():
            if not c.get_visible():
                continue
            w = c.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            fits = fits and x + w <= width
            c.set_child_visible(fits)
            if fits:
                c.allocate(w, height, -1, Gsk.Transform().translate(Graphene.Point().init(x, 0)))
                x += w + self.spacing

    def do_dispose(self):
        while (c := self.get_first_child()) is not None:
            c.unparent()


def tile(icon, color, size=18, cls="tile"):
    box = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    box.add_css_class(cls)
    box.add_css_class(f"c-{color}")
    w = icon_widget(icon, size)
    w.set_halign(Gtk.Align.CENTER)
    w.set_valign(Gtk.Align.CENTER)
    w.set_hexpand(True)
    box.append(w)
    # The icon's hexpand would otherwise spread to the tile itself, which
    # then takes a share of the row's spare width and drifts right.
    box.set_hexpand(False)
    return box


def row_widget(row):
    box = Gtk.Box(spacing=12)
    box.add_css_class("row")
    if row.dim:
        box.add_css_class("dim")
    box.append(tile(row.icon, row.color))
    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
    title = Gtk.Box(spacing=8)
    t = label(row.title, "row-title", markup=row.markup, xalign=0, ellipsize=Pango.EllipsizeMode.END)
    t.set_hexpand(False)
    title.append(t)
    if row.badge:
        b = label(row.badge, "badge", f"c-{row.badge_color or row.color}")
        b.set_valign(Gtk.Align.CENTER)
        title.append(b)
    text.append(title)
    if row.subtitle:
        text.append(label(row.subtitle, "row-sub", markup=row.markup, xalign=0,
                          ellipsize=Pango.EllipsizeMode.END))
    box.append(text)
    for c in row.chips or ():
        text_, color = (c, "gray") if isinstance(c, str) else (c[0], c[1])
        ch = label(text_, "chip", f"c-{color}", valign=Gtk.Align.CENTER)
        box.append(ch)
    if row.level >= 0:
        from .ui import bars
        lv = Gtk.Box(spacing=7, valign=Gtk.Align.CENTER)
        lv.add_css_class("level")
        lv.add_css_class(f"c-{row.level_color or 'gray'}")
        lv.append(bars(row.level, row.level_color or "gray"))
        if row.level_text:
            lv.append(label(row.level_text, "level-text"))
        box.append(lv)
    if row.meta:
        box.append(label(row.meta, "row-meta", markup=row.markup, valign=Gtk.Align.CENTER))
    return box


class Panel(Gtk.ApplicationWindow):
    def __init__(self, app, plugin):
        super().__init__(application=app, title=f"Vyom {plugin.title}")
        self.app, self.plugin = app, plugin
        plugin.panel = self
        self.add_css_class("vyom")
        LayerShell.init_for_window(self)
        LayerShell.set_namespace(self, "vyom")
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.EXCLUSIVE)
        # Centered, unless the tool anchors itself (kendra: top right, under
        # the bar) or the config gives a distance from the top.
        edges = {"top": LayerShell.Edge.TOP, "right": LayerShell.Edge.RIGHT,
                 "bottom": LayerShell.Edge.BOTTOM, "left": LayerShell.Edge.LEFT}
        anchor = list(getattr(plugin, "anchor", ()) or ())
        margins = dict(getattr(plugin, "margins", {}) or {})
        if plugin.conf.get("top") is not None:
            anchor.append("top")
            margins["top"] = plugin.conf["top"]
        self.anchored = bool(anchor)
        self.edges, self.home_anchor, self.home_margins = edges, anchor, margins
        self.full = False
        self.place()

        self.items = []        # selectable (Row, widget) in order
        self.sel = -1
        self.gen = 0           # search generation: stale results are dropped
        self.pending = None
        self.live_id = None
        self.preview_box = None
        self.preview_scroll = None   # the preview column (Space u p hides it)
        self.strip_holder = None
        self.searching = False   # a search is on its way (keys that move wait for it)
        self.tab_buttons = {}    # tab key -> its button (build_tabs)
        # Vim keys: every panel can ask (confirm) and show overlays; a modal
        # tool's keys all go through it.
        self.vim = Modal(self)
        self.modal = self.vim if plugin.modal else None

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        root.add_css_class("vyom-panel")
        root.add_css_class(f"plugin-{plugin.name}")
        w, h, pw = self.sizes()
        root.set_size_request(w, -1)
        self.root = root

        if plugin.layout == "card":
            if plugin.tabs:   # a card with tabs gets the same tab bar as every tool
                root.append(self.build_card_top())
            self.card_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
            root.append(self.card_holder)
            if plugin.height < 400:   # a small card: the strip grows the panel instead of floating over it
                self.vim.which.set_margin_bottom(8)
                self.vim.which.set_margin_top(4)
                root.append(self.vim.which)
            if self.modal is not None:   # a modal card gets the panel's footer (mode, keys, status)
                root.append(self.build_foot())
        else:
            root.append(self.build_top())
            body = Gtk.Box(vexpand=True)
            body.set_size_request(-1, max(200, h - 110))  # minus the bar and footer
            # The list column: the tool's status strip (build_strip) over the results.
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            self.strip_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.strip_holder.add_css_class("strip-holder")
            column.append(self.strip_holder)
            column.append(self.build_results())
            # A tool's side rail (bhava's categories): Plugin.build_rail().
            rail = plugin.build_rail()
            if rail is not None:
                rail.set_hexpand(False)
                body.append(rail)
            body.append(column)
            if plugin.preview:
                # A fixed-width column: wrapped text in it must not grow it.
                pscroll = Gtk.ScrolledWindow(hexpand=False)
                pscroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
                pscroll.set_propagate_natural_width(False)
                pscroll.set_size_request(pw, -1)
                pscroll.add_css_class("preview")
                self.preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                self.preview_box.add_css_class("preview-inner")
                pscroll.set_child(self.preview_box)
                self.preview_scroll = pscroll
                body.append(pscroll)
            root.append(body)
            root.append(self.build_foot())
        over = Gtk.Overlay()   # the which-key strip, help, palette and confirm float over the panel
        over.set_child(root)
        if self.vim.which.get_parent() is None:
            over.add_overlay(self.vim.which)
        self.set_child(over)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)
        self.connect("close-request", lambda *_: (self.hide_panel(), True)[1])

    # ---------------------------------------------------------- fullscreen
    def place(self):
        """Anchors and margins: the tool's own place, or, fullscreen, every
        edge a small gap from the screen's (the corners stay round)."""
        for e in self.edges.values():
            LayerShell.set_anchor(self, e, False)
            LayerShell.set_margin(self, e, 0)
        if self.full:
            for e in self.edges.values():
                LayerShell.set_anchor(self, e, True)
                LayerShell.set_margin(self, e, FULL_GAP)
            return
        for e in self.home_anchor:
            LayerShell.set_anchor(self, self.edges[e], True)
        for e, px in self.home_margins.items():
            LayerShell.set_margin(self, self.edges[e], int(px))

    def set_full(self, on, save=True):
        if on == self.full:
            return
        self.full = on
        self.place()
        if on:
            self.root.add_css_class("full")
        else:
            self.root.remove_css_class("full")
            self.set_default_size(1, 1)   # back to its own size
        if save:
            state = util.load_state("vyom-fullscreen", {})
            state[self.plugin.name] = on
            util.save_state("vyom-fullscreen", state)

    def set_preview(self, on, save=True):
        """Shows or hides the preview column (Space u p); each tool remembers it."""
        if self.preview_scroll is None:
            return
        self.preview_scroll.set_visible(on)
        if save:
            state = util.load_state("vyom-preview", {})
            state[self.plugin.name] = on
            util.save_state("vyom-preview", state)

    # ------------------------------------------------------------ building
    def sizes(self):
        """(width, height, preview width) times [vyom] scale (default 1.25),
        never more than 90% of the screen. Every centered panel is the same
        size ([vyom] width x height, default 900 x 520), so switching between
        search tools never jumps. A card (power menu, battery, quick
        settings) is a different kind of panel: the tool's own width, as
        tall as its content."""
        conf = self.app.conf.get("vyom", {})
        scale = float(conf.get("scale", 1.25))
        if self.anchored or self.plugin.layout == "card":
            w, h = self.plugin.width, self.plugin.height
        else:
            w, h = float(conf.get("width", 900)), float(conf.get("height", 520))
        w, h = w * scale, h * scale
        try:
            mon = Gdk.Display.get_default().get_monitors().get_item(0).get_geometry()
            w, h = min(w, mon.width * 0.9), min(h, mon.height * 0.9)
        except (AttributeError, TypeError):
            pass
        pw = min(self.plugin.preview_width * scale, w * 0.45)
        return int(w), int(h), int(pw)

    def build_top(self):
        bar = Gtk.Box(spacing=10)
        bar.add_css_class("topbar")
        pill = Gtk.Box(spacing=7)
        pill.add_css_class("mode")
        pill.add_css_class(f"c-{self.plugin.color}")
        pill.append(label(self.plugin.icon, "glyph"))
        pill.append(label(self.plugin.title, "mode-title"))
        bar.append(pill)
        self.entry = Gtk.Text(hexpand=True)
        self.entry.add_css_class("query")
        self.entry.set_placeholder_text(self.plugin.placeholder)
        self.entry.connect("changed", lambda *_: self.refresh_soon())
        bar.append(self.entry)
        self.tab_box = Gtk.Box(spacing=2, valign=Gtk.Align.CENTER)
        self.tab_box.add_css_class("tabs")
        self.tab_buttons = {}
        bar.append(self.tab_box)
        self.build_tabs()
        extra = self.plugin.header_extra()
        if extra is not None:
            bar.append(extra)
        return bar

    def build_card_top(self):
        """A card's top bar: its mode pill and its tabs (no search box)."""
        bar = Gtk.Box(spacing=10)
        bar.add_css_class("topbar")
        pill = Gtk.Box(spacing=7)
        pill.add_css_class("mode")
        pill.add_css_class(f"c-{self.plugin.color}")
        pill.append(label(self.plugin.icon, "glyph"))
        pill.append(label(self.plugin.title, "mode-title"))
        bar.append(pill)
        bar.append(Gtk.Box(hexpand=True))
        self.tab_box = Gtk.Box(spacing=2, valign=Gtk.Align.CENTER)
        self.tab_box.add_css_class("tabs")
        bar.append(self.tab_box)
        self.build_tabs()
        return bar

    def rebuild_card(self):
        """The card again from the plugin (a card's tab switched)."""
        if self.plugin.layout != "card":
            return
        old = self.card_holder.get_first_child()
        if old is not None:
            self.card_holder.remove(old)
        card = self.plugin.build_card()
        if card is not None:
            parent = card.get_parent()
            if parent is not None and parent is not self.card_holder:
                parent.remove(card)
            if card.get_parent() is None:
                self.card_holder.append(card)

    def build_tabs(self):
        """The tool's tabs as toggle buttons (again when set_tabs() changes them)."""
        child = self.tab_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.tab_box.remove(child)
            child = nxt
        self.tab_buttons = {}
        tabs = self.plugin.tabs
        if tabs and self.plugin.tab not in [t[0] for t in tabs]:
            self.plugin.tab = tabs[0][0]
        first = None
        for i, t in enumerate(tabs):
            key, text = t[0], t[1]
            # Just its name: Ctrl+<its place> (1..9, 0 for the tenth) goes
            # there, and the tooltip says which.
            b = Gtk.ToggleButton()
            b.set_child(label(text))
            b.add_css_class(self.plugin.tab_class)
            b.set_can_focus(False)
            n = f"Ctrl+{(i + 1) % 10}" if i < 10 else "Ctrl+H/L"
            b.set_tooltip_text(f"{t[2]} ({n})" if len(t) > 2 and t[2] else n)
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.set_active(key == self.plugin.tab)
            b.connect("toggled", lambda btn, k=key: btn.get_active() and self.on_tab(k))
            self.tab_buttons[key] = b
            self.tab_box.append(b)
        self.tab_box.set_visible(bool(tabs) and not getattr(self.plugin, "tabs_in_rail", False))
        if hasattr(self, "tab_hint"):
            self.tab_hint.set_visible(bool(tabs))

    def on_tab(self, key):
        if key != self.plugin.tab:
            self.plugin.tab = key
            self.plugin.tab_changed(key)
            self.refresh_hints()

    def select_tab(self, key):
        b = self.tab_buttons.get(key)
        if b is not None and not b.get_active():
            b.set_active(True)   # toggled -> on_tab

    def step_tab(self, delta=None, index=None):
        keys = list(self.tab_buttons)
        if not keys:
            return False
        if index is None:
            cur = keys.index(self.plugin.tab) if self.plugin.tab in keys else 0
            index = (cur + delta) % len(keys)
        if 0 <= index < len(keys):
            self.select_tab(keys[index])
        return True

    def build_results(self):
        self.scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.add_css_class("results")
        if self.plugin.layout == "grid":
            self.grid = Gtk.FlowBox(homogeneous=True, valign=Gtk.Align.START)
            self.grid.set_max_children_per_line(self.plugin.grid_columns)
            self.grid.set_min_children_per_line(self.plugin.grid_columns)
            self.grid.set_selection_mode(Gtk.SelectionMode.SINGLE)
            self.grid.add_css_class("grid")
            self.grid.connect("child-activated", lambda _g, c: self.activate(self.index_of(c), set()))
            self.scroll.set_child(self.grid)
        else:
            self.list = Gtk.ListBox()
            self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
            self.list.add_css_class("list")
            self.list.connect("row-activated", lambda _l, r: self.activate(self.index_of(r), set()))
            self.scroll.set_child(self.list)
        self.empty = label("", "empty", vexpand=True, valign=Gtk.Align.CENTER, wrap=True,
                           justify=Gtk.Justification.CENTER)
        overlay = Gtk.Overlay()
        overlay.set_child(self.scroll)
        overlay.add_overlay(self.empty)
        self.empty.set_can_target(False)
        return overlay

    def build_foot(self):
        foot = Gtk.Box(spacing=16)
        foot.add_css_class("foot")
        if self.modal is not None:   # the mode and the keys typed so far (5, Space y…)
            foot.append(self.modal.pill)
            foot.append(self.modal.typed)
        # The tool's keys (Plugin.tab_hints). They never widen the panel and
        # a hint is never cut in half: what doesn't fit is left out whole.
        self.hint_box = HintRow(spacing=16)
        self.hint_box.set_hexpand(True)
        self.hint_box.add_css_class("hint-clip")
        self.hint_clip = self.hint_box
        foot.append(self.hint_box)
        self.refresh_hints()
        self.tab_hint = hint_label("H/L" if self.modal is not None else "Tab", "tabs")
        self.tab_hint.set_visible(bool(self.tab_buttons))
        foot.append(self.tab_hint)
        # max_width_chars keeps its natural width small: a long message is
        # cut with … instead of growing the panel past the screen.
        self.status = label("", "status", hexpand=True, xalign=1,
                            ellipsize=Pango.EllipsizeMode.END, max_width_chars=1)
        self.status.set_visible(False)
        foot.append(self.status)
        if self.modal is not None:
            self.modal_hints = Gtk.Box(spacing=16)
            self.modal_hints.append(hint_label("Space", "leader"))
            self.modal_hints.append(hint_label("?", "keys"))
            self.modal_hints.append(hint_label("Esc", "back"))
            foot.append(self.modal_hints)
        else:
            foot.append(hint_label("F11", "fullscreen"))
            foot.append(hint_label("Esc", "close"))
        return foot

    def refresh_hints(self):
        """Redraws the tool's keys in the footer, for the tab it's on."""
        if not hasattr(self, "hint_box"):
            return
        while (c := self.hint_box.get_first_child()) is not None:
            self.hint_box.remove(c)
        hints = self.modal.hints() if self.modal is not None else self.plugin.tab_hints()
        for h in hints:
            self.hint_box.append(hint_label(h.keys, h.what))
        if self.modal is not None and hasattr(self, "modal_hints"):
            normal = self.modal.mode == "normal"
            self.modal_hints.set_visible(normal)
            self.tab_hint.set_visible(normal and bool(self.tab_buttons))

    # ------------------------------------------------------------- showing
    def release_card(self):
        """Lets go of the plugin's card (before this panel is destroyed), so
        the plugin can show the same card in the next panel."""
        holder = getattr(self, "card_holder", None)
        child = holder.get_first_child() if holder is not None else None
        if child is not None:
            holder.remove(child)

    def show_panel(self, args):
        self.set_full(bool(util.load_state("vyom-fullscreen", {}).get(self.plugin.name)), save=False)
        self.set_preview(bool(util.load_state("vyom-preview", {}).get(self.plugin.name, True)), save=False)
        self.plugin.opened(args)
        self.refresh_hints()
        if self.plugin.layout == "card":
            old = self.card_holder.get_first_child()
            if old is not None:
                self.card_holder.remove(old)
            card = self.plugin.build_card()
            if card is not None:
                # A plugin may keep its card between openings; after a reload
                # it's still in the old (destroyed) panel: take it from there.
                parent = card.get_parent()
                if parent is not None and parent is not self.card_holder:
                    parent.remove(card)
                if card.get_parent() is None:
                    self.card_holder.append(card)
            self.vim.machine.reset()
            self.vim.over = None
            self.vim.draw()
            if self.modal is not None:
                self.set_status("")
                self.modal.opened()
            self.present()
            return
        if not self.plugin.keep_query:
            self.entry.set_text("")
        self.set_status("")
        self.vim.machine.reset()
        self.vim.over = None
        self.vim.draw()
        if self.modal is not None:
            self.modal.opened()
        self.present()
        self.entry.grab_focus()
        self.refresh_now()
        if self.plugin.live and self.live_id is None:
            self.live_id = GLib.timeout_add_seconds(self.plugin.live, self._live_tick)

    def _live_tick(self):
        if not self.get_visible():
            self.live_id = None
            return False
        self.refresh_now(keep_selection=True)
        return True

    def hide_panel(self):
        if self.get_visible():
            self.hide()
            self.plugin.closed()

    # ------------------------------------------------------------ searching
    def query(self):
        return self.entry.get_text() if self.plugin.layout != "card" else ""

    def refresh_soon(self):
        if self.plugin.layout == "card":
            return
        self.searching = True
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(self.plugin.debounce, self._fire)

    def _fire(self):
        self.pending = None
        self.refresh_now()
        return False

    def refresh_now(self, keep_selection=False):
        if self.plugin.layout == "card":
            return
        self.gen += 1
        self.searching = True
        gen, q = self.gen, self.query()
        keep = self.selected_row() if keep_selection else None

        def work():
            try:
                res = self.plugin.search(q)
            except Exception as e:  # a plugin bug shouldn't kill the panel
                logging.getLogger(f"vyom.{self.plugin.name}").exception("search(%r) failed", q)
                res = [Row(f"{self.plugin.name}: {e}", icon="", color="red")]
            GLib.idle_add(self.show_results, gen, res, keep)
        threading.Thread(target=work, daemon=True).start()

    def show_results(self, gen, results, keep=None):
        if gen != self.gen:
            return False  # a newer search is on its way
        container = self.grid if self.plugin.layout == "grid" else self.list
        child = container.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            container.remove(child)
            child = nxt
        self.items = []
        for r in results[:400]:
            if isinstance(r, Section):
                if self.plugin.layout == "grid":
                    continue
                w = Gtk.Box(spacing=8)
                w.add_css_class("section")
                w.append(label(r.title.upper(), "section-title", xalign=0))
                if r.count != "":
                    w.append(label(str(r.count), "section-count"))
                if r.note:
                    w.append(label(r.note, "section-note", hexpand=True, xalign=1))
                lr = Gtk.ListBoxRow(selectable=False, activatable=False)
                lr.set_child(w)
                lr.add_css_class("section-row")
                self.list.append(lr)
                continue
            if self.plugin.layout == "grid":
                cell = label(r.title, "cell")
                cell.set_tooltip_text(r.subtitle or None)
                self.grid.append(cell)
                w = cell.get_parent()
            else:
                w = Gtk.ListBoxRow()
                w.set_child(row_widget(r))
                self.list.append(w)
            self.items.append((r, w))
        self.empty.set_label("" if self.items else getattr(self.plugin, "empty_text", "Nothing found"))
        self.refresh_strip()
        idx = 0
        if keep is not None:
            idx = next((i for i, (r, _) in enumerate(self.items)
                        if r.title == keep.title and r.subtitle == keep.subtitle), 0)
        self.select(idx if self.items else -1)
        if self.pending is None:   # no newer search waiting: moves typed meanwhile run now
            self.searching = False
            if self.modal is not None:
                self.modal.flush()
        return False

    # ------------------------------------------------------------ selection
    def index_of(self, widget):
        return next((i for i, (_, w) in enumerate(self.items) if w is widget), -1)

    def selected_row(self):
        return self.items[self.sel][0] if 0 <= self.sel < len(self.items) else None

    def select(self, i):
        if not self.items:
            self.sel = -1
            self.update_preview()
            return
        i = max(0, min(i, len(self.items) - 1))
        self.sel = i
        w = self.items[i][1]
        if self.plugin.layout == "grid":
            self.grid.select_child(w)
        else:
            self.list.select_row(w)
        GLib.idle_add(self.scroll_to, w)
        self.update_preview()

    def scroll_to(self, w):
        adj = self.scroll.get_vadjustment()
        # Relative to the list itself (its full height), not the scroll's
        # direct child: GTK wraps the list in a Viewport, which is only the
        # visible part, so rows past it measured as "visible" and selection
        # walked off the bottom without scrolling.
        content = self.grid if self.plugin.layout == "grid" else self.list
        res = w.translate_coordinates(content, 0, 0)
        if not res or (len(res) == 3 and not res[0]):
            return False
        y = res[-1]  # (x, y), or (ok, x, y) in older PyGObject
        h = w.get_height()
        top, page = adj.get_value(), adj.get_page_size()
        if y < top:
            adj.set_value(y)
        elif y + h > top + page:
            adj.set_value(y + h - page)
        return False

    def move(self, delta):
        if self.items:
            self.select(self.sel + delta)

    def update_preview(self):
        if self.preview_box is None:
            return
        old = self.preview_box.get_first_child()
        while old is not None:
            nxt = old.get_next_sibling()
            self.preview_box.remove(old)
            old = nxt
        row = self.selected_row()
        w = self.plugin.build_preview(row) if row is not None else None
        if w is not None:
            self.preview_box.append(w)

    def refresh_strip(self):
        """The tool's status strip again (Plugin.build_strip), above the list."""
        if self.strip_holder is None:
            return
        old = self.strip_holder.get_first_child()
        while old is not None:
            nxt = old.get_next_sibling()
            self.strip_holder.remove(old)
            old = nxt
        w = self.plugin.build_strip()
        self.strip_holder.set_visible(w is not None)
        if w is not None:
            self.strip_holder.append(w)

    def update_preview_soon(self):
        GLib.idle_add(lambda: (self.update_preview(), False)[1])

    # ------------------------------------------------------------- actions
    def activate(self, i, mods):
        if not (0 <= i < len(self.items)):
            return
        self.sel = i
        if self.plugin.activate(self.items[i][0], mods):
            self.app.close_all()

    def on_key(self, _ctl, keyval, _code, state):
        name = Gdk.keyval_name(keyval) or ""
        mods = mods_of(state)
        if self.modal is not None:
            return self.modal.key(name, mods)
        if self.vim.over == "confirm" and not name.startswith(("Shift", "Control", "Alt", "Super")):
            return self.vim.key(name, mods)   # a question (Plugin.confirm): y or not
        # The tool first (e.g. Esc cancels tarang's password prompt).
        row = self.selected_row() if self.plugin.layout != "card" else None
        if self.plugin.key(name, row, mods):
            return True
        # Space never presses a focused button on a card (GTK's default would:
        # the power menu's focused Lock locked the screen). Enter does.
        if self.plugin.layout == "card" and keyval == Gdk.KEY_space and not isinstance(self.get_focus(), Gtk.Editable):
            return True
        if keyval == Gdk.KEY_Escape:
            self.app.close_all()
            return True
        if keyval == Gdk.KEY_F11 and not mods:
            self.set_full(not self.full)
            return True
        # A tool's tabs, in every layout: Tab / Shift+Tab (Shift+Tab can arrive
        # as ISO_Left_Tab, with or without the shift flag), Ctrl+H / Ctrl+L and
        # Ctrl+1..9. A card without tabs keeps Tab for moving between its controls.
        if self.tab_buttons:
            if name in ("Tab", "ISO_Left_Tab") and mods <= {"shift", "ctrl"}:
                back = name == "ISO_Left_Tab" or "shift" in mods
                return self.step_tab(delta=-1 if back else 1)
            if mods == {"ctrl"}:
                if name in ("h", "l"):
                    return self.step_tab(delta=-1 if name == "h" else 1)
                if len(name) == 1 and name.isdigit():
                    return self.step_tab(index=(int(name) - 1) % 10)
        if self.plugin.layout == "card":
            return False
        cols = self.plugin.grid_columns if self.plugin.layout == "grid" else 1
        if keyval in (Gdk.KEY_Down,) or (name == "j" and "ctrl" in mods):
            self.move(cols)
        elif keyval in (Gdk.KEY_Up,) or (name == "k" and "ctrl" in mods):
            self.move(-cols)
        elif self.plugin.layout == "grid" and keyval in (Gdk.KEY_Right, Gdk.KEY_Left) and not self.query_has_caret_use():
            self.move(1 if keyval == Gdk.KEY_Right else -1)
        elif keyval == Gdk.KEY_Page_Down:
            self.move(8 * cols)
        elif keyval == Gdk.KEY_Page_Up:
            self.move(-8 * cols)
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.activate(self.sel, mods)
        elif keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            pass   # no tabs here: Tab does nothing (it doesn't leave the search box)
        else:
            return False
        return True

    def query_has_caret_use(self):
        """In the grid, Left/Right move between cells unless you're
        editing text in the middle of the query."""
        pos = self.entry.get_position()
        return 0 < pos < len(self.entry.get_text())

    # -------------------------------------------------------------- helpers
    def background(self, work, then=None):
        def go():
            try:
                r = work()
            except Exception as e:
                logging.getLogger(f"vyom.{self.plugin.name}").exception("background work failed")
                r = e
            if then is not None:
                GLib.idle_add(lambda: (then(r), False)[1])
        threading.Thread(target=go, daemon=True).start()

    def set_status(self, text, kind=None, clear_after=None):
        # A message takes the tool's key hints' place while it shows, so it
        # isn't cut to a few letters; Tab, F11 and Esc stay. (A modal tool
        # keeps its hints: its messages are short, and the status ellipsizes.)
        # kind: "ok" (green) or "bad" (yellow) colours it.
        if hasattr(self, "status"):
            self.status.set_label(text)
            self.status.set_tooltip_text(text or None)
            for c in ("ok", "bad"):
                self.status.remove_css_class(c)
            if kind in ("ok", "bad"):
                self.status.add_css_class(kind)
            # The message takes the keys' place while it shows (both
            # would only fit cut short); the keys come back when it clears.
            self.status.set_visible(bool(text))
            self.hint_clip.set_visible(not text)
            # A passing note (core's "that key moved", "not a key here")
            # clears itself, so the keys come back.
            if getattr(self, "status_clear", None):
                GLib.source_remove(self.status_clear)
                self.status_clear = None
            if text and clear_after:
                def clear():
                    self.status_clear = None
                    if self.status.get_label() == text:
                        self.set_status("")
                    return False
                self.status_clear = GLib.timeout_add(int(clear_after * 1000), clear)
