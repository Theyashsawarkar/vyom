"""Volume and brightness steps (vyom/osd.py): the level, the clamp, mute at
0%, bursts stacking on the level asked for. Needs PyGObject."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from vyom import live, osd
except Exception:  # noqa: BLE001 - no PyGObject here
    osd = None


@unittest.skipIf(osd is None, "needs PyGObject")
class Steps(unittest.TestCase):
    def setUp(self):
        self.state = {"volume": {"volume": 40, "muted": False},
                      "brightness": {"device": "bl0", "brightness": 500, "max": 1000, "percent": 50}}
        self.get, live.get = live.get, lambda name: dict(self.state[name]) if name in self.state else None
        self.o = osd._Osd()
        self.shown, self.ran, self.bri = [], [], []
        self.o.show = lambda summary, body, icon, value: self.shown.append((summary, body, icon, value))
        self.o._run = lambda steps: self.ran.append(steps) or setattr(self.o, "running", True)
        self.o.set_brightness = lambda device, val, pct: self.bri.append((device, val, pct))

    def tearDown(self):
        live.get = self.get

    def test_step_up_shows_first_and_sets_once(self):
        self.assertTrue(self.o.volume("+5"))
        self.assertEqual(self.shown, [("Volume", "45%", "audio-volume-medium", 45)])
        self.assertEqual(self.ran, [[["pactl", "set-sink-volume", "@DEFAULT_SINK@", "45%"]]])

    def test_burst_stacks_and_waits_for_the_running_one(self):
        for _ in range(3):
            self.o.volume("+5")
        self.assertEqual([s[3] for s in self.shown], [45, 50, 55])
        self.assertEqual(len(self.ran), 1)            # one pactl at a time
        self.assertEqual(self.o.queued, (55, False))  # the latest level after it

    def test_clamped_and_zero_mutes(self):
        self.state["volume"] = {"volume": 98, "muted": False}
        self.o.volume("+5")
        self.assertEqual(self.shown[-1][3], 100)
        o = osd._Osd()
        o.show, o._run = self.o.show, self.o._run
        self.state["volume"] = {"volume": 3, "muted": False}
        o.volume("-5")
        self.assertEqual(self.shown[-1], ("Volume", "Muted", "audio-volume-muted", 0))
        self.assertIn(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], self.ran[-1])

    def test_raising_unmutes(self):
        self.state["volume"] = {"volume": 30, "muted": True}
        self.o.volume("+5")
        self.assertIn(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], self.ran[-1])

    def test_mute_toggle(self):
        self.o.volume("mute-toggle")
        self.assertEqual(self.shown[-1][1], "Muted")
        self.assertEqual(self.ran[-1], [["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"]])

    def test_unknown_level_says_no(self):
        del self.state["volume"]
        self.assertFalse(self.o.volume("+5"))
        self.assertFalse(osd.step("nonsense +5"))

    def test_brightness(self):
        self.assertTrue(self.o.brightness("+5"))
        self.assertEqual(self.bri, [("bl0", 550, 55)])
        self.o.brightness("-10")
        self.assertEqual(self.bri[-1], ("bl0", 450, 45))   # from the level asked for, not the old one
        self.assertEqual(self.shown[-1], ("Brightness", "45%", "display-brightness", 45))


if __name__ == "__main__":
    unittest.main()
