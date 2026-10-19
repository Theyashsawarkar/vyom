"""The Vyom runtime: one resident process (GTK single instance) that loads
every installed plugin and owns their panels, so a key press only has to
show one.

bin/vyom talks to it over D-Bus (org.gtk.Actions on dev.vayu.Vyom):
  open   ["<plugin>", args...]   show a plugin (again: hide it)
  dmenu  "<request.json>"        pick one of stdin's lines (vyom dmenu)
  reload / quit
"""
import importlib
import json
import os
import sys
import threading
import tomllib

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import config, util  # noqa: E402
from .panel import Panel  # noqa: E402
from .plugin import Hint, Plugin, Row  # noqa: E402

APP_ID = "dev.vayu.Vyom"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "vyom")


def plugin_dirs():
    """Every directory holding a plugin (one with a plugin.toml)."""
    roots = [os.path.join(DATA, "plugins")]
    roots += [p for p in os.environ.get("VYOM_PLUGIN_PATH", "").split(":") if p]
    found, seen = [], set()
    for root in roots:
        root = os.path.expanduser(root)
        cands = [root] if os.path.exists(os.path.join(root, "plugin.toml")) else \
            sorted(os.path.join(root, d) for d in (os.listdir(root) if os.path.isdir(root) else []))
        for d in cands:
            meta = os.path.join(d, "plugin.toml")
            if os.path.exists(meta) and os.path.realpath(d) not in seen:
                seen.add(os.path.realpath(d))
                found.append(d)
    return found


def read_meta(d):
    with open(os.path.join(d, "plugin.toml"), "rb") as f:
        return tomllib.load(f)


class DmenuPlugin(Plugin):
    """`vyom dmenu`: a list of the caller's lines; Enter prints the pick."""
    name, title, icon, color = "dmenu", "Choose", "\U000f0279", "mauve"
    hints = [Hint("Enter", "choose"), Hint("Shift+Enter", "use what you typed")]

    def __init__(self, vyom, conf):
        super().__init__(vyom, conf)
        self.req = None
        self.answered = True

    def opened(self, args):
        with open(args[0]) as f:
            self.req = json.load(f)
        os.unlink(args[0])
        self.answered = False
        self.placeholder = self.req.get("prompt") or "Choose…"
        if self.panel is not None and hasattr(self.panel, "entry"):
            self.panel.entry.set_placeholder_text(self.placeholder)

    def search(self, query):
        opts = self.req.get("options", []) if self.req else []
        markup = self.req.get("markup", False) if self.req else False
        scored = []
        for i, o in enumerate(opts):
            s = util.fuzzy(query, util.strip_markup(o) if markup else o)
            if s is not None:
                scored.append((-s if query else i, i, o))
        scored.sort()
        return [Row(o, data=o, markup=markup, icon="\U000f0142", color="mauve") for _, _, o in scored]

    def reply(self, text):
        if self.answered or not self.req:
            return
        self.answered = True
        path = self.req["reply"]

        def write():  # opening a FIFO blocks until the caller reads it
            try:
                with open(path, "w") as f:
                    f.write(text)
            except OSError:
                pass
        threading.Thread(target=write, daemon=True).start()

    def activate(self, row, mods):
        typed = self.panel.query() if self.panel else ""
        # Shift+Enter returns what you typed (dmenu's "custom entry").
        self.reply((typed if "shift" in mods and typed else util.strip_markup(row.data)
                    if self.req.get("markup") else row.data) + "\n")
        return True

    def key(self, name, row, mods):
        # Nothing matches what you typed: Enter returns the typed text.
        if name in ("Return", "KP_Enter") and row is None and self.panel and self.panel.query():
            self.reply(self.panel.query() + "\n")
            self.vyom.close_all()
            return True
        return False

    def closed(self):
        self.reply("")  # Esc: the caller gets nothing (exit 1)


class Vyom(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.plugins, self.panels, self.skipped = {}, {}, {}
        self.order = []
        self.last_args = {}
        for name, ptype, cb in (("open", "s", self.on_open), ("dmenu", "s", self.on_dmenu),
                                ("quick", None, lambda *_: self.open("kendra", [])),
                                ("close", None, lambda *_: self.close_all()),
                                ("reload", None, self.on_reload), ("quit", None, lambda *_: self.quit())):
            a = Gio.SimpleAction.new(name, GLib.VariantType.new(ptype) if ptype else None)
            a.connect("activate", cb)
            self.add_action(a)

    # ------------------------------------------------------------- startup
    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()  # stay resident: the next key press is instant
        self.css = Gtk.CssProvider()
        self.load_css()
        self.conf = config.load()
        self.load_plugins()

    def load_css(self):
        paths = [os.path.join(HERE, "style.css")]
        paths += [os.path.join(d, "style.css") for d in plugin_dirs() if os.path.exists(os.path.join(d, "style.css"))]
        user = os.path.join(os.path.dirname(config.PATH), "style.css")
        if os.path.exists(user):
            paths.append(user)
        self.css.load_from_string("\n".join(open(p).read() for p in paths))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def load_plugins(self):
        self.plugins = {"dmenu": DmenuPlugin(self, {})}
        self.order, self.skipped = [], {}
        disabled = set(self.conf.get("vyom", {}).get("disabled", []))
        for d in plugin_dirs():
            try:
                meta = read_meta(d)
                name = meta["name"]
            except (OSError, KeyError, tomllib.TOMLDecodeError) as e:
                print(f"vyom: {d}: bad plugin.toml ({e})", file=sys.stderr)
                continue
            if name in disabled or name in self.plugins:
                continue
            missing = [t for t in meta.get("requires", []) if not util.have(t)]
            if missing:
                self.skipped[name] = f"needs {', '.join(missing)}"
                continue
            try:
                if d not in sys.path:
                    sys.path.insert(0, d)
                mod = importlib.import_module(name)
                cls = mod.Plugin
                for k in ("title", "icon", "color"):
                    if not cls.__dict__.get(k) and meta.get(k):
                        setattr(cls, k, meta[k])
                cls.name = name
                p = cls(self, self.conf.get("plugin", {}).get(name, {}))
                ok, why = p.available()
            except Exception as e:  # one broken plugin must not stop the rest
                self.skipped[name] = f"failed to load: {e}"
                print(f"vyom: plugin {name}: {e}", file=sys.stderr)
                continue
            if not ok:
                self.skipped[name] = why
                continue
            self.plugins[name] = p
            self.order.append(name)
        for name, why in self.skipped.items():
            print(f"vyom: plugin {name} skipped: {why}", file=sys.stderr)

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        if (args[0] if args else "daemon") == "daemon":
            GLib.idle_add(self.prewarm)
        return 0

    def prewarm(self):
        """Build every panel now, so the first key press only shows one."""
        for name in list(self.plugins):
            self.panel(name)
        return False

    def panel(self, name):
        if name not in self.panels:
            self.panels[name] = Panel(self, self.plugins[name])
        return self.panels[name]

    # ------------------------------------------------------------- actions
    def on_open(self, _a, param):
        argv = json.loads(param.get_string())
        self.open(argv[0], argv[1:])

    def open(self, name, args):
        if name not in self.plugins:
            why = self.skipped.get(name, "not installed")
            util.notify("Vyom", f"{name}: {why}", icon="dialog-warning")
            return
        p = self.panel(name)
        if p.get_visible() and self.last_args.get(name) == args:
            self.close_all()          # the same key again closes it
            return
        self.close_all()
        self.last_args[name] = args
        p.show_panel(args)

    def on_dmenu(self, _a, param):
        self.close_all()
        self.panel("dmenu").show_panel([param.get_string()])

    def close_all(self):
        for p in self.panels.values():
            p.hide_panel()

    def open_next(self, current):
        cycle = self.conf.get("vyom", {}).get("cycle") or [
            n for n in self.order if self.plugins[n].layout in ("list", "grid")]
        cycle = [n for n in cycle if n in self.plugins]
        if not cycle:
            return
        i = cycle.index(current) + 1 if current in cycle else 0
        self.open(cycle[i % len(cycle)], [])

    def on_reload(self, *_):
        """Re-reads config.toml and the CSS; panels rebuild."""
        self.close_all()
        for p in self.panels.values():
            p.destroy()
        self.panels = {}
        self.conf = config.load()
        self.load_css()
        for name, p in list(self.plugins.items()):
            p.conf = self.conf.get("plugin", {}).get(name, {})
        GLib.idle_add(self.prewarm)


def main(argv=None):
    return Vyom().run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
