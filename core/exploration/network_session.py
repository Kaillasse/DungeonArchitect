"""Networked-play logic mixed into Explorator (multiplayer Phase 3-6e):
server-side session lifecycle (add_network_session/remove_session, called
from GameServer when a client joins/leaves), and everything client-side --
hosting/joining, applying a server snapshot onto the local mirror world,
client-side prediction/reconciliation (Phase 4), remote-entity smoothing,
and chat.

Split out of explorator.py, which had grown past 2500 lines across every
multiplayer phase, once it became clear every method below is reached
exclusively through run_networked/apply_network_snapshot's own call graph
(or, for add_network_session/remove_session, exclusively from GameServer) --
never from solo run()/update(). Explorator(NetworkSessionMixin) resolves
every self.<method>() call here identically through Python's normal MRO, so
this split changes nothing about runtime behavior -- see CLAUDE.md's
"Pre-Phase-3 refactor pass" entry for the same reasoning applied earlier to
other Explorator helpers.
"""

from __future__ import annotations

import threading

import pygame

from core.world.entities import Mob, Pickup, ItemPickup, ThrownDynamite, Explosion
from core.world.object_manager import make_item
from core.exploration.player_session import PlayerSession
from core.engine.gamestate import GameState
from core.data.profile_manager import Profile, ProfileManager
from core.network import protocol


class NetworkSessionMixin:
    """Mixed into Explorator -- see module docstring."""

    def add_network_session(self, player_id, profile_name=None):
        """A client just connected -- create its PlayerSession, add it to
        self.players (simulated/rendered exactly like any local session, see
        Phase 1/2's players dict), and spawn it the same way every other
        session gets spawned. profile_name (the client's own `join` "name"
        field, see GameServer._handle_connection) loads/creates its Profile
        server-side -- this is the one place multiplayer XP actually gets
        tracked from, same authoritative-server reasoning as every other
        simulation fact."""
        session = PlayerSession(player_id, "network")
        if profile_name is not None:
            session.profile = ProfileManager().load(profile_name)
        self.players[player_id] = session
        self._spawn_new_session_at_start(session)
        return session

    def remove_session(self, player_id):
        self.players.pop(player_id, None)
        # Only discards the departing id from the ready set -- deliberately
        # does NOT check/trigger sync-barrier completion here (this can run
        # from a connection's own reader thread server-side, where touching
        # shared world state via generate_assembly would be unsafe). The
        # main tick thread's own per-frame check
        # (_maybe_complete_dungeon_entrance_barrier, called unconditionally
        # from _resolve_dungeon_transitions) is what actually notices the
        # barrier is now satisfied for whoever's left.
        self.dungeon_entrance_ready.discard(player_id)

    # ------------------------------------------------------
    # Networking (Phase 3) -- client-side: applying a server snapshot onto
    # this Explorator's local mirror world instead of simulating it (see
    # run_networked). No physics/collision is recomputed here -- purely
    # presentation state, so render()/WorldRenderer/Player.draw/etc need no
    # changes at all to work off it.
    # ------------------------------------------------------

    def adopt_local_player_id(self, new_id):
        """__init__ always creates this Explorator's own local session under
        id 0 (today's solo-keyboard default) -- re-keys it to whatever
        player_id the server actually assigned in its "welcome" message,
        which only coincidentally is 0 (whoever connects first)."""
        if new_id == self._local_player_id:
            return
        session = self.players.pop(self._local_player_id)
        session.player_id = new_id
        self.players[new_id] = session
        self._local_player_id = new_id

    def start_hosting(self, port=None):
        """Starts hosting whichever single room this Explorator currently
        has open (always home in practice -- see MultiplayerPanelUI, only
        offered while Creator/Explorator._is_home_room()) and immediately
        connects THIS SAME process to it as a normal NetworkClient over
        loopback (127.0.0.1) -- the host plays their own hosted world
        exactly like any other connected player (confirmed with the user
        over a separate local-authority path: reuses 100% of existing
        client code -- prediction, chat, rendering -- with zero
        special-casing, at the cost of a tiny loopback round-trip for the
        host's own input too). Also starts a discovery.HostAnnouncer so
        other players on the LAN can find this session without typing an
        IP. Returns (client, error) -- error is None on success, an
        explanatory string otherwise, so the caller (MultiplayerPanelUI)
        can show it as a status line instead of an exception surfacing
        into the render loop."""
        from core.network.server import GameServer, DEFAULT_PORT
        from core.network.client import NetworkClient, ServerFullError
        from core.network.discovery import HostAnnouncer

        if self.current_room is None:
            return None, "Aucune salle a heberger (uniquement depuis home)."
        if port is None:
            port = DEFAULT_PORT

        try:
            server = GameServer(port, room=self.current_room, screen=self.screen)
        except OSError as exc:
            return None, f"Impossible de demarrer le serveur : {exc}"

        threading.Thread(target=server.serve_forever, daemon=True).start()

        host_name = self.settings.local_player_name if self.settings is not None else "host"
        announcer = HostAnnouncer(host_name, port, "room", self.current_room)
        announcer.start()

        client = None
        try:
            client = NetworkClient("127.0.0.1", port, name=host_name)
            welcome = client.wait_for_welcome()
        except (OSError, TimeoutError, ServerFullError) as exc:
            # NetworkClient's own socket + reader thread are already up by
            # the time wait_for_welcome() can fail -- only its constructor
            # failing leaves `client` unset (nothing to close in that case).
            if client is not None:
                client.close()
            server._running = False
            announcer.stop()
            return None, f"Connexion locale au serveur echouee : {exc}"

        self._finish_connecting(client, welcome)
        self.game_manager._game_server = server
        self.game_manager._host_announcer = announcer
        return client, None

    def join_session(self, host_ip, port, name=None):
        """Connects to someone else's hosted session (an entry picked from
        MultiplayerPanelUI's discovery.SessionBrowser list, or -- not yet
        exposed in the UI -- a manually-entered address). Returns (client,
        error), same contract as start_hosting."""
        from core.network.client import NetworkClient, ServerFullError

        if name is None:
            name = self.settings.local_player_name if self.settings is not None else "player"

        client = None
        try:
            client = NetworkClient(host_ip, port, name=name)
            welcome = client.wait_for_welcome()
        except (OSError, TimeoutError, ServerFullError) as exc:
            if client is not None:
                client.close()
            return None, f"Connexion echouee : {exc}"

        self._finish_connecting(client, welcome)
        return client, None

    def _finish_connecting(self, client, welcome):
        """Shared by start_hosting (connecting to its own loopback server)
        and join_session (connecting to someone else's) -- loads whichever
        room/donjon the server says to (mirrors main.py's old run_client
        sequence), adopts the assigned player_id, and hands the live
        client to GameManager so its dispatch routes into run_networked
        instead of run() from now on (see GameManager.run())."""
        # Before the open_room/open_donjon call right below -- see
        # self.is_network_client's own docstring for why order matters here
        # (it must already be True by the time either of those runs, so
        # they skip locally spawning mobs that would otherwise double up
        # with apply_network_snapshot's own mirrored ones).
        self.is_network_client = True
        if welcome["room_kind"] == "donjon":
            self.open_donjon(welcome["room_name"])
        else:
            self.open_room(welcome["room_name"])
        self.adopt_local_player_id(welcome["player_id"])
        self.game_manager.network_client = client

    def stop_networking(self):
        """Disconnects (or stops hosting) and returns to solo play. Rather
        than unwinding every bit of network-driven state (mirrored remote
        entities/sessions, an assembly that might not even be a real local
        Dungeon) by hand, GameManager gets a fresh Explorator -- same
        object graph a brand-new app launch's own GameManager.__init__
        would build -- and this method's job is just tearing down the
        network/server objects and handing back that reset. Doesn't touch
        game_manager.state/pending_room/boot_into_home itself -- the
        caller (MultiplayerPanelUI's "Deconnecter" handler, inside
        run_networked's own event loop) sets those and breaks its loop
        exactly the same way ESC already does, so this method stays a pure
        teardown with no control-flow side effects of its own."""
        gm = self.game_manager
        if gm.network_client is not None:
            gm.network_client.close()
            gm.network_client = None
        if gm._host_announcer is not None:
            gm._host_announcer.stop()
            gm._host_announcer = None
        if gm._game_server is not None:
            gm._game_server._running = False
            gm._game_server = None
        # Local import -- explorator.py imports this module (for the
        # mixin itself), so a module-level import here would cycle.
        from core.exploration.explorator import Explorator
        gm.explorator = Explorator(gm)
        gm.boot_into_home = True

    def _dungeon_for_room(self, room_ref):
        """room_ref is None (single-room mode) or a PlacedRoom.index (see
        protocol.build_snapshot) -- the same room-identity convention the
        server used to build this snapshot."""
        if room_ref is None:
            return self.dungeon
        return next((room.dungeon for room in self.assembly.rooms if room.index == room_ref), None)

    def _room_for_ref(self, room_ref):
        """Same room_ref convention as _dungeon_for_room, but returns the
        actual PlacedRoom (not just its Dungeon) -- used to set a session's
        current_placed_room from a snapshot player entry's own "room" field
        (see apply_network_snapshot/_reconcile_local_player). None in
        single-room mode (self.assembly is None) or if room_ref itself is
        None (a player entry from before this room got set, or a
        single-room-mode server)."""
        if room_ref is None or self.assembly is None:
            return None
        return next((room for room in self.assembly.rooms if room.index == room_ref), None)

    @staticmethod
    def _sync_mirror_list(mirror_map, live_list, entries, factory, updater):
        """Reconciles one dungeon's live entity list (e.g.
        mob_manager.mobs) against this tick's snapshot entries for it:
        creates a local mirror object the first time a network id is seen,
        updates it every time, and drops any mirror whose id no longer
        appears (despawned/died server-side). `mirror_map` is
        {network_id: local_object}, persisted across ticks on
        self._network_mirrors.

        A freshly-created object has its position snapped straight to the
        entry's (x, y) before `updater` runs (Phase 4) -- `updater` itself
        only ever registers a *smoothing target* now (see
        _smooth_network_entities), so without this a brand-new mirror would
        otherwise visibly lerp in from whatever placeholder spot its
        `factory` constructed it at instead of appearing where it actually
        is."""
        seen_ids = set()
        for entry in entries:
            seen_ids.add(entry["id"])
            obj = mirror_map.get(entry["id"])
            if obj is None:
                obj = factory(entry)
                obj.position.update(entry["x"], entry["y"])
                mirror_map[entry["id"]] = obj
                live_list.append(obj)
            updater(obj, entry)
        for stale_id in [network_id for network_id in mirror_map if network_id not in seen_ids]:
            stale_obj = mirror_map.pop(stale_id)
            if stale_obj in live_list:
                live_list.remove(stale_obj)

    def _register_network_target(self, entity, x, y):
        """Client-side only (Phase 4): records `entity`'s latest known
        server-authoritative position without moving it there directly --
        _smooth_network_entities lerps `.position` toward it every render
        frame instead, so a remote entity's motion doesn't visibly stutter at
        the server's 30Hz tick rate. Rebuilt from scratch on every snapshot
        (see apply_network_snapshot), so nothing needs to unregister an
        entity that disappears -- it simply stops being re-added."""
        self._network_targets[id(entity)] = (entity, x, y)

    def _apply_mob_entry(self, mob, entry):
        self._register_network_target(mob, entry["x"], entry["y"])
        mob.state = entry["state"]
        mob.direction = pygame.Vector2(entry["dir_x"], entry["dir_y"])
        mob.flip = entry["flip"]
        mob.frame = entry["frame"]
        mob.health = entry["health"]
        mob.alive = entry["alive"]

    def _apply_pickup_entry(self, pickup, entry):
        self._register_network_target(pickup, entry["x"], entry["y"])
        pickup.state = entry["state"]
        pickup.frame = entry["frame"]

    def _apply_item_pickup_entry(self, item_pickup, entry):
        self._register_network_target(item_pickup, entry["x"], entry["y"])

    def _apply_projectile_entry(self, projectile, entry):
        self._register_network_target(projectile, entry["x"], entry["y"])
        projectile.frame = entry["frame"]

    def _predict_local_movement(self, dt):
        """Client-side only (Phase 4): applies this frame's local input to
        the local session's player immediately, instead of waiting a full
        round-trip for the server's snapshot to reflect it (the old "thin
        client" behavior). Buffers (seq, direction, running, dt) in
        session.pending_inputs so a later server correction can replay
        whatever hasn't been acknowledged yet on top of the authoritative
        position -- see _reconcile_local_player. Only movement is predicted
        (see CLAUDE.md's Phase 4 notes) -- attack/interact/jump stay purely
        server-authoritative, applied only once the snapshot reflects them.
        Returns the assigned seq, sent alongside this frame's input message
        by run_networked."""
        session = self.players[self._local_player_id]
        seq = session.next_input_seq
        session.next_input_seq += 1

        direction = pygame.Vector2(session.input.move_direction)
        running = session.input.running
        session.pending_inputs.append((seq, direction, running, dt))

        self._resolve_movement_step(session, direction, running, dt, predicting=True)
        return seq

    def _reconcile_local_player(self, entry):
        """Client-side only (Phase 4): entry is the local player's own dict
        from payload["players"]. Recales position/health to the server's
        authoritative state for this tick, drops every buffered predicted
        input the server has now confirmed (seq <= entry's last_input_seq),
        then replays whatever's left so the locally predicted position ends
        up exactly where it would if the server had already processed those
        too. In the common case (no divergence) the replay reproduces the
        same position that was already on screen, so this is invisible; a
        genuine mismatch (e.g. a collision the client didn't know about)
        corrects immediately, with no separate smoothing of the correction
        itself.

        `action`/`animation`/`frame` are deliberately NOT part of that
        recalage while the player is just walking/idling: those are
        continuous, purely cosmetic client state already being driven every
        real frame by _predict_local_movement's own player.update(dt) call
        (see _resolve_movement_step's advance_animation), and forcing them
        back to the server's -- always somewhat stale, 30Hz-tick-quantized --
        values here fights that local clock and shows up as visible frame
        jumps/skips (this was a real, reported bug, not a hypothetical).
        They're only ever taken from the server while a one-shot action
        (attack/interact/jump) is genuinely in play -- entry["action"] or the
        local player's own .action is not None -- since those aren't
        predicted at all (see CLAUDE.md's Phase 4 scope) and only the server
        gets to say when one starts, progresses, or ends. The replay below
        never advances animation either way (advance_animation=False) --
        it can re-run the same buffered input several times before the
        server acks it, and Player.update(dt)'s animation_timer is a
        cumulative accumulator that isn't safe to call more than once per
        real elapsed frame."""
        session = self.players[self._local_player_id]
        player = session.player
        player.position.update(entry["x"], entry["y"])
        player.health = entry["health"]

        # Room/floor crossings are never predicted client-side (see
        # _resolve_movement_step's predicting=True branch) -- this is the
        # ONLY place the local session's own current_placed_room ever
        # changes on a client, driven by the server's own authoritative
        # room for this player. Without this, current_placed_room stayed
        # frozen at whatever open_room/open_donjon set it to at connect
        # time, forever -- rendering (active_floor) and even local
        # prediction's own collision (_is_walkable reads
        # moving_session.current_placed_room) silently kept using the
        # spawn room no matter how far the player actually walked, which
        # is exactly the "first room stays active forever" bug this fixes.
        session.current_placed_room = self._room_for_ref(entry.get("room"))

        # XP/level is another server-authoritative fact, same as health --
        # this client never grants XP itself (_grant_xp is only ever called
        # from the full simulation, which run_networked never runs). Creates
        # a display-only Profile on first sight if this session somehow
        # reached here without one (e.g. --connect used without ever going
        # through Menu's name-entry screen, so no local_player_name existed
        # at Explorator.__init__ time).
        if session.profile is None:
            session.profile = Profile(self.settings.local_player_name if self.settings else None, xp=entry.get("xp", 0))
        else:
            session.profile.xp = entry.get("xp", session.profile.xp)

        if entry["action"] is not None or player.action is not None:
            player.action = entry["action"]
            player.animation = entry["animation"]
            player.frame = entry["frame"]

        last_acked = entry.get("last_input_seq", 0)
        session.pending_inputs = [item for item in session.pending_inputs if item[0] > last_acked]
        # One shared visible-mob snapshot for the whole replay batch below
        # (see _resolve_movement_step) instead of every replayed input
        # redoing the same room-wide scan -- this replay is a synchronous
        # catch-up over already-buffered inputs, not real elapsed time, so
        # mobs genuinely haven't moved between iterations.
        visible_mobs = self._visible_mobs_global()
        for _seq, direction, running, replay_dt in session.pending_inputs:
            self._resolve_movement_step(session, direction, running, replay_dt, predicting=True, advance_animation=False,
                                         visible_mobs=visible_mobs)

    def _smooth_network_entities(self, dt):
        """Client-side only (Phase 4), called once per render frame from
        run_networked: eases every mirrored non-local entity's `.position`
        toward its latest server-known target (see _register_network_target)
        instead of the old instant snap, so 30Hz-tick network state doesn't
        visibly stutter at the client's 60fps render rate. The local player
        never has an entry in _network_targets (handled by
        _reconcile_local_player instead), so nothing needs excluding here."""
        factor = min(1.0, self.NETWORK_INTERP_RATE * dt)
        for entity, target_x, target_y in self._network_targets.values():
            entity.position.x += (target_x - entity.position.x) * factor
            entity.position.y += (target_y - entity.position.y) * factor

    def apply_network_snapshot(self, payload):
        """Client-side only (Phase 3+4): writes a server snapshot's fields
        onto this Explorator's local mirror world -- directly for everything
        except continuous positions, which go through _network_targets/
        _smooth_network_entities instead (remote entities) or
        _reconcile_local_player (the local player, predicted -- see Phase 4
        notes above)."""
        # The authoritative Explorator (the server, or the local one in solo
        # play) can swap into a freshly generated dungeon mid-session (the
        # dungeon_entrance sync barrier, see _maybe_complete_dungeon_entrance_
        # barrier) that this client was never told about at connect time --
        # noticing the name changed here and mirroring it via open_donjon
        # (loading that exact saved assembly from this client's own local
        # assets/donjons/) is what lets _room_for_ref below actually resolve
        # to a real room instead of staying stuck at None forever (which
        # crashed render()'s _render_viewport on room.floor -- the "ça crash
        # au moment ou les personnages rentres dans le donjon" bug) or,
        # short of crashing, silently kept rendering whatever single room
        # this client happened to have loaded before crossing (the "decors
        # differents en fonction de la fenetre" bug). Edge-triggered against
        # self.current_donjon_name (set by open_donjon/_enter_assembly) so
        # this only actually reloads the one tick it changes, not every
        # tick. Done first, before the payload's own authoritative fields
        # below are applied, since open_donjon/_enter_assembly resets
        # victory/dungeon_entrance_ready itself -- applying those from the
        # payload afterward is what actually makes them correct for this
        # tick rather than getting clobbered back to open_donjon's own
        # just-loaded-a-fresh-room defaults.
        donjon_name = payload.get("donjon_name")
        if donjon_name is not None and donjon_name != self.current_donjon_name:
            self.open_donjon(donjon_name)

        self.pvp_enabled = payload["pvp_enabled"]
        self.victory = payload["victory"]
        self.dungeon_entrance_ready = set(payload.get("dungeon_entrance_ready", []))
        if payload.get("game_over") and self.game_manager.state == GameState.EXPLORATION:
            self.game_manager.state = GameState.MENU

        self._network_targets = {}  # rebuilt fresh every snapshot -- see _register_network_target

        seen_players = set()
        for entry in payload["players"]:
            seen_players.add(entry["id"])
            session = self.players.get(entry["id"])
            if session is None:
                session = PlayerSession(entry["id"], "network")
                session.player.position.update(entry["x"], entry["y"])  # avoid lerping in from Player()'s default spawn
                # Display-only mirror -- no name travels over the wire for a
                # remote player, and this Profile is never saved (only the
                # server's own session, loaded in add_network_session, is
                # authoritative/persisted for this player).
                session.profile = Profile(None, xp=entry.get("xp", 0))
                self.players[entry["id"]] = session

            if entry["id"] == self._local_player_id:
                self._reconcile_local_player(entry)
                continue

            player = session.player
            player.direction = entry["direction"]
            player.animation = entry["animation"]
            player.action = entry["action"]
            player.frame = entry["frame"]
            player.health = entry["health"]
            session.profile.xp = entry.get("xp", session.profile.xp)
            # Same reasoning as _reconcile_local_player -- a remote mirror's
            # own current_placed_room now comes straight from the server's
            # authoritative snapshot too, instead of staying None forever
            # (the old "drawn in every local viewport regardless of floor"
            # fallback in render()/_draw_debug_hitboxes still applies for as
            # long as this is None, e.g. one frame before a mirror's first
            # snapshot with a "room" field arrives).
            session.current_placed_room = self._room_for_ref(entry.get("room"))
            self._register_network_target(player, entry["x"], entry["y"])
        for stale_id in [pid for pid in self.players if pid not in seen_players and pid != self._local_player_id]:
            del self.players[stale_id]

        grouped = {}
        for category in ("mobs", "pickups", "dynamites", "explosions"):
            for entry in payload[category]:
                grouped.setdefault(entry["room"], {}).setdefault(category, []).append(entry)

        for room_ref, categories in grouped.items():
            dungeon = self._dungeon_for_room(room_ref)
            if dungeon is None:
                continue
            mirrors = self._network_mirrors.setdefault(room_ref, {
                "mobs": {}, "pickups": {}, "item_pickups": {},
                "dynamites": {}, "explosions": {},
            })

            currency_entries = [e for e in categories.get("pickups", []) if e["kind"] == "currency"]
            item_entries = [e for e in categories.get("pickups", []) if e["kind"] == "item"]

            self._sync_mirror_list(
                mirrors["mobs"], dungeon.mob_manager.mobs, categories.get("mobs", []),
                factory=lambda e, d=dungeon: Mob(e["mob_type"], 0, 0, d),
                updater=self._apply_mob_entry,
            )
            self._sync_mirror_list(
                mirrors["pickups"], dungeon.pickup_manager.pickups, currency_entries,
                factory=lambda e: Pickup(e["currency_type"], e["x"], e["y"]),
                updater=self._apply_pickup_entry,
            )
            self._sync_mirror_list(
                mirrors["item_pickups"], dungeon.pickup_manager.item_pickups, item_entries,
                factory=lambda e: ItemPickup(make_item(e["item_id"]), e["slot"], e["x"], e["y"]),
                updater=self._apply_item_pickup_entry,
            )
            self._sync_mirror_list(
                mirrors["dynamites"], dungeon.projectile_manager.dynamites, categories.get("dynamites", []),
                factory=lambda e: ThrownDynamite(e["x"], e["y"], pygame.Vector2()),
                updater=self._apply_projectile_entry,
            )
            self._sync_mirror_list(
                mirrors["explosions"], dungeon.projectile_manager.explosions, categories.get("explosions", []),
                factory=lambda e: Explosion(e["x"], e["y"]),
                updater=self._apply_projectile_entry,
            )

        for entry in payload["objects"]:
            dungeon = self._dungeon_for_room(entry["room"])
            if dungeon is None or entry["index"] >= len(dungeon.object_manager.objects):
                continue
            obj = dungeon.object_manager.objects[entry["index"]]
            obj["activated"] = entry["activated"]
            obj["open"] = entry["open"]
            obj["frame"] = entry["frame"]

        for entry in payload["terrain"]:
            dungeon = self._dungeon_for_room(entry["room"])
            if dungeon is not None:
                dungeon.logical_grid = entry["logical_grid"]
                dungeon.sprite_grid = entry["sprite_grid"]

    def run_networked(self, client):
        """Client-side main loop for networked play -- the network-driven
        counterpart to run(): same shared event handling
        (_handle_shared_debug_event) for QUIT/mouse-wheel-zoom/F3 (TAB has
        nothing to switch to here, no local editor on a network client), but
        F4 sends a pvp_toggle request instead of flipping the flag locally
        (must stay server-authoritative -- it gates real damage).

        Phase 4: the local session's movement is predicted immediately
        (_predict_local_movement) instead of waiting for a round-trip, and
        reconciled against each arriving snapshot
        (apply_network_snapshot -> _reconcile_local_player); every other
        mirrored entity (remote players, animals, enemies, pickups,
        projectiles) is eased toward its latest known position every frame
        (_smooth_network_entities) rather than snapped, so the server's 30Hz
        tick rate doesn't visibly stutter at the client's 60fps render rate.
        attack/interact/jump are still never predicted -- only movement is,
        see CLAUDE.md's Phase 4 notes."""
        pygame.display.set_caption("Dungeon Architect - Exploration (reseau)")

        local_session = self.players[self._local_player_id]
        running = True

        while running:
            dt = self.clock.tick(60) / 1000

            for event in pygame.event.get():
                shared_result = self._handle_shared_debug_event(event)
                if shared_result == "stop":
                    running = False
                    continue
                if shared_result == "handled":
                    continue

                if self.game_manager.settings_panel.is_open:
                    # Pure local-settings overlay, no server round-trip
                    # needed -- works identically here to run()'s own copy
                    # of this check.
                    self.game_manager.settings_panel.handle_event(event)
                    continue

                if self.multiplayer_panel.is_open:
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        self.multiplayer_panel.close()
                        continue
                    if event.type in (pygame.MOUSEBUTTONDOWN, pygame.KEYDOWN):
                        # KEYDOWN routes into the manual-address field (see
                        # MultiplayerPanelUI.handle_event) -- M is no longer
                        # a close-shortcut here on purpose, since a typed
                        # hostname could legitimately contain the letter.
                        result = self.multiplayer_panel.handle_event(event, self)
                        if result == "disconnected":
                            self.game_manager.state = GameState.MENU
                            running = False
                        continue
                    continue

                if (
                    local_session.inventory_open
                    and event.type == pygame.MOUSEBUTTONDOWN
                    and local_session.inventory_panel.handle_click(self.screen, event.pos)
                ):
                    self.game_manager.settings_panel.open()
                    continue

                if self.victory and event.type == pygame.MOUSEBUTTONDOWN:
                    # Unlike run()'s own version, this can't just call
                    # _return_to_home() locally -- victory/the world reset
                    # it triggers are shared, whole-session state that only
                    # the server can actually change (this client's own
                    # self.victory is just a mirror of the server's, set
                    # fresh every snapshot -- flipping it locally here would
                    # only last until the very next snapshot set it right
                    # back). See GameServer._apply_message's MSG_RETURN_HOME
                    # handling.
                    client.send(protocol.MSG_RETURN_HOME)
                    continue

                if self.chat_open:
                    self._handle_chat_event(event, client)
                    continue

                if event.type == pygame.KEYDOWN and event.key == pygame.K_m:
                    self.multiplayer_panel.open()
                    continue

                if event.type == pygame.KEYDOWN and event.key == pygame.K_t:
                    self.chat_open = True
                    self.chat_input = ""
                    continue

                if event.type == pygame.KEYDOWN and event.key == pygame.K_F4:
                    client.send(protocol.MSG_PVP_TOGGLE)
                    continue

                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if local_session.inventory_open:
                        local_session.inventory_open = False
                    else:
                        self.game_manager.state = GameState.MENU
                        running = False
                    continue

                self._handle_session_event(local_session, event)

            self._read_input()
            seq = self._predict_local_movement(dt)
            client.send(protocol.MSG_INPUT, seq=seq, **protocol.input_state_to_fields(local_session.input))

            for payload in client.drain():
                if payload["type"] == protocol.MSG_SNAPSHOT:
                    self.apply_network_snapshot(payload)
                elif payload["type"] == protocol.MSG_CHAT:
                    self._append_chat(payload)

            if not client.is_connected:
                # Kicked, the server stopped, or a network error -- nothing
                # left to render (the server has already forgotten this
                # session), so there's no "one more frame" to fall through
                # to render, same as every other state-changing branch here.
                print("[client] Connexion perdue (deconnecte ou hote arrete).")
                self.game_manager.state = GameState.MENU
                break

            if self.game_manager.state != GameState.EXPLORATION:
                break

            self._smooth_network_entities(dt)
            self._update_camera(dt)
            self.render()

    def _handle_chat_event(self, event, client):
        """Routes every event while the chat box is open (run_networked's
        top-of-loop guard, checked before F4/ESC/session gameplay dispatch
        so a keystroke while typing can never also trigger PvP-toggle or
        close the menu) into the text buffer instead -- the identical
        input pattern Menu's own name-entry field already uses (backspace,
        printable-char filter, length cap, K_RETURN sends, K_ESCAPE cancels
        without sending)."""
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_RETURN:
            text = self.chat_input.strip()
            if text:
                client.send(protocol.MSG_CHAT, text=text)
            self.chat_input = ""
            self.chat_open = False
        elif event.key == pygame.K_ESCAPE:
            self.chat_input = ""
            self.chat_open = False
        elif event.key == pygame.K_BACKSPACE:
            self.chat_input = self.chat_input[:-1]
        elif event.unicode and event.unicode.isprintable():
            if len(self.chat_input) < self.CHAT_MAX_LENGTH:
                self.chat_input += event.unicode

    def _append_chat(self, payload):
        self.chat_log.append({
            "player_id": payload.get("player_id"),
            "name": payload.get("name", "?"),
            "text": payload.get("text", ""),
            "system": bool(payload.get("system", False)),
            "time": pygame.time.get_ticks(),
        })
        if len(self.chat_log) > self.CHAT_LOG_MAX:
            self.chat_log = self.chat_log[-self.CHAT_LOG_MAX:]

