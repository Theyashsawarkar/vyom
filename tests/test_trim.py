"""util.trim_memory(): glibc's malloc_trim, or a no-op without it."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vyom import util  # noqa: E402


class Trim(unittest.TestCase):
    def test_returns_a_bool_and_can_run_again(self):
        junk = [bytes(4096) for _ in range(20000)]   # ~80 MB to free
        del junk
        self.assertIsInstance(util.trim_memory(), bool)
        self.assertIsInstance(util.trim_memory(), bool)

    def test_without_malloc_trim_it_does_nothing(self):
        saved = util._malloc_trim
        try:
            util._malloc_trim = False
            self.assertFalse(util.trim_memory())
        finally:
            util._malloc_trim = saved


if __name__ == "__main__":
    unittest.main()
