"""The Vyom application: one resident process (GTK single instance) that
owns every window, so a key press only has to show one.

bin/vyom talks to it over D-Bus (org.gtk.Actions on dev.vayu.Vyom), which
is why opening a panel takes milliseconds after the first start.
"""
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import VERSION, config  # noqa: E402
from .quick import QuickPanel  # noqa: E402

APP_ID = "dev.vayu.Vyom"
HERE = os.path.dirname(os.path.abspath(__file__))


class Vyom(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.quick = None
        for name, cb in (("quick", self.on_quick), ("reload", self.on_reload), ("quit", lambda *_: self.quit())):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()  # stay resident: the next key press is instant
        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(HERE, "style.css"))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.conf = config.load()

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        what = args[0] if args else "daemon"
        if what in ("quick", "reload", "quit"):
            self.activate_action(what, None)
        elif what == "daemon" and self.quick is None:
            # Build the panels now (tile checks run tools), so even the first
            # key press after login only has to show one.
            GLib.idle_add(self.prewarm)
        return 0

    def prewarm(self):
        if self.quick is None:
            self.quick = QuickPanel(self, self.conf)
        return False

    def on_quick(self, *_):
        if self.quick is None:
            self.quick = QuickPanel(self, self.conf)
        self.quick.toggle()

    def on_reload(self, *_):
        """Re-reads config.toml (rebuilds the panels on next open)."""
        self.conf = config.load()
        if self.quick is not None:
            self.quick.destroy()
            self.quick = None


def main(argv=None):
    argv = argv if argv is not None else sys.argv
    if len(argv) > 1 and argv[1] in ("-V", "--version"):
        print(f"vyom {VERSION}")
        return 0
    return Vyom().run(argv)


if __name__ == "__main__":
    sys.exit(main())
