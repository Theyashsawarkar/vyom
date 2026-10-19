"""Small helpers every plugin uses: running commands, the clipboard,
notifications, state files, fuzzy matching."""
import json
import os
import re
import shutil
import subprocess

STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "vyom")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "vyom")


def expand(cmd):
    return os.path.expanduser(os.path.expandvars(cmd))


def run(cmd, timeout=5, input=None):
    """Runs a command (a string goes through the shell, a list doesn't).
    Returns (exit code, stdout stripped); a missing tool or a timeout is
    (127, "")."""
    try:
        r = subprocess.run(expand(cmd) if isinstance(cmd, str) else cmd, shell=isinstance(cmd, str),
                           capture_output=True, text=True, timeout=timeout, input=input)
        return r.returncode, r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def run_full(cmd, timeout=30):
    """Like run(), but returns (code, stdout, stderr) unstripped of nothing."""
    try:
        r = subprocess.run(expand(cmd) if isinstance(cmd, str) else cmd, shell=isinstance(cmd, str),
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)


def spawn(cmd):
    """Starts a command detached and returns at once."""
    subprocess.Popen(expand(cmd) if isinstance(cmd, str) else cmd, shell=isinstance(cmd, str),
                     start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
