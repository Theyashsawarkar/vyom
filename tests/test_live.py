"""vyom.live: helpers die with Vyom, and the pure parts (no buses touched).

The volume source's `pactl subscribe` is a fake here (a script on a private
PATH, in a private XDG_RUNTIME_DIR): nothing reaches a real sound server."""
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from vyom import live  # noqa: E402


class Pure(unittest.TestCase):
    def test_security_words(self):
        self.assertEqual(live.ap_security(0, 0, 0), "")
        self.assertEqual(live.ap_security(1, 0, 0), "WEP")
        self.assertEqual(live.ap_security(1, 0, 0x188), "WPA2")
        self.assertEqual(live.ap_security(1, 0x188, 0x188), "WPA1 WPA2")
        self.assertEqual(live.ap_security(1, 0, 0x588), "WPA2 WPA3")
        self.assertEqual(live.ap_security(1, 0, 0x288), "WPA2 802.1X")

    def test_channels(self):
        self.assertEqual(live.channel(2437), 6)
        self.assertEqual(live.channel(5180), 36)
        self.assertEqual(live.channel(5955), 1)

    def test_unknown_source(self):
        self.assertIsNone(live.get("no-such-source"))
        self.assertIsNone(live.watch("no-such-source", print))


def running(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


class HelpersDieWithVyom(unittest.TestCase):
    def test_sigkill_parent_takes_the_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bindir, rt = tmp / "bin", tmp / "rt"
            bindir.mkdir()
            rt.mkdir(mode=0o700)
            pidfile = tmp / "child.pid"
            fake = bindir / "pactl"
            fake.write_text(textwrap.dedent(f"""\
                #!/bin/sh
                [ "$1" = subscribe ] || exit 1
                echo $$ > {pidfile}
                exec sleep 300
                """))
            fake.chmod(0o755)
            parent = textwrap.dedent(f"""\
                import sys
                sys.path.insert(0, {str(ROOT)!r})
                from gi.repository import GLib
                from vyom import live
                live.start("volume")
                GLib.MainLoop().run()
                """)
            env = dict(os.environ, PATH=f"{bindir}:/usr/bin:/bin", XDG_RUNTIME_DIR=str(rt))
            env.pop("PULSE_SERVER", None)
            p = subprocess.Popen([sys.executable, "-c", parent], env=env)
            try:
                for _ in range(100):
                    if pidfile.exists() and pidfile.read_text().strip():
                        break
                    time.sleep(0.05)
                child = int(pidfile.read_text())
                self.assertTrue(running(child))
            finally:
                p.send_signal(signal.SIGKILL)
                p.wait()
            for _ in range(100):
                if not running(child):
                    break
                time.sleep(0.05)
            alive = running(child)
            if alive:
                os.kill(child, signal.SIGKILL)
            self.assertFalse(alive, "pactl subscribe outlived Vyom")


if __name__ == "__main__":
    unittest.main()
