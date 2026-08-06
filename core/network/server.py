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
needed around the simulation or the outgoing broadcast itself. self._clients_
lock guards every dict that's both mutated by a connection thread (join/
disconnect) and read or mutated by the main thread: self._clients (write
sockets), self._connections (raw sockets, Phase 5 -- see _kick), and
self._flood_strikes (Phase 5 rate-limit bookkeeping).

Phase 5 hardening (protocol robustness, not position/damage anti-cheat --
that's already covered by the server recomputing all of it itself, see
CLAUDE.md): every decoded line is shape-validated (protocol.validate_message)
in its own connection's reader thread before ever reaching the shared tick
thread, with a bounded per-connection tolerance for consecutive invalid
messages; a per-tick rate limit protects the shared tick loop from a flooding
client; pvp_toggle is restricted to the "host" (lowest currently-connected
player_id); --max-players rejects a connection over capacity before it ever
consumes a player_id."""

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

    # Phase 5 hardening tuning. An honest client sends ~1 "input" message per
    # its own rendered frame (60fps) -- roughly 2 per server tick at 30Hz --
    # so MAX_MESSAGES_PER_TICK leaves generous headroom for jitter/bursts
    # while still catching a real flood. FLOOD_STRIKE_LIMIT requires several
    # *consecutive* over-cap ticks (~165ms of sustained flooding) before
    # disconnecting, so a single burst doesn't cost a legitimate client its
    # connection. INVALID_STRIKE_LIMIT (see _handle_connection) is the same
    # idea for structurally-invalid-but-valid-JSON messages.
    MAX_MESSAGES_PER_TICK = 15
    FLOOD_STRIKE_LIMIT = 5
    INVALID_STRIKE_LIMIT = 10

    def __init__(self, port, room=None, donjon=None, max_players=4):
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

        self.max_players = max_players

        self._next_player_id = 0
        self._clients = {}  # player_id -> binary socket file (write side)
        self._connections = {}  # player_id -> raw socket, so _kick() can shut it down (Phase 5)
        self._flood_strikes = {}  # player_id -> consecutive over-cap ticks (Phase 5)
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
            try:
                join_msg = protocol.decode(first_line)
                protocol.validate_message(join_msg)
            except (ValueError, TypeError) as exc:
                print(f"[server] {addr} sent an invalid join message ({exc}), dropping")
                return

            with self._clients_lock:
                already_connected = len(self._clients)
            if already_connected >= self.max_players:
                print(f"[server] {addr} rejected -- server full ({already_connected}/{self.max_players})")
                try:
                    writer.write(protocol.encode(protocol.MSG_SERVER_FULL))
                    writer.flush()
                except OSError:
                    pass
                return

            player_id = self._next_player_id
            self._next_player_id += 1

            self.explorator.add_network_session(player_id)
            with self._clients_lock:
                self._clients[player_id] = writer
                self._connections[player_id] = conn

            print(f"[server] {addr} joined as player {player_id} ({join_msg.get('name', '?')})")

            writer.write(protocol.encode(
                protocol.MSG_WELCOME, player_id=player_id,
                room_kind=self.room_kind, room_name=self.room_name,
            ))
            writer.flush()

            # Bounded tolerance for structurally-invalid-but-valid-JSON lines
            # (wrong types, missing fields, out-of-range values) -- this
            # counter is local to this connection's own thread, never shared,
            # since each connection has exactly one reader thread. A genuine
            # JSON-parse failure (not even valid JSON) stays strict/immediate
            # -- deliberately NOT the same try/except as validate_message
            # below: unreadable bytes on the wire from a client using our own
            # protocol.encode() should never happen except from a broken or
            # hostile actor, so there's no legitimate-client case to be
            # lenient for there, unlike a merely out-of-range/wrong-type
            # field.
            invalid_streak = 0
            for line in reader:
                if not line.strip():
                    continue
                try:
                    payload = protocol.decode(line)
                except ValueError as exc:
                    print(f"[server] player {player_id} sent unreadable JSON ({exc}), disconnecting")
                    break
                try:
                    protocol.validate_message(payload)
                except (ValueError, TypeError) as exc:
                    invalid_streak += 1
                    print(f"[server] player {player_id} sent an invalid message ({exc}), "
                          f"streak {invalid_streak}/{self.INVALID_STRIKE_LIMIT}")
                    if invalid_streak >= self.INVALID_STRIKE_LIMIT:
                        print(f"[server] disconnecting player {player_id}: too many invalid messages")
                        break
                    continue
                invalid_streak = 0
                self._incoming.put((player_id, payload))
        except OSError:
            pass
        finally:
            if player_id is not None:
                with self._clients_lock:
                    self._clients.pop(player_id, None)
                    self._connections.pop(player_id, None)
                    self._flood_strikes.pop(player_id, None)
                self.explorator.remove_session(player_id)
                self._broadcast(protocol.encode(protocol.MSG_LEAVE, player_id=player_id))
                print(f"[server] player {player_id} disconnected")
            conn.close()

    def _drain_incoming(self):
        """Groups queued messages by player first (rather than applying each
        as it's popped) so a per-tick rate limit can be enforced -- see
        MAX_MESSAGES_PER_TICK. This is deliberately checked here, not in a
        connection's reader thread (Phase 5's other tolerance mechanism,
        invalid_streak in _handle_connection): a reader thread has no notion
        of the server's own tick rate, so "too many messages per tick" can
        only be measured where ticks actually happen."""
        per_player_messages = {}
        while True:
            try:
                player_id, payload = self._incoming.get_nowait()
            except queue.Empty:
                break
            per_player_messages.setdefault(player_id, []).append(payload)

        for player_id, messages in per_player_messages.items():
            if len(messages) > self.MAX_MESSAGES_PER_TICK:
                strikes = self._flood_strikes.get(player_id, 0) + 1
                self._flood_strikes[player_id] = strikes
                print(f"[server] player {player_id} sent {len(messages)} messages in one tick "
                      f"(cap {self.MAX_MESSAGES_PER_TICK}), strike {strikes}/{self.FLOOD_STRIKE_LIMIT}")
                if strikes >= self.FLOOD_STRIKE_LIMIT:
                    self._kick(player_id, "rate limit exceeded")
                    continue
                # Still apply the allowed head of this tick's messages
                # instead of dropping all of them -- a strike shouldn't cost
                # a client every input this tick, only the excess.
                messages = messages[:self.MAX_MESSAGES_PER_TICK]
            else:
                self._flood_strikes[player_id] = 0

            session = self.explorator.players.get(player_id)
            if session is None:
                continue
            for payload in messages:
                self._apply_message(player_id, session, payload)

    def _apply_message(self, player_id, session, payload):
        """try/except is a defense-in-depth safety net, not the primary
        validation -- protocol.validate_message (run in the message's own
        connection thread, see _handle_connection) should already have
        rejected anything malformed before it ever reached this queue. No
        single message is ever allowed to crash the shared tick loop,
        validated or not."""
        try:
            msg_type = payload["type"]
            if msg_type == protocol.MSG_INPUT:
                session.network_input = protocol.input_state_from_fields(payload)
                session.pending_actions.extend(payload.get("requested_actions", []))
                session.last_input_seq = payload.get("seq", session.last_input_seq)
            elif msg_type == protocol.MSG_PVP_TOGGLE:
                if player_id != self._host_player_id():
                    print(f"[server] player {player_id} tried to toggle PvP -- not the host, ignored")
                    return
                self.explorator.pvp_enabled = not self.explorator.pvp_enabled
                print(f"[server] PvP {'ON' if self.explorator.pvp_enabled else 'OFF'} (host: player {player_id})")
        except (KeyError, ValueError, TypeError) as exc:
            print(f"[server] player {player_id} sent a message that failed to apply ({exc}), ignoring")

    def _host_player_id(self):
        """The "host" is whichever currently-connected session has the
        lowest player_id -- not a literal, permanently-fixed id 0. player_ids
        are assigned in increasing connection order and never reused, so
        this is "whoever's been here longest" in spirit, but recomputed live
        so the ability to toggle PvP doesn't get stranded forever if the
        original first-connected player later disconnects."""
        return min(self.explorator.players.keys(), default=None)

    def _kick(self, player_id, reason):
        """Force-disconnects `player_id` from the main thread (used by the
        rate limiter, which can only ever detect the problem here -- see
        _drain_incoming). Shuts down the raw socket rather than touching
        self._clients/self.explorator directly: that unblocks the
        connection's own reader thread (its blocked readline() sees EOF/
        OSError), which then runs through the exact same cleanup path
        (_handle_connection's finally) as any ordinary disconnect -- nothing
        is duplicated here. Mirrors NetworkClient.close()'s own reasoning
        for calling shutdown() before close()."""
        print(f"[server] kicking player {player_id}: {reason}")
        with self._clients_lock:
            conn = self._connections.get(player_id)
        if conn is not None:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

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
