"""LAN discovery for host/join-from-home (multiplayer): plain UDP
broadcast, host-announces / client-listens -- like Minecraft's own LAN
world discovery, not a request/response protocol, so no coordination is
needed between the two sides. No internet/friends-list component -- pure
local-network broadcast, the rest is explicitly future work (see
CLAUDE.md's Phase 6c-original-follow-up writeup)."""

from __future__ import annotations

import json
import socket
import threading
import time

DISCOVERY_PORT = 42423
ANNOUNCE_INTERVAL = 1.0  # seconds between a hosting process's broadcasts
ENTRY_TIMEOUT = 5.0  # a browsed entry not re-announced within this long is dropped
_MAGIC = "da_announce"  # payload["type"], distinguishes our packets from other LAN traffic on this port


class HostAnnouncer:
    """Background daemon thread broadcasting a small UDP packet advertising
    a hosted session -- started/stopped alongside GameServer itself (see
    Explorator.start_hosting/stop_networking), never on its own."""

    def __init__(self, name, tcp_port, room_kind, room_name):
        self._payload = json.dumps({
            "type": _MAGIC,
            "name": name,
            "tcp_port": tcp_port,
            "room_kind": room_kind,
            "room_name": room_name,
        }).encode("utf-8")
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            while self._running:
                try:
                    sock.sendto(self._payload, ("255.255.255.255", DISCOVERY_PORT))
                except OSError:
                    pass  # no network / broadcast blocked -- just try again next interval
                time.sleep(ANNOUNCE_INTERVAL)
        finally:
            sock.close()


class SessionBrowser:
    """Listens for HostAnnouncer broadcasts while a "browse sessions"
    screen is open (see MultiplayerPanelUI) -- entries() returns every
    session heard from within ENTRY_TIMEOUT seconds, keyed by (source_ip,
    tcp_port) so one host re-announcing repeatedly doesn't duplicate a
    row. Non-blocking throughout -- poll() is meant to be called once a
    frame from the render loop, never blocks waiting for a packet."""

    def __init__(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("", DISCOVERY_PORT))
        self._sock.setblocking(False)
        self._entries = {}  # (ip, tcp_port) -> (name, room_kind, room_name, last_seen)

    def poll(self):
        """Drains every packet currently waiting (never blocks) and
        updates self._entries; stale pruning happens in entries()."""
        while True:
            try:
                data, addr = self._sock.recvfrom(2048)
            except (BlockingIOError, OSError):
                break
            try:
                payload = json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(payload, dict) or payload.get("type") != _MAGIC:
                continue
            try:
                tcp_port = int(payload["tcp_port"])
                name = str(payload["name"])
                room_kind = str(payload["room_kind"])
                room_name = str(payload["room_name"])
            except (KeyError, TypeError, ValueError):
                continue
            self._entries[(addr[0], tcp_port)] = (name, room_kind, room_name, time.monotonic())

    def entries(self):
        """(ip, tcp_port, name, room_kind, room_name) for every session
        heard from recently -- anything not re-announced within
        ENTRY_TIMEOUT (the host stopped, or closed the game) is dropped."""
        now = time.monotonic()
        self._entries = {
            key: value for key, value in self._entries.items()
            if now - value[3] <= ENTRY_TIMEOUT
        }
        return [
            (ip, tcp_port, name, room_kind, room_name)
            for (ip, tcp_port), (name, room_kind, room_name, _last_seen) in self._entries.items()
        ]

    def close(self):
        self._sock.close()
