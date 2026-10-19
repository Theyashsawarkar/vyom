"""Building blocks for previews and cards, styled by vyom/style.css.

    from vyom import ui
    box = ui.vbox(ui.title("Pixel 8"), ui.kv([("Battery", "82%")]), ui.buttons([("Ring", ring)]))
"""
from gi.repository import Gtk, Pango

from .panel import icon_widget, label, tile  # noqa: F401  (re-exported)


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


def chip(text, color="gray"):
    w = label(text, "chip", f"c-{color}")
    w.set_halign(Gtk.Align.START)
    return w


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


def button(text, callback, kind="", icon=""):
    b = Gtk.Button()
    b.add_css_class("btn")
    if kind:
        b.add_css_class(kind)
    inner = hbox(spacing=7)
    if icon:
        inner.append(label(icon, "glyph"))
    inner.append(label(text))
    b.set_child(inner)
    b.connect("clicked", lambda *_: callback())
    return b


def buttons(specs, homogeneous=False):
    """[(text, callback[, kind[, icon]])] in a row."""
    row = Gtk.Box(spacing=8, homogeneous=homogeneous)
    for s in specs:
        row.append(button(*s))
    return row


def switch(active, on_toggle):
    s = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
    s.connect("state-set", lambda _s, state: (on_toggle(state), False)[1])
    return s


def progress(fraction):
    p = Gtk.ProgressBar()
    p.set_fraction(max(0.0, min(1.0, fraction)))
    return p


def picture(path, height=180):
    pic = Gtk.Picture.new_for_filename(path)
    pic.set_content_fit(Gtk.ContentFit.CONTAIN)
    pic.set_size_request(-1, height)
    return pic


def spacer():
    return Gtk.Box(vexpand=True)
