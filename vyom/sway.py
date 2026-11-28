"""Sway's workspaces, followed in-process over its IPC socket ($SWAYSOCK,
i3's protocol): one connection subscribed to workspace, output and shutdown
events, read by a GLib fd watch. Nothing polls: Vyom wakes only when sway
says something changed, and then asks for the workspace list once (ADR 17).

Without sway (another compositor, no socket) nothing happens and panels
behave as if there were one workspace."""
import glob
import json
import logging
import os
import socket
import struct

log = logging.getLogger("vyom")

MAGIC = b"i3-ipc"
HEADER = struct.Struct("=6sII")   # magic, payload length, type (native byte order)
GET_WORKSPACES, SUBSCRIBE = 1, 2
EVENT = 0x80000000
EV_WORKSPACE, EV_OUTPUT, EV_SHUTDOWN = EVENT | 0, EVENT | 1, EVENT | 6
# Workspace changes that can move panels (not "urgent": a window's hint).
WORKSPACE_CHANGES = {"focus", "init", "empty", "move", "rename", "reload"}


def pack(kind, payload=b""):
    if isinstance(payload, str):
        payload = payload.encode()
    return HEADER.pack(MAGIC, len(payload), kind) + payload


def unpack(buf):
    """Whole messages at the start of buf: ([(type, payload bytes)], the rest).
    Raises ValueError on a stream that isn't i3 IPC."""
    out = []
    while len(buf) >= HEADER.size:
        magic, size, kind = HEADER.unpack_from(buf)
        if magic != MAGIC:
            raise ValueError("not i3-ipc")
        if len(buf) < HEADER.size + size:
            break
        out.append((kind, bytes(buf[HEADER.size:HEADER.size + size])))
        buf = buf[HEADER.size + size:]
    return out, buf


def summarize(workspaces):
    """GET_WORKSPACES' reply -> (focused name, {output: name on screen},
    {id: name})."""
    focused, visible, ids = None, {}, {}
    for w in workspaces or ():
        name = w.get("name")
        if name is None:
            continue
        ids[w.get("id")] = name
        if w.get("visible") and w.get("output"):
            visible[w["output"]] = name
        if w.get("focused"):
            focused = name
    return focused, visible, ids


def socket_path(env=os.environ):
    """$SWAYSOCK (or $I3SOCK when it's sway's), else the one live sway
    socket in $XDG_RUNTIME_DIR."""
    for k in ("SWAYSOCK", "I3SOCK"):
        p = env.get(k)
        if p and os.path.exists(p):
            return p
    rt = env.get("XDG_RUNTIME_DIR")
    if not rt:
        return None
    alive = []
    for p in glob.glob(os.path.join(rt, f"sway-ipc.{os.getuid()}.*.sock")):
        try:
            pid = int(os.path.basename(p).split(".")[2])
            os.kill(pid, 0)
            alive.append(p)
        except (ValueError, IndexError, ProcessLookupError, PermissionError):
            continue
    return alive[0] if len(alive) == 1 else None


class Watch:
    """Calls on_workspaces(focused, visible, ids) at start and after every
    change sway reports. stop() (or sway's shutdown) closes the socket."""

    def __init__(self, on_workspaces, path=None):
        self.on_workspaces = on_workspaces
        self.path = path or socket_path()
        self.sock = None
        self.src = 0
        self.buf = b""
        self.asked = False   # a GET_WORKSPACES is on its way: changes before it lands need no second one
        self.last = None     # what on_workspaces was last told

    def start(self):
        if not self.path:
            log.info("no sway socket: panels don't follow workspaces")
            return False
        from gi.repository import GLib
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
            s.connect(self.path)
            s.sendall(pack(SUBSCRIBE, json.dumps(["workspace", "output", "shutdown"])) + pack(GET_WORKSPACES))
            s.setblocking(False)
        except OSError as e:
            log.warning("sway IPC (%s): %s; panels don't follow workspaces", self.path, e)
            return False
        self.sock, self.asked = s, True
        self.src = GLib.unix_fd_add_full(GLib.PRIORITY_HIGH, s.fileno(),
                                         GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
                                         self._readable)
        return True

    def stop(self):
        if self.src:
            from gi.repository import GLib
            GLib.source_remove(self.src)
            self.src = 0
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _ask(self):
        if self.asked or self.sock is None:
            return
        try:
            self.sock.sendall(pack(GET_WORKSPACES))
            self.asked = True
        except OSError as e:
            log.warning("sway IPC: %s", e)

    def _tell(self, focused, visible, ids):
        if self.last == (focused, visible, ids):
            return
        self.last = (focused, visible, ids)
        try:
            self.on_workspaces(focused, visible, ids)
        except Exception:   # a bug in Vyom's handler must not stop the watch
            log.exception("following sway's workspaces")

    def _readable(self, _fd, _cond):
        try:
            data = self.sock.recv(65536) if self.sock is not None else b""
        except BlockingIOError:
            return True
        except OSError:
            data = b""
        if not data:
            log.info("sway IPC closed: panels stop following workspaces")
            self.src = 0
            self.stop()
            return False
        try:
            msgs, self.buf = unpack(self.buf + data)
        except ValueError:
            log.warning("sway IPC: unreadable reply; stopped following workspaces")
            self.src = 0
            self.stop()
            return False
        for kind, payload in msgs:
            self.handle(kind, payload)
        if self.sock is None:
            self.src = 0
            return False
        return True

    def handle(self, kind, payload):
        if kind == SUBSCRIBE:
            return
        try:
            body = json.loads(payload or b"null")
        except ValueError:
            return
        if kind == GET_WORKSPACES:
            self.asked = False
            self._tell(*summarize(body))
        elif kind == EV_WORKSPACE:
            change = (body or {}).get("change")
            cur = (body or {}).get("current") or {}
            if change == "focus" and self.last is not None and cur.get("name") is not None and cur.get("output"):
                # Told at once from the event itself (one round trip less
                # before panels hide); the list asked next corrects it.
                _focused, visible, ids = self.last
                visible = {**visible, cur["output"]: cur["name"]}
                ids = {**ids, cur.get("id"): cur["name"]}
                self._tell(cur["name"], visible, ids)
            if change in WORKSPACE_CHANGES:
                self._ask()
        elif kind == EV_OUTPUT:
            self._ask()
        elif kind == EV_SHUTDOWN:
            self.stop()
