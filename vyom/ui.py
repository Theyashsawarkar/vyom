"""Building blocks for previews and cards, styled by vyom/style.css.

    from vyom import ui
    box = ui.vbox(ui.title("Pixel 8"), ui.kv([("Battery", "82%")]), ui.buttons([("Ring", ring)]))
"""
import math

from gi.repository import Gtk, Pango

from .panel import hint_label, icon_widget, keycap_markup, label, tile  # noqa: F401  (re-exported)


def vbox(*children, spacing=8, cls=None):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    if cls:
        b.add_css_class(cls)
    for c in children:
        if c is not None:
            b.append(c)
    return b


def hbox(*children, spacing=10, cls=None):
    b = Gtk.Box(spacing=spacing)
    if cls:
        b.add_css_class(cls)
    for c in children:
        if c is not None:
            b.append(c)
    return b


def title(text, cls="p-title"):
    return label(text, cls, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)


def meta(text):
    return label(text, "p-meta", xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)


def body(text, markup=False):
    return label(text, "p-body", markup=markup, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                 selectable=False)


def mono(text):
    w = label(text, "p-mono", xalign=0, wrap=True, wrap_mode=Pango.WrapMode.CHAR)
    w.set_selectable(False)
    return w


def chip(text, color="gray", icon=""):
    """A small rounded label in a colour that means something (green
    connected, yellow waiting, red danger...); icon: a Nerd Font glyph."""
    if not icon:
        w = label(text, "chip", f"c-{color}")
        w.set_halign(Gtk.Align.START)
        w.set_valign(Gtk.Align.CENTER)
        return w
    w = hbox(label(icon, "glyph", "chip-icon"), label(text), spacing=5, cls="chip")
    w.add_css_class(f"c-{color}")
    w.set_halign(Gtk.Align.START)
    w.set_valign(Gtk.Align.CENTER)
    return w


def chips(*specs):
    """chips(("5 GHz",), ("WPA2", "green", "")) in a wrapping row."""
    box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=6,
                      max_children_per_line=12, homogeneous=False, valign=Gtk.Align.START)
    box.add_css_class("chips")
    for sp in specs:
        if sp:
            c = chip(*sp)
            box.append(c)
    return box


def keycap(keys):
    """A key cap as a widget ("Ctrl+D"), for buttons and notes."""
    return label(keys, "keycap", valign=Gtk.Align.CENTER)


def kv(pairs, wrap=True):
    """Label/value rows in two aligned columns. wrap=False for cards: a
    wrapping label measured at a narrow width can make a whole row tall."""
    g = Gtk.Grid(column_spacing=14, row_spacing=6, valign=Gtk.Align.START)
    for i, (k, v) in enumerate(pairs):
        g.attach(label(k, "kv-key", xalign=0), 0, i, 1, 1)
        val = label(str(v), "kv-val", xalign=0, wrap=wrap, wrap_mode=Pango.WrapMode.WORD_CHAR)
        if wrap:
            val.set_max_width_chars(32)
        g.attach(val, 1, i, 1, 1)
    return g


def button(text, callback, kind="", icon="", key=""):
    """kind: primary, danger, ok or "". key: the keys that do the same, shown
    on the button ("Ctrl+D")."""
    b = Gtk.Button()
    b.add_css_class("btn")
    if kind:
        b.add_css_class(kind)
    inner = hbox(spacing=7)
    if icon:
        inner.append(label(icon, "glyph"))
    inner.append(label(text))
    if key:
        inner.append(keycap(key))
    b.set_child(inner)
    b.connect("clicked", lambda *_: callback())
    return b


def buttons(specs, homogeneous=False):
    """[(text, callback[, kind[, icon[, key]]])] in a row."""
    row = Gtk.Box(spacing=8, homogeneous=homogeneous)
    for s in specs:
        row.append(button(*s))
    return row


def switch(active, on_toggle, tooltip=""):
    """An on/off switch. Its handler is s.handler (block it to set the state
    from code). GTK's two tiny on/off images warn about their baselines in a
    header, so they're hidden: the switch reads fine without them."""
    s = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
    s.set_can_focus(False)
    c = s.get_first_child()
    while c is not None:
        if isinstance(c, Gtk.Image):
            c.set_visible(False)
        c = c.get_next_sibling()
    if tooltip:
        s.set_tooltip_text(tooltip)
    s.handler = s.connect("state-set", lambda _s, state: (on_toggle(state), False)[1])
    return s


def progress(fraction, color=""):
    """A bar; color (green, yellow, red...) says what the amount means."""
    p = Gtk.ProgressBar()
    p.set_fraction(max(0.0, min(1.0, fraction)))
    if color:
        p.add_css_class(f"m-{color}")
    return p


def meter(name, value_text, fraction, color="green", note=""):
    """A labelled bar in a soft card: "Battery  78% · about 23 h", the bar, a note."""
    head = hbox(label(name, "meter-name", xalign=0, hexpand=True), label(value_text, "meter-value", f"t-{color}"))
    box = vbox(head, progress(fraction, color), spacing=6, cls="soft")
    if note:
        box.append(label(note, "p-meta", xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR))
    return box


class _Drawn(Gtk.DrawingArea):
    """Draws in the colour of its CSS class (c-green → @green), so a theme's
    colours apply."""

    def __init__(self, color, w, h):
        super().__init__(content_width=w, content_height=h, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.add_css_class("drawn")
        self.add_css_class(f"t-{color}")
        self.set_draw_func(self.draw)

    def rgba(self):
        c = self.get_color()
        return c.red, c.green, c.blue


def bars(level, color="gray", height=16):
    """Signal strength as 4 bars, the first `level` filled: the shape says it,
    not only the colour."""
    class Bars(_Drawn):
        def draw(self, _a, cr, w, h):
            r, g, b = self.rgba()
            bw, gap = 4, 2
            for i in range(4):
                bh = h * (i + 1) / 4
                x, y = i * (bw + gap), h - bh
                cr.set_source_rgba(r, g, b, 1 if i < level else 0.18)
                _round_rect(cr, x, y, bw, bh, 1.5)
                cr.fill()
    return Bars(color, 4 * 4 + 3 * 2, height)


def ring(fraction, color="green", size=64, width=6, child=None):
    """A charge ring with `child` (a widget or text) in the middle."""
    class Ring(_Drawn):
        def draw(self, _a, cr, w, h):
            r, g, b = self.rgba()
            cx, cy, rad = w / 2, h / 2, min(w, h) / 2 - width / 2
            cr.set_line_width(width)
            cr.set_source_rgba(1, 1, 1, 0.10)
            cr.arc(cx, cy, rad, 0, 2 * math.pi)
            cr.stroke()
            f = max(0.0, min(1.0, fraction))
            if f > 0:
                cr.set_line_cap(1)   # round
                cr.set_source_rgba(r, g, b, 1)
                cr.arc(cx, cy, rad, -math.pi / 2, -math.pi / 2 + 2 * math.pi * f)
                cr.stroke()
    over = Gtk.Overlay(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    over.set_child(Ring(color, size, size))
    if child is not None:
        if isinstance(child, str):
            child = label(child, "ring-text")
        child.set_halign(Gtk.Align.CENTER)
        child.set_valign(Gtk.Align.CENTER)
        over.add_overlay(child)
    return over


def _round_rect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def hero(*children, color="green", spacing=14):
    """The status strip's card: what's going on, tinted in its colour
    (green connected, yellow waiting, red trouble)."""
    b = hbox(*children, spacing=spacing, cls="hero")
    b.add_css_class(f"h-{color}")
    return b


def steps(items):
    """[(text, state)] with state "done" (green), "now" (yellow) or "todo":
    what a slow action (connecting, pairing) is doing."""
    row = hbox(spacing=6, cls="steps")
    for text, state in items:
        mark = {"done": "\U000f012c ", "now": "\U000f0996 "}.get(state, "")
        row.append(label(mark + text, "step", f"step-{state}"))
    return row


def notice(title_text, text="", color="red", icon=""):
    """A rounded note in a colour that means something: red what went wrong
    (and why), yellow a warning, green done."""
    icon = icon or {"red": "\U000f0028", "yellow": "\U000f0026", "green": "\U000f05e0"}.get(color, "\U000f02fc")
    inner = vbox(label(title_text, "notice-title", xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR),
                 spacing=2)
    if text:
        inner.append(label(text, "notice-text", xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR))
    inner.set_hexpand(True)
    box = hbox(label(icon, "glyph", "notice-icon", valign=Gtk.Align.START), inner, spacing=10, cls="notice")
    box.add_css_class(f"n-{color}")
    return box


def segmented(options, current, on_pick):
    """[(key, text)] as one rounded control; the current one filled."""
    row = Gtk.Box(homogeneous=True)
    row.add_css_class("segmented")
    for key, text in options:
        b = Gtk.Button(label=text)
        b.add_css_class("seg")
        if key == current:
            b.add_css_class("seg-on")
        b.connect("clicked", lambda _b, k=key: on_pick(k))
        row.append(b)
    return row


def section(text, count="", note=""):
    """A section heading in a card or preview, like the list's."""
    row = hbox(label(text.upper(), "section-title", xalign=0), spacing=8, cls="section")
    if count != "":
        row.append(label(str(count), "section-count"))
    if note:
        row.append(label(note, "section-note", hexpand=True, xalign=1))
    return row


def soft(*children, spacing=8):
    """A soft rounded card (a group in a preview or card)."""
    return vbox(*children, spacing=spacing, cls="soft")


def picture(path, height=180):
    pic = Gtk.Picture.new_for_filename(path)
    pic.set_content_fit(Gtk.ContentFit.CONTAIN)
    pic.set_size_request(-1, height)
    return pic


def spacer():
    return Gtk.Box(vexpand=True)
