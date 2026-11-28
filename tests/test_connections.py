"""vyom.live's connections (Vyom 0.12): every kind of active connection
classified and ordered, the primary first, a VPN after what it rides on.
Pure functions: no bus touched."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vyom import live  # noqa: E402


class Kind(unittest.TestCase):
    def test_every_kind(self):
        k = live.conn_kind
        self.assertEqual(k("802-3-ethernet", 1, "e1000e", "enp3s0"), ("ethernet", "Ethernet"))
        self.assertEqual(k("802-11-wireless", 2, "iwlwifi", "wlan0"), ("wifi", "Wi-Fi"))
        self.assertEqual(k("802-11-wireless", 2, "iwlwifi", "wlan0", mode="ap"), ("hotspot", "Hotspot"))
        self.assertEqual(k("802-3-ethernet", 1, "rndis_host", "usb0"), ("usb", "USB"))
        self.assertEqual(k("802-3-ethernet", 1, "ipheth", "eth1"), ("usb", "USB"))
        self.assertEqual(k("gsm", 8, "qmi_wwan", "wwan0"), ("mobile", "Mobile"))
        self.assertEqual(k("bluetooth", 5, "", "bnep0"), ("bluetooth", "Bluetooth"))
        self.assertEqual(k("vpn", 1, "e1000e", "enp3s0", vpn=True), ("vpn", "VPN"))
        self.assertEqual(k("wireguard", 29, "", "wg0"), ("wireguard", "WireGuard"))
        self.assertEqual(k("tun", 16, "", "tailscale0", external=True), ("vpn", "VPN"))

    def test_plumbing_is_left_out(self):
        k = live.conn_kind
        self.assertIsNone(k("loopback", 32, "", "lo", external=True))
        self.assertIsNone(k("bridge", 13, "bridge", "docker0", external=True))
        self.assertIsNone(k("bridge", 13, "bridge", "br-6cde592b51ae", external=True))
        self.assertIsNone(k("bridge", 13, "bridge", "virbr0"))
        self.assertIsNone(k("802-3-ethernet", 20, "veth", "veth37f6bd3"))
        self.assertEqual(k("bridge", 13, "bridge", "br0"), ("bridge", "Bridge"))   # your own bridge is your way out


def c(name, kind, primary=False, default=False, dev="", vpn=False, base="", path="", gw=""):
    return {"name": name, "type": kind, "primary": primary, "default": default, "device": dev, "vpn": vpn,
            "base_device": base, "device_path": path, "gateway": gw}


class Order(unittest.TestCase):
    def test_primary_first(self):
        conns = [c("Home", "wifi", dev="wlan0"), c("Wired", "ethernet", primary=True, default=True, dev="eth0")]
        self.assertEqual([x["name"] for x in live.order_connections(conns)], ["Wired", "Home"])

    def test_vpn_rides_on_its_device(self):
        conns = [c("Office VPN", "vpn", vpn=True, base="/d/wlan", primary=True, default=True),
                 c("Wired", "ethernet", dev="eth0", path="/d/eth", gw="10.0.0.1"),
                 c("Home", "wifi", dev="wlan0", path="/d/wlan", gw="192.168.1.1")]
        out = live.order_connections(conns)
        self.assertEqual([x["name"] for x in out], ["Home", "Office VPN", "Wired"])
        self.assertEqual(out[1]["via"], "Home")
        self.assertEqual(out[1]["via_device"], "wlan0")

    def test_wireguard_rides_on_the_default_route(self):
        conns = [c("wg0", "wireguard", vpn=True, dev="wg0", primary=True, default=True),
                 c("Home", "wifi", dev="wlan0", gw="192.168.1.1"),
                 c("Wired", "ethernet", dev="eth0", default=True, gw="10.0.0.1")]
        out = live.order_connections(conns)
        self.assertEqual([x["name"] for x in out], ["Wired", "wg0", "Home"])
        self.assertEqual(out[1]["via"], "Wired")

    def test_hotspot_last(self):
        conns = [c("Hotspot", "hotspot", dev="wlan0"), c("Phone", "usb", dev="usb0", default=True)]
        self.assertEqual([x["name"] for x in live.order_connections(conns)], ["Phone", "Hotspot"])


class Settings(unittest.TestCase):
    def test_vpn_server(self):
        self.assertEqual(live.vpn_server({"vpn": {"data": {"remote": "vpn.example.org:1194, b.example.org"}}}),
                         "vpn.example.org:1194")
        self.assertEqual(live.vpn_server({"vpn": {"data": {"gateway": "gw.example.org"}}}), "gw.example.org")
        self.assertEqual(live.vpn_server({"wireguard": {"peers": [{"endpoint": "203.0.113.5:51820"}]}}),
                         "203.0.113.5:51820")
        self.assertEqual(live.vpn_server({}), "")

    def test_link_speed_and_duplex_from_sysfs(self):
        d = tempfile.mkdtemp()
        for dev, speed, duplex in (("eth9", "1000\n", "full\n"), ("wl9", "-1\n", "unknown\n")):
            os.makedirs(os.path.join(d, dev))
            for k, v in (("speed", speed), ("duplex", duplex)):
                with open(os.path.join(d, dev, k), "w") as f:
                    f.write(v)
        old = live.SYS_NET
        live.SYS_NET = d
        try:
            self.assertEqual(live.link_speed("eth9"), 1000)
            self.assertEqual(live.link_duplex("eth9"), "full")
            self.assertEqual(live.link_speed("wl9"), 0)
            self.assertEqual(live.link_duplex("wl9"), "")
            self.assertEqual(live.link_speed("nope"), 0)
        finally:
            live.SYS_NET = old


if __name__ == "__main__":
    unittest.main()
