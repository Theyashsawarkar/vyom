"""Live system state, shared by every panel and exported (Vyom 0.9, ADR 12).

A panel that shows the system (Wi-Fi, Bluetooth, the battery, the power
profile, volume, brightness) used to ask for it each time it opened:
nmcli, bluetoothctl, powerprofilesctl, wpctl, 10-170 ms each, so the
panel showed old numbers or waited. Here each source is followed once,
for the daemon's whole life, by the signals its daemon sends anyway
(D-Bus PropertiesChanged and friends, PulseAudio/PipeWire's subscribe,
the kernel's backlight uevents). Nothing polls: with nothing changing,
nothing wakes. Reading it is a look at memory.

    from vyom import live
    snap = live.get("wifi")        # a dict, at once; None while it's not known
    h = live.watch("wifi", fn)     # fn(snap) on the main loop when it changes
    live.unwatch(h)

Sources (each starts on its first get() or watch(), then keeps running):

  wifi           NetworkManager: radio, the Wi-Fi device, access points,
                 the network you're on, addresses, saved networks, wired;
                 "connections": every active connection, whatever its kind
                 (Wi-Fi, Ethernet, USB tethering, mobile, Bluetooth, VPN,
                 WireGuard), the primary one first (Vyom 0.12)
  bluetooth      BlueZ: the adapter and every device (battery, connected...)
  battery        UPower: the display device and every device with a battery
  power_profiles power-profiles-daemon: the active profile and the choices
  volume         the default output's volume, mute and name
  brightness     the first backlight's level
  units          systemd user units' ActiveState (live.track_unit(name) adds one)
  theme          GNOME's colour scheme and GTK theme (GSettings)

The daemon also publishes every source for other programs (bars, scripts):
the D-Bus object /dev/vayu/Vyom/State (interface dev.vayu.Vyom.State: a
JSON string property per source, PropertiesChanged when one changes, and
Get(name)), and $XDG_RUNTIME_DIR/vayu/state/<name>.json, replaced (atomic
rename) only when its contents change. Both hold a summary (Wi-Fi without
the scan list); a (re)started Vyom writes everything fresh.

Graphs draw what live has kept since the daemon started (Vyom 0.10):

    live.history("net")            # the last minute of speeds, per device
    live.history("battery")        # the charge over the last hours
    h = live.watch("net", fn, fast=True)   # fn(None) on each new reading

  net            each connected device's byte counters (sysfs, no command;
                 every kind of connection),
                 read every 2 s for the daemon's life (every second while a
                 panel draws them), the last minute kept: nothing connected,
                 no timer
  battery        UPower's own charge record, read once, then every change
                 its signals bring: no timer

Neither is exported in the state files or pushed on D-Bus (readings every
2 s would wake every program that follows them); dev.vayu.Vyom.State's
History(name) method returns one as JSON when asked.

get() is safe from any thread (a search() worker reads it too); watch()
callbacks and everything else run on the GTK main loop. A tool that must
work with an older Vyom imports this in a try and keeps its old path:

    try:
        from vyom import live
    except ImportError:
        live = None
"""
import collections
import copy
import glob
import logging
import os
import re
import shutil
import time

from gi.repository import Gio, GLib

log = logging.getLogger("vyom.state")
# where the network devices' counters, speed and duplex are read; the
# headless tests point it at made-up ones (a fake NetworkManager's devices
# have no sysfs of their own)
SYS_NET = os.environ.get("VYOM_SYS_NET") or "/sys/class/net"

_sources = {}


def get(name):
    """The source's current state (a fresh dict), or None while it isn't
    known: not started yet, its daemon isn't running, no such hardware."""
    src = _source(name)
    if src is None:
        return None
    try:
        return src.get()
    except Exception:   # a half-built cache must never take a panel down
        log.exception("state %s", name)
        return None


def watch(name, fn, fast=False):
    """Calls fn(snapshot) on the main loop whenever the source changes
    (several changes in a row come as one call), and once when it first
    becomes known. Returns a handle for unwatch().

    watch("net", fn) calls fn(None) after each new throughput reading
    (history("net") has it); fast=True asks for one a second instead of
    every two while the handle lives (a graph drawn by the second)."""
    if name not in SOURCES and name in HISTORIES:
        h = _history(name)
        return h.watch(fn, fast) if h is not None else None
    src = _source(name)
    if src is None:
        return None
    src.watchers.append(fn)
    src.watched(True)
    return (name, fn)


def unwatch(handle):
    if not handle:
        return
    if handle[0] not in SOURCES and handle[0] in _histories:
        _histories[handle[0]].unwatch(handle)
        return
    src = _sources.get(handle[0])
    if src is not None and handle[1] in src.watchers:
        src.watchers.remove(handle[1])
        src.watched(bool(src.watchers))


def history(name, **kw):
    """What a graph draws, kept since the daemon started (Vyom 0.10):

      history("net", dev=None, step=1, window=60)
          {"dev": "wlan0", "step": 1, "rx": [bytes/s...], "tx": [...],
           "totals": (rx_bytes, tx_bytes), "devices": [...]}, oldest first,
          the last `window` seconds in `step`-second bins (fewer while
          there's less, none for a device that isn't up), for any device
          an active connection runs through (Ethernet, Wi-Fi, USB, a
          modem, Bluetooth, WireGuard: Vyom 0.12); dev None: the primary
          connection's device, else the Wi-Fi device while it's
          connected, else the first device up.
          None without NetworkManager (a tool samples by itself then).
      history("battery", seconds=10800)
          [(unix time, percent, charging)]: UPower's own record (on disk,
          kept by upowerd anyway) and every change since; the first point
          is the one before the window (the charge then, carried forward).

    Safe from any thread: a look at memory, no command, no file read."""
    h = _history(name)
    if h is None:
        return None
    try:
        return h.history(**kw)
    except Exception:   # never take a panel down
        log.exception("history %s", name)
        return None


def start(*names):
    """Starts sources now (a tool's prewarm), so the first get() has them."""
    for n in names:
        _source(n)


def _source(name):
    src = _sources.get(name)
    if src is None:
        cls = SOURCES.get(name)
        if cls is None:
            return None
        src = _sources[name] = cls()
        try:
            src.start()
        except Exception:
            log.exception("state %s didn't start", name)
    return src


class Source:
    cache = True     # keep the last snapshot until something changes
    # Published at most once per this many seconds (the first change of a
    # burst at once, the last when it settles). Sources you change by hand,
    # a step at a time (volume, brightness), publish sooner: a bar showing
    # them must follow your scrolling.
    publish_every = 0.25

    def __init__(self):
        self.watchers = []
        self.hooks = []      # fn() at once on every change (live's own histories)
        self._pending = 0
        self._dirty = True
        self._snap = None

    def get(self):
        """A copy (callers may change it) of the last snapshot, worked out
        again only after a change: a get() between changes is a copy."""
        if not self.cache:
            return self.snapshot()
        if self._dirty:
            self._dirty = False
            self._snap = self.snapshot()
        return copy.deepcopy(self._snap)

    def start(self):
        pass

    def snapshot(self):
        return None

    def watched(self, yes):
        """A panel started (True) or stopped watching (False, the last one)."""

    def public(self):
        """What's exported for other programs (a summary; default: all)."""
        return self.get()

    def changed(self, *_):
        """Something changed: tell the watchers once, at idle."""
        self._dirty = True
        self._export = True
        for h in self.hooks:
            h()
        if (self.watchers or _exporter is not None) and not self._pending:
            self._pending = GLib.idle_add(self._notify)

    def _publish_later(self):
        self._later = 0
        if getattr(self, "_export", False) and _exporter is not None:
            self._export = False
            self._published = time.monotonic()
            _exporter.publish(self)
        return False

    def volatile(self):
        """Only what the export leaves out changed (signal strengths while
        scanning): watchers hear of it, other programs aren't woken."""
        self._dirty = True
        if self.watchers and not self._pending:
            self._pending = GLib.idle_add(self._notify)

    def _notify(self):
        self._pending = 0
        if _exporter is not None and getattr(self, "_export", True):
            # at most four times a second (publish_every): a burst (a scan
            # starting) is published once it settles, not change by change
            wait = getattr(self, "_published", 0) + self.publish_every - time.monotonic()
            if wait > 0:
                if not getattr(self, "_later", 0):
                    self._later = GLib.timeout_add(int(wait * 1000) + 1, self._publish_later)
            else:
                self._export = False
                self._published = time.monotonic()
                _exporter.publish(self)
        if not self.watchers:
            return False
        snap = get(self.name)
        for fn in list(self.watchers):
            try:
                fn(snap)
            except Exception:
                log.exception("state %s watcher", self.name)
        return False


def _unpack(proxy, prop, default=None):
    if proxy is None:
        return default
    v = proxy.get_cached_property(prop)
    return v.unpack() if v is not None else default


class _ObjectManager(Source):
    """A daemon that exports org.freedesktop.DBus.ObjectManager (NetworkManager,
    BlueZ): one client follows every object, its properties and comings and
    goings, with one match rule."""
    bus_name = path = ""

    def start(self):
        self.mgr = None
        Gio.DBusObjectManagerClient.new_for_bus(
            Gio.BusType.SYSTEM, Gio.DBusObjectManagerClientFlags.DO_NOT_AUTO_START,
            self.bus_name, self.path, None, None, None, self._made, None)

    def _made(self, _src, res, *_):
        try:
            self.mgr = Gio.DBusObjectManagerClient.new_for_bus_finish(res)
        except GLib.Error as e:
            log.info("state %s: %s", self.name, e.message)
            return
        self.mgr.connect("notify::name-owner", self.changed)
        self.mgr.connect("interface-proxy-properties-changed", self._props)
        self.mgr.connect("object-added", lambda _m, o: self.added(o))
        self.mgr.connect("interface-added", lambda _m, o, _i: self.added(o))
        self.mgr.connect("object-removed", lambda _m, o: self.removed(o))
        self.mgr.connect("interface-removed", lambda _m, o, _i: self.removed(o))
        self.mgr.connect("interface-proxy-signal", self._signal)
        self.ready()
        self.changed()

    VOLATILE = frozenset()   # properties the export leaves out

    def _props(self, _mgr, _obj, _iface, changed, invalidated):
        keys = set(changed.keys()) | set(invalidated or ())
        if keys and keys <= self.VOLATILE:
            self.volatile()
        else:
            self.changed()

    def added(self, _obj):
        self.changed()

    def removed(self, _obj):
        self.changed()

    def _signal(self, *_):
        pass

    def ready(self):
        pass

    def running(self):
        return self.mgr is not None and self.mgr.get_name_owner() is not None

    def objects(self, iface):
        """[(path, proxy)] of every object with this interface."""
        if self.mgr is None:
            return []
        out = []
        for o in self.mgr.get_objects():
            i = o.get_interface(iface)
            if i is not None:
                out.append((o.get_object_path(), i))
        return out

    def iface(self, path, iface):
        if self.mgr is None or not path or path == "/":
            return None
        o = self.mgr.get_object(path)
        return o.get_interface(iface) if o is not None else None


# ------------------------------------------------------------ NetworkManager
NM = "org.freedesktop.NetworkManager"
NM_STATES = {0: "unknown", 10: "unmanaged", 20: "unavailable", 30: "disconnected", 40: "prepare",
             50: "config", 60: "need-auth", 70: "ip-config", 80: "ip-check", 90: "secondaries",
             100: "activated", 110: "deactivating", 120: "failed"}
CONNECTIVITY = {0: "unknown", 1: "none", 2: "portal", 3: "limited", 4: "full"}
METERED = {0: "unknown", 1: "yes", 2: "no", 3: "yes (guessed)", 4: "no (guessed)"}


def ap_security(flags, wpa, rsn):
    """NetworkManager's access-point flags in nmcli's words ("WPA2", "WPA1
    WPA2", "WPA3", "WPA2 802.1X", "WEP", "" for an open network)."""
    words = []
    if flags & 0x1 and not wpa and not rsn:
        words.append("WEP")
    if wpa:
        words.append("WPA1")
    if rsn & (0x100 | 0x200):
        words.append("WPA2")
    if rsn & 0x400:
        words.append("WPA3")
    if rsn & (0x800 | 0x1000):
        words.append("OWE")
    if (wpa | rsn) & 0x200:
        words.append("802.1X")
    return " ".join(words)


def channel(freq):
    if 2412 <= freq <= 2472:
        return (freq - 2407) // 5
    if freq == 2484:
        return 14
    if 5000 <= freq < 5900:
        return (freq - 5000) // 5
    if 5955 <= freq <= 7115:
        return (freq - 5950) // 5
    return 0


class Wifi(_ObjectManager):
    name, bus_name, path = "wifi", NM, "/org/freedesktop"
    VOLATILE = frozenset({"Strength", "LastSeen", "LastScan"})   # nearby networks' levels

    def _props(self, mgr, obj, iface, changed, invalidated):
        # the network you're on: its level is exported; the others' aren't
        if obj.get_object_path() == getattr(self, "active_ap", None):
            self.changed()
        else:
            super()._props(mgr, obj, iface, changed, invalidated)


    def __init__(self):
        super().__init__()
        self.saved = {}      # settings path -> what the connection says (GetSettings)

    def ready(self):
        for path, _ in self.objects(NM + ".Settings.Connection"):
            self._fetch(path)

    def added(self, obj):
        if obj.get_interface(NM + ".Settings.Connection") is not None:
            self._fetch(obj.get_object_path())
        self.changed()

    def removed(self, obj):
        self.saved.pop(obj.get_object_path(), None)
        self.changed()

    def _signal(self, _mgr, _obj, proxy, _sender, signal, _params):
        if signal == "Updated" and proxy.get_interface_name() == NM + ".Settings.Connection":
            self._fetch(proxy.get_object_path())
        elif signal == "Removed":
            self.saved.pop(proxy.get_object_path(), None)
            self.changed()

    def _fetch(self, path):
        p = self.iface(path, NM + ".Settings.Connection")
        if p is None:
            return

        def done(proxy, res):
            try:
                s = proxy.call_finish(res).unpack()[0]
            except GLib.Error:
                return
            c, w = s.get("connection", {}), s.get("802-11-wireless", {})
            ssid = bytes(w.get("ssid") or b"").decode("utf-8", "replace") if w else ""
            self.saved[path] = {"name": c.get("id", ""), "uuid": c.get("uuid", ""), "type": c.get("type", ""),
                                "ssid": ssid, "mode": w.get("mode", ""), "timestamp": c.get("timestamp", 0),
                                "metered": METERED.get(c.get("metered", 0), "unknown"), "path": path,
                                "server": vpn_server(s), "apn": (s.get("gsm") or {}).get("apn", "")}
            self.changed()
        p.call("GetSettings", None, Gio.DBusCallFlags.NONE, 5000, None, done)

    def _ap(self, path, active_path):
        p = self.iface(path, NM + ".AccessPoint")
        if p is None:
            return None
        freq = _unpack(p, "Frequency", 0)
        raw = _unpack(p, "Ssid", b"") or b""
        return {"ssid": bytes(raw).decode("utf-8", "replace"), "bssid": _unpack(p, "HwAddress", ""),
                "strength": _unpack(p, "Strength", 0), "freq": freq, "channel": channel(freq),
                "security": ap_security(_unpack(p, "Flags", 0), _unpack(p, "WpaFlags", 0), _unpack(p, "RsnFlags", 0)),
                "max_bitrate": _unpack(p, "MaxBitrate", 0) // 1000, "mode": _unpack(p, "Mode", 0),
                "active": path == active_path, "path": path}

    def _ip(self, path, iface):
        p = self.iface(path, iface)
        if p is None:
            return [], "", []
        addrs = [f"{a.get('address')}/{a.get('prefix')}" for a in _unpack(p, "AddressData", []) if a.get("address")]
        dns = [d.get("address") for d in _unpack(p, "NameserverData", []) if isinstance(d, dict) and d.get("address")]
        return addrs, _unpack(p, "Gateway", ""), dns

    def snapshot(self):
        if not self.running():
            return {"running": False} if self.mgr is not None else None
        root = self.iface("/org/freedesktop/NetworkManager", NM)
        snap = {"running": True, "enabled": bool(_unpack(root, "WirelessEnabled", False)),
                "hw_enabled": bool(_unpack(root, "WirelessHardwareEnabled", True)),
                "connectivity": CONNECTIVITY.get(_unpack(root, "Connectivity", 0), "unknown"),
                "device": None, "state": "unknown", "aps": [], "active": None, "wired": "",
                "connection": None, "ip4": [], "gateway": "", "dns": [], "ip6": [], "mac": "", "bitrate": 0}
        acs = {path: p for path, p in self.objects(NM + ".Connection.Active")}
        for path, dev in self.objects(NM + ".Device"):
            kind = _unpack(dev, "DeviceType", 0)
            if kind == 1 and _unpack(dev, "State", 0) == 100:          # ethernet, connected
                ac = acs.get(_unpack(dev, "ActiveConnection", "/"))
                snap["wired"] = snap["wired"] or _unpack(ac, "Id", "") or _unpack(dev, "Interface", "")
            if kind != 2 or snap["device"]:                              # the first Wi-Fi device
                continue
            wl = self.iface(path, NM + ".Device.Wireless")
            snap["device"] = _unpack(dev, "Interface", "")
            snap["state"] = NM_STATES.get(_unpack(dev, "State", 0), "unknown")
            snap["mac"] = _unpack(wl, "HwAddress", "") or _unpack(dev, "HwAddress", "")
            snap["bitrate"] = _unpack(wl, "Bitrate", 0) // 1000
            active = _unpack(wl, "ActiveAccessPoint", "/")
            self.active_ap = active
            aps = [a for a in (self._ap(p, active) for p in _unpack(wl, "AccessPoints", [])) if a]
            snap["aps"] = sorted(aps, key=lambda a: -a["strength"])
            snap["active"] = next((a for a in aps if a["active"]), None)
            ac = acs.get(_unpack(dev, "ActiveConnection", "/"))
            if ac is not None:
                snap["connection"] = {"name": _unpack(ac, "Id", ""), "uuid": _unpack(ac, "Uuid", ""),
                                      "state": _unpack(ac, "State", 0)}
            snap["ip4"], snap["gateway"], snap["dns"] = self._ip(_unpack(dev, "Ip4Config", "/"), NM + ".IP4Config")
            snap["ip6"], gw6, dns6 = self._ip(_unpack(dev, "Ip6Config", "/"), NM + ".IP6Config")
            snap["dns"] += dns6
            # a hotspot is the Wi-Fi device's connection in access-point mode
            conn = next((v for v in list(self.saved.values())
                         if snap["connection"] and v["uuid"] == snap["connection"]["uuid"]), None)
            snap["hotspot"] = {"on": True, "ssid": conn["ssid"], "name": conn["name"]} \
                if conn and conn.get("mode") == "ap" else {"on": False}
        snap["saved"] = [dict(v) for v in list(self.saved.values()) if v["type"] == "802-11-wireless"]
        snap["connections"] = self._connections(root, acs)
        snap["primary"] = next((c["uuid"] for c in snap["connections"] if c["primary"]), "")
        return snap

    def _connections(self, root, acs):
        """Every active connection worth showing (Vyom 0.12), whatever it
        runs over: Wi-Fi, Ethernet, USB tethering, mobile broadband,
        Bluetooth, VPN and WireGuard; the one carrying the default route
        (NetworkManager's PrimaryConnection) first, a VPN right after the
        connection it rides on. Docker's bridges, loopback and the like are
        left out."""
        primary = _unpack(root, "PrimaryConnection", "/")
        by_uuid = {v["uuid"]: v for v in list(self.saved.values())}
        out = []
        for path, ac in acs.items():
            devs = [self.iface(d, NM + ".Device") for d in _unpack(ac, "Devices", []) or []]
            dev = next((d for d in devs if d is not None), None)
            dpath = dev.get_object_path() if dev is not None else ""
            iface = _unpack(dev, "IpInterface", "") or _unpack(dev, "Interface", "")
            conf = by_uuid.get(_unpack(ac, "Uuid", "")) or {}
            vpn = bool(_unpack(ac, "Vpn", False))
            kind = conn_kind(_unpack(ac, "Type", ""), _unpack(dev, "DeviceType", 0), _unpack(dev, "Driver", ""),
                             iface, bool(_unpack(ac, "StateFlags", 0) & 0x80), conf.get("mode", ""), vpn)
            if kind is None:
                continue
            ip4p = _unpack(ac, "Ip4Config", "/")
            ip6p = _unpack(ac, "Ip6Config", "/")
            if not vpn:     # a VPN's addresses are its own (on the active connection); a device's on it
                ip4p = ip4p if ip4p not in ("", "/") else _unpack(dev, "Ip4Config", "/")
                ip6p = ip6p if ip6p not in ("", "/") else _unpack(dev, "Ip6Config", "/")
            ip4, gw4, dns4 = self._ip(ip4p, NM + ".IP4Config")
            ip6, gw6, dns6 = self._ip(ip6p, NM + ".IP6Config")
            c = {"name": _unpack(ac, "Id", ""), "uuid": _unpack(ac, "Uuid", ""), "type": kind[0], "label": kind[1],
                 "device": iface, "device_path": dpath, "vpn": kind[0] in ("vpn", "wireguard"),
                 "state": {1: "activating", 2: "activated", 3: "deactivating"}.get(_unpack(ac, "State", 0), "unknown"),
                 "primary": path == primary, "default": bool(_unpack(ac, "Default", False)),
                 "default6": bool(_unpack(ac, "Default6", False)), "ip4": ip4, "gateway": gw4, "ip6": ip6,
                 "gateway6": gw6, "dns": dns4 + dns6, "driver": _unpack(dev, "Driver", ""),
                 "mac": "", "speed": 0, "duplex": "", "metered": conf.get("metered", "unknown"),
                 "path": path, "base_device": dpath if vpn else ""}
            dtype = _unpack(dev, "DeviceType", 0)
            if dtype == 2:
                wl = self.iface(dpath, NM + ".Device.Wireless")
                c["mac"] = _unpack(wl, "HwAddress", "") or _unpack(dev, "HwAddress", "")
                c["bitrate"] = _unpack(wl, "Bitrate", 0) // 1000
                c["speed"] = c["bitrate"]
                ap = self._ap(_unpack(wl, "ActiveAccessPoint", "/"), _unpack(wl, "ActiveAccessPoint", "/"))
                if ap:
                    c.update({"ssid": ap["ssid"], "strength": ap["strength"], "freq": ap["freq"],
                              "channel": ap["channel"], "security": ap["security"], "bssid": ap["bssid"]})
            elif dtype == 1 and not vpn:
                wd = self.iface(dpath, NM + ".Device.Wired")
                c["mac"] = _unpack(wd, "HwAddress", "") or _unpack(dev, "HwAddress", "")
                c["speed"] = _unpack(wd, "Speed", 0) or link_speed(iface)
                c["duplex"] = link_duplex(iface)
            elif dtype == 8 and not vpn:
                md = self.iface(dpath, NM + ".Device.Modem")
                c["operator"] = _unpack(md, "OperatorCode", "")
                c["apn"] = _unpack(md, "Apn", "") or conf.get("apn", "")
                c["modem"] = _unpack(md, "DeviceId", "")
            elif dtype == 5 and not vpn:
                bt = self.iface(dpath, NM + ".Device.Bluetooth")
                c["peer"] = _unpack(bt, "Name", "")
                c["mac"] = _unpack(bt, "HwAddress", "")
            elif not vpn:
                c["mac"] = _unpack(dev, "HwAddress", "")
            if c["vpn"]:
                c["server"] = conf.get("server", "")
                if kind[0] == "wireguard" or iface:
                    c["vpn_device"] = iface
            out.append(c)
        return order_connections(out)

    def public(self):
        s = self.get()
        if s:
            s.pop("aps", None)
            s.pop("saved", None)
        return s


# NetworkManager's device types left out of the connections and the speed
# history: virtual plumbing, not a way out (veth, dummy, Wi-Fi P2P, loopback,
# Open vSwitch ports and bridges, VRF)
HIDDEN_DEVICES = frozenset({20, 22, 30, 32, 25, 26, 31})
# drivers of the "ethernet" a phone makes over USB (tethering): Android's
# RNDIS and NCM, the CDC ones some phones and modems use, the iPhone's
USB_TETHER = frozenset({"rndis_host", "cdc_ether", "cdc_ncm", "cdc_eem", "ipheth", "cdc_subset"})
# bridges a container runtime or a VM manager made (docker0, br-1a2b…, virbr0)
VIRTUAL_BRIDGE = re.compile(r"^(docker\d*|br-[0-9a-f]{6,}|virbr\d+|lxcbr\d+|lxdbr\d+|cni\d*|podman\d+)$")
CONN_LABELS = {"wifi": "Wi-Fi", "hotspot": "Hotspot", "ethernet": "Ethernet", "usb": "USB", "mobile": "Mobile",
               "bluetooth": "Bluetooth", "vpn": "VPN", "wireguard": "WireGuard", "bridge": "Bridge", "bond": "Bond",
               "vlan": "VLAN", "team": "Team", "infiniband": "InfiniBand", "other": "Network"}


def conn_kind(ac_type, dev_type=0, driver="", iface="", external=False, mode="", vpn=False):
    """(type, label) of an active connection for the panels ("ethernet",
    "Ethernet"; "usb", "USB" for a phone tethered over USB; "mobile";
    "bluetooth"; "vpn"; "wireguard"; "hotspot" for your own access point),
    or None for what isn't a way out (loopback, a container's bridge)."""
    if dev_type in HIDDEN_DEVICES or ac_type in ("loopback", "veth", "dummy", "wifi-p2p", "ovs-port", "ovs-bridge"):
        return None
    if vpn or ac_type == "vpn":
        kind = "vpn"
    elif ac_type == "wireguard" or dev_type == 29:
        kind = "wireguard"
    elif ac_type == "802-11-wireless" or dev_type == 2:
        kind = "hotspot" if mode == "ap" else "wifi"
    elif ac_type in ("802-3-ethernet", "pppoe") or dev_type == 1:
        kind = "usb" if driver in USB_TETHER else "ethernet"
    elif ac_type in ("gsm", "cdma") or dev_type == 8:
        kind = "mobile"
    elif ac_type == "bluetooth" or dev_type == 5:
        kind = "bluetooth"
    elif ac_type in ("tun", "ip-tunnel") or dev_type in (16, 17):
        kind = "vpn"            # Tailscale, an OpenVPN started by hand: a tunnel is a VPN to you
    elif ac_type == "bridge" or dev_type == 13:
        if VIRTUAL_BRIDGE.match(iface or ""):
            return None
        kind = "bridge"
    elif ac_type in ("bond", "vlan", "team", "infiniband"):
        kind = ac_type
    else:
        kind = "other"
    return kind, CONN_LABELS[kind]


def order_connections(conns):
    """The connection carrying the default route first, each VPN right
    after the connection it rides on (its device, else the one with the
    default route, else the first), each with `via`: that connection's
    name (and `via_device`, `via_type`). Mutates and returns the list."""
    base = [c for c in conns if not c.get("vpn")]
    vpns = [c for c in conns if c.get("vpn")]

    def under(v):
        if v.get("base_device"):
            hit = next((c for c in base if c.get("device_path") == v["base_device"]), None)
            if hit is not None:
                return hit
        return next((c for c in base if c.get("default") or c.get("default6")), None) \
            or next((c for c in base if c.get("gateway") or c.get("gateway6")), None) \
            or (base[0] if base else None)
    rides = {}
    for v in vpns:
        b = under(v)
        if b is not None:
            v["via"], v["via_device"], v["via_type"] = b["name"], b.get("device", ""), b.get("type", "")
        rides.setdefault(id(b) if b is not None else None, []).append(v)
    rank = {"wifi": 1, "ethernet": 0, "usb": 2, "mobile": 3, "bluetooth": 4}

    def key(c):
        lead = c.get("primary") or any(v.get("primary") for v in rides.get(id(c), []))
        return (not lead, not (c.get("default") or c.get("default6")), c.get("type") == "hotspot",
                rank.get(c.get("type"), 9))
    out = []
    for c in sorted(base, key=key):
        out.append(c)
        out += rides.get(id(c), [])
    out += rides.get(None, [])
    conns[:] = out
    return conns


def vpn_server(settings):
    """The server a VPN connection goes to, from its settings (OpenVPN's
    remote, the gateway of the others, WireGuard's first peer's endpoint)."""
    data = (settings.get("vpn") or {}).get("data") or {}
    for k in ("remote", "gateway", "server", "host", "remote-ip"):
        if data.get(k):
            return str(data[k]).split(",")[0].strip()
    for peer in (settings.get("wireguard") or {}).get("peers") or []:
        if isinstance(peer, dict) and peer.get("endpoint"):
            return str(peer["endpoint"])
    return ""


def _sys_read(iface, name):
    try:
        with open(os.path.join(SYS_NET, iface, name)) as f:
            return f.read(64).strip()
    except (OSError, TypeError, ValueError):
        return ""


def link_speed(iface):
    """The link's speed in Mb/s from sysfs (0 when the driver doesn't say)."""
    try:
        v = int(_sys_read(iface, "speed") or 0) if iface else 0
    except ValueError:
        return 0
    return v if 0 < v < 10_000_000 else 0


def link_duplex(iface):
    v = _sys_read(iface, "duplex") if iface else ""
    return v if v in ("full", "half") else ""


def wifi_rescan():
    """Asks NetworkManager for a fresh scan, without a command; the results
    come in as the live state's own changes. False when it can't be asked
    (no NetworkManager in the live state): run `nmcli device wifi rescan`."""
    src = _sources.get("wifi")
    if src is None or not src.running():
        return False
    for path, dev in src.objects(NM + ".Device"):
        if _unpack(dev, "DeviceType", 0) == 2:
            wl = src.iface(path, NM + ".Device.Wireless")
            if wl is None:
                return False

            def ask(wl=wl):
                wl.call("RequestScan", GLib.Variant("(a{sv})", ({},)), Gio.DBusCallFlags.NONE, 5000, None,
                        lambda p, r: _finish_quietly(p, r))
                return False
            GLib.idle_add(ask)      # from any thread: the call is made on the main loop
            return True
    return False


def _finish_quietly(proxy, res):
    try:
        proxy.call_finish(res)
    except GLib.Error:      # scanned a moment ago, or the radio is off
        pass


# ------------------------------------------------------------------- BlueZ
class Bluetooth(Source):
    """BlueZ, followed narrowly: every object once (GetManagedObjects), then
    InterfacesAdded / Removed, the adapter's changes and those of the
    devices you have (paired, or connected). A scan anywhere on the system
    (another program's, a phone's) reports every stranger's signal many
    times a second; those reach Vyom only while a panel watches
    (live.watch), when it follows everything."""
    name = "bluetooth"
    BLUEZ = "org.bluez"

    def start(self):
        self.conn = None
        self.objs = None        # path -> {interface: {property: value}}
        self.owner = None
        self.subs = {}          # path (or "*") -> subscription id
        self.broad = False
        self._widen = 0
        Gio.bus_get(Gio.BusType.SYSTEM, None, self._bus)

    def _bus(self, _src, res, *_):
        try:
            self.conn = Gio.bus_get_finish(res)
        except GLib.Error:
            return
        self.conn.signal_subscribe(self.BLUEZ, "org.freedesktop.DBus.ObjectManager", None, "/", None,
                                   Gio.DBusSignalFlags.NONE, self._om_signal)
        self.conn.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                                   "/org/freedesktop/DBus", self.BLUEZ, Gio.DBusSignalFlags.NONE,
                                   lambda *_: self._load())
        self._load()

    def _load(self):
        def done(conn, res):
            try:
                objs = conn.call_finish(res).unpack()[0]
            except GLib.Error:
                objs = None
            self.objs = objs
            self._follow()
            self.changed()
        self.conn.call(self.BLUEZ, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects", None,
                       None, Gio.DBusCallFlags.NO_AUTO_START, 5000, None, done)

    def _om_signal(self, _conn, _sender, _path, _iface, signal, params):
        if self.objs is None:
            return
        path, rest = params.unpack()
        if signal == "InterfacesAdded":
            for iface, props in rest.items():
                self.objs.setdefault(path, {}).setdefault(iface, {}).update(props)
        elif signal == "InterfacesRemoved":
            o = self.objs.get(path, {})
            for iface in rest:
                o.pop(iface, None)
            if not o:
                self.objs.pop(path, None)
        if "/dev_" in path and path.count("/") == 4 or "org.bluez.Adapter1" in rest:
            self._follow()
            self.changed()

    def _props(self, _conn, _sender, path, _iface, _signal, params):
        iface, changed, gone = params.unpack()
        if self.objs is None:
            return
        o = self.objs.setdefault(path, {}).setdefault(iface, {})
        o.update(changed)
        for k in gone:
            o.pop(k, None)
        if iface == "org.bluez.Device1" and ("Paired" in changed or "Connected" in changed):
            self._follow()
        if set(changed) | set(gone) <= {"RSSI", "TxPower", "ManufacturerData", "ServiceData",
                                         "AdvertisingFlags", "AdvertisingData"}:
            self.volatile()
        else:
            self.changed()

    def _mine(self, path):
        o = self.objs.get(path, {})
        if "org.bluez.Adapter1" in o:
            return True
        d = o.get("org.bluez.Device1")
        if d is None:
            dev = path[:path.index("/dev_") + 22] if "/dev_" in path else None   # a device's sub-object
            d = self.objs.get(dev, {}).get("org.bluez.Device1") if dev else None
        return bool(d and (d.get("Paired") or d.get("Connected")))

    def _follow(self):
        """Subscribe to what's worth following now."""
        if self.conn is None:
            return
        want = {"*"} if self.broad else {p for p in (self.objs or {}) if "/dev_" not in p or p.count("/") == 4
                                         if self._mine(p)}
        for key in list(self.subs):
            if key not in want:
                self.conn.signal_unsubscribe(self.subs.pop(key))
        for key in want - set(self.subs):
            self.subs[key] = self.conn.signal_subscribe(
                self.BLUEZ, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                None if key == "*" else key, None, Gio.DBusSignalFlags.NONE, self._props)

    def watched(self, yes):
        if yes == self.broad:
            return
        self.broad = yes
        if self._widen:
            GLib.source_remove(self._widen)
            self._widen = 0
        if not yes:
            self._follow()
            return

        def widen():
            # after the panel's first frame: the scan it starts pours in
            self._widen = 0
            if self.broad:
                if self.objs is not None:
                    self._load()    # strangers' state moved while nobody looked
                self._follow()
            return False
        self._widen = GLib.timeout_add(300, widen)

    def public(self):
        s = self.get()
        for d in (s or {}).get("devices", []):
            d.pop("rssi", None)
        return s

    def snapshot(self):
        if self.conn is None:
            return None
        if self.objs is None:
            return {"running": False}
        snap = {"running": True, "adapter": None, "devices": []}
        for path, o in sorted(self.objs.items()):
            a = o.get("org.bluez.Adapter1")
            if a is not None and snap["adapter"] is None:
                snap["adapter"] = {"path": path, "address": a.get("Address", ""),
                                   "alias": a.get("Alias", "") or a.get("Name", ""),
                                   "powered": bool(a.get("Powered", False)),
                                   "discoverable": bool(a.get("Discoverable", False)),
                                   "discovering": bool(a.get("Discovering", False)),
                                   "power_state": a.get("PowerState", ""),
                                   "blocked": a.get("PowerState", "") == "off-blocked"}
            d = o.get("org.bluez.Device1")
            if d is None:
                continue
            bat = o.get("org.bluez.Battery1")
            snap["devices"].append({
                "path": path, "mac": (d.get("Address", "") or "").upper(),
                "name": d.get("Name", ""), "alias": d.get("Alias", ""), "icon": d.get("Icon", ""),
                "connected": bool(d.get("Connected", False)), "paired": bool(d.get("Paired", False)),
                "bonded": bool(d.get("Bonded", False)), "trusted": bool(d.get("Trusted", False)),
                "blocked": bool(d.get("Blocked", False)), "rssi": d.get("RSSI"),
                "uuids": list(d.get("UUIDs", []) or []), "class": d.get("Class"),
                "battery": bat.get("Percentage") if bat is not None else None})
        return snap


# ------------------------------------------------------------------ UPower
UPOWER = "org.freedesktop.UPower"
UP_TYPES = {0: "unknown", 1: "line-power", 2: "battery", 3: "ups", 4: "monitor", 5: "mouse", 6: "keyboard",
            7: "pda", 8: "phone", 9: "media-player", 10: "tablet", 11: "computer", 12: "gaming-input",
            13: "pen", 14: "touchpad", 15: "modem", 16: "network", 17: "headset", 18: "speakers",
            19: "headphones", 20: "video", 21: "other-audio", 22: "remote-control", 23: "printer",
            24: "scanner", 25: "camera", 26: "wearable", 27: "toy", 28: "bluetooth-generic"}
UP_STATES = {0: "unknown", 1: "charging", 2: "discharging", 3: "empty", 4: "fully-charged",
             5: "pending-charge", 6: "pending-discharge"}


def _proxy(bus, name, path, iface, done):
    def made(_src, res, *_):
        try:
            done(Gio.DBusProxy.new_for_bus_finish(res))
        except GLib.Error:
            done(None)
    Gio.DBusProxy.new_for_bus(bus, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None, name, path, iface, None, made, None)


class Battery(Source):
    name = "battery"

    def start(self):
        self.root = self.display = None
        self.devices = {}     # path -> proxy
        _proxy(Gio.BusType.SYSTEM, UPOWER, "/org/freedesktop/UPower", UPOWER, self._root)

    def _root(self, p):
        if p is None:
            return
        self.root = p
        p.connect("g-properties-changed", self.changed)
        p.connect("g-signal", self._root_signal)
        p.connect("notify::g-name-owner", lambda *_: self._enumerate())
        _proxy(Gio.BusType.SYSTEM, UPOWER, "/org/freedesktop/UPower/devices/DisplayDevice", UPOWER + ".Device",
               self._display)
        self._enumerate()

    def _display(self, p):
        self.display = p
        if p is not None:
            p.connect("g-properties-changed", self.changed)
        self.changed()

    def _enumerate(self):
        self.devices = {}
        if self.root is None or self.root.get_name_owner() is None:
            self.changed()
            return

        def done(proxy, res):
            try:
                paths = proxy.call_finish(res).unpack()[0]
            except GLib.Error:
                return
            for path in paths:
                self._add(path)
        self.root.call("EnumerateDevices", None, Gio.DBusCallFlags.NONE, 5000, None, done)

    def _add(self, path):
        def got(p):
            if p is not None:
                self.devices[path] = p
                p.connect("g-properties-changed", self.changed)
                self.changed()
        _proxy(Gio.BusType.SYSTEM, UPOWER, path, UPOWER + ".Device", got)

    def _root_signal(self, _p, _sender, signal, params):
        path = params.unpack()[0] if params is not None else None
        if signal == "DeviceAdded" and path:
            self._add(path)
        elif signal == "DeviceRemoved" and path:
            self.devices.pop(path, None)
            self.changed()

    @staticmethod
    def _dev(path, p):
        return {"path": path, "type": UP_TYPES.get(_unpack(p, "Type", 0), "unknown"),
                "power_supply": bool(_unpack(p, "PowerSupply", False)), "native_path": _unpack(p, "NativePath", ""),
                "model": _unpack(p, "Model", ""), "vendor": _unpack(p, "Vendor", ""), "serial": _unpack(p, "Serial", ""),
                "present": bool(_unpack(p, "IsPresent", False)), "percentage": _unpack(p, "Percentage", 0.0),
                "state": UP_STATES.get(_unpack(p, "State", 0), "unknown"), "online": bool(_unpack(p, "Online", False)),
                "energy_rate": _unpack(p, "EnergyRate", 0.0), "time_to_empty": _unpack(p, "TimeToEmpty", 0),
                "time_to_full": _unpack(p, "TimeToFull", 0), "icon": _unpack(p, "IconName", "")}

    def snapshot(self):
        if self.root is None:
            return None
        if self.root.get_name_owner() is None:
            return {"running": False}
        return {"running": True, "on_battery": bool(_unpack(self.root, "OnBattery", False)),
                "display": self._dev("DisplayDevice", self.display) if self.display is not None else None,
                "devices": [self._dev(path, p) for path, p in list(self.devices.items())]}


# ---------------------------------------------------- power-profiles-daemon
PPD = (("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles"),
       ("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles"))


class PowerProfiles(Source):
    name = "power_profiles"

    def start(self):
        self.proxy = None
        self._try(0)

    def _try(self, i):
        if i >= len(PPD):
            return
        name, path = PPD[i]

        def got(p):
            if p is None or p.get_name_owner() is None:
                self._try(i + 1)
                return
            self.proxy = p
            p.connect("g-properties-changed", self.changed)
            p.connect("notify::g-name-owner", self.changed)
            self.changed()
        _proxy(Gio.BusType.SYSTEM, name, path, name, got)

    def snapshot(self):
        p = self.proxy
        if p is None or p.get_name_owner() is None:
            return None
        return {"active": _unpack(p, "ActiveProfile", ""), "degraded": _unpack(p, "PerformanceDegraded", ""),
                "profiles": [d.get("Profile") for d in _unpack(p, "Profiles", []) or [] if d.get("Profile")]}

    def set(self, profile, then=None):
        """Switches profile without blocking; the daemon's signal updates
        everyone. then(ok) on the main loop."""
        p = self.proxy
        if p is None:
            if then:
                then(False)
            return

        def done(proxy, res):
            try:
                proxy.call_finish(res)
                ok = True
            except GLib.Error:
                ok = False
            if then:
                then(ok)
        p.call("org.freedesktop.DBus.Properties.Set",
               GLib.Variant("(ssv)", (p.get_interface_name(), "ActiveProfile", GLib.Variant("s", profile))),
               Gio.DBusCallFlags.NONE, 5000, None, done)


def set_power_profile(profile, then=None):
    src = _source("power_profiles")
    src.set(profile, then)


# ------------------------------------------------------------- children
_children = []


def _prctl_pdeathsig():
    """In the child, before exec: die with Vyom (SIGTERM when it goes,
    however it goes: even SIGKILL), so no helper outlives it."""
    try:
        import ctypes
        import signal
        ctypes.CDLL(None).prctl(1, int(signal.SIGTERM))    # PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        pass


def spawn_child(argv, flags):
    """A long-lived helper (pactl subscribe) that dies with Vyom: through
    setpriv --pdeathsig when it's there (nothing runs in the forked child),
    else a child_setup that asks the kernel the same. Kept for stop()."""
    if shutil.which("setpriv"):
        proc = Gio.Subprocess.new(["setpriv", "--pdeathsig", "TERM", "--", *argv], flags)
    else:
        launcher = Gio.SubprocessLauncher.new(flags)
        launcher.set_child_setup(_prctl_pdeathsig)
        proc = launcher.spawnv(argv)
    _children.append(proc)
    return proc


def stop():
    """Ends every helper (the app's shutdown; they'd die with it anyway)."""
    for proc in _children:
        try:
            proc.send_signal(15)
        except GLib.Error:
            pass
    _children.clear()


# ------------------------------------------------------------------ volume
def sink_summary(default, sinks):
    """The default output from `pactl get-default-sink` and `pactl -f json
    list sinks`: what it is (description; bus, API, form factor and active
    port, so a bar can tell earbuds from a TV), its volume (the channels'
    average, in pactl's percent, the same scale as wpctl's) and whether it's
    muted. {"sink": ""} when there's no output."""
    sink = next((x for x in sinks if isinstance(x, dict) and x.get("name") == default), None)
    if sink is None:
        return {"sink": ""}
    vols = []
    for v in (sink.get("volume") or {}).values():
        try:
            vols.append(int(str(v["value_percent"]).rstrip("%")))
        except (KeyError, TypeError, ValueError):
            pass
    p = sink.get("properties") or {}
    return {"sink": default, "device": sink.get("description") or "",
            "volume": round(sum(vols) / len(vols)) if vols else 0, "muted": bool(sink.get("mute")),
            "bus": p.get("device.bus") or "", "api": p.get("device.api") or "",
            "form_factor": p.get("device.form-factor") or "", "port": sink.get("active_port") or ""}


class Volume(Source):
    """The default output through `pactl subscribe` (PipeWire's pulse server
    or PulseAudio): one process that only speaks when something changes;
    then the output is read again (`pactl -f json list sinks`, and the
    default's name when the server changed: one or two runs side by side,
    ~10 ms). Published at once (publish_every 0): the bar's sound capsule
    follows it while you scroll."""
    name = "volume"
    publish_every = 0

    def start(self):
        self.snap = None
        self.proc = None
        self.reading = False
        self.again = False
        self.need_name = True
        self.default = ""
        self.fails = 0
        self.json = True     # pactl -f json (pactl 16 and later)
        if shutil.which("pactl"):
            self._spawn()

    def _spawn(self):
        try:
            self.proc = spawn_child(["pactl", "subscribe"], Gio.SubprocessFlags.STDOUT_PIPE |
                                    Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            return
        self.started = time.monotonic()
        self.lines = Gio.DataInputStream.new(self.proc.get_stdout_pipe())
        self.lines.read_line_async(GLib.PRIORITY_DEFAULT, None, self._line)
        self.need_name = True
        self.read()

    def _line(self, stream, res):
        try:
            line, _ = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:                 # pactl ended (the sound server restarted, or is gone)
            if self.proc in _children:
                _children.remove(self.proc)
            self.proc = None
            # ran a while: the server restarted, come back quickly; else back
            # off (3, 6, 9... s, up to a minute), never giving up
            self.fails = 1 if time.monotonic() - self.started > 60 else self.fails + 1
            GLib.timeout_add_seconds(min(3 * self.fails, 60), lambda: (self._spawn(), False)[1])
            self.need_name = True
            self.read()                  # what it is now (no output, while the server is away)
            return
        # "Event 'change' on sink #56", "Event 'change' on server #-1", a
        # card (a Bluetooth profile, a port); not sink-input (an app's stream)
        if re.search(r"on (?:sink|card) #|on server\b", line):
            if "server" in line or "'new'" in line or "'remove'" in line:
                self.need_name = True
            self.read()
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._line)

    def _run(self, argv, then):
        try:
            p = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            then("")
            return

        def done(proc, res):
            try:
                _ok, out, _err = proc.communicate_utf8_finish(res)
            except GLib.Error:
                out = ""
            then(out or "")
        p.communicate_utf8_async(None, None, done)

    def read(self):
        if self.reading:
            self.again = True
            return
        self.reading = True
        if not self.json:
            return self._read_plain()
        import json
        answers = {}
        need_name = self.need_name
        self.need_name = False

        def got(key, out):
            answers[key] = out
            if len(answers) < (2 if need_name else 1):
                return
            if need_name:
                self.default = answers["default"].strip()
            try:
                sinks = json.loads(answers["sinks"]) if answers["sinks"].strip() else []
            except ValueError:
                # a pactl without -f json (before 16): ask the plain way from now on
                self.json = False
                self.reading = False
                self.need_name = True
                return self.read()
            self.snap = sink_summary(self.default, sinks if isinstance(sinks, list) else [])
            if not self.default or not answers["sinks"].strip():
                self.need_name = True    # no server or no output: ask its name again next time
            self._finish()
        self._run(["pactl", "-f", "json", "list", "sinks"], lambda out: got("sinks", out))
        if need_name:
            self._run(["pactl", "get-default-sink"], lambda out: got("default", out))

    def _finish(self):
        self.reading = False
        self.changed()
        if self.again:
            self.again = False
            self.read()

    def _read_plain(self):
        """An old pactl: the volume, mute and description in three runs."""
        snap = dict(self.snap or {})

        def got_volume(out):
            m = re.search(r"(\d+)%", out)
            snap["volume"] = int(m.group(1)) if m else 0
            self._run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
                      lambda o: (snap.__setitem__("muted", "yes" in o), got_mute()))

        def got_mute():
            self._run(["pactl", "info"], got_info)

        def got_info(out):
            m = re.search(r"Default Sink: (.+)", out)
            snap["sink"] = m.group(1).strip() if m else ""
            if not snap["sink"]:
                snap.clear()
                snap["sink"] = ""
            self.snap = snap
            self._finish()
        self._run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], got_volume)

    def snapshot(self):
        return dict(self.snap) if self.snap and "volume" in self.snap else None

    def public(self):
        """None while nothing follows the sound server (no pactl, or not
        yet read); {"sink": ""} when there's no output; else the summary."""
        return dict(self.snap) if self.snap else None


# -------------------------------------------------------------- brightness
class Brightness(Source):
    """The first backlight, read from sysfs when asked (two tiny files); the
    kernel's uevent on every change (udev, through GUdev) tells watchers."""
    name = "brightness"
    cache = False    # two small reads: always current, even without udev
    # a key held down steps it ~30 times a second: published at most 20
    # times, the first and the last step at once
    publish_every = 0.05

    def start(self):
        self.udev = None
        try:
            import gi
            gi.require_version("GUdev", "1.0")
            from gi.repository import GUdev
            self.udev = GUdev.Client(subsystems=["backlight"])
            self.udev.connect("uevent", self.changed)
        except (ImportError, ValueError):
            log.debug("state brightness: no GUdev, watchers won't hear of changes")

    def snapshot(self):
        for d in sorted(glob.glob("/sys/class/backlight/*")):
            try:
                with open(os.path.join(d, "brightness")) as f:
                    cur = int(f.read())
                with open(os.path.join(d, "max_brightness")) as f:
                    top = int(f.read())
            except (OSError, ValueError):
                continue
            return {"device": os.path.basename(d), "brightness": cur, "max": top,
                    "percent": round(cur * 100 / top) if top else 0}
        return None


# ----------------------------------------------------------- systemd units
class Units(Source):
    """ActiveState of the systemd user units someone asked about
    (track_unit), from the user manager's PropertiesChanged."""
    name = "units"

    def start(self):
        self.mgr = None
        self.units = {}        # name -> proxy (or None while it's being made)
        _proxy(Gio.BusType.SESSION, "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
               "org.freedesktop.systemd1.Manager", self._manager)

    def _manager(self, p):
        self.mgr = p
        for name in list(self.units):
            self._load(name)
        self.changed()

    def track(self, name):
        if name in self.units:
            return
        self.units[name] = None
        if self.mgr is not None:
            self._load(name)

    def _load(self, name):
        if self.mgr is None or self.mgr.get_name_owner() is None:
            return

        def done(m, res):
            try:
                path = m.call_finish(res).unpack()[0]
            except GLib.Error:
                return

            def got(p):
                if p is not None:
                    self.units[name] = p
                    p.connect("g-properties-changed", self.changed)
                    self.changed()
            _proxy(Gio.BusType.SESSION, "org.freedesktop.systemd1", path, "org.freedesktop.systemd1.Unit", got)
        # LoadUnit: the unit's object even when it isn't running (GetUnit fails then)
        self.mgr.call("LoadUnit", GLib.Variant("(s)", (name,)), Gio.DBusCallFlags.NONE, 5000, None, done)

    def snapshot(self):
        if self.mgr is None or self.mgr.get_name_owner() is None:
            return None
        return {n: _unpack(p, "ActiveState", "unknown") for n, p in list(self.units.items()) if p is not None}


def track_unit(name):
    """Follow a user unit's ActiveState in live.get("units")[name]."""
    _source("units").track(name)


# ------------------------------------------------------------------- theme
class Theme(Source):
    name = "theme"

    def start(self):
        self.settings = None
        src = Gio.SettingsSchemaSource.get_default()
        if src is not None and src.lookup("org.gnome.desktop.interface", True) is not None:
            self.settings = Gio.Settings.new("org.gnome.desktop.interface")
            self.settings.connect("changed::color-scheme", self.changed)
            self.settings.connect("changed::gtk-theme", self.changed)

    def snapshot(self):
        if self.settings is None:
            return None
        scheme = self.settings.get_string("color-scheme")
        return {"color_scheme": scheme, "dark": scheme == "prefer-dark", "gtk_theme": self.settings.get_string("gtk-theme")}


# ---------------------------------------------------------------- histories
# A graph that opened empty and filled while you watched (kendra's and
# tarang's network speed) or lost its past when Vyom restarted (urja's
# charge) draws, instead, what these kept since the daemon started.
_histories = {}


def _history(name):
    h = _histories.get(name)
    if h is None:
        cls = HISTORIES.get(name)
        if cls is None:
            return None
        h = _histories[name] = cls()
        try:
            h.start()
        except Exception:
            log.exception("history %s didn't start", name)
    return h


def _boottime():
    """Seconds since boot, suspend included: a reading from before a
    suspend is as old as it really is, not a moment ago."""
    try:
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    except (AttributeError, OSError):
        return time.monotonic()




def net_counters(dev, base=None):
    """(rx_bytes, tx_bytes) of a network device from sysfs, or None."""
    try:
        d = os.path.join(base or SYS_NET, dev, "statistics")
        with open(os.path.join(d, "rx_bytes"), "rb") as rx, open(os.path.join(d, "tx_bytes"), "rb") as tx:
            return int(rx.read()), int(tx.read())
    except (OSError, ValueError, TypeError):
        return None


def net_bins(readings, step=1, window=60, gap=6.0):
    """[(time, rx_bytes, tx_bytes)] (oldest first) -> (rx, tx): bytes a
    second in `step`-second bins ending at the last reading, at most
    `window` seconds' worth, fewer while there's less. Readings may come
    every second or every two (or mixed): between two readings the speed is
    the bytes moved over the time, spread evenly over the bins it covers.
    Two readings more than `gap` seconds apart (a suspend, a disconnect) or
    with a counter that went back (the driver reloaded) moved nothing that
    can be known: those bins are 0, never a spike."""
    if len(readings) < 2 or step <= 0:
        return [], []
    end = readings[-1][0]
    n = int(min(window, end - readings[0][0]) / step + 1e-6)
    if n <= 0:
        return [], []
    start = end - n * step
    rx, tx = [0.0] * n, [0.0] * n
    for a, b in zip(readings, readings[1:]):
        dt = b[0] - a[0]
        if b[0] <= start or dt <= 0 or dt > gap or b[1] < a[1] or b[2] < a[2]:
            continue
        r, t = (b[1] - a[1]) / dt, (b[2] - a[2]) / dt
        k = max(0, int((a[0] - start) / step))
        while k < n:
            lo = start + k * step
            if lo >= b[0]:
                break
            ov = min(lo + step, b[0]) - max(lo, a[0])
            if ov > 0:
                rx[k] += r * ov
                tx[k] += t * ov
            k += 1
    return [v / step for v in rx], [v / step for v in tx]


class NetHistory:
    """Every connected network device's byte counters, read from sysfs (two
    small files, no command, nothing on the network) every SLOW seconds for
    the daemon's whole life and kept for the last WINDOW seconds, so a speed
    graph opens on its full minute. While a panel draws it by the second
    (watch("net", fn, fast=True)) it's read every FAST seconds into the same
    record. Nothing connected (NetworkManager says which devices are up):
    no timer, nothing wakes. The readings stay in this process: not in the
    state files or on D-Bus (that would wake every program that follows
    them); History("net") on D-Bus asks for them."""
    SLOW, FAST = 2, 1
    WINDOW = 60            # the longest any panel draws (kendra, tarang: a minute)
    KEEP = WINDOW // FAST + 4

    def __init__(self):
        self.rings = {}    # interface -> deque of (boottime, rx_bytes, tx_bytes)
        self.devs = []     # interfaces up now
        self.wifi_dev = ""
        self.primary_dev = ""
        self.watchers = []  # [fn, fast]
        self.timer = 0
        self.every = 0
        self._look = 0
        self.nm = None

    def start(self):
        self.nm = _source("wifi")
        if self.nm is not None:
            self.nm.hooks.append(self._nm_changed)
        self._nm_changed()

    def _nm_changed(self):
        # NetworkManager said something: which devices are up, at idle (once
        # for a burst of signals)
        if not self._look:
            self._look = GLib.idle_add(self._devices)

    def _devices(self):
        # every connection the live state shows (Vyom 0.12: Ethernet, Wi-Fi,
        # USB tethering, mobile broadband, Bluetooth, WireGuard...), by the
        # interface its bytes go through, the primary connection's first
        self._look = 0
        devs, wifi, primary = [], "", ""
        nm = self.nm
        if nm is not None and nm.running():
            snap = nm.get() or {}
            for c in snap.get("connections") or []:
                for i in (c.get("device"), c.get("vpn_device")):
                    if i and i not in devs:
                        devs.append(i)
                if c.get("primary") and not primary:
                    primary = c.get("vpn_device") or c.get("device") or ""
                if c.get("type") == "wifi" and not wifi:
                    wifi = c.get("device") or ""
        if devs != self.devs:
            self.devs = devs
            if devs and not self.timer:
                self._read()       # a first reading now: the record starts at once
        self.wifi_dev = wifi
        self.primary_dev = primary
        self._schedule()
        return False

    def _schedule(self):
        every = (self.FAST if any(f for _fn, f in self.watchers) else self.SLOW) if self.devs else 0
        if every == self.every and (self.timer or not every):
            return
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        self.every = every
        if every:
            # whole seconds: GLib wakes for these together with every other
            # timer of the kind in Vyom
            self.timer = GLib.timeout_add_seconds(every, self._tick)

    def _read(self):
        now = _boottime()
        for dev in self.devs:
            c = net_counters(dev)
            if c is None:
                continue
            ring = self.rings.get(dev)
            if ring is None:
                ring = self.rings[dev] = collections.deque(maxlen=self.KEEP)
            ring.append((now, c[0], c[1]))
        for dev in [d for d, r in self.rings.items() if d not in self.devs and (not r or now - r[-1][0] > self.WINDOW)]:
            del self.rings[dev]     # gone for longer than any graph looks back

    def _tick(self):
        if not self.devs:
            self.timer = self.every = 0
            return False
        self._read()
        for fn, _fast in list(self.watchers):
            try:
                fn(None)
            except Exception:
                log.exception("history net watcher")
        return True

    def watch(self, fn, fast):
        self.watchers.append([fn, bool(fast)])
        self._schedule()
        return ("net", fn)

    def unwatch(self, handle):
        self.watchers = [w for w in self.watchers if w[0] is not handle[1]]
        self._schedule()

    def default(self):
        if self.primary_dev in self.devs:
            return self.primary_dev
        if self.wifi_dev in self.devs:
            return self.wifi_dev
        return self.devs[0] if self.devs else (self.wifi_dev or None)

    def history(self, dev=None, step=1, window=WINDOW):
        if self.nm is None or not self.nm.running():
            return None
        dev = dev or self.default()
        ring = self.rings.get(dev) if dev else None
        if dev is None:
            return None
        readings = list(ring or ())
        rx, tx = net_bins(readings, step, window, gap=3 * self.SLOW)
        last = readings[-1] if readings else None
        return {"dev": dev, "step": step, "rx": rx, "tx": tx, "up": dev in self.devs,
                "totals": (last[1], last[2]) if last else None, "devices": list(self.devs)}


class BatteryHistory:
    """The laptop battery's charge over time: UPower's own record, read once
    (upowerd writes it to disk anyway, so it covers Vyom's restarts and the
    hours before), then every change UPower signals (the live battery
    state's own signals: no timer, no file)."""
    KEEP = 24 * 3600       # seconds kept
    CHARGING = 1           # UPower's state

    def __init__(self):
        self.points = collections.deque(maxlen=4000)  # (unix time, percent, charging), oldest first
        self.asked = None    # the device path UPower's record was asked for
        self.bat = None

    def start(self):
        self.bat = _source("battery")
        if self.bat is not None:
            self.bat.hooks.append(self._changed)
            self._changed()

    def _laptop(self):
        """(path, proxy) of the battery that powers the machine, or None."""
        for path, p in list(getattr(self.bat, "devices", {}).items()):
            if _unpack(p, "Type", 0) == 2 and _unpack(p, "PowerSupply", False) and _unpack(p, "IsPresent", True):
                return path, p
        return None

    def _changed(self):
        found = self._laptop()
        if found is None:
            return
        path, p = found
        if self.asked != path:
            self.asked = path
            p.call("GetHistory", GLib.Variant("(suu)", ("charge", 0, 100000)), Gio.DBusCallFlags.NONE, 5000, None,
                   self._got)
        pct = _unpack(p, "Percentage", None)
        if pct is not None:
            self._add((time.time(), float(pct), _unpack(p, "State", 0) == self.CHARGING))

    def _add(self, pt):
        last = self.points[-1] if self.points else None
        if last is None or (last[1], last[2]) != (pt[1], pt[2]):
            self.points.append(pt)

    def _got(self, proxy, res):
        try:
            rows = proxy.call_finish(res).unpack()[0]
        except GLib.Error as e:
            log.info("history battery: %s", e.message)
            return
        cut = time.time() - self.KEEP
        old = sorted((float(t), float(v), st == self.CHARGING) for t, v, st in rows if v > 0 or st)
        keep = [p for p in old if p[0] >= cut]
        before = [p for p in old if p[0] < cut]
        mine = [p for p in self.points if not old or p[0] > old[-1][0]]
        self.points.clear()
        for p in before[-1:] + keep + mine:
            self._add(p)

    def history(self, seconds=3 * 3600):
        pts = list(self.points)
        cut = time.time() - seconds
        i = next((k for k, p in enumerate(pts) if p[0] >= cut), len(pts))
        return pts[max(0, i - 1):]


HISTORIES = {"net": NetHistory, "battery": BatteryHistory}


SOURCES = {"wifi": Wifi, "bluetooth": Bluetooth, "battery": Battery, "power_profiles": PowerProfiles,
           "volume": Volume, "brightness": Brightness, "units": Units, "theme": Theme}


# ------------------------------------------------------------------ export
IFACE = "dev.vayu.Vyom.State"
STATE_PATH = "/dev/vayu/Vyom/State"
_exporter = None


class Exporter:
    """Publishes every source's public() summary: a JSON property on D-Bus
    and a JSON file, each only when it changed."""

    def __init__(self, conn, folder):
        self.conn, self.folder = conn, folder
        self.last = {}
        self.reg = 0
        if conn is not None:
            props = "".join(f'<property name="{n}" type="s" access="read"/>' for n in SOURCES)
            xml = (f'<node><interface name="{IFACE}"><method name="Get"><arg name="name" type="s" direction="in"/>'
                   f'<arg name="json" type="s" direction="out"/></method>'
                   f'<method name="History"><arg name="name" type="s" direction="in"/>'
                   f'<arg name="json" type="s" direction="out"/></method>{props}</interface></node>')
            info = Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]
            try:
                self.reg = conn.register_object(STATE_PATH, info, self._call, self._get, None)
            except (GLib.Error, TypeError) as e:
                log.warning("live: couldn't export %s: %s", STATE_PATH, e)
        if folder:
            os.makedirs(folder, mode=0o700, exist_ok=True)
            for f in glob.glob(os.path.join(folder, "*.json")):   # nothing stale from a run before
                if os.path.splitext(os.path.basename(f))[0] not in SOURCES:
                    os.unlink(f)

    def text(self, name):
        return self.last.get(name, "null")

    def _call(self, _conn, _sender, _path, _iface, method, params, inv):
        if method == "Get":
            name = params.unpack()[0]
            src = _source(name)
            if src is not None and name not in self.last:
                self.publish(src)
            inv.return_value(GLib.Variant("(s)", (self.text(name),)))
        elif method == "History":
            # asked for, never pushed: the readings would wake every follower
            import json
            inv.return_value(GLib.Variant("(s)", (json.dumps(history(params.unpack()[0]), default=str),)))

    def _get(self, _conn, _sender, _path, _iface, prop):
        return GLib.Variant("s", self.text(prop))

    def publish(self, src):
        try:
            pub = src.public()
        except Exception:
            log.exception("live %s", src.name)
            return
        import json
        text = json.dumps(pub, sort_keys=True, default=str)
        if self.last.get(src.name) == text:
            return
        self.last[src.name] = text
        if self.folder:
            path = os.path.join(self.folder, f"{src.name}.json")
            tmp = path + ".tmp"
            try:
                with open(tmp, "w") as f:
                    f.write(text + "\n")
                os.replace(tmp, path)
            except OSError as e:
                log.debug("live: %s: %s", path, e)
        if self.reg and self.conn is not None:
            self.conn.emit_signal(None, STATE_PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                  GLib.Variant("(sa{sv}as)", (IFACE, {src.name: GLib.Variant("s", text)}, [])))


def export(conn, folder=None):
    """Starts every source and publishes them (the daemon calls this once).
    folder: where the JSON files go (default $XDG_RUNTIME_DIR/vayu/state)."""
    global _exporter
    if _exporter is not None:
        return
    if folder is None:
        rt = os.environ.get("XDG_RUNTIME_DIR")
        folder = os.path.join(rt, "vayu", "state") if rt else None
    _exporter = Exporter(conn, folder)
    for name in SOURCES:
        src = _source(name)
        if src is not None:
            src.changed()
    for name in HISTORIES:      # kept from now on, so a graph opens full
        _history(name)
