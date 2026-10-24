"""The window every plugin shows in: a centered layer-shell panel with a
search bar (mode pill, query, an optional widget), a list or grid of
results, an optional preview pane, and a footer of key hints.

Keys (all panels): type to search, Up/Down (or Ctrl+J/K) move, Page
Up/Down jump, Enter activates, Shift/Ctrl+Enter are a row's other actions
(the plugin says which in its hints), Tab opens the next tool, Esc closes.
A tool's tabs switch with Ctrl+H / Ctrl+L and Ctrl+1..9 in every tool.
"""
import logging
import os
import threading

from gi.repository import Gdk, Gio, GLib, Gtk, Gtk4LayerShell as LayerShell, Pango

from .plugin import Row, Section

# keybind: Vyom/every panel | Up / Down | Move to the previous / next result
# keybind: Vyom/every panel | Ctrl+K / Ctrl+J | Move to the previous / next result
# keybind: Vyom/every panel | Page Up / Page Down | Jump a page of results
# keybind: Vyom/every panel | Enter | Open or run the selected result
# keybind: Vyom/every panel | Tab | Switch to the next Vyom tool
# keybind: Vyom/every panel | Ctrl+H / Ctrl+L | Switch to the previous / next tab (tools with tabs)
# keybind: Vyom/every panel | Ctrl+1..9 | Switch to that numbered tab (Ctrl+0: the tenth)
# keybind: Vyom/every panel | Esc | Close the panel

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


def keycap_markup(keys):
    """'Ctrl+Enter' as a key cap (Pango), for footers and hints."""
    return ("<span background='#313244' foreground='#bac2de' font_family='JetBrainsMono Nerd Font'> "
            + GLib.markup_escape_text(keys) + " </span>")


def hint_label(keys, what):
    """A footer hint: the keys as a key cap, then what they do."""
    return label(f"{keycap_markup(keys)} {GLib.markup_escape_text(what)}", "hint", markup=True)


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
        for e in anchor:
            LayerShell.set_anchor(self, edges[e], True)
        for e, px in margins.items():
            LayerShell.set_margin(self, edges[e], int(px))

        self.items = []        # selectable (Row, widget) in order
        self.sel = -1
        self.gen = 0           # search generation: stale results are dropped
        self.pending = None
        self.live_id = None
        self.preview_box = None
        self.tab_buttons = {}    # tab key -> its button (build_tabs)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("vyom-panel")
        root.add_css_class(f"plugin-{plugin.name}")
        w, h, pw = self.sizes()
        root.set_size_request(w, -1)
        self.root = root

        if plugin.layout == "card":
            self.card_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            root.append(self.card_holder)
        else:
            root.append(self.build_top())
            body = Gtk.Box(vexpand=True)
            body.set_size_request(-1, max(200, h - 110))  # minus the bar and footer
            body.append(self.build_results())
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
                body.append(pscroll)
            root.append(body)
            root.append(self.build_foot())
        self.set_child(root)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)
        self.connect("close-request", lambda *_: (self.hide_panel(), True)[1])

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

    def build_tabs(self):
        """The tool's tabs as toggle buttons (again when set_tabs() changes them)."""
        child = self.tab_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.tab_box.remove(child)
            child = nxt
        self.tab_buttons = {}
        tabs = self.plugin.tabs if self.plugin.layout != "card" else []
        if tabs and self.plugin.tab not in [t[0] for t in tabs]:
            self.plugin.tab = tabs[0][0]
        first = None
        for i, t in enumerate(tabs):
            key, text = t[0], t[1]
            b = Gtk.ToggleButton(label=text)
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
        self.tab_box.set_visible(bool(tabs))
        if hasattr(self, "tab_hint"):
            self.tab_hint.set_visible(bool(tabs))

    def on_tab(self, key):
        if key != self.plugin.tab:
            self.plugin.tab = key
            self.plugin.tab_changed(key)

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
        for h in self.plugin.hints:
            foot.append(hint_label(h.keys, h.what))
        self.tab_hint = hint_label("Ctrl+H/L", "tabs")
        self.tab_hint.set_visible(bool(self.tab_buttons))
        foot.append(self.tab_hint)
        self.status = label("", "status", hexpand=True, halign=Gtk.Align.END,
                            ellipsize=Pango.EllipsizeMode.END)
        foot.append(self.status)
        foot.append(hint_label("Esc", "close"))
        return foot

    # ------------------------------------------------------------- showing
    def show_panel(self, args):
        self.plugin.opened(args)
        if self.plugin.layout == "card":
            old = self.card_holder.get_first_child()
            if old is not None:
                self.card_holder.remove(old)
            card = self.plugin.build_card()
            if card is not None:
                self.card_holder.append(card)
            self.present()
            return
        if not self.plugin.keep_query:
            self.entry.set_text("")
        self.set_status("")
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
                w = label(r.title.upper(), "section", xalign=0)
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
        idx = 0
        if keep is not None:
            idx = next((i for i, (r, _) in enumerate(self.items)
                        if r.title == keep.title and r.subtitle == keep.subtitle), 0)
        self.select(idx if self.items else -1)
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
        # The tool first (e.g. Esc cancels tarang's password prompt).
        row = self.selected_row() if self.plugin.layout != "card" else None
        if self.plugin.key(name, row, mods):
            return True
        if keyval == Gdk.KEY_Escape:
            self.app.close_all()
            return True
        if self.plugin.layout == "card":
            return False
        if self.tab_buttons and mods == {"ctrl"}:
            if name in ("h", "l"):
                return self.step_tab(delta=-1 if name == "h" else 1)
            if len(name) == 1 and name.isdigit():
                return self.step_tab(index=(int(name) - 1) % 10)
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
        elif keyval == Gdk.KEY_Tab and not mods:
            self.app.open_next(self.plugin.name)
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

    def set_status(self, text):
        if hasattr(self, "status"):
            self.status.set_label(text)
