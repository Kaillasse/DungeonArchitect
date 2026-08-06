"""Headless authoritative server (multiplayer Phase 3): owns one Explorator
instance -- screen-less, no local input devices -- and runs it at a fixed
tick. Every PlayerSession here is "network" (see PlayerSession/Explorator's
_read_input), driven by whatever a connected client's own reader thread most
recently decoded from that client's socket, rather than a local device.

Threading model: one accept thread, one reader thread per connected client
(blocking readline() -> decode -> pushed onto a shared queue.Queue). The
single main thread (serve_forever's tick loop) is the only thing that ever
calls Explorator.update() or writes to a client socket -- reads and writes
never share a thread, and writes never race each other, so no locking is
needed around the simulation or the outgoing broadcast itself (only
self._clients, mutated by both the accept/connection threads and read by the
broadcast, is guarded)."""

from __future__ import annotations

import os
import queue
import socket
import threading
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from core.engine.gamestate import GameState
from core.exploration.explorator import Explorator
from core.network import protocol


class _HeadlessGameManager:
    """The minimal surface Explorator.__init__/_game_over actually touch
    (screen, settings, state, running) -- a server has no real window and no
    Settings-driven local player, so a real GameManager (which also
    constructs Menu/Creator) would be pure overhead here."""

    def __init__(self, screen):
        self.screen = screen
        self.settings = None
        self.state = GameState.EXPLORATION
        self.running = True


class GameServer:
    TICK_RATE = 30
    TICK_DT = 1.0 / TICK_RATE

    def __init__(self, port, room=None, donjon=None):
        assert (room is None) != (donjon is None), "exactly one of room/donjon must be given"

        pygame.init()
        screen = pygame.display.set_mode((1, 1))

        self._game_manager = _HeadlessGameManager(screen)
        self.explorator = Explorator(self._game_manager)
        # __init__ always creates a local id-0 keyboard session (and maybe a
        # gamepad one, if this machine happens to have a controller) -- a
        # server has no local player at all, every session arrives over the
        # network.
        self.explorator.players.clear()

        if donjon is not None:
            self.room_kind, self.room_name = "donjon", donjon
            self.explorator.open_donjon(donjon)
        else:
            self.room_kind, self.room_name = "room", room
            self.explorator.open_room(room)

        self._next_player_id = 0
        self._clients = {}  # player_id -> binary socket file (write side)
        self._clients_lock = threading.Lock()
        self._incoming = queue.Queue()  # (player_id, payload) from every reader thread
        self._terrain_versions = {}
        self._tick = 0
        self._running = True

        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind(("0.0.0.0", port))
        self._server_socket.listen()

    def serve_forever(self):
        threading.Thread(target=self._accept_loop, daemon=True).start()
        print(f"[server] listening on port {self._server_socket.getsockname()[1]}, "
              f"{self.room_kind}={self.room_name!r}, tick={self.TICK_RATE}Hz")
        try:
            while self._running:
                tick_start = time.monotonic()

                self._drain_incoming()
                self.explorator.update(self.TICK_DT)
                self._tick += 1
                self._broadcast_snapshot()

                if self._game_manager.state != GameState.EXPLORATION:
                    print("[server] game over -- stopping")
                    break

                elapsed = time.monotonic() - tick_start
                time.sleep(max(0.0, self.TICK_DT - elapsed))
        finally:
            self._shutdown()

    # ------------------------------------------------------

    def _accept_loop(self):
        while self._running:
            try:
                conn, addr = self._server_socket.accept()
            except OSError:
                return
            threading.Thread(target=self._handle_connection, args=(conn, addr), daemon=True).start()

    def _handle_connection(self, conn, addr):
        reader = conn.makefile("rb")
        writer = conn.makefile("wb")
        player_id = None
        try:
            first_line = reader.readline()
            if not first_line:
                return
            join_msg = protocol.decode(first_line)

            player_id = self._next_player_id
            self._next_player_id += 1

            self.explorator.add_network_session(player_id)
            with self._clients_lock:
                self._clients[player_id] = writer

            print(f"[server] {addr} joined as player {player_id} ({join_msg.get('name', '?')})")

            writer.write(protocol.encode(
                protocol.MSG_WELCOME, player_id=player_id,
                room_kind=self.room_kind, room_name=self.room_name,
            ))
            writer.flush()

            for line in reader:
                if not line.strip():
                    continue
                self._incoming.put((player_id, protocol.decode(line)))
        except (OSError, ValueError):
            pass
        finally:
            if player_id is not None:
                with self._clients_lock:
                    self._clients.pop(player_id, None)
                self.explorator.remove_session(player_id)
                self._broadcast(protocol.encode(protocol.MSG_LEAVE, player_id=player_id))
                print(f"[server] player {player_id} disconnected")
            conn.close()

    def _drain_incoming(self):
        while True:
            try:
                player_id, payload = self._incoming.get_nowait()
            except queue.Empty:
                break

            session = self.explorator.players.get(player_id)
            if session is None:
                continue

            if payload["type"] == protocol.MSG_INPUT:
                session.network_input = protocol.input_state_from_fields(payload)
                session.pending_actions.extend(payload.get("requested_actions", []))
                session.last_input_seq = payload.get("seq", session.last_input_seq)
            elif payload["type"] == protocol.MSG_PVP_TOGGLE:
                self.explorator.pvp_enabled = not self.explorator.pvp_enabled
                print(f"[server] PvP {'ON' if self.explorator.pvp_enabled else 'OFF'}")

    def _broadcast_snapshot(self):
        snapshot = protocol.build_snapshot(self.explorator, self._tick, self._terrain_versions)
        self._broadcast(protocol.encode_dict(snapshot))

    def _broadcast(self, raw_bytes):
        with self._clients_lock:
            dead = []
            for player_id, writer in self._clients.items():
                try:
                    writer.write(raw_bytes)
                    writer.flush()
                except OSError:
                    dead.append(player_id)
            for player_id in dead:
                self._clients.pop(player_id, None)

    def _shutdown(self):
        self._running = False
        try:
            self._server_socket.close()
        except OSError:
            pass
