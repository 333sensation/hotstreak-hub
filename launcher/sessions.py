#!/usr/bin/env python3
"""Who is hosting right now: a tiny LAN session browser.

Dolphin's own netplay lobby needs dolphin-emu.org, so this keeps its own list:
a host announces its session over UDP broadcast, every launcher on the same
network picks it up and shows it in "active sessions". Nothing to sign up for,
nothing to host, works on Windows, macOS and Linux the same way.

Packet (JSON, one datagram):

    {"app": "sscr-netplay", "code": "ABC123", "host": "Ana",
     "addr": "192.168.1.5", "port": 2626, "players": 2, "version": 1}
"""
import json
import platform
import socket
import threading
import time

PORT = 9797
APP = "sscr-netplay"
VERSION = 1
BROADCAST_ADDRS = ("255.255.255.255", "127.0.0.1")


class Beacon:
    """Announce one hosted session while it is open."""

    def __init__(self, code, port, players=2, name=None, addr=None):
        self.code = code.upper()
        self.port = port
        self.players = players
        self.name = name or platform.node() or "player"
        self.addr = addr
        self._stop = threading.Event()
        self._thread = None

    def payload(self):
        return json.dumps({
            "app": APP, "version": VERSION, "code": self.code,
            "host": self.name, "addr": self.addr or local_ip(),
            "port": self.port, "players": self.players,
        }).encode()

    def start(self):
        if self._thread:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock = sock

        def loop():
            while not self._stop.is_set():
                for dst in BROADCAST_ADDRS:
                    try:
                        sock.sendto(self.payload(), (dst, PORT))
                    except OSError:
                        pass
                self._stop.wait(2.0)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            self._sock.close()
        except (AttributeError, OSError):
            pass
        self._thread = None


class Discovery:
    """Collect the sessions other launchers are announcing."""

    def __init__(self, port=PORT):
        self.port = port
        self.sessions = {}          # code -> (info, last_seen)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        sock.bind(("", self.port))
        sock.settimeout(0.5)
        self._sock = sock

        def loop():
            while not self._stop.is_set():
                try:
                    data, src = sock.recvfrom(2048)
                except (socket.timeout, OSError):
                    continue
                try:
                    info = json.loads(data.decode())
                except (ValueError, UnicodeDecodeError):
                    continue
                if info.get("app") != APP or not info.get("code"):
                    continue
                info.setdefault("addr", src[0])
                with self._lock:
                    self.sessions[info["code"].upper()] = (info, time.time())

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def active(self, within=8.0):
        now = time.time()
        with self._lock:
            out = [info for info, seen in self.sessions.values() if now - seen <= within]
            for code in [c for c, (_, seen) in self.sessions.items() if now - seen > within]:
                self.sessions.pop(code, None)
        out.sort(key=lambda i: i.get("host", ""))
        return out

    def stop(self):
        self._stop.set()
        try:
            self._sock.close()
        except (AttributeError, OSError):
            pass
        self._thread = None


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"
