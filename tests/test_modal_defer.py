"""Moves typed before the results arrive wait for them (Modal.run / flush).
Needs PyGObject (modal.py imports Gtk); skipped without it."""
import importlib
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    import gi
    gi.require_version("Gtk", "4.0")
    modal = importlib.import_module("vyom.modal")
except Exception:  # noqa: BLE001 - no GTK here
    modal = None


@unittest.skipIf(modal is None, "needs PyGObject with GTK 4")
class Defer(unittest.TestCase):
    def make(self, searching):
        m = modal.Modal.__new__(modal.Modal)
        moved = []
        m.p = types.SimpleNamespace(searching=searching, move=moved.append, items=[1], sel=0)
        m.plugin = types.SimpleNamespace(layout="list", grid_columns=1, name="t")
        m.deferred = []
        m.machine = types.SimpleNamespace(typed=lambda: "", pending="")
        m.typed = types.SimpleNamespace(set_label=lambda *_: None, set_visible=lambda *_: None)
        m.over = None
        m.which = types.SimpleNamespace(set_visible=lambda *_: None)
        return m, moved

    def test_waits_while_searching(self):
        m, moved = self.make(searching=True)
        m.run(modal.K.Bind("j", "down", "Move down"), 4)
        self.assertEqual(moved, [])
        m.p.searching = False
        m.flush()
        self.assertEqual(moved, [4])

    def test_runs_at_once_otherwise(self):
        m, moved = self.make(searching=False)
        m.run(modal.K.Bind("j", "down", "Move down"), 2)
        self.assertEqual(moved, [2])

    def test_modifier_enter_waits_too(self):
        m, _ = self.make(searching=True)
        got = []
        m.p.activate = lambda sel, mods: got.append(mods)
        m.activate_with({"shift"})
        self.assertEqual(got, [])
        m.p.searching = False
        m.flush()
        self.assertEqual(got, [{"shift"}])


@unittest.skipIf(modal is None, "needs PyGObject with GTK 4")
class CardTabs(unittest.TestCase):
    def test_tab_in_insert_mode_switches_tabs_on_a_card(self):
        """Tab in a card's INSERT mode switches tabs (as without vim keys);
        it never takes the focus out of the box you type in (ganit)."""
        m = modal.Modal.__new__(modal.Modal)
        m.p = types.SimpleNamespace(preview_scroll=None, tab_buttons={"a": 1, "b": 2})
        m.plugin = types.SimpleNamespace(layout="card", tabs=[("a", "Alpha"), ("b", "Beta")], card_cursor=False,
                                         editables=lambda: [object()])
        table = {b.seq: b for b in m.core_binds() if b.mode == "insert"}
        self.assertEqual(table["<Tab>"].action, "tab:+1")
        self.assertEqual(table["<S-Tab>"].action, "tab:-1")


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(modal is None, "needs PyGObject with GTK 4")
class WantsAllKeys(unittest.TestCase):
    """A busy tool (vishram's countdown) sees the next key even while a key
    is half-typed or the palette is open; what was pending is dropped."""

    def make(self, busy, pending="", over=None):
        m = modal.Modal.__new__(modal.Modal)
        seen = []
        m.plugin = types.SimpleNamespace(
            layout="card", name="t", keys_to_widget=lambda: False, wants_all_keys=lambda: busy,
            key=lambda name, row, mods: (seen.append(name), True)[1])
        m.p = types.SimpleNamespace(selected_row=lambda: None)
        m.machine = modal.K.Machine()
        m.machine.pending = pending
        m.over, m.confirm_q = over, (("Delete?", lambda: seen.append("ran")) if over == "confirm" else None)
        m.show_typed = lambda: None
        m.draw = lambda: None
        return m, seen

    def test_pending_space_is_dropped_and_the_tool_sees_the_key(self):
        m, seen = self.make(busy=True, pending=" ")
        self.assertTrue(m.key("j", set()))
        self.assertEqual(seen, ["j"])
        self.assertEqual(m.machine.pending, "")

    def test_open_confirm_is_dropped_not_answered(self):
        m, seen = self.make(busy=True, over="confirm")
        self.assertTrue(m.key("y", set()))
        self.assertEqual(seen, ["y"])       # the tool got it; the confirm didn't run
        self.assertIsNone(m.over)

    def test_not_busy_keeps_the_pending_key(self):
        m, seen = self.make(busy=False, pending=" ")
        m.normal_key = lambda name, tok, mods: (seen.append("normal:" + name), True)[1]
        m.mode = "normal"
        m.key("j", set())
        self.assertEqual(seen, ["normal:j"])
        self.assertEqual(m.machine.pending, " ")
