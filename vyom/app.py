"""The Vyom runtime: one resident process (GTK single instance) that loads
every installed plugin and owns their panels, so a key press only has to
show one.

bin/vyom talks to it over D-Bus (org.gtk.Actions on dev.vayu.Vyom):
  open   ["<plugin>", args...]   show a plugin (again: hide it)
  dmenu  "<request.json>"        pick one of stdin's lines (vyom dmenu)
  hide   "<plugin>"              close that one panel
  close                          close every panel, on every workspace
  reload / quit

Panels belong to the workspace they open on and take a slot there (the
centre, a corner): places.py decides, sway.py follows sway (ADR 17).
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

from . import VERSION, config, live, osd, sway, util  # noqa: E402
from . import log as vlog  # noqa: E402
from .panel import Panel, set_keycap_colours  # noqa: E402
from .places import CENTER, Places, clear_of, edge_rect, slot_of  # noqa: E402
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
    transient = True   # a script waits for it: it never stays behind (ADR 17)
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
            self.close()
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
        self.warm_queue = []    # kept panels still to warm up after it
        self.uses = None        # {tool: [unix times it opened]}, the last week (keeps)
        self.uses_dirty = False
        self.places = Places()   # which workspace and slot each open panel has, who has the keys
        self.sway = None
        self.ws_ids = {}
        self.settle_until = 0.0  # Vyom's own keyboard changes: focus notices until then are its own
        for name, ptype, cb in (("open", "s", self.on_open), ("dmenu", "s", self.on_dmenu),
                                ("hide", "s", lambda _a, v: self.close_panel(v.get_string())),
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
        # Panels follow sway's workspaces (ADR 17): its events, no polling.
        if self.conf.get("vyom", {}).get("follow_workspaces", True) is not False:
            self.sway = sway.Watch(self.on_workspaces)
            self.sway.start()

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
        if self.sway is not None:
            self.sway.stop()
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
            osd.export(self.get_dbus_connection())   # volume / brightness keys (ADR 15)
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
        # Then every other panel that keeps its surface (keep, keep_often),
        # one after another: it would make its surface on its first opening
        # anyway and keep it; made now, the first opening is as quick as the
        # next (bhava's emoji, kendra: 55-150 ms -> 10-20 ms).
        self.warm_queue = [n for n in self.order if n != self.warm_name and n in self.plugins and self.keeps(n)]
        self.panel(self.warm_name).warm_up()

    def warm_next(self):
        """The next kept panel's warm-up (Panel.end_warm_up calls this), while
        nothing is open: a panel you opened meanwhile goes first."""
        if any(p.get_visible() for p in self.panels.values()):
            GLib.timeout_add(500, lambda: (self.warm_next(), False)[1])
            return False
        while getattr(self, "warm_queue", None):
            p = self.panel(self.warm_queue.pop(0))
            if not p.get_visible() and not p.get_realized():
                p.warm_up()
                return False
        return False

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

    def slot(self, name):
        """The panel's slot (ADR 17): [plugin.<name>] slot, the tool's own
        `slot`, else from its anchor (kendra: top-right; none: center)."""
        plugin = self.plugins[name]
        conf = self.conf.get("plugin", {}).get(name, {})
        return slot_of(getattr(plugin, "anchor", ()) or (), conf.get("slot") or getattr(plugin, "slot", ""))

    def transient(self, name):
        own = self.conf.get("plugin", {}).get(name, {}).get("transient")
        return own if isinstance(own, bool) else bool(getattr(self.plugins[name], "transient", False))

    def open(self, name, args):
        """A tool's key (`vyom <tool>`, a bar click): opens it on the focused
        workspace with the keyboard; the same key again closes it (only it).
        Covered by another panel here, it comes back as it was."""
        if name not in self.plugins:
            why = self.skipped.get(name, "not installed")
            util.notify("Vyom", f"{name}: {why}", icon="dialog-warning")
            return
        for q in self.panels.values():
            q.end_warm_up()
        pl = self.places
        same = self.last_args.get(name) == args
        if pl.visible(name) and pl.here(name) and same:
            self.close_panel(name)    # the same key again closes it
            return
        e = pl.entries.get(name)
        if e is not None and e.covered and pl.here(name) and (same or not args) and name in self.panels:
            t0 = time.monotonic()
            self.apply(pl.restore(name))
            self.log_first_paint(self.panels[name], name, t0)
            return
        self.last_args[name] = args
        self.note_use(name)
        t0 = time.monotonic()
        self.apply(pl.open(name, self.slot(name), self.transient(name)), {name: args})
        self.log_first_paint(self.panels[name], name, t0)

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
        self.last_args["dmenu"] = [param.get_string()]
        self.apply(self.places.open("dmenu", "center", transient=True), {"dmenu": [param.get_string()]})

    def close_panel(self, name):
        """Closes one panel (Esc, its key, the tool's close()); the keyboard
        goes back to the panel that had it before."""
        if name in self.places.entries:
            self.apply(self.places.close(name))
        elif name in self.panels:
            self.panels[name].hide_panel()

    def close_all(self):
        """Every panel, on every workspace (`close` on D-Bus, a reload)."""
        self.apply(self.places.close_all())
        for p in self.panels.values():
            p.hide_panel()

    # ------------------------------------------------- applying a placement
    def monitor(self, output):
        """The Gdk.Monitor of a sway output name (None: the compositor picks)."""
        if not output:
            return None
        mons = Gdk.Display.get_default().get_monitors()
        for i in range(mons.get_n_items()):
            m = mons.get_item(i)
            if m.get_connector() == output:
                return m
        return None

    def apply(self, ch, args=None):
        """Does what places.py decided: hides first (so the compositor
        hands the keyboard back before the next panel takes it), shows,
        moves, then sets who takes keys."""
        pl = self.places
        for name, why in ch.hide:
            p = self.panels.get(name)
            if p is None:
                continue
            if why == "closed":
                p.hide_panel()
            else:
                p.park()
        if ch.show or ch.hide or ch.move:
            self.arrange()     # before showing: a panel appears where it stays
        for name, how in ch.show:
            p = self.panel(name)
            p.set_output(self.monitor(pl.output_of(name)))
            if pl.focus == name and any(n != name and self.panels[n].get_visible()
                                        for n in pl.shown() if n in self.panels):
                p.raise_up()     # beside another panel: drawn on top of it
            keys = "exclusive" if pl.focus == name else "none"
            if how == "open":
                p.show_panel((args or {}).get(name, self.last_args.get(name, [])), keys=keys)
            else:
                p.unpark(keys=keys)
        for name, output in ch.move:
            p = self.panels.get(name)
            if p is not None:
                p.set_output(self.monitor(output))
        if ch:
            self.settle()
            log.debug("places: %s, keys: %s", ch, pl.focus)
        self.sync_keys()

    def sync_keys(self):
        """The panel with the keyboard takes keys exclusively (sway hands the
        keyboard to it); the others shown take none (a click asks for it:
        panel_pressed). The focused one is lit, the others quieter glass."""
        pl = self.places
        shown = [n for n in pl.shown() if n in self.panels]
        # Others give it up first: two exclusive panels would fight for it.
        dropped = []
        for n in shown:
            if n != pl.focus:
                if self.panels[n].keys == "exclusive":
                    dropped.append(n)
                self.panels[n].set_keys("none")
        if dropped and pl.focus is None:
            GLib.timeout_add(150, self._kept_keys, dropped)
        if pl.focus in shown:
            self.panels[pl.focus].set_keys("exclusive")
        for n in shown:
            self.panels[n].set_lit(n == pl.focus, others=len(shown) > 1)
        self.arrange()

    def arrange(self):
        """Panels shown side by side never cover each other (ADR 17): on
        each output, a centre panel beside an edge or corner panel (kendra
        under the bar) moves into the free area, narrower only if it must
        (places.clear_of); back to its own place once the edge panel goes."""
        pl = self.places
        shown = [n for n in pl.shown() if n in self.panels or n in self.plugins]
        by_out = {}
        for n in shown:
            by_out.setdefault(pl.output_of(n), []).append(n)
        for out, names in by_out.items():
            mon = self.monitor(out)
            if mon is None:
                mons = Gdk.Display.get_default().get_monitors()
                mon = mons.get_item(0) if mons.get_n_items() else None
            if mon is None:
                continue
            g = mon.get_geometry()
            screen = (g.width, g.height)
            edges = []
            for n in names:
                slot = self.slot(n)
                p = self.panel(n)
                if slot != CENTER and not p.full:
                    edges.append((slot, edge_rect(slot, p.natural_size(), screen, p.home_margins)))
            for n in names:
                p = self.panel(n)
                if self.slot(n) != CENTER or p.anchored or p.full:
                    continue
                w = p.base_width
                h = p.natural_size()[1]
                p.set_clear(clear_of(screen, (w, h), edges))
        # a parked or hidden centre panel goes back to its own place, so it
        # never reappears where it was moved for a panel that's gone
        for n, p in self.panels.items():
            if n not in shown and p.clear is not None and not p.get_visible():
                p.set_clear(None)

    def _kept_keys(self, names):
        """Sway leaves the keyboard on a panel that lets go of it when
        there is no window to give it to (an empty workspace): it still
        gets every key, so it stays the panel with the keyboard (lit)."""
        pl = self.places
        if pl.focus is None:
            for n in names:
                p = self.panels.get(n)
                if p is not None and pl.visible(n) and p.get_visible() and p.is_active():
                    log.debug("%s: kept the keyboard (no window to take it)", n)
                    pl.clicked(n)
                    self.settle()
                    self.sync_keys()
                    break
        return False

    def settle(self, seconds=0.25):
        self.settle_until = max(self.settle_until, time.monotonic() + seconds)

    def panel_pressed(self, panel):
        """A click or tap on a panel that shows: it takes the keyboard."""
        name = panel.plugin.name
        log.debug("%s: pressed", name)
        if self.places.visible(name) and self.places.focus != name:
            self.apply(self.places.clicked(name))
            self.settle()
            self.sync_keys()
            panel.raise_up()     # clicked: on top, like a window

    def panel_active(self, panel):
        """The panel with the keyboard lost it. A click on a window
        makes sway take the keyboard away from it and give it straight
        back (the panel takes keys exclusively): that blip, or a loss that
        lasts, means a window has it now: the panel lets go."""
        name = panel.plugin.name
        if self.places.focus != name or panel.is_active() or time.monotonic() < self.settle_until:
            return
        GLib.timeout_add(40, self._lost_check, name)

    def _lost_check(self, name):
        pl = self.places
        if pl.focus != name or time.monotonic() < self.settle_until or name not in self.panels:
            return False
        p = self.panels[name]
        if not p.get_visible():
            return False
        if any(q.is_active() for n, q in self.panels.items() if n != name and q.get_visible()):
            return False     # another panel has it: its click is handled there
        log.debug("%s: a window took the keyboard", name)
        self.apply(pl.window_took_keyboard(time.monotonic()))
        return False

    def on_workspaces(self, focused, visible, ids):
        """Sway's workspaces changed (sway.Watch)."""
        for i, name in ids.items():
            old = self.ws_ids.get(i)
            if old is not None and old != name:
                self.places.renamed(old, name)
        self.ws_ids = ids
        log.debug("sway: workspace %s, on screen %s", focused, visible)
        ch = self.places.workspaces(focused, visible, time.monotonic())
        self.apply(ch)

    def on_reload(self, *_):
        """Re-reads config.toml and the CSS; panels rebuild."""
        self.close_all()
        self.places = Places()
        if self.sway is not None and self.sway.sock is not None:
            self.sway.asked = False
            self.sway._ask()
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
