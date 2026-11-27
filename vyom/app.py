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
import logging
import os
import sys
import threading
import time
import tomllib

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import VERSION, config, live, util  # noqa: E402
from . import log as vlog  # noqa: E402
from .panel import Panel, set_keycap_colours  # noqa: E402
from .plugin import Hint, Plugin, Row  # noqa: E402

log = logging.getLogger("vyom")

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
        # A tool's directory is named after its package, which has no dot:
        # skip kosha's `<name>.kosha-release` (kept while you `kosha link`
        # your checkout) and backups, which would load twice.
        cands = [root] if os.path.exists(os.path.join(root, "plugin.toml")) else \
            sorted(os.path.join(root, d) for d in (os.listdir(root) if os.path.isdir(root) else [])
                   if "." not in d)
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
        self.warm_name = None   # the warm-up's panel (the launcher): always kept
        self.uses = None        # {tool: [unix times it opened]}, the last week (keeps)
        self.uses_dirty = False
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
        self.conf = config.load()
        self.load_css()
        self.load_plugins()

    def load_css(self):
        paths = [os.path.join(HERE, "style.css")]
        paths += [os.path.join(d, "style.css") for d in plugin_dirs() if os.path.exists(os.path.join(d, "style.css"))]
        css = [open(p).read() for p in paths]
        # [vyom] opacity: how much of the (blurred) desktop shows through.
        try:
            opacity = min(1.0, max(0.3, float(self.conf.get("vyom", {}).get("opacity", 0.72))))
        except (TypeError, ValueError):
            opacity = 0.72
        css.append(f".vyom-panel {{ background-color: alpha(@base, {opacity:.2f}); }}")
        user = os.path.join(os.path.dirname(config.PATH), "style.css")
        if os.path.exists(user):
            css.append(open(user).read())
        # [vyom] css: more stylesheets, last (a theme engine's colours, e.g.
        # varna's ~/.local/state/varna/vyom.css redefining @base, @mauve...).
        extra = self.conf.get("vyom", {}).get("css", [])
        for p in [extra] if isinstance(extra, str) else extra:
            p = os.path.expanduser(str(p))
            if os.path.exists(p):
                css.append(open(p).read())
        self.css.load_from_string("\n".join(css))
        set_keycap_colours("\n".join(css))   # key caps in the theme's colours too
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
                log.error("%s: bad plugin.toml (%s)", d, e)
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
                log.exception("plugin %s failed to load", name)
                continue
            if not ok:
                self.skipped[name] = why
                continue
            self.plugins[name] = p
            self.order.append(name)
        for name, why in self.skipped.items():
            log.info("plugin %s skipped: %s", name, why)

    def do_shutdown(self):
        live.stop()     # its helpers (pactl subscribe) go with Vyom
        Gtk.Application.do_shutdown(self)

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        if (args[0] if args else "daemon") == "daemon":
            GLib.idle_add(self.prewarm)
        return 0

    def prewarm(self):
        """Build every panel now, so the first key press only shows one."""
        t0 = time.monotonic()
        # The live state (ADR 12): every source starts now and stays, panels
        # read it, other programs get it on D-Bus and in $XDG_RUNTIME_DIR.
        if self.conf.get("vyom", {}).get("live", True) is not False:
            live.export(self.get_dbus_connection())
        for name in list(self.plugins):
            self.panel(name)
        log.info("built %d panels in %d ms", len(self.panels), (time.monotonic() - t0) * 1000)
        # Then, one idle step at a time (a key press in between is served
        # first): GTK's own first-window work, and each tool's caches. The
        # first opening otherwise paid for both: 0.6 s for the launcher on
        # a fast machine, seconds right after a boot.
        steps = [(n, self.plugins[n].prewarm) for n in self.order if n in self.plugins] + [("gtk", self.warm_gtk)]
        def step():
            if not steps:
                log.info("warmed up in %d ms", (time.monotonic() - t0) * 1000)
                # Starting leaves the C heap full of freed pages (GTK's
                # start-up, Mesa's shader compiler after a driver update:
                # 140 MB, 20 MB trimmed): give them back.
                GLib.timeout_add(1000, lambda: (util.trim_memory(), False)[1])
                return False
            name, fn = steps.pop(0)
            t = time.monotonic()
            try:
                fn()
                log.debug("prewarm %s: %d ms", name, (time.monotonic() - t) * 1000)
            except Exception:  # a tool's cache is never worth a crash
                log.exception("prewarm %s failed", name)
            return True
        GLib.idle_add(step, priority=GLib.PRIORITY_LOW)
        return False

    def warm_gtk(self):
        """One invisible first frame (Panel.warm_up) for the launcher, or
        the first tool without it: the one-time GTK work it does is shared
        by every panel. [vyom] warm_up = false turns it off."""
        if not self.order or self.conf.get("vyom", {}).get("warm_up", True) is False:
            return
        self.warm_name = "dvara" if "dvara" in self.plugins else self.order[0]
        self.panel(self.warm_name).warm_up()

    # ------------------------------------------------- which panels stay warm
    WEEK = 7 * 86400

    def keeps(self, name):
        """True when a hidden panel keeps its surface for good (ADR 11):
        `keep` in its [plugin.<name>] (true or false wins), the warm-up's
        panel (the launcher), one named in [vyom] keep, or one opened at
        least [vyom] keep_often times (default 5, 0: off) in the last week."""
        own = self.conf.get("plugin", {}).get(name, {}).get("keep")
        if isinstance(own, bool):
            return own
        conf = self.conf.get("vyom", {})
        if name == self.warm_name or name in (conf.get("keep") or []):
            return True
        often = conf.get("keep_often", 5)
        if not isinstance(often, int) or isinstance(often, bool) or often <= 0:
            return False
        cut = time.time() - self.WEEK
        return sum(1 for t in self.load_uses().get(name, ()) if t > cut) >= often

    def load_uses(self):
        if self.uses is None:
            raw = util.load_state("vyom-uses", {})
            self.uses = {k: [t for t in v if isinstance(t, (int, float))][-64:]
                         for k, v in (raw.items() if isinstance(raw, dict) else ()) if isinstance(v, list)}
        return self.uses

    def note_use(self, name):
        """Counts an opening (in memory; written when the panel hides)."""
        uses = self.load_uses()
        cut = time.time() - self.WEEK
        uses[name] = [t for t in uses.get(name, []) if t > cut][-63:] + [int(time.time())]
        self.uses_dirty = True

    def save_uses(self):
        """Called after a panel hides, at idle: never on the way to a frame."""
        if self.uses_dirty and self.uses is not None:
            self.uses_dirty = False
            try:
                util.save_state("vyom-uses", self.uses)
            except OSError:
                pass
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
        for q in self.panels.values():
            q.end_warm_up()
        p = self.panel(name)
        if p.get_visible() and self.last_args.get(name) == args:
            self.close_all()          # the same key again closes it
            return
        self.close_all()
        self.last_args[name] = args
        self.note_use(name)
        t0 = time.monotonic()
        p.show_panel(args)
        self.log_first_paint(p, name, t0)

    def log_first_paint(self, panel, name, t0):
        """How long from the key press reaching Vyom to the panel's first
        frame: debug normally, info when it's slow enough to notice."""
        clock = panel.get_frame_clock()
        if clock is None:
            return
        def painted(c, *_):
            c.disconnect(hid)
            ms = (time.monotonic() - t0) * 1000
            log.log(logging.INFO if ms > 150 else logging.DEBUG, "%s: first frame in %d ms", name, ms)
        hid = clock.connect("after-paint", painted)

    def on_dmenu(self, _a, param):
        self.close_all()
        self.panel("dmenu").show_panel([param.get_string()])

    def close_all(self):
        for p in self.panels.values():
            p.hide_panel()

    def on_reload(self, *_):
        """Re-reads config.toml and the CSS; panels rebuild."""
        self.close_all()
        for p in self.panels.values():
            p.release_card()   # a plugin's cached card must outlive its panel
            p.destroy()
        self.panels = {}
        self.conf = config.load()
        self.load_css()
        for name, p in list(self.plugins.items()):
            p.conf = self.conf.get("plugin", {}).get(name, {})
        GLib.idle_add(self.prewarm)


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv)
    debug = "--debug" in argv
    if debug:
        argv.remove("--debug")
    vlog.setup("vyom", debug=debug or None)
    log.info("vyom %s starting", VERSION)
    # Started before the session has a display (D-Bus activated by an early
    # notification, for akashvani, before sway's environment reached systemd):
    # GTK would come up with no screen and serve nothing. Exit instead, so the
    # unit's Restart= (or the session starting it) brings it back with one.
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")) or Gdk.Display.get_default() is None:
        log.error("no display yet (WAYLAND_DISPLAY isn't set): exiting; the session starts Vyom again")
        return 1
    return Vyom().run(argv)


if __name__ == "__main__":
    sys.exit(main())
