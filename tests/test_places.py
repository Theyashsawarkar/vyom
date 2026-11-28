"""Where panels are (places.py, ADR 17): workspaces, slots, the keyboard.
Pure: no GTK, no sway."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vyom import sway  # noqa: E402
from vyom.places import CENTER, Places, Settle, clear_of, edge_rect, slot_of  # noqa: E402

TR = "top-right"


def two_ws():
    """Workspaces 1 and 2 on one output, 1 focused."""
    p = Places()
    p.workspaces("1", {"OUT-1": "1"})
    return p


def go(p, ws, now=0.0, out="OUT-1", other=None):
    vis = {out: ws}
    vis.update(other or {})
    return p.workspaces(ws, vis, now)


class Slots(unittest.TestCase):
    def test_from_anchor(self):
        self.assertEqual(slot_of(()), CENTER)
        self.assertEqual(slot_of(("top", "right")), TR)
        self.assertEqual(slot_of(("right", "top")), TR)
        self.assertEqual(slot_of(("top",)), "top")
        self.assertEqual(slot_of(("bottom", "left")), "bottom-left")
        self.assertEqual(slot_of(("top", "bottom")), CENTER)        # stretched: no edge
        self.assertEqual(slot_of(("top", "left", "right")), "top")

    def test_override(self):
        self.assertEqual(slot_of(("top", "right"), "center"), CENTER)
        self.assertEqual(slot_of((), "Centre"), CENTER)
        self.assertEqual(slot_of((), "top-right"), TR)
        self.assertEqual(slot_of((), "right top"), TR)
        self.assertEqual(slot_of((), "top_left"), "top-left")
        self.assertEqual(slot_of(("top", "right"), ""), TR)        # empty: the anchor's
        self.assertEqual(slot_of(("top", "right"), None), TR)


class SeveralAtOnce(unittest.TestCase):
    def test_different_slots_coexist_newest_has_keys(self):
        p = two_ws()
        ch = p.open("dvara", CENTER)
        self.assertEqual(ch.show, [("dvara", "open")])
        ch = p.open("kendra", TR)
        self.assertEqual(ch.hide, [])
        self.assertEqual(ch.show, [("kendra", "open")])
        self.assertEqual(sorted(p.shown()), ["dvara", "kendra"])
        self.assertEqual(p.focus, "kendra")

    def test_same_slot_covers_and_keeps(self):
        p = two_ws()
        p.open("dvara", CENTER)
        ch = p.open("ganit", CENTER)
        self.assertEqual(ch.hide, [("dvara", "covered")])
        self.assertTrue(p.entries["dvara"].covered)
        self.assertEqual(p.shown(), ["ganit"])
        ch = p.restore("dvara")
        self.assertEqual(ch.hide, [("ganit", "covered")])
        self.assertEqual(ch.show, [("dvara", "restore")])
        self.assertEqual(p.focus, "dvara")
        self.assertTrue(p.entries["ganit"].covered)

    def test_close_hands_keys_back(self):
        p = two_ws()
        p.open("dvara", CENTER)
        p.open("kendra", TR)
        ch = p.close("kendra")
        self.assertEqual(ch.hide, [("kendra", "closed")])
        self.assertEqual(p.focus, "dvara")
        ch = p.close("dvara")
        self.assertIsNone(p.focus)
        self.assertEqual(p.shown(), [])

    def test_close_unfocused_keeps_focus(self):
        p = two_ws()
        p.open("dvara", CENTER)
        p.open("kendra", TR)
        p.close("dvara")
        self.assertEqual(p.focus, "kendra")

    def test_closing_cover_doesnt_bring_back_covered(self):
        p = two_ws()
        p.open("dvara", CENTER)
        p.open("ganit", CENTER)
        ch = p.close("ganit")
        self.assertEqual(ch.show, [])
        self.assertEqual(p.shown(), [])
        self.assertIn("dvara", p.entries)    # still kept: its key brings it back

    def test_click_and_window(self):
        p = two_ws()
        p.open("dvara", CENTER)
        p.open("kendra", TR)
        p.clicked("dvara")
        self.assertEqual(p.focus, "dvara")
        self.assertEqual(p.recent[:2], ["dvara", "kendra"])
        p.window_took_keyboard()
        self.assertIsNone(p.focus)
        self.assertEqual(sorted(p.shown()), ["dvara", "kendra"])   # they stay open
        p.clicked("kendra")
        self.assertEqual(p.focus, "kendra")

    def test_click_on_hidden_is_nothing(self):
        p = two_ws()
        p.open("dvara", CENTER)
        p.open("ganit", CENTER)
        p.clicked("dvara")
        self.assertEqual(p.focus, "ganit")

    def test_reopen_closes_old_first(self):
        p = two_ws()
        p.open("tarang", CENTER)
        ch = p.open("tarang", CENTER)    # other args: closed, opened again
        self.assertEqual(ch.hide, [("tarang", "closed")])
        self.assertEqual(ch.show, [("tarang", "open")])

    def test_close_all(self):
        p = two_ws()
        p.open("dvara", CENTER)
        p.open("kendra", TR)
        go(p, "2")
        p.open("ganit", CENTER)
        ch = p.close_all()
        self.assertEqual(sorted(n for n, _ in ch.hide), ["dvara", "ganit", "kendra"])
        self.assertEqual(p.entries, {})


class Workspaces(unittest.TestCase):
    def test_leaving_hides_returning_shows(self):
        p = two_ws()
        p.open("dvara", CENTER)
        ch = go(p, "2")
        self.assertEqual(ch.hide, [("dvara", "away")])
        self.assertIsNone(p.focus)
        ch = go(p, "1")
        self.assertEqual(ch.show, [("dvara", "back")])
        self.assertEqual(p.focus, "dvara")

    def test_returning_restores_who_had_keys(self):
        p = two_ws()
        p.open("dvara", CENTER)
        p.open("kendra", TR)
        p.clicked("dvara")
        go(p, "2")
        go(p, "1")
        self.assertEqual(p.focus, "dvara")

    def test_window_had_keys_stays_with_window(self):
        p = two_ws()
        p.open("dvara", CENTER)
        p.window_took_keyboard(now=10.0)
        go(p, "2", now=30.0)
        go(p, "1", now=40.0)
        self.assertIsNone(p.focus)
        self.assertEqual(p.shown(), ["dvara"])

    def test_switch_blip_doesnt_count_as_a_window(self):
        # Sway takes the keyboard from the panel as it switches; Vyom may
        # hear that before the workspace event.
        p = two_ws()
        p.open("dvara", CENTER)
        p.window_took_keyboard(now=5.0)
        go(p, "2", now=5.05)
        go(p, "1", now=9.0)
        self.assertEqual(p.focus, "dvara")

    def test_each_workspace_its_own(self):
        p = two_ws()
        p.open("dvara", CENTER)
        p.open("kendra", TR)
        go(p, "2")
        ch = p.open("ganit", CENTER)
        self.assertEqual(ch.hide, [])            # dvara is on 1: nothing covered here
        self.assertEqual(p.shown(), ["ganit"])
        ch = go(p, "1")
        self.assertEqual(ch.hide, [("ganit", "away")])
        self.assertEqual(sorted(n for n, _ in ch.show), ["dvara", "kendra"])
        self.assertEqual(p.focus, "kendra")
        ch = go(p, "2")
        self.assertEqual(ch.show, [("ganit", "back")])
        self.assertEqual(p.focus, "ganit")

    def test_open_from_other_workspace_moves_it(self):
        p = two_ws()
        p.open("dvara", CENTER)
        go(p, "2")
        ch = p.open("dvara", CENTER)
        self.assertEqual(ch.hide, [("dvara", "closed")])
        self.assertEqual(p.entries["dvara"].ws, "2")
        ch = go(p, "1")
        self.assertEqual(ch.show, [])

    def test_restore_only_here(self):
        p = two_ws()
        p.open("dvara", CENTER)
        p.open("ganit", CENTER)
        go(p, "2")
        self.assertFalse(p.here("dvara"))
        self.assertEqual(p.restore("dvara").show, [])

    def test_two_outputs(self):
        p = Places()
        p.workspaces("1", {"A": "1", "B": "3"})
        p.open("dvara", CENTER)
        self.assertEqual(p.output_of("dvara"), "A")
        # focus the other output: dvara's workspace is still on screen
        ch = p.workspaces("3", {"A": "1", "B": "3"})
        self.assertEqual(ch.hide, [])
        self.assertEqual(p.shown(), ["dvara"])
        self.assertIsNone(p.focus)               # but the keyboard is over there
        self.assertFalse(p.here("dvara"))
        p.open("ganit", CENTER)                  # the centre of B is free
        self.assertEqual(p.output_of("ganit"), "B")
        self.assertEqual(sorted(p.shown()), ["dvara", "ganit"])
        ch = p.workspaces("1", {"A": "1", "B": "3"})
        self.assertEqual(p.focus, "dvara")

    def test_workspace_moves_to_other_output(self):
        p = Places()
        p.workspaces("1", {"A": "1", "B": "3"})
        p.open("dvara", CENTER)
        ch = p.workspaces("1", {"A": "2", "B": "1"})
        self.assertEqual(ch.move, [("dvara", "B")])
        self.assertEqual(ch.hide, [])
        self.assertEqual(p.output_of("dvara"), "B")

    def test_rename(self):
        p = two_ws()
        p.open("dvara", CENTER)
        p.renamed("1", "1:web")
        self.assertEqual(p.entries["dvara"].ws, "1:web")
        self.assertEqual(p.current, "1:web")
        self.assertEqual(p.shown(), ["dvara"])

    def test_no_compositor_info(self):
        p = Places()
        p.open("dvara", CENTER)
        p.open("kendra", TR)
        self.assertEqual(sorted(p.shown()), ["dvara", "kendra"])
        self.assertTrue(p.here("dvara"))
        # sway answers late: what's open belongs to the focused workspace
        ch = p.workspaces("4", {"A": "4"})
        self.assertEqual(ch.hide, [])
        self.assertEqual(p.entries["dvara"].ws, "4")


class Transient(unittest.TestCase):
    def test_loses_keys_closes(self):
        p = two_ws()
        p.open("dmenu", CENTER, transient=True)
        ch = p.window_took_keyboard()
        self.assertEqual(ch.hide, [("dmenu", "closed")])
        self.assertNotIn("dmenu", p.entries)

    def test_other_panel_opens_closes(self):
        p = two_ws()
        p.open("dmenu", CENTER, transient=True)
        ch = p.open("kendra", TR)
        self.assertIn(("dmenu", "closed"), ch.hide)

    def test_covered_closes(self):
        p = two_ws()
        p.open("dvara", CENTER)
        p.open("dmenu", CENTER, transient=True)
        self.assertTrue(p.entries["dvara"].covered)
        ch = p.restore("dvara")
        self.assertIn(("dmenu", "closed"), ch.hide)
        self.assertNotIn("dmenu", p.entries)

    def test_picker_over_panel_gives_it_back(self):
        p = two_ws()
        p.open("smriti", CENTER)
        p.open("dmenu", CENTER, transient=True)
        self.assertEqual(p.shown(), ["dmenu"])
        ch = p.close("dmenu")
        self.assertEqual(ch.show, [("smriti", "restore")])
        self.assertEqual(p.focus, "smriti")
        p.open("dmenu", CENTER, transient=True)
        ch = p.window_took_keyboard()
        self.assertEqual(ch.show, [("smriti", "restore")])
        self.assertIsNone(p.focus)
        self.assertEqual(p.shown(), ["smriti"])

    def test_panel_over_picker_keeps_what_was_under_covered(self):
        p = two_ws()
        p.open("smriti", CENTER)
        p.open("dmenu", CENTER, transient=True)
        ch = p.open("ganit", CENTER)
        self.assertIn(("dmenu", "closed"), ch.hide)
        self.assertEqual(ch.show, [("ganit", "open")])
        self.assertTrue(p.entries["smriti"].covered)
        self.assertEqual(p.shown(), ["ganit"])

    def test_workspace_left_closes(self):
        p = two_ws()
        p.open("dmenu", CENTER, transient=True)
        ch = go(p, "2")
        self.assertEqual(ch.hide, [("dmenu", "closed")])
        self.assertNotIn("dmenu", p.entries)


class ClearOf(unittest.TestCase):
    """A centre panel beside an edge panel (the user's 1920x1080: dvara
    1125x650 centred, kendra ~440x580 at the top right)."""
    S = (1920, 1080)
    KENDRA = edge_rect("top-right", (438, 580), (1920, 1080), {"top": 6, "right": 8})

    def test_edge_rect(self):
        self.assertEqual(self.KENDRA, (1474, 6, 438, 580))
        self.assertEqual(edge_rect("bottom-left", (100, 50), (1000, 800)), (0, 750, 100, 50))
        self.assertEqual(edge_rect("top", (100, 50), (1000, 800), {"top": 4}), (450, 4, 100, 50))

    def test_no_overlap_stays_centred(self):
        small = edge_rect("top-right", (200, 100), self.S)
        self.assertIsNone(clear_of(self.S, (1125, 650), [("top-right", small)]))
        self.assertIsNone(clear_of(self.S, (1125, 650), []))

    def test_moves_left_of_kendra(self):
        x, y, w = clear_of(self.S, (1125, 650), [("top-right", self.KENDRA)])
        self.assertEqual(w, 1125)                       # it fits: same width
        self.assertIsNone(y)                            # still centred vertically
        self.assertLessEqual(x + w, self.KENDRA[0] - 12)  # a gap from kendra
        self.assertGreaterEqual(x, 0)
        self.assertEqual(x, round(12 + (1474 - 12 - 12 - 1125) / 2))   # centred in the free area

    def test_shrinks_when_narrow(self):
        s = (1280, 800)
        k = edge_rect("top-right", (438, 580), s, {"top": 6, "right": 8})
        x, y, w = clear_of(s, (1125, 650), [("top-right", k)])
        self.assertLess(w, 1125)
        self.assertLessEqual(x + w, k[0] - 12)
        self.assertGreaterEqual(x, 12)                  # its usual gap from the screen's edge
        self.assertGreaterEqual(w, 640)

    def test_never_below_minimum(self):
        s = (1000, 800)
        k = edge_rect("top-right", (438, 580), s)
        x, y, w = clear_of(s, (900, 600), [("top-right", k)])
        self.assertEqual(w, 640)                         # overlaps rather than unusable

    def test_left_edge_and_both(self):
        left = edge_rect("left", (500, 900), self.S)
        x, y, w = clear_of(self.S, (1125, 650), [("left", left)])
        self.assertGreaterEqual(x, 500 + 12)
        both = [("left", left), ("top-right", self.KENDRA)]
        x, y, w = clear_of(self.S, (1125, 650), both)
        self.assertGreaterEqual(x, 512)
        self.assertLessEqual(x + w, self.KENDRA[0] - 12)
        self.assertEqual(w, 1474 - 12 - 512)            # narrower: the room between them

    def test_top_edge_moves_down(self):
        top = edge_rect("top", (1600, 300), self.S, {"top": 6})
        x, y, w = clear_of(self.S, (1125, 650), [("top", top)])
        self.assertGreaterEqual(y, 306 + 12)
        self.assertEqual(w, 1125)


class SwayIpc(unittest.TestCase):
    def test_roundtrip_and_partial(self):
        a = sway.pack(sway.GET_WORKSPACES, b"[]")
        b = sway.pack(sway.EV_WORKSPACE, json.dumps({"change": "focus"}))
        msgs, rest = sway.unpack(a + b[:5])
        self.assertEqual(msgs, [(sway.GET_WORKSPACES, b"[]")])
        msgs, rest = sway.unpack(rest + b[5:])
        self.assertEqual(rest, b"")
        self.assertEqual(msgs[0][0], sway.EV_WORKSPACE)

    def test_garbage(self):
        with self.assertRaises(ValueError):
            sway.unpack(b"HTTP/1.1 200 OK\r\n\r\n")

    def test_summarize(self):
        ws = [{"id": 4, "name": "1", "visible": True, "focused": False, "output": "A"},
              {"id": 7, "name": "2", "visible": False, "focused": False, "output": "A"},
              {"id": 9, "name": "3", "visible": True, "focused": True, "output": "B"}]
        self.assertEqual(sway.summarize(ws), ("3", {"A": "1", "B": "3"}, {4: "1", 7: "2", 9: "3"}))

    def test_watch_asks_once_per_burst(self):
        got = []
        w = sway.Watch(lambda *a: got.append(a), path="/nonexistent")
        sent = []
        w.sock = type("S", (), {"sendall": lambda self, b: sent.append(b)})()
        w.asked = False
        w.handle(sway.EV_WORKSPACE, json.dumps({"change": "focus"}).encode())
        w.handle(sway.EV_WORKSPACE, json.dumps({"change": "focus"}).encode())
        w.handle(sway.EV_WORKSPACE, json.dumps({"change": "urgent"}).encode())
        self.assertEqual(len(sent), 1)
        w.handle(sway.GET_WORKSPACES, json.dumps([{"id": 1, "name": "2", "visible": True,
                                                    "focused": True, "output": "A"}]).encode())
        self.assertEqual(got, [("2", {"A": "2"}, {1: "2"})])
        w.handle(sway.EV_OUTPUT, b'{"change": "unspecified"}')
        self.assertEqual(len(sent), 2)
        w.sock = None
        w.handle(sway.EV_SHUTDOWN, b'{"change": "exit"}')

    def test_focus_event_tells_at_once(self):
        got = []
        w = sway.Watch(lambda *a: got.append(a), path="/nonexistent")
        w.sock = type("S", (), {"sendall": lambda self, b: None})()
        w.handle(sway.GET_WORKSPACES, json.dumps([
            {"id": 1, "name": "1", "visible": True, "focused": True, "output": "A"},
            {"id": 3, "name": "3", "visible": True, "focused": False, "output": "B"}]).encode())
        ev = {"change": "focus", "current": {"id": 2, "name": "2", "output": "A"}, "old": {"id": 1, "name": "1"}}
        w.handle(sway.EV_WORKSPACE, json.dumps(ev).encode())
        self.assertEqual(got[-1], ("2", {"A": "2", "B": "3"}, {1: "1", 3: "3", 2: "2"}))
        n = len(got)
        w.handle(sway.GET_WORKSPACES, json.dumps([   # the same again: not told twice
            {"id": 1, "name": "1", "visible": False, "focused": False, "output": "A"},
            {"id": 2, "name": "2", "visible": True, "focused": True, "output": "A"},
            {"id": 3, "name": "3", "visible": True, "focused": False, "output": "B"}]).encode())
        self.assertEqual(len(got), n)

    def test_socket_path(self):
        self.assertIsNone(sway.socket_path({}))
        self.assertEqual(sway.socket_path({"SWAYSOCK": __file__}), __file__)


class Settling(unittest.TestCase):
    """Focus notices while Vyom's own change reaches sway are its own: until
    a moment after the panel paints the frame carrying it, however late."""

    def test_slow_first_frame(self):
        # kendra opened beside dvara over a window; its first frame came 270 ms
        # after the key, and sway's handover blip with it (seen headless): that
        # blip is no click on a window.
        s = Settle()
        s.hold("kendra", 10.0)
        self.assertFalse(s.quiet(10.27))           # no frame yet: still Vyom's
        s.painted("kendra", 10.27)
        self.assertFalse(s.quiet(10.273))          # the blip, right after the frame
        self.assertFalse(s.quiet(10.27 + Settle.AFTER - 0.01))
        self.assertTrue(s.quiet(10.27 + Settle.AFTER))   # then a loss is yours

    def test_quick_frame_as_before(self):
        s = Settle()
        s.hold("dvara", 5.0)
        s.painted("dvara", 5.01)
        self.assertFalse(s.quiet(5.2))
        self.assertTrue(s.quiet(5.27))

    def test_frame_that_never_comes(self):
        s = Settle()
        s.hold("ganit", 1.0)                       # hidden before it painted
        self.assertFalse(s.quiet(1.0 + Settle.HOLD - 0.01))
        self.assertTrue(s.quiet(1.0 + Settle.HOLD))
        s.painted("ganit", 9.0)                    # a late frame after: nothing held, no new settling
        self.assertTrue(s.quiet(9.0))

    def test_every_held_panel_paints(self):
        s = Settle()
        s.hold("dvara", 0.0)
        s.hold("kendra", 0.0)
        s.painted("dvara", 0.05)
        self.assertFalse(s.quiet(1.0))             # kendra hasn't painted
        s.painted("kendra", 1.0)
        self.assertTrue(s.quiet(1.0 + Settle.AFTER))

    def test_now(self):
        s = Settle()
        s.now(3.0)
        self.assertFalse(s.quiet(3.1))
        self.assertTrue(s.quiet(3.0 + Settle.AFTER))
        s.now(4.0, 1.0)
        self.assertFalse(s.quiet(4.9))
        self.assertTrue(s.quiet(5.0))


if __name__ == "__main__":
    unittest.main()
