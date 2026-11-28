"""A keystroke searches at once; keystrokes during a search are one search
after it (Panel.refresh_soon / _landed). Needs PyGObject; skipped without it."""
import importlib
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gtk4LayerShell", "1.0")
    panel = importlib.import_module("vyom.panel")
except Exception:  # noqa: BLE001 - no GTK or layer shell here
    panel = None


@unittest.skipIf(panel is None, "needs PyGObject with GTK 4 and gtk4-layer-shell")
class SearchNow(unittest.TestCase):
    def make(self, debounce=40):
        p = panel.Panel.__new__(panel.Panel)
        p.plugin = types.SimpleNamespace(layout="list", debounce=debounce)
        p.pending = None
        p.in_flight = False
        p.queued = False
        p.searching = False
        p.gen = 0
        p.runs = []

        def now(keep_selection=False):
            p.gen += 1
            p.in_flight = True
            p.runs.append(p.gen)
        p.refresh_now = now
        p.show_results = lambda *a: None
        return p

    def test_first_key_searches_at_once(self):
        p = self.make()
        p.refresh_soon()
        self.assertEqual(p.runs, [1])
        self.assertIsNone(p.pending)

    def test_keys_during_a_search_are_one_more_search(self):
        p = self.make()
        p.refresh_soon()
        p.refresh_soon()
        p.refresh_soon()
        self.assertEqual(p.runs, [1])
        self.assertTrue(p.queued)
        p._landed(1, [], None)
        self.assertEqual(p.runs, [1, 2])
        self.assertFalse(p.queued)
        p._landed(2, [], None)
        self.assertEqual(p.runs, [1, 2])
        self.assertFalse(p.in_flight)

    def test_a_stale_result_keeps_the_newer_search_in_flight(self):
        p = self.make()
        p.refresh_soon()
        p.refresh_now()           # a live refresh started meanwhile (gen 2)
        p._landed(1, [], None)
        self.assertTrue(p.in_flight)

    def test_a_long_debounce_still_waits(self):
        p = self.make(debounce=700)
        p.refresh_soon()
        self.assertEqual(p.runs, [])
        self.assertIsNotNone(p.pending)
        panel.GLib.source_remove(p.pending)


if __name__ == "__main__":
    unittest.main()
