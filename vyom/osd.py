"""Volume and brightness keys in one call (Vyom 0.11, ADR 15).

    busctl --user call dev.vayu.Vyom /dev/vayu/Vyom/Osd dev.vayu.Vyom.Osd Step s 'volume +5'
    -> b true      (false: the level isn't known; do it another way)

Step takes "volume +N" / "volume -N" / "volume mute-toggle" or
"brightness +N" / "brightness -N" (percent). A volume or brightness key used
to run a shell script per press: ~11 processes (pactl five times, grep,
head, flock, notify-send...), 40-80 ms before the slider showed. Here the
level is already known (vyom.live follows both), so a press is worked out at
once, the slider is asked for at once (a desktop notification with the
value hint, as notify-send sent it: the same look in any notification
server), and the change is applied behind it:

  volume      one `pactl set-sink-volume` (and `set-sink-mute` only when the
              mute changes), never two at once: presses that come while one
              runs are one more after it, from the latest level, so a burst
              (a touchpad's scroll) stacks correctly and never passes 0-100.
              0% also mutes; raising or lowering unmutes.
  brightness  logind's SetBrightness (no process at all; any user in the
              active session may), else `brightnessctl set`.
"""
import logging
import os
import re

from gi.repository import Gio, GLib

from . import live

log = logging.getLogger("vyom.osd")

SYNC = "sys-notify"   # the synchronous tag the scripts used: one slider that replaces itself


def volume_icon(pct, muted=False):
    if muted or pct <= 0:
        return "audio-volume-muted"
    return "audio-volume-low" if pct < 34 else "audio-volume-medium" if pct < 67 else "audio-volume-high"


class _Osd:
    def __init__(self):
        self.vol = None       # {"volume": n, "muted": b}: what we last asked for (ahead of live)
        self.vol_at = 0
        self.running = False  # a pactl is running
        self.queued = None    # (volume, muted) to apply after it
        self.applied = None   # (volume, muted) last sent to the sound server
        self.bri = None
        self.bri_at = 0
        self.bri_running = False
        self.bri_queued = None
        self.system = None
        self.session = None   # logind's object path of our session
        self.logind = None    # False once SetBrightness failed: brightnessctl from then on

    # ---------------------------------------------------------------- slider
    def show(self, summary, body, icon, value):
        hints = {"x-canonical-private-synchronous": GLib.Variant("s", SYNC),
                 "urgency": GLib.Variant("y", 0), "value": GLib.Variant("i", int(value))}
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                     "org.freedesktop.Notifications", "Notify",
                     GLib.Variant("(susssasa{sv}i)", ("Vyom", 0, icon, summary, body, [], hints, -1)),
                     GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 2000, None, self._shown)
        except GLib.Error as e:
            log.debug("osd: no notification server: %s", e.message)

    @staticmethod
    def _shown(bus, res):
        try:
            bus.call_finish(res)
        except GLib.Error as e:
            log.debug("osd: %s", e.message)

    # ---------------------------------------------------------------- volume
    def current_volume(self):
        now = GLib.get_monotonic_time()
        snap = live.get("volume") or {}
        # Our own last level while a change is on its way (the sound server's
        # answer comes ~10 ms later): a burst stacks on it, not on old news.
        if self.vol is not None and (self.running or now - self.vol_at < 1_000_000):
            return self.vol["volume"], self.vol["muted"]
        if "volume" not in snap:
            return None
        return int(snap.get("volume") or 0), bool(snap.get("muted"))

    def volume(self, how):
        if not self.running and GLib.get_monotonic_time() - self.vol_at >= 1_000_000:
            self.applied = None   # a new burst: start from what the sound server says
        cur = self.current_volume()
        if cur is None:
            return False
        vol, muted = cur
        if how == "mute-toggle":
            muted = not muted
        else:
            m = re.fullmatch(r"([+-]?)(\d+)%?", how)
            if not m:
                return False
            n = int(m.group(2))
            vol = max(0, min(100, vol + n if m.group(1) == "+" else vol - n if m.group(1) == "-" else n))
            muted = vol == 0   # 0% is muted; any other level is heard
        self.vol, self.vol_at = {"volume": vol, "muted": muted}, GLib.get_monotonic_time()
        if muted:
            self.show("Volume", "Muted", volume_icon(0), 0)
        else:
            self.show("Volume", f"{vol}%", volume_icon(vol), vol)
        self.apply_volume(vol, muted)
        return True

    def apply_volume(self, vol, muted):
        if self.running:
            self.queued = (vol, muted)
            return
        snap = live.get("volume") or {}
        was = self.applied or (snap.get("volume"), snap.get("muted"))
        steps = []
        if was[0] != vol:
            steps.append(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{vol}%"])
        if was[1] is None or bool(was[1]) != muted:
            steps.append(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if muted else "0"])
        self.applied = (vol, muted)
        if steps:
            self._run(steps)

    def _run(self, steps):
        """The steps side by side; when all are done, the queued level."""
        self.running = True
        left = [len(steps)]

        def one_done(*_):
            left[0] -= 1
            if left[0] == 0:
                self.running = False
                if self.queued is not None:
                    q, self.queued = self.queued, None
                    self.apply_volume(*q)

        def done(proc, res):
            try:
                proc.wait_finish(res)
            except GLib.Error:
                pass
            one_done()
        for argv in steps:
            try:
                Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_SILENCE |
                                   Gio.SubprocessFlags.STDERR_SILENCE).wait_async(None, done)
            except GLib.Error as e:
                log.warning("osd: %s: %s", argv[0], e.message)
                one_done()

    # ------------------------------------------------------------ brightness
    def brightness(self, how):
        m = re.fullmatch(r"([+-]?)(\d+)%?", how)
        snap = live.get("brightness")
        if not m or not snap or not snap.get("max"):
            return False
        top = int(snap["max"])
        now = GLib.get_monotonic_time()
        cur = self.bri if self.bri is not None and now - self.bri_at < 1_000_000 else int(snap["brightness"])
        n = int(m.group(2)) * top / 100
        val = cur + n if m.group(1) == "+" else cur - n if m.group(1) == "-" else n
        val = int(round(max(0, min(top, val))))
        self.bri, self.bri_at = val, now
        pct = round(val * 100 / top)
        self.show("Brightness", f"{pct}%", "display-brightness", pct)
        self.set_brightness(snap["device"], val, pct)
        return True

    def set_brightness(self, device, val, pct):
        """logind's Session.SetBrightness for our graphical session (found
        once: $XDG_SESSION_ID, else the user's display session), else one
        `brightnessctl set` at a time (a burst's last level wins)."""
        if self.bri_running:
            self.bri_queued = (device, val, pct)
            return
        self.bri_running = True

        def finished():
            self.bri_running = False
            if self.bri_queued is not None:
                q, self.bri_queued = self.bri_queued, None
                self.set_brightness(*q)

        def fallback():
            self.logind = False
            try:
                p = Gio.Subprocess.new(["brightnessctl", "-q", "set", str(val)],
                                       Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
                p.wait_async(None, lambda *_: finished())
            except GLib.Error as e:
                log.warning("osd: brightnessctl: %s", e.message)
                finished()

        def done(bus, res):
            try:
                bus.call_finish(res)
            except GLib.Error as e:
                log.debug("osd: logind SetBrightness: %s; brightnessctl from now on", e.message)
                fallback()
                return
            finished()

        def with_session(path):
            if not path:
                fallback()
                return
            self.session = path
            self.system.call("org.freedesktop.login1", path, "org.freedesktop.login1.Session", "SetBrightness",
                             GLib.Variant("(ssu)", ("backlight", device, val)), None, Gio.DBusCallFlags.NONE,
                             2000, None, done)
        if self.logind is False:
            fallback()
            return
        try:
            self.system = self.system or Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error:
            fallback()
            return
        if self.session:
            with_session(self.session)
        else:
            self.find_session(with_session)

    def find_session(self, then):
        """Our session's object path: Vyom often runs as a user service,
        outside any session, so logind's "auto" wouldn't find one."""
        sid = os.environ.get("XDG_SESSION_ID")

        def got(bus, res, prop=False):
            try:
                v = bus.call_finish(res).unpack()[0]
                then(v[1] if prop else v)
            except (GLib.Error, IndexError, TypeError):
                then(None)

        def got_user(bus, res):
            try:
                user = bus.call_finish(res).unpack()[0]
            except GLib.Error:
                then(None)
                return
            bus.call("org.freedesktop.login1", user, "org.freedesktop.DBus.Properties", "Get",
                     GLib.Variant("(ss)", ("org.freedesktop.login1.User", "Display")), None,
                     Gio.DBusCallFlags.NONE, 2000, None, lambda b, r: got(b, r, prop=True))
        if sid:
            self.system.call("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager",
                             "GetSession", GLib.Variant("(s)", (sid,)), None, Gio.DBusCallFlags.NONE, 2000, None, got)
        else:
            self.system.call("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager",
                             "GetUser", GLib.Variant("(u)", (os.getuid(),)), None, Gio.DBusCallFlags.NONE, 2000,
                             None, got_user)


_osd = None


def step(what):
    """'volume +5', 'volume -5', 'volume mute-toggle', 'brightness +5'...
    False when it can't (no such level known): the caller does it the old way."""
    global _osd
    if _osd is None:
        _osd = _Osd()
    kind, _, how = what.strip().partition(" ")
    how = how.strip()
    if kind == "volume":
        return _osd.volume(how)
    if kind == "brightness":
        return _osd.brightness(how)
    return False


PATH, IFACE = "/dev/vayu/Vyom/Osd", "dev.vayu.Vyom.Osd"
_reg = 0


def export(conn):
    """dev.vayu.Vyom.Osd.Step(s) -> b on the daemon's connection."""
    global _reg
    if _reg or conn is None:
        return
    xml = (f'<node><interface name="{IFACE}"><method name="Step"><arg name="what" type="s" direction="in"/>'
           '<arg name="ok" type="b" direction="out"/></method></interface></node>')

    def call(_conn, _sender, _path, _iface, method, params, inv):
        try:
            ok = bool(step(params.unpack()[0]))
        except Exception:   # a key must never break the daemon
            log.exception("osd")
            ok = False
        inv.return_value(GLib.Variant("(b)", (ok,)))
    try:
        _reg = conn.register_object(PATH, Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0], call, None, None)
    except (GLib.Error, TypeError) as e:
        log.warning("osd: couldn't export %s: %s", PATH, e)
