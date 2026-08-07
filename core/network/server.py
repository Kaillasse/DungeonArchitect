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
import sys
import threading
import time

# No SDL_VIDEODRIVER/SDL_AUDIODRIVER env-forcing at module scope anymore --
# this module is now also imported by the normal windowed process (hosting
# from home, see Explorator.start_hosting), which must keep its real
# display driver. The standalone dummy-driver setup now lives in whichever
# caller actually needs a headless display (GameServer.__init__ below,
# only when constructed without an existing `screen`).
import pygame

from core.engine.gamestate import GameState
from core.exploration.explorator import Explorator
from core.data import progression
from core.data.profile_manager import ProfileManager
from core.network import protocol


DEFAULT_PORT = 5555


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

    # How often each connection's reader thread wakes from a blocking read to
    # check whether it's been kicked (see _kick) -- a lower value notices a
    # kick sooner but wakes every idle connection's thread more often for no
    # real benefit; 1s is imperceptible for a kicked player and negligible
    # overhead for N idle connections.
    READ_POLL_TIMEOUT = 1.0

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

    def __init__(self, port, room=None, donjon=None, max_players=4, screen=None):
        """screen: pass the real, already-created display Surface when
        constructing this from inside a normal windowed process (hosting
        from home -- see Explorator.start_hosting); pygame is already
        initialized there and must keep its real video driver. Left None
        for the standalone headless case (main.py's own dedicated-server
        path, if kept) -- only then does this force the dummy SDL drivers
        and create its own throwaway 1x1 display, exactly as before."""
        assert (room is None) != (donjon is None), "exactly one of room/donjon must be given"

        if screen is None:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
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
        self._kick_requested = set()  # player_id set -- see _kick/_handle_connection
        self._flood_strikes = {}  # player_id -> consecutive over-cap ticks (Phase 5)
        self._clients_lock = threading.Lock()
        self._incoming = queue.Queue()  # (player_id, payload) from every reader thread
        self._admin_commands = queue.Queue()  # raw stdin lines from the admin console thread
        self._terrain_versions = {}
        self._tick = 0
        self._running = True

        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind(("0.0.0.0", port))
        self._server_socket.listen()

    def serve_forever(self):
        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._admin_console_loop, daemon=True).start()
        print(f"[server] listening on port {self._server_socket.getsockname()[1]}, "
              f"{self.room_kind}={self.room_name!r}, tick={self.TICK_RATE}Hz")
        print("[server] admin console ready -- type 'help' for commands")
        try:
            while self._running:
                tick_start = time.monotonic()

                self._drain_incoming()
                self._drain_admin_commands()
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
    # Admin commands: a shared dispatcher (_dispatch_command) reused by two
    # sources -- a daemon thread reading trusted operator lines from stdin
    # (mirroring every other external-input thread here: one accept thread,
    # one reader thread per client), and a "/..." chat message from a
    # connected client (see _apply_message's MSG_CHAT branch), which is NOT
    # trusted the same way and gets an extra host-only check for privileged
    # verbs first. Only the main tick thread ever applies one, same "no
    # locking needed around the simulation" invariant as _drain_incoming.
    # ------------------------------------------------------

    ADMIN_HELP = (
        "commands: level <player_id> <N|+N|-N> | kick <player_id> [reason] | "
        "list | stop | help -- same commands work as /... in chat, "
        "level/kick/stop reserved to the host there"
    )

    # Verbs a chat-originated command must be the host to run -- level/kick/
    # stop change or end someone else's session; list/help are harmless
    # and stay open to everyone. Stdin (requester_player_id=None) always
    # skips this check -- an operator with console access is trusted by
    # definition.
    PRIVILEGED_COMMANDS = ("level", "kick", "stop", "shutdown", "kill")

    def _admin_console_loop(self):
        try:
            for line in sys.stdin:
                line = line.strip()
                if line:
                    self._admin_commands.put(line)
        except (OSError, ValueError):
            pass

    def _drain_admin_commands(self):
        while True:
            try:
                line = self._admin_commands.get_nowait()
            except queue.Empty:
                break
            reply = self._dispatch_command(line)
            if reply is not None:
                print(f"[server] {reply}")

    def _dispatch_command(self, line, requester_player_id=None):
        """Parses and applies one command line, returning an optional reply
        string -- the caller decides where it goes (printed for the stdin
        admin console, sent back privately over chat for a network sender,
        see _apply_message). requester_player_id is None for the trusted
        stdin console (every command allowed); a real player_id gates
        PRIVILEGED_COMMANDS to _host_player_id() only. A malformed/unknown
        command should never crash the shared tick loop -- same
        defense-in-depth reasoning as _apply_message's own try/except
        around a client's message."""
        parts = line.split()
        if not parts:
            return None
        command, args = parts[0].lower(), parts[1:]

        if requester_player_id is not None and command in self.PRIVILEGED_COMMANDS:
            if requester_player_id != self._host_player_id():
                return "reserve a l'hote."

        try:
            if command in ("help", "?"):
                return self.ADMIN_HELP
            elif command in ("list", "players"):
                return self._cmd_list_players()
            elif command == "level" and len(args) >= 2:
                return self._cmd_level(args[0], args[1])
            elif command == "kick" and args:
                return self._cmd_kick(args[0], " ".join(args[1:]) or "kicked by admin")
            elif command in ("stop", "shutdown", "kill"):
                self._running = False
                return "admin requested shutdown"
            else:
                return f"unknown command: {line!r} ({self.ADMIN_HELP})"
        except Exception as exc:
            return f"command {line!r} failed: {exc}"

    def _cmd_list_players(self):
        if not self.explorator.players:
            return "no players connected"
        lines = []
        for player_id, session in sorted(self.explorator.players.items()):
            if session.profile is not None:
                lines.append(f"{player_id}: {session.profile.name} (level {session.profile.level})")
            else:
                lines.append(f"{player_id}: (no profile)")
        return "\n".join(lines)

    def _cmd_level(self, player_id_str, value_str):
        player_id = int(player_id_str)
        session = self.explorator.players.get(player_id)
        if session is None:
            return f"no player {player_id}"
        if session.profile is None:
            return f"player {player_id} has no profile to level"

        current_level = session.profile.level
        if value_str[0] in "+-":
            new_level = current_level + int(value_str)
        else:
            new_level = int(value_str)
        new_level = max(1, min(progression.MAX_LEVEL, new_level))

        session.profile.xp = progression.xp_for_level(new_level)
        ProfileManager().save(session.profile)
        return f"player {player_id} ({session.profile.name}) level {current_level} -> {new_level}"

    def _cmd_kick(self, player_id_str, reason):
        player_id = int(player_id_str)
        if player_id not in self.explorator.players:
            return f"no player {player_id}"
        self._kick(player_id, reason)
        return f"kicking player {player_id}: {reason}"

    def _accept_loop(self):
        while self._running:
            try:
                conn, addr = self._server_socket.accept()
            except OSError:
                return
            threading.Thread(target=self._handle_connection, args=(conn, addr), daemon=True).start()

    @staticmethod
    def _recv_line(conn, buffer_holder):
        """Reads one newline-terminated line from `conn`'s raw socket.
        `buffer_holder` is a 1-element list acting as an in/out parameter
        -- its bytes are updated after *every* individual recv() call, not
        just once the full line is assembled, so a socket.timeout raised
        mid-read (conn.settimeout()) never loses bytes already received;
        the caller just calls this again with the same buffer_holder after
        reacting to the timeout (e.g. checking for a kick). Returns the
        line (without its trailing "\\n"), or None on clean EOF.

        Deliberately NOT socket.makefile()'s buffered reader: a raw
        socket.recv() reliably raises socket.timeout on every call after
        conn.settimeout() elapses, while a makefile()-wrapped reader's
        underlying SocketIO permanently taints itself after its FIRST
        timeout and raises a plain OSError ("cannot read from timed out
        object") on every read after that -- a real CPython gotcha this
        server used to hit on any connection idle for longer than
        READ_POLL_TIMEOUT, found via an ad hoc idle-connection test. Every
        previous smoke test kept connections busy with constant input
        traffic (a real player always sends "input" every rendered frame)
        and so never actually exercised a *second* timeout on the same
        connection until hosting-from-home made a genuinely idle
        connection (sitting in a menu/panel, or simply not moving) common."""
        while b"\n" not in buffer_holder[0]:
            chunk = conn.recv(4096)
            if not chunk:
                return None
            buffer_holder[0] += chunk
        line, _, rest = buffer_holder[0].partition(b"\n")
        buffer_holder[0] = rest
        return line

    def _handle_connection(self, conn, addr):
        writer = conn.makefile("wb")
        player_id = None
        recv_buffer = [b""]
        try:
            first_line = self._recv_line(conn, recv_buffer)
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

            self.explorator.add_network_session(player_id, profile_name=join_msg.get("name"))
            with self._clients_lock:
                self._clients[player_id] = writer
                self._connections[player_id] = conn

            print(f"[server] {addr} joined as player {player_id} ({join_msg.get('name', '?')})")

            writer.write(protocol.encode(
                protocol.MSG_WELCOME, player_id=player_id,
                room_kind=self.room_kind, room_name=self.room_name,
            ))
            writer.flush()

            # Poll instead of blocking forever on readline(): a plain
            # blocking read can't be woken from another thread on Windows
            # (see _kick's docstring) -- with a timeout, this loop instead
            # wakes up on its own every READ_POLL_TIMEOUT seconds to check
            # self._kick_requested, so a server-initiated disconnect (rate
            # limit, admin console) actually takes effect without needing
            # the client to cooperate.
            conn.settimeout(self.READ_POLL_TIMEOUT)

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
            while True:
                with self._clients_lock:
                    kicked = player_id in self._kick_requested
                if kicked:
                    print(f"[server] player {player_id} connection closed (kicked)")
                    break

                try:
                    line = self._recv_line(conn, recv_buffer)
                except socket.timeout:
                    continue  # nothing arrived within READ_POLL_TIMEOUT -- loop back to the kick check above

                if line is None:
                    break  # EOF -- the client closed its end

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
                    self._kick_requested.discard(player_id)
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
            elif msg_type == protocol.MSG_CHAT:
                self._apply_chat(player_id, session, payload)
        except (KeyError, ValueError, TypeError) as exc:
            print(f"[server] player {player_id} sent a message that failed to apply ({exc}), ignoring")

    def _apply_chat(self, player_id, session, payload):
        """A "/..." message is routed to _dispatch_command (host-only for
        privileged verbs) and replied to privately -- the requester alone,
        never broadcast, since a command's result/rejection isn't something
        every other player needs to see. Plain text is broadcast to
        everyone as an ordinary chat line under the sender's own profile
        name (or a generic placeholder for a session with none)."""
        text = payload.get("text", "").strip()
        if not text:
            return

        if text.startswith("/"):
            reply = self._dispatch_command(text[1:], requester_player_id=player_id)
            if reply is not None:
                self._send_to(player_id, protocol.encode(
                    protocol.MSG_CHAT, player_id=player_id, name="serveur", text=reply, system=True,
                ))
            return

        name = session.profile.name if session.profile is not None else f"joueur {player_id}"
        self._broadcast(protocol.encode(
            protocol.MSG_CHAT, player_id=player_id, name=name, text=text, system=False,
        ))

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
        rate limiter -- see _drain_incoming -- and by the admin console's
        'kick' command).

        Originally this only called conn.shutdown(SHUT_RDWR), on the theory
        that it would unblock the connection's own reader thread (blocked in
        a plain readline()) the way it does on POSIX. Verified by an ad hoc
        raw-socket test that this does NOT hold on Windows: neither
        shutdown() nor even close() issued from another thread on the same
        socket object reliably wakes a thread already blocked in recv() --
        the kicked session just sat there until the CLIENT eventually closed
        its own end. So _handle_connection's reader loop now polls
        (conn.settimeout()) instead of blocking forever, and _kick's real
        signal is adding player_id to self._kick_requested -- the loop
        notices within READ_POLL_TIMEOUT and exits on its own. The
        shutdown() call is kept too (harmless, and still speeds up an
        in-progress recv on platforms where it does work), but is no longer
        load-bearing."""
        print(f"[server] kicking player {player_id}: {reason}")
        with self._clients_lock:
            self._kick_requested.add(player_id)
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

    def _send_to(self, player_id, raw_bytes):
        """Same idea as _broadcast, but to exactly one client -- used for a
        chat command's private reply/rejection (see _apply_chat), which
        nobody else needs to see. Silently no-ops if that player has
        already disconnected (a dead-writer race with _broadcast's own
        cleanup, harmless either way)."""
        with self._clients_lock:
            writer = self._clients.get(player_id)
        if writer is None:
            return
        try:
            writer.write(raw_bytes)
            writer.flush()
        except OSError:
            pass

    def _shutdown(self):
        self._running = False
        try:
            self._server_socket.close()
        except OSError:
            pass
