"""Where open panels are (ADR 17): the workspace each belongs to, the slot
it takes there, and which one has the keyboard. Pure (no GTK, no sway):
app.py feeds it what sway says and what you do, and acts on the Change it
gets back.

- A panel opens on the focused workspace and stays there: leaving the
  workspace hides it with all its state, coming back shows it as it was.
- Panels in different slots (the centre, a corner or an edge: kendra under
  the bar at the top right) are open side by side; opening one whose slot
  is taken covers the panel there, which keeps its state: its key brings
  it back as it was.
- The keyboard goes to the panel opened last, to one you click, back to a
  window you click (`focus` None), and, when the panel that had it
  closes, to the one that had it before.
- A transient panel (`vyom dmenu`'s picker: a script waits for it) closes
  instead of staying behind when it loses the keyboard, is covered, or its
  workspace is left.
"""

CENTER = "center"
_ALIASES = {"centre": CENTER, "middle": CENTER, "": CENTER}


def slot_of(anchor=(), override=None):
    """The slot a panel takes: `override` ([plugin.<name>] slot) when set,
    else from its anchor: none is the centre, ("top", "right") is
    "top-right", ("top",) is "top". Opposite edges cancel out."""
    if isinstance(override, str) and override.strip():
        words = override.strip().lower().replace("_", "-").replace(" ", "-").split("-")
        if words in (["center"], ["centre"], ["middle"]):
            return CENTER
        return slot_of(tuple(w for w in words if w))
    edges = {str(e).lower() for e in (anchor or ())}
    v = ("top" if "top" in edges else "bottom" if "bottom" in edges else "") \
        if ("top" in edges) != ("bottom" in edges) else ""
    h = ("left" if "left" in edges else "right" if "right" in edges else "") \
        if ("left" in edges) != ("right" in edges) else ""
    name = "-".join(x for x in (v, h) if x)
    return _ALIASES.get(name, name)


class Entry:
    """An open panel: its slot, its workspace (None: no compositor told us
    any), whether another panel covers it there, whether it's transient."""
    __slots__ = ("name", "slot", "ws", "covered", "transient", "over")

    def __init__(self, name, slot, ws, transient=False):
        self.name, self.slot, self.ws = name, slot, ws
        self.covered, self.transient = False, transient
        self.over = None   # a transient panel: the one it covers, back when it goes

    def __repr__(self):
        return f"Entry({self.name}, {self.slot}, ws={self.ws!r}{', covered' if self.covered else ''})"


class Change:
    """What app.py does: hide (name, why: "covered" | "away" | "closed"),
    show (name, how: "open" | "restore" | "back"), move (name, output)."""
    __slots__ = ("hide", "show", "move")

    def __init__(self):
        self.hide, self.show, self.move = [], [], []

    def __bool__(self):
        return bool(self.hide or self.show or self.move)

    def __repr__(self):
        return f"Change(hide={self.hide}, show={self.show}, move={self.move})"


class Places:
    BLIP = 0.5   # seconds: a window "took the keyboard" this soon before a workspace switch was the switch

    def __init__(self):
        self.entries = {}      # name -> Entry: every panel that isn't closed
        self.current = None    # the focused workspace (None: nothing known, one workspace)
        self.shown_ws = set()  # workspaces on screen, one per output
        self.outputs = {}      # workspace -> its output
        self.focus = None      # the panel with the keyboard (None: a window has it)
        self.recent = []       # panel names, the latest to have the keyboard first
        self.left = {}         # workspace -> the panel that had the keyboard when you left it
        self.lost = None       # (panel, time) the last time a window took the keyboard from it

    # ------------------------------------------------------------ queries
    def ws_shown(self, ws):
        return ws is None or self.current is None or ws in self.shown_ws

    def visible(self, name):
        e = self.entries.get(name)
        return e is not None and not e.covered and self.ws_shown(e.ws)

    def here(self, name):
        """name is open on the focused workspace (shown or covered)."""
        e = self.entries.get(name)
        return e is not None and (e.ws is None or self.current is None or e.ws == self.current)

    def shown(self):
        return [n for n in self.entries if self.visible(n)]

    def output_of(self, name):
        e = self.entries.get(name)
        return self.outputs.get(e.ws) if e is not None else None

    def occupant(self, ws, slot, but=None):
        for e in self.entries.values():
            if e.ws == ws and e.slot == slot and not e.covered and e.name != but:
                return e
        return None

    # ------------------------------------------------------------ helpers
    def _bump(self, name):
        if name in self.recent:
            self.recent.remove(name)
        self.recent.insert(0, name)

    def _next_focus(self, ws, but=None):
        """The panel that had the keyboard most recently among those shown
        on workspace ws (None: back to the window)."""
        for n in self.recent:
            e = self.entries.get(n)
            if n != but and e is not None and not e.covered and self.visible(n) and \
                    (ws is None or e.ws is None or e.ws == ws):
                return n
        return None

    def _drop(self, name, ch, why="closed"):
        e = self.entries.pop(name, None)
        if e is None:
            return None
        if why is not None:
            ch.hide.append((name, why))
        if name in self.recent:
            self.recent.remove(name)
        for ws, n in list(self.left.items()):
            if n == name:
                del self.left[ws]
        # A transient picker over a panel: that panel comes back as it goes.
        under = self.entries.get(e.over) if e.over else None
        if under is not None and under.covered and under.ws == e.ws and \
                self.occupant(under.ws, under.slot) is None:
            under.covered = False
            if self.visible(under.name):
                ch.show.append((under.name, "restore"))
        return e

    def _cover(self, ws, slot, but, ch):
        """Covers what's in slot on ws; returns its name."""
        occ = self.occupant(ws, slot, but)
        if occ is None:
            return None
        if occ.transient:
            under = occ.over
            occ.over = None
            self._drop(occ.name, ch)
            under_e = self.entries.get(under) if under else None
            if under_e is not None and under_e.covered:
                return under    # stays covered, now by the new one
            return None
        was_shown = self.visible(occ.name)
        occ.covered = True
        if was_shown:
            ch.hide.append((occ.name, "covered"))
        if self.focus == occ.name:
            self.focus = None
        return occ.name

    def _lose_focus(self, ch):
        """The focused panel lost the keyboard: a transient one closes."""
        e = self.entries.get(self.focus) if self.focus else None
        self.focus = None
        if e is not None and e.transient:
            self._drop(e.name, ch)

    # ------------------------------------------------------------ what you do
    def open(self, name, slot, transient=False):
        """Opens name fresh on the focused workspace with the keyboard.
        Open elsewhere (another workspace, or covered), it's taken from
        there: hidden ("closed": the tool's closed(), then opened() again)."""
        ch = Change()
        if name in self.entries:
            self._drop(name, ch, why="closed")
        ws = self.current
        under = self._cover(ws, slot, name, ch)
        if self.focus is not None and self.focus != name:
            self._lose_focus(ch)
        self.entries[name] = Entry(name, slot, ws, transient)
        if transient:
            self.entries[name].over = under
        self.focus = name
        self._bump(name)
        ch.show.append((name, "open"))
        return ch

    def restore(self, name):
        """name was covered on the focused workspace: back as it was, with
        the keyboard, covering what's in its slot now."""
        ch = Change()
        e = self.entries.get(name)
        if e is None or not e.covered or not self.here(name):
            return ch
        self._cover(e.ws, e.slot, name, ch)
        if self.focus is not None and self.focus != name:
            self._lose_focus(ch)
        e.covered = False
        self.focus = name
        self._bump(name)
        ch.show.append((name, "restore"))
        return ch

    def close(self, name):
        """name closes (Esc, its key again, the tool's close()). The
        keyboard goes back to the panel that had it before, if one shows."""
        ch = Change()
        e = self.entries.get(name)
        if e is None:
            return ch
        self._drop(name, ch)
        if self.focus == name:
            self.focus = self._next_focus(e.ws if e.ws is not None else self.current)
            if self.focus is not None:
                self._bump(self.focus)
        return ch

    def close_all(self):
        ch = Change()
        for name in list(self.entries):
            self._drop(name, ch)
        self.focus = None
        return ch

    def clicked(self, name):
        """You clicked a panel that shows: it takes the keyboard."""
        ch = Change()
        if not self.visible(name) or self.focus == name:
            return ch
        if self.focus is not None:
            self._lose_focus(ch)
        self.focus = name
        self._bump(name)
        return ch

    def window_took_keyboard(self, now=0.0):
        """A window took the keyboard (you clicked it, sway focused one)."""
        ch = Change()
        if self.focus is not None:
            self.lost = (self.focus, now)
            self._lose_focus(ch)
        return ch

    # ------------------------------------------------------------ what sway says
    def workspaces(self, focused, visible, now=0.0):
        """Sway's workspaces changed: focused is the focused workspace's
        name, visible {output: workspace on screen there}. Panels whose
        workspace left the screen hide ("away"), those whose came back show
        ("back"); a workspace that moved to another output takes its panels."""
        ch = Change()
        before = {n for n in self.entries if self.visible(n)}
        old_out = dict(self.outputs)
        old = self.current
        if focused is not None and old is not None and focused != old:
            had = self.focus
            if had is None and self.lost is not None and now - self.lost[1] <= self.BLIP:
                had = self.lost[0]   # the switch itself took the keyboard first
            e = self.entries.get(had) if had else None
            if e is not None and e.ws == old:
                self.left[old] = had
            else:
                self.left.pop(old, None)
        self.current = focused
        self.shown_ws = {ws for ws in visible.values() if ws is not None}
        self.outputs = {ws: out for out, ws in visible.items() if ws is not None}
        for ws, out in old_out.items():   # off screen now: its output may still be right
            self.outputs.setdefault(ws, out)
        if old is None and focused is not None:
            # Sway answered only now: panels opened before belong here.
            for e in self.entries.values():
                if e.ws is None:
                    e.ws = focused
        after = {n for n in self.entries if self.visible(n)}
        for n in [n for n in self.entries if n in before and n not in after]:
            if self.entries[n].transient:
                self._drop(n, ch)
                if self.focus == n:
                    self.focus = None
            else:
                ch.hide.append((n, "away"))
        for n in self.entries:
            if n in after and n not in before:
                ch.show.append((n, "back"))
            elif n in after and old_out.get(self.entries[n].ws) not in (None, self.outputs.get(self.entries[n].ws)):
                ch.move.append((n, self.outputs.get(self.entries[n].ws)))
        if focused != old and old is not None:
            f = self.focus
            fe = self.entries.get(f) if f else None
            if fe is not None and fe.ws not in (None, focused):
                self.focus = None    # its workspace isn't the focused one any more
            if focused is not None:
                back = self.left.pop(focused, None)
                if back is not None and self.visible(back):
                    self.focus = back
                    self._bump(back)
                elif self.focus is not None and not self.visible(self.focus):
                    self.focus = None
            self.lost = None
        return ch

    def renamed(self, old, new):
        for e in self.entries.values():
            if e.ws == old:
                e.ws = new
        if old in self.left:
            self.left[new] = self.left.pop(old)
        if self.current == old:
            self.current = new
        if old in self.shown_ws:
            self.shown_ws.discard(old)
            self.shown_ws.add(new)
        if old in self.outputs:
            self.outputs[new] = self.outputs.pop(old)
