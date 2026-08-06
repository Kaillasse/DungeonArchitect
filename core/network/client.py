"""Thin network client (multiplayer Phase 3): connects to a GameServer,
sends this machine's local input once per frame, and hands decoded server
messages back to the caller (Explorator.run_networked) to apply -- no
simulation of the shared world happens here, purely a socket-to-queue pump.
See CLAUDE.md's Phase 3 section ("thin client, no prediction") for why the
client never simulates locally."""

from __future__ import annotations

import queue
import socket
import threading
import time

from core.network import protocol


class NetworkClient:
    def __init__(self, host, port, name="player"):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        self._reader_file = self.sock.makefile("rb")
        self._writer_file = self.sock.makefile("wb")
        self._incoming = queue.Queue()
        self._running = True

        self.send(protocol.MSG_JOIN, name=name)

        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def wait_for_welcome(self, timeout=5.0):
        """Blocks (briefly) for the server's initial "welcome" message --
        called once, before the render loop starts, so the caller knows
        which room to load locally and which player_id is its own (see
        Explorator.adopt_local_player_id)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                payload = self._incoming.get(timeout=0.1)
            except queue.Empty:
                continue
            if payload["type"] == protocol.MSG_WELCOME:
                return payload
        raise TimeoutError("No welcome message received from server")

    def send(self, msg_type, **fields):
        if not self._running:
            return
        try:
            self._writer_file.write(protocol.encode(msg_type, **fields))
            self._writer_file.flush()
        except OSError:
            self._running = False

    def drain(self):
        """Every message received since the last call, oldest first."""
        messages = []
        while True:
            try:
                messages.append(self._incoming.get_nowait())
            except queue.Empty:
                break
        return messages

    def _read_loop(self):
        try:
            for line in self._reader_file:
                if not line.strip():
                    continue
                self._incoming.put(protocol.decode(line))
        except OSError:
            pass
        finally:
            self._running = False

    def close(self):
        self._running = False
        # socket.makefile()'s file objects each hold their own reference to
        # the underlying fd -- plain sock.close() only drops the socket
        # object's own reference and leaves the fd (and the TCP connection)
        # open for as long as self._reader_file/_writer_file still exist,
        # so the server's blocking readline() would never see EOF.
        # shutdown() acts on the real OS socket immediately regardless of
        # how many Python-level references remain.
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        for file_obj in (self._reader_file, self._writer_file):
            try:
                file_obj.close()
            except OSError:
                pass
        try:
            self.sock.close()
        except OSError:
            pass
