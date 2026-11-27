"""Small helpers every plugin uses: running commands, the clipboard,
notifications, state files, fuzzy matching."""
import json
import logging
import os
import re
import shutil
import subprocess

STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "vyom")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "vyom")

log = logging.getLogger("vyom.util")


def expand(cmd):
    return os.path.expanduser(os.path.expandvars(cmd))


def run(cmd, timeout=5, input=None):
    """Runs a command (a string goes through the shell, a list doesn't).
    Returns (exit code, stdout stripped); a missing tool or a timeout is
    (127, "")."""
    try:
        r = subprocess.run(expand(cmd) if isinstance(cmd, str) else cmd, shell=isinstance(cmd, str),
                           capture_output=True, text=True, timeout=timeout, input=input)
        if r.returncode:
            log.debug("%s: exit %d: %s", cmd, r.returncode, r.stderr.strip()[-500:])
        return r.returncode, r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        log.debug("%s: %s", cmd, e)
        return 127, ""


def run_full(cmd, timeout=30):
    """Like run(), but returns (code, stdout, stderr) unstripped of nothing."""
    try:
        r = subprocess.run(expand(cmd) if isinstance(cmd, str) else cmd, shell=isinstance(cmd, str),
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode:
            log.debug("%s: exit %d: %s", cmd, r.returncode, r.stderr.strip()[-500:])
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        log.debug("%s: %s", cmd, e)
        return 127, "", str(e)


def unit_part(name):
    """name as a piece of a systemd unit name: [A-Za-z0-9_.-] only."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:64] or "app"


def adopt(pid, name):
    """Moves a process Vyom just started into its own systemd user scope
    (app-vyom-<name>-<pid>.scope in app.slice), the way desktop shells do.
    Without it an app opened from a panel lives in vyom.service's cgroup:
    its memory and CPU count as Vyom's, and stopping or restarting Vyom
    kills it. False (and nothing else happens) without a systemd user
    manager."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        props = [("PIDs", GLib.Variant("au", [pid])), ("Slice", GLib.Variant("s", "app.slice")),
                 ("CollectMode", GLib.Variant("s", "inactive-or-failed"))]
        bus.call_sync("org.freedesktop.systemd1", "/org/freedesktop/systemd1",
                      "org.freedesktop.systemd1.Manager", "StartTransientUnit",
                      GLib.Variant("(ssa(sv)a(sa(sv)))",
                                   (f"app-vyom-{unit_part(name)}-{pid}.scope", "fail", props, [])),
                      None, Gio.DBusCallFlags.NO_AUTO_START, 1000, None)
        return True
    except Exception as e:  # no systemd, no session bus, the process already exited
        log.debug("couldn't move %s (pid %d) into its own scope: %s", name, pid, e)
        return False


def spawn(cmd):
    """Starts a command detached, in its own systemd scope (see adopt), and
    returns at once."""
    p = subprocess.Popen(expand(cmd) if isinstance(cmd, str) else cmd, shell=isinstance(cmd, str),
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    argv0 = (expand(cmd).split() or ["sh"])[0] if isinstance(cmd, str) else cmd[0]
    adopt(p.pid, os.path.basename(argv0))


def have(tool):
    tool = expand(tool).split()[0]
    return shutil.which(tool) is not None or os.access(tool, os.X_OK)


def copy(text):
    """To the clipboard (wl-copy, else xclip)."""
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text, text=True, timeout=3)
                return True
            except (OSError, subprocess.TimeoutExpired):
                pass
    return False


def type_text(text):
    """Types text into the focused window (wtype, else ydotool)."""
    if shutil.which("wtype"):
        return subprocess.run(["wtype", text]).returncode == 0
    if shutil.which("ydotool"):
        return subprocess.run(["ydotool", "type", text]).returncode == 0
    return False


def notify(title, body="", icon="", app="Vyom", urgency=None):
    if not shutil.which("notify-send"):
        return
    cmd = ["notify-send", "-a", app, title, body]
    if icon:
        cmd[1:1] = ["-i", icon]
    if urgency:
        cmd[1:1] = ["-u", urgency]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def load_state(name, default=None):
    try:
        with open(os.path.join(STATE, name + ".json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default if default is not None else {}


def save_state(name, data):
    os.makedirs(STATE, exist_ok=True)
    tmp = os.path.join(STATE, name + ".json.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, os.path.join(STATE, name + ".json"))


def fuzzy(query, text, loose=True):
    """Score of `query` in `text` (higher is better), or None when the
    letters don't all appear in order. Whole-word and prefix hits win.
    loose=False only accepts the query as a substring (for big lists of
    short names, like emoji, where scattered letters match everything)."""
    if not query:
        return 0
    q, t = query.lower(), text.lower()
    if not loose and q not in t:
        return None
    if q in t:
        i = t.index(q)
        score = 100 - i
        if i == 0:
            score += 50
        elif not t[i - 1].isalnum():
            score += 30
        return score
    pos, score, last = 0, 0, -1
    for ch in q:
        i = t.find(ch, pos)
        if i < 0:
            return None
        score += 10 if i == last + 1 else 1
        last, pos = i, i + 1
    return score


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def strip_markup(s):
    return re.sub(r"<[^>]+>", "", s)


_malloc_trim = None


def trim_memory():
    """Hands the C heap's free pages back to the system (glibc's
    malloc_trim). GTK, Pango and the Vulkan driver free a lot when a panel
    goes away, but glibc keeps the pages: after Mesa compiles its shaders
    (the first start after a driver update) the heap stayed at 140 MB, 20
    MB with this. Under a millisecond; a no-op without glibc. True if
    anything was returned."""
    global _malloc_trim
    if _malloc_trim is None:
        try:
            import ctypes
            # The C library this process already has (no ctypes.util: it
            # runs ldconfig to look for it, 100+ ms).
            _malloc_trim = ctypes.CDLL(None).malloc_trim
            _malloc_trim.argtypes = [ctypes.c_size_t]
        except (OSError, AttributeError):   # musl and friends have no malloc_trim
            _malloc_trim = False
    return bool(_malloc_trim and _malloc_trim(0))
