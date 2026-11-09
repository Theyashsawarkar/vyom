"""Vim keys for a panel (ADR 0008): NORMAL and INSERT modes, counts,
sequences, Space as the leader with a which-key strip, ? help, Space Space
palette, a y-only confirm, and a cursor for cards. A tool opts in with
`modal = True` and declares its keys as data (Plugin.keys(tab) -> [Bind]);
a tool that doesn't keeps the panel's old keys exactly.

The keys themselves (tokens, sequences, counts) are vyom/keys.py, which has no
GTK in it, so the Python tools outside Vyom share it.
"""
import logging

from gi.repository import GLib, Gtk, Pango

from . import keys as K

# keybind: Vyom/every panel:normal | j / k | Move down / up (a count first moves further: 5j)
# keybind: Vyom/every panel:normal | g g / G | Jump to the first / last result (a count picks the row: 5G)
# keybind: Vyom/every panel:normal | Ctrl+d / Ctrl+u | Scroll half a page down / up
# keybind: Vyom/every panel:normal | H / L | Switch to the previous / next tab (Tab and Shift+Tab too)
# keybind: Vyom/every panel:normal | / | Search again: clear the search box and type (insert mode)
# keybind: Vyom/every panel:normal | i / a | Enter insert mode to type in the search box
# keybind: Vyom/every panel:normal | Enter | Open or run the selected result
# keybind: Vyom/every panel:normal | q | Close the panel
# keybind: Vyom/every panel:normal | Esc | Cancel a pending key, then clear the search, then close the panel
# keybind: Vyom/every panel:normal | ? | Show every key of this view
# keybind: Vyom/every panel:normal | Space Space | Open the palette: every action of this view, type to filter
# keybind: Vyom/every panel:normal | Space ? | Show every key of this view
# keybind: Vyom/every panel:normal | Space q | Close the panel
# keybind: Vyom/every panel:normal | Space t <initial> / Space t 1..9 | Switch to a tab by its initial or its place
# keybind: Vyom/every panel:normal | Space u f | Toggle fullscreen (F11 too)
# keybind: Vyom/every panel:normal | Space r | Reload what the panel shows
# keybind: Vyom/every panel:normal | Space u p | Toggle the preview pane (tools with one; each tool remembers it)
# keybind: Vyom/every panel:insert | Esc | Leave insert mode (normal mode: letters are keys again)
# keybind: Vyom/every panel:insert | Ctrl+j / Ctrl+k | Move down / up the results while typing
# keybind: Vyom/every panel:insert | Enter | Open or run the selected result
# keybind: Vyom/every card:normal | j / k | Move to the next / previous control (a count moves further)
# keybind: Vyom/every card:normal | h / l | Move the focused slider down / up (else move left / right between controls)
# keybind: Vyom/every card:normal | 0 / $ | Set the focused slider to its minimum / maximum
# keybind: Vyom/every card:normal | Enter | Toggle or open the focused control
# keybind: Vyom/confirm | y | Confirm (any other key cancels)
# keybind: Vyom/palette | Ctrl+j / Ctrl+k | Move down / up the palette (Up / Down too)
# keybind: Vyom/palette | Enter | Run the highlighted action

log = logging.getLogger("vyom.keys")
WHICH_DELAY = 300   # ms after a prefix before the which-key strip shows


def lbl(text, *classes, **kw):
    w = Gtk.Label(label=text, **kw)
    for c in classes:
        w.add_css_class(c)
    return w


def clear(box):
    while (c := box.get_first_child()) is not None:
        box.remove(c)


class Modal:
    def __init__(self, panel):
        self.p = panel
        self.plugin = panel.plugin
        self.machine = K.Machine()
        self.mode = self.start_mode()
        self.over = None            # "help" | "palette" | "confirm" | "custom"
        self.confirm_q = None       # (question, action)
        self.pal_query, self.pal_i, self.pal_rows = "", 0, []
        self.custom = None          # a tool's own overlay: fn(box) draws it
        self.which_id = None
        self.which = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.which.add_css_class("vk-which")
        self.which.add_css_class(f"plugin-{self.plugin.name}")   # a tool's own CSS reaches its overlay (ganit's picker)
        self.which.set_valign(Gtk.Align.END)
        self.which.set_margin_bottom(52)
        self.which.set_visible(False)
        self.pill = lbl("", "vk-mode")
        self.typed = lbl("", "vk-pending")
        self.deferred = []          # moves typed before the first results (run when they arrive)
        self.cursor = None          # the card control marked as where you are
        if self.plugin.modal and self.plugin.layout == "card" and getattr(self.plugin, "card_cursor", True):
            panel.connect("notify::focus-widget", lambda *_: self.mark_cursor())

    # ------------------------------------------------------------ the mode
    def start_mode(self):
        m = self.plugin.conf.get("start_mode", getattr(self.plugin, "start_mode", "normal"))
        if isinstance(m, dict):   # per tab: {"calc": "insert", "convert": "normal"}
            m = m.get(self.plugin.tab, "normal")
        return "insert" if m == "insert" else "normal"

    def opened(self):
        self.machine.reset()
        self.deferred = []
        self.over, self.confirm_q, self.custom = None, None, None
        self.set_mode(self.start_mode(), focus=False)
        self.draw()

    def editables(self):
        if self.plugin.layout != "card":
            return [self.p.entry]
        return [w for w in (self.plugin.editables() or []) if w is not None]

    def set_mode(self, mode, focus=True, end=True):
        changed = mode != self.mode
        self.mode = mode
        self.machine.reset()
        self.apply()
        if mode == "insert" and focus:
            w = self.plugin.insert_target() if self.plugin.layout == "card" else self.p.entry
            if w is not None and w.get_root() is not None:
                w.grab_focus()
                if end and hasattr(w, "set_position"):
                    w.set_position(-1)
        if changed:
            self.plugin.mode_changed(mode)

    def apply(self):
        """Shows the mode: the pill, the footer keys, boxes that only take
        typing in INSERT (click one to type)."""
        normal = self.mode == "normal"
        self.pill.set_label("NORMAL" if normal else "INSERT")
        self.pill.remove_css_class("insert" if normal else "normal")
        self.pill.add_css_class("normal" if normal else "insert")
        for e in self.editables():
            if e.get_root() is None:
                continue
            if hasattr(e, "set_editable"):
                e.set_editable(not normal)
            (e.add_css_class if normal else e.remove_css_class)("locked")
            # Marked on the widget itself: a rebuilt card's new box can get a
            # freed one's id(), and then it would never get its click.
            if not getattr(e, "_vk_click", False):
                e._vk_click = True
                click = Gtk.GestureClick()
                click.connect("pressed", lambda *_: self.mode == "normal" and GLib.idle_add(
                    lambda: (self.set_mode("insert", end=False), False)[1]))
                e.add_controller(click)
        self.p.refresh_hints()
        self.show_typed()

    # ------------------------------------------------------------- keymaps
    def core_binds(self):
        b, card = K.Bind, self.plugin.layout == "card"
        out = [
            b("q", "close", "Close the panel"),
            b("?", "help", "Show every key of this view"),
            b("  ", "palette", "Open the palette (every action here)"),
            b(" ?", "help", "Show every key of this view"),
            b(" q", "close", "Close the panel"),
            b(" uf", "fullscreen", "Toggle fullscreen"),
            b(" r", "refresh", "Reload what the panel shows"),
            b("<F11>", "fullscreen", "Toggle fullscreen", hidden=True),
            b("<Esc>", "escape", "", hidden=True),
        ]
        if getattr(self.p, "preview_scroll", None) is not None:
            out.append(b(" up", "preview", "Toggle the preview pane"))
        if self.p.tab_buttons:
            out += [b("H", "tab:-1", "Switch to the previous tab"), b("L", "tab:+1", "Switch to the next tab"),
                    b("<Tab>", "tab:+1", "", hidden=True), b("<S-Tab>", "tab:-1", "", hidden=True),
                    b("<C-S-Tab>", "tab:-1", "", hidden=True),
                    b("<C-h>", "tab:-1", "", hidden=True), b("<C-l>", "tab:+1", "", hidden=True)]
            out += [b(f"<C-{(i + 1) % 10}>", f"tab:#{i}", "", hidden=True) for i in range(min(10, len(self.p.tab_buttons)))]
            out += self.tab_binds()
        if not card:
            cols = self.plugin.grid_columns if self.plugin.layout == "grid" else 1
            out += [
                b("j", "down", "Move down"), b("k", "up", "Move up"),
                b("<Down>", "down", "", hidden=True), b("<Up>", "up", "", hidden=True),
                b("gg", "top", "Jump to the first result"), b("G", "bottom", "Jump to the last result"),
                b("<C-d>", "halfdown", "Scroll half a page down"), b("<C-u>", "halfup", "Scroll half a page up"),
                b("<PgDn>", "pagedown", "", hidden=True), b("<PgUp>", "pageup", "", hidden=True),
                b("<CR>", "activate", "Open or run the selected result"),
                b("/", "search", "Search again (clear the box and type)"),
                b("i", "insert", "Type in the search box"), b("a", "insert", "", hidden=True),
            ]
            if cols > 1:
                out += [b("h", "left", "Move left"), b("l", "right", "Move right"),
                        b("<Left>", "left", "", hidden=True), b("<Right>", "right", "", hidden=True)]
        elif getattr(self.plugin, "card_cursor", True):
            out += [
                b("j", "focus:+1", "Move to the next control"), b("k", "focus:-1", "Move to the previous control"),
                b("<Down>", "focus:+1", "", hidden=True), b("<Up>", "focus:-1", "", hidden=True),
                b("gg", "focus:first", "Jump to the first control"), b("G", "focus:last", "Jump to the last control"),
                b("h", "adjust:-1", "Move the focused slider down (else move left)"),
                b("l", "adjust:+1", "Move the focused slider up (else move right)"),
                b("<Left>", "adjust:-1", "", hidden=True), b("<Right>", "adjust:+1", "", hidden=True),
                b("0", "adjust:min", "Set the focused slider to its minimum"),
                b("$", "adjust:max", "Set the focused slider to its maximum"),
                b("<CR>", "press", "Toggle or open the focused control"),
            ]
        if card and self.editables():
            out += [b("i", "insert", "Type in the box"), b("a", "insert", "", hidden=True)]
        insert = [
            b("<Esc>", "normal", "Leave insert mode", mode="insert"),
            b("<F11>", "fullscreen", "", mode="insert", hidden=True),
        ]
        if not card:
            insert += [
                b("<CR>", "activate", "Open or run the selected result", mode="insert"),
                b("<C-j>", "down", "Move down the results", mode="insert"),
                b("<C-k>", "up", "Move up the results", mode="insert"),
                b("<Down>", "down", "", mode="insert", hidden=True), b("<Up>", "up", "", mode="insert", hidden=True),
                b("<PgDn>", "pagedown", "", mode="insert", hidden=True),
                b("<PgUp>", "pageup", "", mode="insert", hidden=True),
            ]
        if self.p.tab_buttons:   # a card's too: Tab never takes the focus out of the box you type in
            insert += [b("<Tab>", "tab:+1", "", mode="insert", hidden=True),
                       b("<S-Tab>", "tab:-1", "", mode="insert", hidden=True),
                       b("<C-S-Tab>", "tab:-1", "", mode="insert", hidden=True),
                       b("<C-h>", "tab:-1", "", mode="insert", hidden=True),
                       b("<C-l>", "tab:+1", "", mode="insert", hidden=True)]
        return out + insert

    def tab_binds(self):
        """Space t <initial>, when no two tabs share one, and Space t 1..9."""
        tabs = self.plugin.tabs
        initials = {}
        for t in tabs:
            ch = (t[1][:1] or "?").lower()
            initials.setdefault(ch, []).append(t)
        out = []
        for i, t in enumerate(tabs[:9]):
            ch = (t[1][:1] or "?").lower()
            if len(initials[ch]) == 1 and ch.isalpha():
                out.append(K.Bind(f" t{ch}", f"tab:{t[0]}", f"Switch to {t[1]}"))
            out.append(K.Bind(f" t{i + 1}", f"tab:{t[0]}", f"Switch to {t[1]}", hidden=len(initials[ch]) == 1))
        return out

    def keymap(self, mode=None):
        mode = mode or self.mode
        tab = self.plugin.tab
        try:
            own = list(self.plugin.keys(tab) or [])
        except Exception:
            log.exception("%s: keys() failed", self.plugin.name)
            own = []
        bs = [x for x in self.core_binds() + own if x.applies(mode, tab)]
        return K.Keymap(bs, getattr(self.plugin, "key_groups", None) or {})

    # ------------------------------------------------------------- the keys
    def key(self, name, mods):
        """Every key press of a modal panel. True: handled."""
        if K.is_modifier(name) or self.plugin.keys_to_widget():
            return False
        tok = K.token(name, mods)
        if self.plugin.wants_all_keys():
            # The tool is busy (a countdown): drop whatever was half-typed or
            # open, and let it see this key first, whatever it is.
            if self.machine.busy() or self.over in ("confirm", "help", "palette"):
                self.machine.reset()
                if self.over in ("confirm", "help", "palette"):
                    self.over, self.confirm_q = None, None
                self.show_typed()
                self.draw()
            row = self.p.selected_row() if self.plugin.layout != "card" else None
            if self.plugin.key(name, row, mods):
                return True
        if self.over == "confirm":
            _q, action = self.confirm_q
            self.over, self.confirm_q = None, None
            self.draw()
            if tok == "y":
                action()
            else:
                self.p.set_status("Kept", clear_after=3)
            return True
        if self.over == "help":
            if tok in ("j", "k", "<C-d>", "<C-u>", "<Down>", "<Up>"):
                self.scroll_help(tok)
                return True
            self.over = None
            self.draw()
            return True
        if self.over == "palette":
            return self.palette_key(name, tok, mods)
        if not self.machine.busy():
            row = self.p.selected_row() if self.plugin.layout != "card" else None
            if self.plugin.key(name, row, mods):
                return True
        if self.over == "custom":
            return True     # a tool's overlay that didn't take the key keeps it from the rest
        if self.mode == "insert":
            return self.insert_key(name, tok, mods)
        return self.normal_key(name, tok, mods)

    def insert_key(self, name, tok, mods):
        km = self.keymap("insert")
        b = km.table.get(tok) if tok else None
        if b is None and tok in ("<C-CR>", "<S-CR>", "<A-CR>", "<C-S-CR>"):
            if self.plugin.layout != "card":
                self.activate_with(mods)
                return True
        if b is None and tok and tok.startswith("<C-") and len(tok) == 5 and tok[3].isdigit() and self.p.tab_buttons:
            return self.p.step_tab(index=(int(tok[3]) - 1) % 10)
        if b is None:
            return False      # typing
        self.run(b, 1)
        return True

    def normal_key(self, name, tok, mods):
        if tok is None:
            return False
        km = self.keymap("normal")
        res = self.machine.feed(km, tok, counts=getattr(self.plugin, "vim_counts", True))
        if res.kind == "cancel":
            self.show_typed()
            return True
        if res.kind == "pending":
            self.show_typed()
            self.which_soon()
            return True
        self.show_typed()
        if res.kind == "run":
            self.run(res.bind, res.count)
            return True
        # Not a key here. Enter with a modifier is still a row's other action.
        if self.plugin.layout != "card" and name in ("Return", "KP_Enter") and mods:
            self.activate_with(mods)
            return True
        if len(tok) == 1 or len(K.tokens(res.seq)) > 1:
            what = K.spell(res.seq)
            self.p.set_status(f"{what}: not a key here · i types · ? lists the keys" if len(tok) == 1
                              and len(K.tokens(res.seq)) == 1 else f"{what}: no such key · ? lists them", kind="bad",
                              clear_after=4)
            return True
        if self.plugin.layout != "card" and tok in ("<Tab>", "<S-Tab>"):
            return True   # Tab never leaves the search box
        return tok.startswith(("<C-", "<A-"))   # a chord: swallowed, it isn't typing

    # ------------------------------------------------------------ running
    WAIT_FOR_RESULTS = frozenset({"down", "up", "left", "right", "top", "bottom", "halfdown", "halfup",
                                  "pagedown", "pageup", "activate"})

    def run(self, bind, count):
        action = bind.action
        # Keys typed before the results are there (5j right after opening,
        # or while a search runs) wait for them instead of moving nothing.
        if (isinstance(action, str) and action.partition(":")[0] in self.WAIT_FOR_RESULTS
                and self.plugin.layout != "card" and getattr(self.p, "searching", False)
                and not getattr(self.plugin, f"v_{action.partition(':')[0]}", None)):
            self.deferred.append((bind, count))
            return
        self._run(bind, count)

    def activate_with(self, mods):
        """A row's other action (Shift/Ctrl+Enter): like Enter, it waits for
        results that are on their way."""
        mods = set(mods)
        if getattr(self.p, "searching", False):
            self.deferred.append((K.Bind("<CR>", lambda _n, _a: self.p.activate(self.p.sel, mods)), 1))
        else:
            self.p.activate(self.p.sel, mods)

    def flush(self):
        """The results arrived: runs the moves typed while they were on their way."""
        todo, self.deferred = self.deferred, []
        for bind, count in todo:
            self._run(bind, count)

    def _run(self, bind, count):
        action = bind.action
        try:
            if callable(action):
                action(count, "")
                return
            verb, _, arg = str(action).partition(":")
            fn = getattr(self.plugin, f"v_{verb}", None) or getattr(self, f"c_{verb}", None)
            if fn is None:
                log.warning("%s: no action %r for %s", self.plugin.name, action, K.spell(bind.seq))
                return
            fn(count, arg)
        except Exception:
            log.exception("%s: %s failed", self.plugin.name, K.spell(bind.seq))
        finally:
            self.show_typed()

    # core actions (a tool overrides one with a v_<name> method)
    def c_close(self, _n, _a):
        self.p.app.close_all()

    def c_escape(self, _n, _a):
        if self.plugin.escape():
            return
        if self.plugin.layout != "card" and self.p.entry.get_text():
            self.p.entry.set_text("")
            return
        self.p.app.close_all()

    def c_normal(self, _n, _a):
        self.set_mode("normal")

    def c_insert(self, _n, _a):
        self.set_mode("insert")

    def c_search(self, _n, _a):
        if self.plugin.layout != "card":
            self.p.entry.set_text("")
        self.set_mode("insert")

    def c_help(self, _n, _a):
        self.over = "help"
        self.draw()

    def c_palette(self, _n, _a):
        self.over, self.pal_query, self.pal_i = "palette", "", 0
        self.draw()

    def c_fullscreen(self, _n, _a):
        self.p.set_full(not self.p.full)

    def c_preview(self, _n, _a):
        sc = self.p.preview_scroll
        if sc is not None:
            self.p.set_preview(not sc.get_visible())

    def c_refresh(self, _n, _a):
        if self.plugin.layout == "card":
            self.p.rebuild_card()
        else:
            self.p.refresh_now(keep_selection=True)

    def c_tab(self, _n, arg):
        if arg in ("+1", "-1"):
            self.p.step_tab(delta=int(arg))
        elif arg.startswith("#"):
            self.p.step_tab(index=int(arg[1:]))
        else:
            self.p.select_tab(arg)

    def c_moved(self, _n, arg):
        """An old key that moved (for one release): says where to."""
        self.p.set_status(f"That key moved: {arg}", kind="bad", clear_after=5)

    def c_nop(self, _n, _a):
        pass

    # list moves
    def cols(self):
        return self.plugin.grid_columns if self.plugin.layout == "grid" else 1

    def c_down(self, n, _a):
        self.p.move(n * self.cols())

    def c_up(self, n, _a):
        self.p.move(-n * self.cols())

    def c_left(self, n, _a):
        self.p.move(-n)

    def c_right(self, n, _a):
        self.p.move(n)

    def c_top(self, n, _a):
        self.p.select((n - 1) * self.cols() if n > 1 else 0)

    def c_bottom(self, n, _a):
        self.p.select((n - 1) * self.cols() if n > 1 else len(self.p.items) - 1)

    def page_rows(self):
        try:
            page = self.p.scroll.get_vadjustment().get_page_size()
            h = self.p.items[0][1].get_height() if self.p.items else 0
            return max(1, int(page / h)) if h > 0 else 8
        except (AttributeError, IndexError):
            return 8

    def c_halfdown(self, n, _a):
        self.p.move(max(1, self.page_rows() // 2) * self.cols() * n)

    def c_halfup(self, n, _a):
        self.p.move(-max(1, self.page_rows() // 2) * self.cols() * n)

    def c_pagedown(self, n, _a):
        self.p.move(self.page_rows() * self.cols() * n)

    def c_pageup(self, n, _a):
        self.p.move(-self.page_rows() * self.cols() * n)

    def c_activate(self, _n, _a):
        self.p.activate(self.p.sel, set())

    # the card cursor
    def focusables(self):
        out = []

        def walk(w):
            if not w.get_visible() or not w.is_sensitive():
                return
            if w.get_focusable() and w.get_can_focus() and not isinstance(w, (Gtk.Window, Gtk.ScrolledWindow)):
                if isinstance(w, (Gtk.Button, Gtk.Switch, Gtk.Range, Gtk.CheckButton, Gtk.DropDown, Gtk.Editable)) \
                        or w.has_css_class("vk-control"):
                    out.append(w)
                    if not isinstance(w, Gtk.Editable):
                        return
            c = w.get_first_child()
            while c is not None:
                walk(c)
                c = c.get_next_sibling()
        holder = getattr(self.p, "card_holder", None)
        if holder is not None:
            walk(holder)
        return out

    def focused(self):
        f = self.p.get_focus()
        items = self.focusables()
        while f is not None and f not in items:
            f = f.get_parent()
        return f, items

    def mark_cursor(self):
        """Where you are on a modal card: the focused control gets vk-cursor
        (an accent ring), since GTK's own focus ring doesn't show in a
        layer-shell panel."""
        f, items = self.focused()
        f = f if f in items else None
        if f is self.cursor:
            return
        if self.cursor is not None:
            self.cursor.remove_css_class("vk-cursor")
        self.cursor = f
        if f is not None:
            f.add_css_class("vk-cursor")

    def c_focus(self, n, arg):
        f, items = self.focused()
        if not items:
            return
        if arg == "first":
            i = 0
        elif arg == "last":
            i = len(items) - 1
        else:
            i = (items.index(f) + n * int(arg)) if f in items else 0
        items[max(0, min(i, len(items) - 1))].grab_focus()

    def c_adjust(self, n, arg):
        f, _ = self.focused()
        rng = f if isinstance(f, Gtk.Range) else None
        if rng is not None:
            adj = rng.get_adjustment()
            if arg == "min":
                rng.set_value(adj.get_lower())
            elif arg == "max":
                rng.set_value(adj.get_upper() - adj.get_page_size())
            else:
                step = adj.get_step_increment() or 1
                rng.set_value(rng.get_value() + int(arg) * n * step)
            return
        if arg in ("min", "max"):
            return
        for _ in range(n):
            self.p.child_focus(Gtk.DirectionType.LEFT if arg == "-1" else Gtk.DirectionType.RIGHT)

    def c_press(self, _n, _a):
        f, _ = self.focused()
        if f is None:
            return
        if isinstance(f, (Gtk.Switch, Gtk.CheckButton)):
            f.set_active(not f.get_active())
        else:
            f.activate()

    # ------------------------------------------------------------- overlays
    def confirm(self, question, action):
        self.over, self.confirm_q = "confirm", (question, action)
        self.draw()

    def show_custom(self, draw):
        """A tool's own overlay in the which-key slot: draw(box) fills it.
        While it shows, keys reach the tool's key() first; a key it doesn't
        take is dropped. hide_custom() ends it."""
        self.over, self.custom = "custom", draw
        self.draw()

    def hide_custom(self):
        if self.over == "custom":
            self.over, self.custom = None, None
        self.draw()

    def which_soon(self):
        if self.which_id:
            GLib.source_remove(self.which_id)

        def show():
            self.which_id = None
            self.draw()
            return False
        self.which_id = GLib.timeout_add(WHICH_DELAY, show)

    def show_typed(self):
        typed = self.machine.typed()
        self.typed.set_label(typed)
        self.typed.set_visible(bool(typed))
        if not self.machine.pending and self.over is None:
            self.which.set_visible(False)

    def draw(self):
        box = self.which
        clear(box)
        if self.over == "custom" and self.custom is not None:
            self.custom(box)
            box.set_visible(True)
            return
        if self.over == "confirm":
            box.append(lbl(self.confirm_q[0], "vk-which-ask", xalign=0, wrap=True, max_width_chars=40))
            box.append(self.title("y  yes      any other key  no"))
            box.set_visible(True)
            return
        if self.over == "palette":
            return self.draw_palette(box)
        if self.over == "help":
            return self.draw_help(box)
        pending = self.machine.pending
        if not pending:
            box.set_visible(False)
            return
        km = self.keymap("normal")
        name = "leader" if pending == K.LEADER else km.group_name(pending)
        box.append(self.title(f"{K.spell(pending).upper()}  ·  {name.upper()}"))
        items = [(K.spell(t), w, g) for t, w, g in km.next_keys(pending)]
        box.append(self.grid(items))
        box.set_visible(True)

    def title(self, text):
        """The strip's title line: on a card it wraps instead of widening it."""
        if self.plugin.layout == "card":
            return lbl(text, "vk-which-title", xalign=0, wrap=True, max_width_chars=28)
        return lbl(text, "vk-which-title", xalign=0)

    def fit_cols(self, cols):
        """Fewer columns on a narrow card, so the strip never widens it."""
        if self.plugin.layout != "card":
            return cols
        width = self.p.sizes()[0]
        return max(1, min(cols, int(width // 190)))

    def grid(self, items, cols=3):
        cols = self.fit_cols(cols)
        grid = Gtk.Grid(column_spacing=10, row_spacing=4)
        rows = max(1, (len(items) + cols - 1) // cols)
        for n, it in enumerate(items):
            k, w = it[0], it[1]
            group = len(it) > 2 and it[2]
            c, r = n // rows, n % rows
            grid.attach(lbl(k, "vk-which-key", xalign=0), c * 2, r, 1, 1)
            what = lbl(w, "vk-which-what", "vk-group" if group else "vk-bind", xalign=0,
                       ellipsize=Pango.EllipsizeMode.END, hexpand=True, width_chars=10, max_width_chars=10)
            what.set_tooltip_text(w)
            grid.attach(what, c * 2 + 1, r, 1, 1)
        return grid

    def draw_help(self, box):
        title = self.plugin.title.upper()
        tab = next((t[1] for t in self.plugin.tabs if t[0] == self.plugin.tab), "")
        box.append(self.title(f"EVERY KEY · {title}{' · ' + tab.upper() if tab else ''}  ·  j / k scroll · any other key closes"))
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        sections = K.help_rows(self.keymap("normal"))
        ins = [(K.spell(b.seq), b.desc) for b in self.keymap("insert").visible()]
        if ins:
            sections.append(("Insert mode (typing)", ins))
        for name, rows in sections:
            inner.append(lbl(name.upper(), "vk-help-section", xalign=0))
            inner.append(self.grid([(k, w) for k, w in rows], cols=2))
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_min_content_height(160)
        scroll.set_max_content_height(max(160, int(self.p.sizes()[1] * 0.6)))
        scroll.set_child(inner)
        self.help_scroll = scroll
        box.append(scroll)
        box.set_visible(True)
        box.queue_resize()

    def scroll_help(self, tok):
        adj = self.help_scroll.get_vadjustment()
        step = {"j": 40, "<Down>": 40, "k": -40, "<Up>": -40}.get(tok, 0)
        if tok in ("<C-d>", "<C-u>"):
            step = adj.get_page_size() / 2 * (1 if tok == "<C-d>" else -1)
        adj.set_value(adj.get_value() + step)

    def palette_matches(self):
        rows = [r for r in K.palette_rows(self.keymap("normal")) if r[2].action != "palette"]
        return [r for r in rows if K.fuzzy(self.pal_query, f"{r[1]} {r[0]}")]

    def palette_slots(self):
        """How many rows the palette shows: always the same number while you
        filter, so it keeps one height, and never more than the panel has
        room for (it floats over the panel, so a taller one is cut off)."""
        if self.plugin.layout == "card" and getattr(self.plugin, "height", 999) < 400:
            return 6        # a small card's strip grows the panel instead
        h = self.p.get_height() if hasattr(self.p, "get_height") else 0
        if h <= 0:
            return 10
        # The strip's bottom margin, its padding, the title, the query and the count line.
        room = h - self.which.get_margin_bottom() - 150
        return max(3, min(10, room // 30))

    def draw_palette(self, box):
        if self.plugin.layout == "card":
            box.append(self.title("PALETTE  ·  type · Enter runs · Esc closes"))
        else:
            box.append(self.title("PALETTE  ·  type to filter · Ctrl+j / Ctrl+k move · Enter runs · Esc closes"))
        box.append(lbl(f"› {self.pal_query}", "vk-pal-query", xalign=0))
        rows = self.palette_matches()
        slots = self.palette_slots()
        self.pal_i = max(0, min(self.pal_i, len(rows) - 1))
        start = max(0, min(self.pal_i - slots // 2, len(rows) - slots))
        shown = rows[start:start + slots]
        for n in range(slots):
            r = Gtk.Box(spacing=12)
            r.add_css_class("vk-pal-row")
            if n < len(shown):
                k, w, _b = shown[n]
                if start + n == self.pal_i:
                    r.add_css_class("on")
                r.append(lbl(w, "vk-which-what", xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                             max_width_chars=30 if self.plugin.layout == "card" else -1))
                r.append(lbl(k, "vk-which-key", xalign=1))
            else:   # an empty slot keeps the height (the first one says why it's empty)
                r.append(lbl("No action matches" if n == 0 else " ", "vk-which-what", xalign=0, hexpand=True))
            box.append(r)
        if len(rows) > slots:
            box.append(lbl(f"{start + 1}–{start + len(shown)} of {len(rows)}", "vk-help-section", xalign=1))
        else:
            box.append(lbl(" ", "vk-help-section", xalign=1))
        box.set_visible(True)
        box.queue_resize()

    def palette_key(self, name, tok, mods):
        rows = self.palette_matches()
        if tok == "<Esc>":
            self.over = None
        elif tok in ("<CR>",):
            self.over = None
            self.draw()
            if rows:
                self.run(rows[min(self.pal_i, len(rows) - 1)][2], 1)
            return True
        elif tok in ("<C-j>", "<Down>", "<C-n>", "<Tab>"):
            self.pal_i += 1
        elif tok in ("<C-k>", "<Up>", "<C-p>", "<S-Tab>"):
            self.pal_i = max(0, self.pal_i - 1)
        elif tok == "<BS>":
            self.pal_query, self.pal_i = self.pal_query[:-1], 0
        elif tok == "<C-u>":
            self.pal_query, self.pal_i = "", 0
        elif tok and len(tok) == 1:
            self.pal_query += tok
            self.pal_i = 0
        self.draw()
        return True

    # ------------------------------------------------------------- footer
    def hints(self):
        """The footer's keys for this mode (Plugin.mode_hints, else tab_hints)."""
        return self.plugin.mode_hints(self.mode)
