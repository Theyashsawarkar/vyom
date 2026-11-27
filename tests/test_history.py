"""vyom.live's histories: the network speed bins and the battery record."""
import time
import unittest

from vyom import live


class NetBins(unittest.TestCase):
    def test_steady_one_second(self):
        r = [(t, t * 1000, t * 10) for t in range(0, 11)]
        rx, tx = live.net_bins(r, step=1, window=60)
        self.assertEqual(len(rx), 10)
        self.assertTrue(all(abs(v - 1000) < 1e-6 for v in rx))
        self.assertTrue(all(abs(v - 10) < 1e-6 for v in tx))

    def test_two_second_readings_fill_one_second_bins(self):
        # the always-on reading is every 2 s; a graph by the second gets each value twice
        r = [(0, 0, 0), (2, 4000, 0), (4, 4000, 0), (6, 10000, 0)]
        rx, _ = live.net_bins(r, step=1, window=60)
        self.assertEqual([round(v) for v in rx], [2000, 2000, 0, 0, 3000, 3000])

    def test_mixed_rates_and_two_second_bins(self):
        r = [(0, 0, 0), (2, 2000, 0), (3, 4000, 0), (4, 6000, 0)]
        rx, _ = live.net_bins(r, step=2, window=60)
        self.assertEqual([round(v) for v in rx], [1000, 2000])

    def test_window_keeps_the_newest(self):
        r = [(t, t * 100, 0) for t in range(0, 200, 2)]
        rx, _ = live.net_bins(r, step=1, window=60)
        self.assertEqual(len(rx), 60)

    def test_gap_and_counter_reset_are_zero_not_a_spike(self):
        r = [(0, 0, 0), (1, 1000, 0), (31, 9_000_000, 0), (32, 9_001_000, 0), (33, 10, 0), (34, 1010, 0)]
        rx, _ = live.net_bins(r, step=1, window=60, gap=6)
        self.assertEqual(max(rx), 1000)
        self.assertEqual(rx[-2], 0)

    def test_too_little(self):
        self.assertEqual(live.net_bins([], 1, 60), ([], []))
        self.assertEqual(live.net_bins([(5, 1, 1)], 1, 60), ([], []))


class Counters(unittest.TestCase):
    def test_reads_sysfs_layout(self):
        import os
        import tempfile
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "demo0", "statistics"))
        for k, v in (("rx_bytes", "1234\n"), ("tx_bytes", "56\n")):
            with open(os.path.join(d, "demo0", "statistics", k), "w") as f:
                f.write(v)
        self.assertEqual(live.net_counters("demo0", d), (1234, 56))
        self.assertIsNone(live.net_counters("nope0", d))


class Battery(unittest.TestCase):
    def test_upower_record_then_changes_and_the_point_before(self):
        h = live.BatteryHistory()
        now = time.time()
        h._add((now - 10, 80.0, False))         # a change heard before UPower answered

        class Res:
            pass

        class Proxy:
            def call_finish(self, _res):
                class V:
                    @staticmethod
                    def unpack():
                        return ([(int(now - 30 * 3600), 50.0, 1), (int(now - 6 * 3600), 99.0, 4),
                                 (int(now - 3600), 90.0, 2)],)
                return V()
        h._got(Proxy(), Res())
        pts = h.history(seconds=3 * 3600)
        self.assertEqual([p[1] for p in pts], [99.0, 90.0, 80.0])   # the one before the window first
        self.assertFalse(pts[0][2])
        # unchanged readings aren't kept twice
        h._add((now, 80.0, False))
        self.assertEqual(len(h.history()), 3)


if __name__ == "__main__":
    unittest.main()
