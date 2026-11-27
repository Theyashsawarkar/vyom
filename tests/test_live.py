"""vyom.live: helpers die with Vyom, and the pure parts (no buses touched).

The volume source's `pactl subscribe` is a fake here (a script on a private
PATH, in a private XDG_RUNTIME_DIR): nothing reaches a real sound server."""
import json
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

    def test_sink_summary(self):
        sinks = [{"name": "a", "description": "Built-in", "mute": False, "active_port": "analog-output-speaker",
                  "volume": {"front-left": {"value_percent": "40%"}, "front-right": {"value_percent": "45%"}},
                  "properties": {"device.bus": "pci", "device.api": "alsa"}},
                 {"name": "b", "description": "Demo Buds", "mute": True, "volume": {"mono": {"value_percent": "70%"}},
                  "properties": {"device.bus": "bluetooth", "device.api": "bluez5", "device.form-factor": "headset"}}]
        self.assertEqual(live.sink_summary("a", sinks),
                         {"sink": "a", "device": "Built-in", "volume": 42, "muted": False, "bus": "pci",
                          "api": "alsa", "form_factor": "", "port": "analog-output-speaker"})
        b = live.sink_summary("b", sinks)
        self.assertEqual((b["volume"], b["muted"], b["bus"], b["form_factor"], b["port"]),
                         (70, True, "bluetooth", "headset", ""))
        self.assertEqual(live.sink_summary("gone", sinks), {"sink": ""})
        self.assertEqual(live.sink_summary("", []), {"sink": ""})

    def test_hand_driven_sources_publish_sooner(self):
        self.assertEqual(live.Volume.publish_every, 0)
        self.assertLess(live.Brightness.publish_every, live.Source.publish_every)

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


class VolumeFile(unittest.TestCase):
    """The volume source, published to a state file at once, from a fake
    pactl (its JSON as pactl 16+ prints it)."""

    def test_follows_the_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bindir, rt, state = tmp / "bin", tmp / "rt", tmp / "state"
            bindir.mkdir()
            rt.mkdir(mode=0o700)
            events, sinks = tmp / "events", tmp / "sinks.json"
            events.touch()

            def set_sinks(pct, bus="pci", desc="Demo Built-in Audio"):
                tmpf = tmp / "s.tmp"
                tmpf.write_text(json.dumps([{
                    "name": "demo", "description": desc, "mute": False, "active_port": "analog-output-speaker",
                    "volume": {"front-left": {"value_percent": f"{pct}%"}}, "properties": {"device.bus": bus}}]))
                os.replace(tmpf, sinks)
            set_sinks(40)
            fake = bindir / "pactl"
            fake.write_text(textwrap.dedent(f"""\
                #!/bin/sh
                case "$*" in
                  subscribe) exec tail -n0 -F {events} ;;
                  get-default-sink) echo demo ;;
                  "-f json list sinks") cat {sinks} ;;
                  *) exit 1 ;;
                esac
                """))
            fake.chmod(0o755)
            child = textwrap.dedent(f"""\
                import sys
                sys.path.insert(0, {str(ROOT)!r})
                from gi.repository import GLib
                from vyom import live
                live._exporter = live.Exporter(None, {str(state)!r})
                live._source("volume")
                GLib.MainLoop().run()
                """)
            env = dict(os.environ, PATH=f"{bindir}:/usr/bin:/bin", XDG_RUNTIME_DIR=str(rt))
            p = subprocess.Popen([sys.executable, "-c", child], env=env)
            out = state / "volume.json"

            def wait_for(pred):
                for _ in range(200):
                    try:
                        v = json.loads(out.read_text())
                        if pred(v):
                            return v
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.01)
                self.fail(f"volume.json never matched: {out.read_text() if out.exists() else None}")
            try:
                v = wait_for(lambda v: v and v.get("volume") == 40)
                self.assertEqual((v["device"], v["bus"], v["port"]),
                                 ("Demo Built-in Audio", "pci", "analog-output-speaker"))
                # two quick steps: both published, no 250 ms wait between them
                set_sinks(45)
                with events.open("a") as f:
                    f.write("Event 'change' on sink #5\n")
                wait_for(lambda v: v.get("volume") == 45)
                t = time.monotonic()
                set_sinks(50, "bluetooth", "Demo Buds")
                with events.open("a") as f:
                    f.write("Event 'change' on server #-1\n")
                v = wait_for(lambda v: v.get("volume") == 50)
                self.assertLess(time.monotonic() - t, 0.2)
                self.assertEqual((v["bus"], v["device"]), ("bluetooth", "Demo Buds"))
                # an app's stream changing isn't the output: nothing is read
                set_sinks(60)
                with events.open("a") as f:
                    f.write("Event 'change' on sink-input #9\n")
                time.sleep(0.3)
                self.assertEqual(json.loads(out.read_text())["volume"], 50)
            finally:
                p.send_signal(signal.SIGKILL)
                p.wait()


if __name__ == "__main__":
    unittest.main()
