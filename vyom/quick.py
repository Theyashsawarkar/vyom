"""Quick settings: toggles, sliders, battery and session buttons, in a
layer-shell panel under the bar's top-right corner.

Opens instantly with the last known state, then every tile refreshes in a
background thread, so slow tools (bluetoothctl, nmcli) never hold up the
window. Keys: arrows move, Enter / Space toggles, Shift+Enter opens a
tile's details (its picker), Esc closes.
"""
import threading

from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell as LayerShell

from . import system

# keybind: Vyom/quick settings | Arrows | Move between the toggles and sliders
# keybind: Vyom/quick settings | Enter / Space | Toggle the focused setting
# keybind: Vyom/quick settings | Shift+Enter | Open the focused setting's details (e.g. the Wi-Fi list)
# keybind: Vyom/quick settings | Esc | Close quick settings


def label(text, *classes, **kw):
    w = Gtk.Label(label=text, **kw)
    for c in classes:
        w.add_css_class(c)
    return w


class TileButton(Gtk.Button):
    def __init__(self, panel, tile):
        super().__init__()
        self.panel, self.tile, self.on = panel, tile, None
        self.add_css_class("tile")
        self.add_css_class(f"c-{tile.color}")
        box = Gtk.Box(spacing=12)
        box.append(label(tile.icon, "tile-icon"))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        text.append(label(tile.title, "tile-title", xalign=0))
        self.sub = label("…", "tile-sub", xalign=0, ellipsize=3, max_width_chars=18)
        text.append(self.sub)
        box.append(text)
        if tile.open_cmd:
            box.append(label("\U000f0142", "tile-more", hexpand=True, halign=Gtk.Align.END))
        self.set_child(box)
        self.connect("clicked", lambda *_: self.activate_tile())
        if tile.open_cmd:
            click = Gtk.GestureClick(button=3)
            click.connect("pressed", lambda *_: self.open_details())
            self.add_controller(click)
            self.set_tooltip_text("Click: toggle · Right click or Shift+Enter: details")

    def show_state(self, on, sub):
        self.on = on
        self.sub.set_label(sub)
        (self.add_css_class if on else self.remove_css_class)("on")

    def activate_tile(self):
        want = not self.on if self.on is not None else True
        if self.on is not None:
            self.show_state(want, "…")
        self.panel.background(lambda: self.tile.toggle(want), then=self.refresh)

    def open_details(self):
        if self.tile.open_cmd:
            self.panel.hide()
            system.spawn(self.tile.open_cmd)

    def refresh(self):
        self.panel.background(self.tile.status, then=lambda r: self.show_state(*r))


class SliderRow(Gtk.Box):
    def __init__(self, panel, source, css):
        super().__init__(spacing=12)
        self.panel, self.source, self.busy = panel, source, False
        self.add_css_class("slider-row")
        self.add_css_class(css)
        self.icon = Gtk.Button(label=source.icon)
        self.icon.add_css_class("slider-icon")
        if hasattr(source, "toggle_mute"):
            self.icon.connect("clicked", lambda *_: panel.background(source.toggle_mute, then=self.refresh))
            self.icon.set_tooltip_text("Mute / unmute")
        else:
            self.icon.set_can_focus(False)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_hexpand(True)
        self.scale.set_draw_value(False)
        self.scale.connect("value-changed", self.changed)
        self.value = label("", "slider-value", width_chars=4, xalign=1)
        for w in (self.icon, self.scale, self.value):
            self.append(w)
        self.pending = None

    def changed(self, scale):
        v = int(scale.get_value())
        self.value.set_label(str(v))
        if self.busy:
            return
        # Coalesce a drag into at most one command every 80 ms.
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(80, self.apply, v)

    def apply(self, v):
        self.pending = None
        self.panel.background(lambda: self.source.set(v))
        return False

    def refresh(self):
        def show(r):
            v, muted = r
            self.busy = True
            self.scale.set_value(v)
            self.busy = False
            self.value.set_label("muted" if muted else str(v))
            if hasattr(self.source, "icon_muted"):
                self.icon.set_label(self.source.icon_muted if muted else self.source.icon)
        self.panel.background(self.source.get, then=show)


class QuickPanel(Gtk.ApplicationWindow):
    def __init__(self, app, conf):
        super().__init__(application=app, title="Vyom quick settings")
        self.conf = conf["quick"]
        self.add_css_class("vyom")
        LayerShell.init_for_window(self)
        LayerShell.set_namespace(self, "vyom")   # SwayFX: layer_effects "vyom" { blur ... }
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_anchor(self, LayerShell.Edge.TOP, True)
        LayerShell.set_anchor(self, LayerShell.Edge.RIGHT, True)
        LayerShell.set_margin(self, LayerShell.Edge.TOP, int(self.conf.get("margin_top", 6)))
        LayerShell.set_margin(self, LayerShell.Edge.RIGHT, int(self.conf.get("margin_right", 8)))
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.EXCLUSIVE)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("panel")
        root.set_size_request(420, -1)
        root.append(self.header())

        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        grid.add_css_class("tiles")
        self.tiles = []
        for key in self.conf["tiles"]:
            tile = system.make_tile(key, self.conf["tile"].get(key, {}))
            if not tile.available():
                continue  # tool missing or no such hardware: no tile
            b = TileButton(self, tile)
            n = len(self.tiles)
            grid.attach(b, n % 2, n // 2, 1, 1)
            self.tiles.append(b)
        root.append(grid)

        self.sliders = []
        sliders = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sliders.add_css_class("sliders")
        for src, css in ((system.Volume(), "volume"), (system.Brightness(), "brightness")):
            if src.available():
                row = SliderRow(self, src, css)
                sliders.append(row)
                self.sliders.append(row)
        root.append(sliders)

        foot = Gtk.Box(spacing=14)
        foot.add_css_class("foot")
        for keys, what in (("←→↑↓", "move"), ("↵", "toggle"), ("⇧↵", "details")):
            foot.append(label(f"{keys}  {what}", "hint"))
        foot.append(label("Esc  close", "hint", hexpand=True, halign=Gtk.Align.END))
        root.append(foot)
        self.set_child(root)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.key)
        self.add_controller(keys)
        self.connect("close-request", lambda *_: (self.hide(), True)[1])

    def header(self):
        box = Gtk.Box(spacing=12)
        box.add_css_class("header")
        name = system.user_name()
        box.append(label(name[:1], "avatar"))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        self.hello = label("", "hello", xalign=0)
        self.meta = label("", "meta", xalign=0)
        text.append(self.hello)
        text.append(self.meta)
        box.append(text)
        for icon, key, tip, css in (("\U000f033e", "lock", "Lock the screen", "lock"),
                                    ("\U000f0425", "power", "Power menu", "power")):
            cmd = self.conf.get(key)
            if not cmd or not system.have(cmd):
                continue
            b = Gtk.Button(label=icon, tooltip_text=tip)
            b.add_css_class("round")
            b.add_css_class(css)
            b.connect("clicked", lambda _b, c=cmd: (self.hide(), system.spawn(c)))
            box.append(b)
        return box

    def update_header(self):
        self.hello.set_label(f"{system.greeting()}, {system.user_name()}")
        parts = [system.uptime()]
        bat = system.battery()
        if bat:
            pct, charging, left = bat
            parts.append(f"{pct}% {'charging' if charging else 'battery'}" + (f", {left} {'to full' if charging else 'left'}" if left else ""))
        self.meta.set_label(" · ".join(p for p in parts if p))

    # Threads do the slow part; GTK is only touched back on the main loop.
    def background(self, work, then=None):
        def go():
            r = work()
            if then:
                GLib.idle_add(lambda: (then(r) if r is not None else then(), False)[1])
        threading.Thread(target=go, daemon=True).start()

    def refresh(self):
        self.update_header()
        for t in self.tiles:
            t.refresh()
        for s in self.sliders:
            s.refresh()

    def toggle(self):
        if self.get_visible():
            self.hide()
        else:
            self.present()
            self.refresh()
            if self.tiles:
                self.tiles[0].grab_focus()

    def key(self, _ctl, keyval, _code, state):
        if keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and state & Gdk.ModifierType.SHIFT_MASK:
            w = self.get_focus()
            while w is not None and not isinstance(w, TileButton):
                w = w.get_parent()
            if w:
                w.open_details()
                return True
        return False
