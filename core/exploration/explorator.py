# Contient toute la logique du game state Exploration

from __future__ import annotations

import math
import random

import pygame
from core.world.dungeon import Dungeon, corner_cells
from core.editor.autotile import FLOOR
from core.world.assembly import load_assembly, save_assembly, generate_assembly
from core.data.ressources import ROOMS_DIRECTORY, next_new_donjon_name
from core.world.entities import Player, PlayerRef, _bucket_direction, _spawn_loot_pickups
from core.world.object_manager import (
    mob_types, ITEM_DEFINITIONS, make_item, OBJECT_TYPES,
)
from core.exploration.player_session import PlayerSession
from core.exploration.multiplayer_ui import MultiplayerPanelUI
from core.exploration.network_session import NetworkSessionMixin
from core.engine.input import (
    InputState, read_local_keyboard_input,
    read_secondary_keyboard_input, secondary_keyboard_matches_event, SECONDARY_KEYBOARD_BINDINGS,
    read_gamepad_input, gamepad_matches_event,
)
from core.engine.gamestate import GameState
from core.engine.camera import Camera
from core.data.sound_manager import SoundManager, play_card_sound
from core.data.profile_manager import ProfileManager, apply_to_fresh_profile
from core.data.progression import XP_ENEMY_KILL, XP_ANIMAL_KILL, XP_DUNGEON_CLEAR
from core.world.home import home_room_name, wants_creator

# Placed objects that are only ever markers during exploration -- a spawn
# point and each mob's placement cell -- and get replaced by a live entity
# (the Player, or a MobManager-owned Mob) instead of being drawn as a
# static object sprite. A FUNCTION, not a frozen set -- mob_types() is
# itself dynamic (a mob type can be registered entirely in-session via the
# sprite editor's PNJ-style registration -- see object_manager.mob_types'
# own docstring), so freezing this whole set once at import would never
# see a type registered afterward and its placed icon would never get
# hidden during exploration. Call hidden_object_types() fresh at each use.
def hidden_object_types():
    return {"spawn", *mob_types()}


def _doorway_interior_offset(dungeon, grid_x, grid_y):
    """(dx, dy) from a doorway cell (grid_x, grid_y) toward its FLOOR-side
    neighbor -- the room interior, as opposed to the EMPTY/void side --
    same up/down-vs-left/right shape ObjectManager.is_valid_doorway itself
    checks (a doorway is only ever valid with exactly one FLOOR neighbor
    directly opposite one EMPTY neighbor). Used by
    Explorator._cancel_dungeon_entrance_wait to put a player who backs out
    of the sync barrier back on the room side of the door they just tried
    to take, not stranded exactly on the door tile itself. None if this
    cell isn't actually shaped like a valid doorway (shouldn't happen for
    an object that was placed through the normal validated path, but
    defensive)."""
    def cell_at(x, y):
        if 0 <= x < dungeon.width and 0 <= y < dungeon.height:
            return dungeon.logical_grid[y][x]
        return None  # off-grid is never FLOOR, that's all this needs to know

    if cell_at(grid_x, grid_y - 1) == FLOOR:
        return 0, -1
    if cell_at(grid_x, grid_y + 1) == FLOOR:
        return 0, 1
    if cell_at(grid_x - 1, grid_y) == FLOOR:
        return -1, 0
    if cell_at(grid_x + 1, grid_y) == FLOOR:
        return 1, 0
    return None

class Explorator(NetworkSessionMixin):

    MOVE_SPEED = 180  # pixels/seconde
    RUN_SPEED = 260  # pixels/seconde -- held with SHIFT

    # Chat overlay tuning (see run_networked/_render_chat) -- CHAT_MAX_LENGTH
    # is enforced client-side as the box is typed into, well under
    # protocol.MAX_CHAT_TEXT_LENGTH's own wire-level sanity cap.
    CHAT_MAX_LENGTH = 200
    CHAT_LOG_MAX = 50
    CHAT_VISIBLE_LINES = 8

    # Footstep sound cadence -- alternates player_footstep_1/2 (see
    # SoundManager) on a plain timer rather than specific walk/run animation
    # frames (not precisely known for these sheets), reset to 0 the instant
    # movement stops so the first step after starting again always plays
    # right away instead of waiting out a stale partial interval.
    FOOTSTEP_INTERVAL_WALK = 0.35
    FOOTSTEP_INTERVAL_RUN = 0.22

    # One-shot actions (Player.play_action), checked against a single event
    # (KEYDOWN or MOUSEBUTTONDOWN) via Settings.matches_event rather than
    # polled -- unlike movement/run, either input kind is valid for these.
    ONE_SHOT_ACTIONS = ("jump", "attack", "interact")

    # Phase 4 (client-side prediction), client-only: fraction of the
    # remaining distance to a remote entity's latest known server position
    # closed per second by _smooth_network_entities -- every mirrored entity
    # except the local player (animals, enemies, other players, pickups,
    # projectiles) only gets a fresh position once per server tick (30Hz)
    # while the client renders at 60fps, so snapping straight to it every
    # snapshot reads as a visible stutter. A plain per-frame lerp toward the
    # latest target is enough for LAN co-op -- no timestamped double-buffer
    # interpolation.
    NETWORK_INTERP_RATE = 15.0

    def __init__(self, game_manager):

        self.game_manager = game_manager
        self.screen = game_manager.screen
        self.settings = game_manager.settings

        # -----------------------------
        # Monde
        # -----------------------------

        self.dungeon = Dungeon(width=22, height=18)
        self.assembly = None
        # Only ever "the room a freshly-joining session should spawn into"
        # now (set once by open_room/open_donjon, read by
        # add_network_session) -- every session's own LIVE room/floor is
        # session.current_placed_room instead (see PlayerSession), so one
        # player crossing a door no longer drags every other player's
        # collision/rendering into the new room/floor with them.
        self.current_placed_room = None

        # Debug mode (F3 toggles): shows/hides the logical grid overlay and
        # every live hitbox on screen (red for the player, yellow for
        # animals), and logs *why* a blocked move was rejected, so a mismatch
        # between what's visually touching and what's actually colliding is
        # directly observable instead of guessed at. Off by default -- the
        # grid is normally only useful while editing, not exploring.
        self.debug_mode = False
        self._last_debug_message = None

        # PvP (F4 toggles, separate from F3's debug_mode -- see run()): off
        # by default, since normal co-op play shouldn't have players
        # accidentally damaging each other. When on, _resolve_player_attacks
        # also checks every other session's hitbox.
        self.pvp_enabled = False

        # Chat overlay (T toggles, network play only -- see run_networked):
        # one shared box, not per-session (there's only ever one local
        # keyboard typing on a network client). chat_log entries are
        # {"player_id", "name", "text", "system", "time"} dicts, newest
        # last, capped at CHAT_LOG_MAX. Never touched by solo run() -- T is
        # simply unhandled there, nobody to talk to.
        self.chat_open = False
        self.chat_input = ""
        self.chat_log = []
        self._chat_font = None  # lazily created on first render (needs pygame.font initialized)

        # Multiplayer panel (M toggles, home only while not yet connected --
        # see run()/run_networked()'s event loops and _is_home_room below).
        self.multiplayer_panel = MultiplayerPanelUI(
            x=self.screen.get_width() / 2 - MultiplayerPanelUI.PANEL_WIDTH / 2,
            y=140,
        )

        # Dungeon-entry sync barrier (see _check_dungeon_entrance): player_
        # ids who have already crossed home's dungeon_entrance and are now
        # frozen, waiting for every other CURRENTLY connected player
        # (self.players.keys(), a live set -- shrinks on its own if someone
        # disconnects while others wait) to do the same before generation
        # actually fires. Authoritative only where update() actually runs
        # (solo-local, or the server's own Explorator) -- mirrored onto a
        # network client via the snapshot's own "dungeon_entrance_ready"
        # field (apply_network_snapshot), same pattern self.victory already
        # uses to reach clients that never simulate it themselves.
        self.dungeon_entrance_ready = set()

        # -----------------------------
        # Joueurs -- toujours pilotee par le clavier local (_local_player_id).
        # Toute la simulation/rendu boucle sur self.players.values() plutot
        # que de viser une instance figee (voir core/player_session.py).
        #
        # Joueur 2 (Phase 2, preuve de concept co-op local) : cree tout de
        # suite si une manette est branchee, sinon cree paresseusement au
        # premier appui sur une touche du second schema clavier (voir
        # run()) -- pour que le mode solo au clavier reste inchange tant que
        # personne n'utilise vraiment ce second schema.
        # -----------------------------

        self._local_player_id = 0
        self.players = {self._local_player_id: PlayerSession(self._local_player_id)}

        # self.settings is None on the headless server (_HeadlessGameManager)
        # -- that id-0 session gets replaced immediately by GameServer's own
        # network sessions anyway, so there's nothing to load here in that
        # case. In every local/client mode, Menu's name-entry screen has
        # already set local_player_name before Explorator is ever built.
        if self.settings is not None and self.settings.local_player_name:
            self.players[self._local_player_id].profile = ProfileManager().load(
                self.settings.local_player_name
            )

        pygame.joystick.init()
        if pygame.joystick.get_count() > 0:
            joystick = pygame.joystick.Joystick(0)
            joystick.init()
            self.players[1] = PlayerSession(1, "gamepad", joystick)

        if not self.load_spawn_room():
            print("Aucune salle avec un spawn n'a été trouvée.")

        self._position_player_at_spawn(self.players[self._local_player_id])

        # The only win condition that exists right now (see
        # _interact_with_chest): freezes gameplay and shows a victory banner
        # once True, same "world paused, just an overlay" shape as a
        # session's inventory_open. No dedicated GameState -- ESC still
        # returns to the menu normally from here.
        self.victory = False

        # -----------------------------
        # Camera
        # -----------------------------
        # self.camera is the MERGED/shared view's camera (solo, or 2+ local
        # co-op sessions all currently in the same room -- see
        # _merged_view). Each PlayerSession also owns its own (see
        # PlayerSession.camera), used instead once real split-screen kicks
        # in (2+ local sessions in DIFFERENT rooms). See
        # _viewport_rects/_update_camera/_render_viewport.

        self.camera = Camera(zoom=1.0)
        # (world_x, world_y) or None -- the merged camera's own eased
        # center point while 2+ local sessions share a room (see
        # _smoothed_center_toward/_update_shared_camera). None until the
        # first time that code path actually runs, so it can seed itself
        # from wherever the players actually are instead of easing in from
        # a made-up starting point.
        self._shared_camera_center = None

        # Name of the single room currently loaded (open_room), or None in
        # assembly mode (open_donjon) -- mirrors Creator.current_room's own
        # convention exactly. Used by _check_home_zoom_switch (core.world.home)
        # to know whether the active room is the local player's own home.
        self.current_room = None

        # Name of the currently active assembly's saved .json (assets/donjons/),
        # or None in single-room mode -- set by open_donjon/_enter_assembly.
        # Included in every network snapshot (protocol.build_snapshot) so a
        # client (including the host's own loopback client -- see
        # Explorator.start_hosting) can notice when the authoritative
        # Explorator (the server, or the local one in solo play) has swapped
        # into a freshly generated dungeon (_maybe_complete_dungeon_entrance_
        # barrier) and mirror that by loading the exact same saved assembly
        # itself (see apply_network_snapshot) -- without this, a client had no
        # way to learn a brand-new assembly (never seen at connect time, only
        # generated mid-session) even exists, and kept rendering whatever
        # single room/assembly it happened to have loaded before crossing.
        self.current_donjon_name = None

        self.clock = pygame.time.Clock()

        # Networking (Phase 3+4), client-side only -- see
        # apply_network_snapshot/_smooth_network_entities. Initialized here
        # (not lazily) so a client's very first render, before any snapshot
        # has arrived, has an empty-but-real dict to iterate rather than
        # needing an AttributeError guard.
        self._network_mirrors = {}  # room_ref -> {"mobs": {...}, ...}
        self._network_targets = {}  # id(entity) -> (entity, target_x, target_y)

        # True once _finish_connecting has run (a thin network client --
        # start_hosting's own loopback client included, see its docstring)
        # -- False for the authoritative Explorator (solo local play, or
        # GameServer's own headless instance). open_room/_enter_assembly
        # check this to skip spawn_mobs(): a client's mobs are entirely
        # mirrored from the server's snapshot (apply_network_snapshot's
        # _sync_mirror_list), so locally spawning a real, separate set too
        # used to leave a second, never-updated (frame-0, standing still)
        # Mob sitting right on top of every mirrored one -- exactly the
        # "double sur leur point de spawn" bug reported after the
        # dungeon-entrance sync barrier started calling open_donjon
        # mid-session on clients too (see apply_network_snapshot), though
        # the same gap already existed at ordinary connect time
        # (_finish_connecting's own open_room/open_donjon call) for any
        # room/donjon that happened to have mobs placed in it.
        self.is_network_client = False

        # The room this session should return to on death/victory (see
        # _return_to_home) when self.settings has no local_player_name of
        # its own to derive a home room name from -- set once by
        # GameServer.__init__ at hosting time (self.current_room itself
        # drifts to None the moment a generated dungeon is entered, see
        # _enter_assembly, so it can't be relied on for this). None here
        # covers every other case (solo play always has settings; a pure
        # network client never calls _return_to_home at all).
        self._home_room_name = None

    def open_room(self, name):
        """Load a specific room (chosen from the menu) and spawn every current
        session's player in it."""
        self.assembly = None
        self.current_placed_room = None
        self.current_room = name
        self.current_donjon_name = None
        self.dungeon.load_from_json(name)
        # Skipped for a network client -- see self.is_network_client's own
        # docstring for why locally spawning here too would double up with
        # the mirrored mobs apply_network_snapshot creates.
        if not self.is_network_client:
            self.dungeon.spawn_mobs()
        for session in self.players.values():
            self._position_player_at_spawn(session)
            session.current_placed_room = None
            session.last_door_obj = None
            # A session's Player is reused across menu <-> exploration
            # transitions (never recreated), so a death from the last run
            # would otherwise leave health at 0 and trigger _game_over again
            # on the very next frame -- reset it here, same idea as
            # re-placing position at the spawn point above.
            session.player.health = session.player.MAX_HEALTH
            # A fresh run (whether this is a genuine new attempt or just
            # returning to home after one ended) starts with an empty card
            # stash -- see Inventory.clear_cards/_trigger_victory for why
            # anything still in grid_slots at this point was never banked
            # (a defeat, or simply never having won yet).
            session.inventory.clear_cards()
        # Same reasoning for victory (see _interact_with_chest) -- otherwise
        # re-entering exploration would start right back on the frozen
        # victory screen from last time.
        self.victory = False

    def open_donjon(self, name):
        """Load a saved procedurally-assembled dungeon and spawn every
        current session's player in its starting room."""
        self._enter_assembly(load_assembly(name), donjon_name=name)

    def _enter_assembly(self, assembly, donjon_name=None):
        """Shared by open_donjon (a saved assembly, chosen from the menu)
        and _maybe_complete_dungeon_entrance_barrier (a freshly
        procedurally-generated one, triggered mid-update() once every
        connected player has crossed home's dungeon_entrance): assigns it
        as the active world, spawns every room's animals/enemies, and
        places every current session at the start room's spawn point.

        donjon_name (assets/donjons/<name>.json) is recorded on
        self.current_donjon_name -- included in every network snapshot
        (protocol.build_snapshot) so a client (including the host's own
        loopback client) can notice the authoritative Explorator entered a
        NEW assembly it was never told about at connect time and mirror it
        by loading that same saved file itself (see
        apply_network_snapshot). _maybe_complete_dungeon_entrance_barrier
        always saves the assembly it just generated (via save_assembly)
        before calling this, specifically so this name is always something
        a client can actually load from its own local assets/donjons/."""
        self.assembly = assembly
        self.current_room = None
        self.current_donjon_name = donjon_name
        self.victory = False
        self.dungeon_entrance_ready.clear()

        # Skipped for a network client -- see self.is_network_client's own
        # docstring.
        if not self.is_network_client:
            for room in self.assembly.rooms:
                room.dungeon.spawn_mobs()

        start_room = next(
            (room for room in self.assembly.rooms if room.has_spawn()),
            self.assembly.rooms[0],
        )
        self.current_placed_room = start_room

        spawn_local = start_room.dungeon.get_spawn_world_position()
        if spawn_local is None:
            spawn_local = (start_room.dungeon.tile_size, start_room.dungeon.tile_size)

        tile_size = start_room.dungeon.tile_size
        for session in self.players.values():
            session.player.health = session.player.MAX_HEALTH
            session.player.position.update(
                start_room.offset_x * tile_size + spawn_local[0] + self._spawn_offset_x(session, tile_size),
                start_room.offset_y * tile_size + spawn_local[1],
            )
            session.current_placed_room = start_room
            session.last_door_obj = None
            session.last_dungeon_entrance_pos = None
            session.last_dungeon_exit_pos = None
            # Entering a dungeon is where a real "run" actually starts --
            # see Inventory.clear_cards/_trigger_victory.
            session.inventory.clear_cards()

    @staticmethod
    def _spawn_offset_x(session, tile_size):
        """One tile to the right per extra session (player 0 is untouched --
        exactly today's single-player spawn point) so two bodies don't spawn
        stacked exactly on top of each other now that _is_walkable checks
        player-vs-player collision too."""
        return session.player_id * tile_size

    def _position_player_at_spawn(self, session):
        spawn = self.dungeon.get_spawn_world_position()

        if spawn is None:
            print("Spawn invalide.")
            spawn = (
                self.dungeon.tile_size,
                self.dungeon.tile_size,
            )

        session.player.position.update(
            spawn[0] + self._spawn_offset_x(session, self.dungeon.tile_size), spawn[1]
        )

    def _is_home_room(self):
        """True while the currently-open single room is the local player's
        own home -- mirrors Creator._is_home_room exactly. Shared by
        _check_home_zoom_switch (further gated to solo play there) and the
        M-key multiplayer-panel toggle in run() (players host/join "from
        home only")."""
        if self.current_room is None:
            return False
        if self.settings is None or not self.settings.local_player_name:
            return False
        return self.current_room == home_room_name(self.settings.local_player_name)

    def _check_home_zoom_switch(self):
        """Zoom-driven switch back to Creator, home room only (see
        core.world.home) -- called from run() only, never run_networked or
        the headless server's own tick loop, since a network client has no
        local Creator to swap into. Solo-only (co-op/multiplayer visiting a
        home room together is out of scope -- Phase 6e, not yet built), and
        uses self.camera (the merged-view camera, always what a lone local
        session renders through)."""
        if len(self.players) != 1 or not self._is_home_room():
            return
        if wants_creator(self.camera.zoom):
            session = self.players[self._local_player_id]
            local_position = session.player.position
            # Persisted so Creator's entity-gated tools (Generateur/Forge,
            # see Creator._entity_in_range) can compare against it -- Creator
            # owns no player entity of its own, so this crossing is the only
            # moment a real position is known to save. apply_to_fresh_profile
            # (not a direct ProfileManager().save(session.profile)) so this
            # never clobbers a card_collection change Creator made during a
            # previous CREATOR visit this same run, same reasoning as
            # _grant_xp's own use of it.
            apply_to_fresh_profile(
                session, lambda profile: profile.set_home_player_position(local_position.x, local_position.y),
            )
            self.game_manager.pending_room = self.current_room
            self.game_manager.pending_zoom_carry = self.camera.zoom
            self.game_manager.pending_camera_center = (local_position.x, local_position.y)
            self.game_manager.state = GameState.CREATOR

    def _resolve_dungeon_transitions(self):
        """Checks the two new E/S roles (core.world.object_manager.get_role)
        once per frame, after every session's own movement has already been
        simulated this frame -- deliberately its own separate pass (not
        folded into the per-session movement loop) so a dungeon_entrance
        crossing, which replaces the entire active world mid-frame, can
        never leave a session later in that same loop iteration processed
        against a world that's about to be swapped out from under it. Lives
        in update(), not run() -- unlike the zoom-switch above, this must
        run identically on a solo client and the headless server, same
        server-authoritative principle every other gameplay fact already
        follows (buttons, combat, pickups)."""
        if self.assembly is None:
            # Checked unconditionally every frame, not only right after a
            # fresh crossing -- a player disconnecting while others wait at
            # the barrier can complete it for whoever's left on its own,
            # without needing anyone to cross again. See
            # _maybe_complete_dungeon_entrance_barrier's own docstring for
            # why this must be the only place that ever actually triggers
            # generation.
            if self._maybe_complete_dungeon_entrance_barrier():
                return
            for session in self.players.values():
                if self._check_dungeon_entrance(session):
                    return  # world just got replaced -- nothing else this frame is still valid to check
        for session in self.players.values():
            self._check_dungeon_exit(session)

    def _dungeon_entrance_source_profile(self):
        """Whose saved generation parameters (Profile.generator_room_names/
        generator_room_count) drive generation once the sync barrier
        completes -- the host's (lowest player_id, matching GameServer.
        _host_player_id's own convention), not whichever player's crossing
        happens to be the one that completes the barrier, so the result
        never depends on crossing order. Works identically solo (the one
        session already IS the host) and on a real multiplayer server,
        where every session's own profile is already loaded
        (add_network_session) -- deliberately doesn't read self.settings.
        local_player_name, since a server's own self.settings is always
        None (see _HeadlessGameManager)."""
        if not self.players:
            return None
        return self.players[min(self.players.keys())].profile

    def _maybe_complete_dungeon_entrance_barrier(self):
        """True (after actually completing generation) iff
        self.dungeon_entrance_ready is non-empty and already covers every
        CURRENTLY connected player (self.players.keys(), a live set).
        Called every frame from _resolve_dungeon_transitions -- not just
        reactively from _check_dungeon_entrance the moment someone crosses
        -- specifically so a player disconnecting while others are still
        waiting gets noticed too: remove_session only ever discards the
        departing id from the ready set, it deliberately never calls this
        itself, since remove_session can run from a connection's own
        reader thread (server-side) where touching shared world state via
        generate_assembly/_enter_assembly would be unsafe -- only the main
        tick thread's own update() -> _resolve_dungeon_transitions call
        ever reaches here. On a failed attempt (no saved generation
        selection, or nothing in it has a spawn+exit) the ready set is
        still cleared rather than left stuck -- everyone frozen un-freezes
        on their own, at the cost of needing to cross again once the
        issue's fixed."""
        if not self.dungeon_entrance_ready or self.dungeon_entrance_ready < set(self.players.keys()):
            return False

        self.dungeon_entrance_ready.clear()

        profile = self._dungeon_entrance_source_profile()
        if profile is None or not profile.generator_room_names:
            print("[dungeon_entrance] Aucune selection de generation enregistree (voir le panneau Generation dans le Creator).")
            return False

        assembly = generate_assembly(profile.generator_room_names, profile.generator_room_count)
        if assembly is None:
            print("[dungeon_entrance] Aucune salle avec spawn + sortie dans la selection.")
            return False

        # Persisted (not just kept in memory) so a client -- including the
        # host's own loopback client, see Explorator.start_hosting -- can
        # load the exact same rooms/offsets itself once it notices
        # current_donjon_name changed in the next snapshot (see
        # apply_network_snapshot). Without this, only the authoritative
        # Explorator (the server, or the local one in solo play) ever knew
        # this assembly existed at all.
        donjon_name = next_new_donjon_name()
        save_assembly(assembly, donjon_name)

        self._enter_assembly(assembly, donjon_name=donjon_name)
        return True

    def _check_dungeon_entrance(self, session):
        """Single-room mode only -- a dungeon_entrance-role object can only
        ever be placed while editing home (Creator._is_home_room() gates
        RolePanelUI's "Entree de donjon" row), so this never fires in
        assembly mode. Edge-triggered off session's feet grid cell freshly
        matching such an object (session.last_dungeon_entrance_pos, same
        shape as last_door_obj).

        Sync barrier: a fresh crossing marks session.player_id "ready"
        (self.dungeon_entrance_ready) and freezes it in place (see
        update()'s per-session loop) rather than generating immediately --
        generation only actually fires once every CURRENTLY connected
        player has crossed, via _maybe_complete_dungeon_entrance_barrier
        (see its own docstring for why that's a separate, unconditionally-
        checked-every-frame method rather than inlined here). Solo play is
        unaffected in practice: with exactly one session, that one
        crossing already satisfies the barrier on the same frame, identical
        to the old immediate-trigger behavior. Returns True iff a
        generation actually happened this frame."""
        if session.player_id in self.dungeon_entrance_ready:
            return False

        hitbox = session.player.get_hitbox()
        grid_x, grid_y = self._feet_grid_cell(hitbox)
        obj = self.dungeon.object_manager.get_object_at(grid_x, grid_y)

        if obj is None or self.dungeon.object_manager.get_role(obj) != "dungeon_entrance":
            session.last_dungeon_entrance_pos = None
            return False

        if session.last_dungeon_entrance_pos == (grid_x, grid_y):
            return False
        session.last_dungeon_entrance_pos = (grid_x, grid_y)

        self.dungeon_entrance_ready.add(session.player_id)
        return self._maybe_complete_dungeon_entrance_barrier()

    def _cancel_dungeon_entrance_wait(self, session):
        """Un-freezes a session waiting at the sync barrier the moment they
        press any movement key (checked in update()'s per-session loop) --
        without this, a waiting player has no way back out on their own,
        and since a single-cell doorway can only hold one hitbox at a time
        (see _is_walkable's own carve-out for a waiting session), the very
        first player to cross would otherwise be the only one who ever
        could, permanently blocking everyone else from ever reaching that
        same cell to cross it themselves -- exactly the stuck-solo-tester
        symptom reported. Repositions the session one cell in front of the
        doorway (the room-interior side, via _doorway_interior_offset)
        instead of leaving them exactly on the door tile they just tried
        to take."""
        self.dungeon_entrance_ready.discard(session.player_id)
        last_pos = session.last_dungeon_entrance_pos
        session.last_dungeon_entrance_pos = None
        if last_pos is None:
            return

        offset = _doorway_interior_offset(self.dungeon, *last_pos)
        if offset is None:
            return
        dx, dy = offset
        world_x, world_y = self.dungeon.grid_to_world(last_pos[0] + dx, last_pos[1] + dy)
        session.player.position.update(world_x, world_y)

    def _check_dungeon_exit(self, session):
        """Edge-triggered off session's feet grid cell freshly matching an
        E/S (gate/wall/cave_entrance/big_entrance) flagged role=
        "dungeon_exit" -- sets self.victory the same way a dungeon_exit
        chest already does (_interact_with_chest). Works in both
        single-room and assembly mode, unlike dungeon_entrance -- a
        dungeon_exit isn't restricted to home. No-ops once victory is
        already set (nothing left to trigger)."""
        if self.victory:
            return

        dungeon, offset_x, offset_y = self._current_room_and_offset(session)
        hitbox = session.player.get_hitbox()
        global_grid_x, global_grid_y = self._feet_grid_cell(hitbox)
        grid_x, grid_y = global_grid_x - offset_x, global_grid_y - offset_y

        obj = dungeon.object_manager.get_object_at(grid_x, grid_y)
        if (
            obj is None
            or not dungeon.object_manager.is_es_type(obj["type"])
            or dungeon.object_manager.get_role(obj) != "dungeon_exit"
        ):
            session.last_dungeon_exit_pos = None
            return

        if session.last_dungeon_exit_pos == (grid_x, grid_y):
            return
        session.last_dungeon_exit_pos = (grid_x, grid_y)

        self._trigger_victory(session)

    def _active_floors(self):
        """Every floor at least one session currently occupies, in assembly
        mode -- {None} in single-room mode (no floor concept there, ignored
        by _rooms_with_offset). Two sessions in two different rooms of the
        same assembly now genuinely happens (see PlayerSession.
        current_placed_room), so anything scoped "to the active floor" needs
        to consider all of them, not just one.

        Skips any session with current_placed_room still None -- a network
        client's mirrored PlayerSessions for REMOTE players (see
        apply_network_snapshot) never get one set at all (the client has no
        idea which room/floor another player is actually on), and this used
        to crash outright the instant a second player connected and either
        client tried to move (_predict_local_movement -> _is_walkable ->
        _visible_mobs_global -> here)."""
        if self.assembly is None:
            return {None}
        return {
            session.current_placed_room.floor for session in self.players.values()
            if session.current_placed_room is not None
        }

    def _rooms_with_offset(self, floors):
        """(dungeon, offset_x, offset_y) -- pixel offset -- for every room on
        any of `floors` (a set, see _active_floors) in assembly mode
        (DungeonAssembly.update already hands every player's hitbox to all
        rooms on their own floor regardless of which specific room each
        player is registered as standing in, so combat/pickups/etc. need to
        look at all of them too), or just self.dungeon (offset (0, 0), one
        yield regardless of `floors`) in single-room mode. Shared by
        _visible_mobs_global/_collect_pickups, which otherwise each
        re-derive this identically."""
        if self.assembly is not None:
            tile_size = Dungeon.TILE_SIZE
            for floor in floors:
                for room in self.assembly.rooms_on_floor(floor):
                    yield room.dungeon, room.offset_x * tile_size, room.offset_y * tile_size
        else:
            yield self.dungeon, 0, 0

    def _visible_mobs_global(self):
        """(mob, hitbox, dungeon) triples for every ALIVE mob that could
        plausibly collide with a player right now, hitbox already in
        global/world coordinates -- a dead one (mid despawn-hold, see
        Mob.DEATH_DESPAWN_DELAY) doesn't block, mirroring MobManager.
        _is_free's own "other.alive" check for mob-vs-mob. `dungeon` is
        whichever room's own Dungeon actually owns this mob, needed by
        combat code to drop loot/pickups into the right room's
        PickupManager rather than always self.dungeon (wrong in assembly
        mode for any mob outside whichever room the attacking session
        itself is currently in). Replaces the old separate
        _visible_animals_global/_visible_enemies_global now that a single
        MobManager covers both."""
        triples = []
        for dungeon, offset_x, offset_y in self._rooms_with_offset(self._active_floors()):
            for mob in dungeon.mob_manager.mobs:
                if mob.alive:
                    triples.append((mob, mob.get_hitbox().move(offset_x, offset_y), dungeon))
        return triples

    @staticmethod
    def _scatter_loot(dungeon, x, y, loot, item_loot, spread):
        """Drops `loot` (currency_type -> count) as individual coin Pickups
        (2 gold + 1 blue -> 3 separate coins, not one "x2" stack) and
        `item_loot` (item_id -> count) as individual ItemPickups (e.g.
        dynamite), each scattered +/-spread px around (x, y) on `dungeon`'s
        own PickupManager. Shared by _spawn_loot (enemy death) and
        _interact_with_chest (opening a chest) -- only the loot-table source
        and scatter radius differ between the two callers."""
        for currency_type, count in loot.items():
            for _ in range(count):
                dungeon.pickup_manager.spawn(
                    currency_type,
                    x + random.uniform(-spread, spread),
                    y + random.uniform(-spread, spread),
                )

        for item_id, count in item_loot.items():
            for _ in range(count):
                dungeon.pickup_manager.spawn_item(
                    make_item(item_id),
                    ITEM_DEFINITIONS[item_id]["slot"],
                    x + random.uniform(-spread, spread),
                    y + random.uniform(-spread, spread),
                )

    @staticmethod
    def _spawn_loot(mob, mob_dungeon):
        """Drops mob.stats' currency loot around the death spot via
        _scatter_loot -- item drops are no longer part of this (see
        mechanics_panel.py's own comment on retiring mob_item_loot): a
        mob's card-based reward, including any real item it's configured
        to also drop, is handled separately by MobManager.
        _spawn_death_reward/_spawn_loot_pickups once its despawn spark
        lands, not here. Fires for any combat-capable mob that dies, not
        just a former "enemy" -- a mob with no "loot" in its stats (every
        animal-style one today) is simply a no-op, same net effect as the
        old animal-never-drops-currency behavior, now via data absence
        rather than a separate code path. mob.position is already local to
        mob_dungeon (never offset-translated -- see Mob's own coordinate
        convention), so no conversion is needed before handing it to that
        same dungeon's PickupManager."""
        Explorator._scatter_loot(
            mob_dungeon, mob.position.x, mob.position.y,
            mob.stats.get("loot", {}), {}, spread=10,
        )

    def _collect_pickups(self, player_hitbox, inventory):
        """Credits inventory.currency for every ground Pickup player_hitbox
        touches this frame, across whichever room(s) that's meaningful for --
        same per-floor scope as _visible_mobs_global. `inventory` is the
        calling session's own Inventory (see _resolve_pickups), not a shared
        singleton."""
        for dungeon, offset_x, offset_y in self._rooms_with_offset(self._active_floors()):
            local_hitbox = player_hitbox.move(-offset_x, -offset_y)
            dungeon.pickup_manager.collect(local_hitbox, inventory)

    def _trigger_action(self, session, action_id):
        """Fires action_id's one-shot behavior for `session` -- normally just
        Player.play_action, but "interact" is intercepted first for a chest
        the player is facing (see _interact_with_chest), then for a usable
        item equipped in the interact slot (see _use_interact_item), either
        of which repurposes the interact input instead of just playing the
        plain interact animation. A facing chest wins over a held item --
        interacting with the world takes priority over the player's own
        inventory."""
        if action_id == "interact" and (self._interact_with_chest(session) or self._use_interact_item(session)):
            return
        session.player.play_action(action_id)

    def _current_room_and_offset(self, session):
        """(dungeon, offset_x, offset_y) for session's own current room --
        offset is (0, 0) in single-room mode. Shared by anything that needs
        to convert a player's (always-global) position/hitbox into that
        room's own local coordinates, the same way every other per-room live
        entity's position already works (see
        _use_interact_item/_interact_with_chest)."""
        if self.assembly is not None:
            room = session.current_placed_room
            return room.dungeon, room.offset_x, room.offset_y
        return self.dungeon, 0, 0

    def _mouse_world_position(self, session):
        """The current mouse cursor's world-space position, or None if
        `session` isn't the one session the mouse actually drives -- "the
        mouse is only ever used by the primary local player" (same rule
        the MOUSEWHEEL zoom handler already applies, see run()'s own
        comment there), so this returns None for every other session
        (secondary local co-op, gamepad, a remote network session) rather
        than guessing. Resolves the same camera + viewport-relative
        position the zoom handler does: self.camera in merged view, or
        session.camera offset by its own _viewport_rects() rect in real
        split-screen."""
        if session.player_id != self._local_player_id:
            return None
        mouse_x, mouse_y = pygame.mouse.get_pos()
        if self._merged_view():
            camera = self.camera
            local_x, local_y = mouse_x, mouse_y
        else:
            rect = self._viewport_rects().get(session.player_id)
            if rect is None:
                return None
            camera = session.camera
            local_x, local_y = mouse_x - rect.x, mouse_y - rect.y
        return pygame.Vector2(camera.screen_to_world(local_x, local_y))

    def _use_interact_item(self, session):
        """Returns True if session's interact slot held a usable item and it
        was used: consumes the item, applies whichever behavior it defines,
        and plays the interact animation for visual feedback. Two kinds of
        "usable" exist today, checked in this priority order:
        - "throwable" capability (see ITEM_DEFINITIONS' "capabilities" dict
          -- currently just dynamite, which also carries "explosive"):
          spawns a live ThrownDynamite in the current room (converted to
          that room's local coordinates, same convention as every other
          per-room live entity) at the player's position, aimed at the
          mouse cursor for whichever session the mouse actually drives
          (see _mouse_world_position) -- a free angle, not snapped to the
          8-way DIRECTION_VECTORS, for precise aim despite the throw
          animation itself only having 8 directional rows. Falls back to
          the player's own facing direction for every other session
          (secondary local co-op, gamepad, network), same as before this
          existed.
        - "effects" list (see ITEM_DEFINITIONS' "effects" -- currently just
          the "heal" kind, e.g. a Potion de soin): applies each recognized
          effect immediately to session.player. An unrecognized "kind" is
          silently skipped rather than raising -- the same "degrade, don't
          crash, on unknown data" spirit as is_cell_walkable's handling of
          a missing type.
        Throwable wins if an item somehow carries both -- throwing already
        has its own "spawn a projectile" mechanic that doesn't compose with
        "apply effects instantly". Returns False (no-op) if the slot is
        empty or the item defines neither, leaving _trigger_action to fall
        back to the plain interact animation."""
        item = session.inventory.main_slots["interact"]
        if item is None:
            return False
        definition = ITEM_DEFINITIONS.get(item.item_id, {})

        capabilities = definition.get("capabilities", {})
        if "throwable" in capabilities:
            session.inventory.main_slots["interact"] = None

            mouse_world = self._mouse_world_position(session)
            if mouse_world is not None and mouse_world != session.player.position:
                direction = (mouse_world - session.player.position).normalize()
            else:
                dx, dy = Player.DIRECTION_VECTORS.get(session.player.direction, (0, 1))
                direction = pygame.Vector2(dx, dy)
            # The throw animation only has 8 directional rows (see
            # Player.DIRECTIONS/get_sprite_direction) -- snap the player's
            # OWN facing to the nearest of those for play_action below,
            # while the dynamite itself keeps the free, unsnapped angle
            # for precise aim (ThrownDynamite.direction is a free
            # pygame.Vector2 already, see its own docstring).
            session.player.direction = _bucket_direction(direction)

            dungeon, offset_x, offset_y = self._current_room_and_offset(session)
            tile_size = dungeon.tile_size
            local_x = session.player.position.x - offset_x * tile_size
            local_y = session.player.position.y - offset_y * tile_size
            dungeon.projectile_manager.throw_dynamite(local_x, local_y, direction, capabilities)
            play_card_sound(
                definition.get("sounds", {}), "throw", fallback_event="dynamite_interact",
                pitch_range=definition.get("sound_pitch", {}).get("throw"),
            )

            session.player.play_action("interact")
            return True

        effects = definition.get("effects", [])
        if effects:
            for effect in effects:
                if effect.get("kind") == "heal":
                    session.player.heal(effect.get("amount", 1))
            session.inventory.main_slots["interact"] = None
            # A card-authored "use" sound (see ITEM_DEFINITIONS' own
            # "sounds" mechanics field / MechanicsPanelUI's "Son :
            # Utilisation" row) wins if the item was given one; otherwise
            # "blue_collect" (currency pickup chime) stays the generic
            # positive-feedback fallback, same as before this field existed.
            play_card_sound(
                definition.get("sounds", {}), "use", fallback_event="blue_collect",
                pitch_range=definition.get("sound_pitch", {}).get("use"),
            )
            session.player.play_action("interact")
            return True

        return False

    def _interact_with_chest(self, session):
        """Returns True if session's player was facing an unopened chest
        (e.g. lilchest) within melee reach and interacted with it: starts its
        opening animation (frame 4, the first frame of row 1 -- see
        OBJECT_TYPES["lilchest"] -- ObjectManager.update takes it from there
        and holds on the last frame once reached, same mechanism as any
        other blocks_until_open object), spawns its configured currency/item
        loot scattered around its own position, and -- only if this
        particular chest is explicitly flagged role="dungeon_exit" (see
        ObjectManager.get_role/set_role; an ordinary role="loot" chest,
        including every one placed before the role system existed, no
        longer auto-wins just by being opened) -- triggers the victory
        screen. Reuses the player's own melee reach (get_attack_hitbox:
        their hitbox shifted one tile in their facing direction) rather
        than a separate "interact range", since a chest blocks movement
        (blocks_movement) so a player can only ever be standing right next
        to it, never on top of it. Returns False (no-op) if there's no such
        chest in reach or it's already open, leaving _trigger_action to
        fall back to throwing/the plain interact animation."""
        dungeon, offset_x, offset_y = self._current_room_and_offset(session)
        tile_size = dungeon.tile_size

        reach_hitbox = session.player.get_attack_hitbox()
        grid_x = int((reach_hitbox.centerx - offset_x * tile_size) // tile_size)
        grid_y = int((reach_hitbox.centery - offset_y * tile_size) // tile_size)

        obj = dungeon.object_manager.get_object_at(grid_x, grid_y)
        if obj is None or not dungeon.object_manager.is_chest(obj["type"]) or obj.get("open"):
            return False

        obj["open"] = True
        obj["frame"] = OBJECT_TYPES[obj["type"]]["frames"] // OBJECT_TYPES[obj["type"]]["rows"]
        obj["anim_timer"] = 0.0
        dungeon.object_manager.begin_animation(obj)

        chest_x, chest_y = dungeon.grid_to_world(obj["x"], obj["y"])
        self._scatter_loot(dungeon, chest_x, chest_y, obj.get("loot", {}), obj.get("item_loot", {}), spread=12)

        session.player.play_action("interact")
        if dungeon.object_manager.get_role(obj) == "dungeon_exit":
            self._trigger_victory(session)
        return True

    def _is_walkable(self, rect, moving_session, debug_label=None, visible_mobs=None):
        """debug_label, only used when self.debug_mode is True, tags a
        printed message identifying which candidate move (e.g. "x"/"y") this
        check was for, so a blocked move's cause (wall vs. mob/
        another player) shows up in the console instead of only being
        inferred from what's on screen.

        visible_mobs lets a caller that's about to run several of these
        checks back-to-back (both movement axes in _resolve_movement_step,
        or a whole replay batch in _reconcile_local_player) pass in one
        shared _visible_mobs_global() snapshot instead of each check
        redoing that same room-scan from scratch. Left None (the default)
        for any other caller, which just computes its own snapshot as
        before.

        Checks each of the 4 corners individually (not a single aggregate
        is_rect_walkable call) so a corner that has crossed into void (see
        _is_void_at) is treated as passable right there, instead of only
        being excused by a single center-anchored point elsewhere. That old
        approach (a plain "is_rect_walkable(rect) or self._is_void(rect)" in
        update()) tested rect.centerx/rect.bottom-1 for void -- a point that
        lags behind the hitbox's leading edge by up to half its width/height
        while moving, so a corner could already be sitting past a room
        boundary or an open gate (making is_rect_walkable False) while the
        center hadn't crossed yet (making the old is_void check also False)
        -- deadlocking the player exactly at that edge, indistinguishable
        from a real wall. Checking void at the same per-corner granularity as
        the wall check removes that gap entirely.

        `moving_session` is excluded from the player-vs-player check below --
        a player's own hitbox obviously always overlaps itself."""
        room = moving_session.current_placed_room
        for grid_x, grid_y in corner_cells(rect, Dungeon.TILE_SIZE):
            if self._is_void_at(grid_x, grid_y, room) or self._is_cell_walkable(grid_x, grid_y, room):
                continue
            self._debug_log(debug_label, "wall")
            return False

        if visible_mobs is None:
            visible_mobs = self._visible_mobs_global()
        for mob, mob_rect, _dungeon in visible_mobs:
            if rect.colliderect(mob_rect):
                self._debug_log(debug_label, f"mob({mob.mob_type} at {mob_rect.center})")
                return False

        for other_session in self.players.values():
            if other_session is moving_session:
                continue
            if other_session.player_id in self.dungeon_entrance_ready:
                # Waiting at the sync barrier (see _check_dungeon_entrance)
                # -- deliberately excluded from collision, not just hidden
                # from rendering (_render_viewport's own entity-sort skips
                # them too): a single-cell doorway can only ever hold one
                # hitbox, so leaving a waiting player solid there would
                # permanently block every other player from ever reaching
                # the same cell to cross it themselves.
                continue
            if rect.colliderect(other_session.player.get_hitbox()):
                self._debug_log(debug_label, f"player({other_session.player_id})")
                return False

        self._last_debug_message = None  # unblocked -- next block (even the same reason) should log again
        return True

    @staticmethod
    def _feet_grid_cell(rect):
        """The grid cell under a hitbox's feet anchor (centerx, bottom-1) --
        the single-point convention shared by every void/room-transition/
        collision check in this file, as opposed to is_rect_walkable's
        4-corner check."""
        return int(rect.centerx // Dungeon.TILE_SIZE), int((rect.bottom - 1) // Dungeon.TILE_SIZE)

    def _magnet_radius(self):
        """World-space radius approximating "what's visible on screen" --
        half of the screen's smaller dimension, scaled back by zoom (same
        math Camera.screen_to_world already uses for a single axis) -- for
        PickupManager's currency/item magnetism (see Dungeon.update). Not a
        true field-of-view/fog-of-war concept (none exists in this
        codebase, see the camera/viewport research behind this feature) --
        an approximation the user explicitly asked for ("rayon equivalent
        au champ de vision"), not a precise viewport rect."""
        return min(self.screen.get_width(), self.screen.get_height()) / (2 * self.camera.zoom)

    def _update_world(self, dt, player_refs):
        """Advances the room(s) any player can currently affect -- objects,
        animals/enemies, pickups -- via whichever of assembly/single-dungeon
        mode is active. Shared by the frozen victory/inventory tick and the
        normal per-frame update, which additionally runs button-trigger
        checks this helper deliberately leaves out (not meaningful while
        input is frozen)."""
        magnet_radius = self._magnet_radius()
        if self.assembly is not None:
            self.assembly.update(dt, player_refs_by_floor=self._player_refs_by_floor(), magnet_radius=magnet_radius)
        else:
            self.dungeon.update(dt, player_refs=player_refs, magnet_radius=magnet_radius)

    def _is_cell_walkable(self, grid_x, grid_y, room):
        """Real wall/closed-door/etc. walkability for a single global cell,
        on `room`'s floor (the calling session's own current_placed_room --
        see _is_walkable) -- ignores void (see _is_void_at, checked
        separately by _is_walkable's caller) and other entities (also
        checked separately), so it's exactly the "is there a real obstacle
        here" half of the corner check."""
        if self.assembly is not None:
            return self.assembly.is_global_cell_walkable(
                grid_x, grid_y, room.floor, prefer_room=room
            )
        return self.dungeon.object_manager.is_cell_walkable(grid_x, grid_y)

    def _debug_log(self, label, reason):
        if not self.debug_mode or label is None:
            return
        message = f"[debug] move '{label}' blocked by {reason}"
        if message != self._last_debug_message:
            print(message)
            self._last_debug_message = message

    def _is_void(self, rect, room):
        """True if no room claims the cell under a player's feet on `room`'s
        floor (the calling session's own current_placed_room) -- distinct
        from being blocked by an actual wall/closed door/animal/enemy, which
        _is_walkable already covers. Single point (feet anchor), same
        convention as _update_current_room/check_button_trigger, not the
        4-corner check is_rect_walkable uses -- falling is about where a
        player's feet are, not a strict hitbox overlap test."""
        grid_x, grid_y = self._feet_grid_cell(rect)
        return self._is_void_at(grid_x, grid_y, room)

    def _is_void_at(self, grid_x, grid_y, room):
        if self.assembly is not None:
            return self.assembly.locate_room(
                grid_x, grid_y, room.floor, prefer_room=room
            ) is None

        return self.dungeon.is_void_at(grid_x, grid_y)

    def _attempt_fall(self, session):
        """Called once session's player's feet actually end up over void (see
        _is_void): looks for the nearest floor below (within the same
        assembly) that owns this exact global cell and lands there --
        session.current_placed_room changes, the player's position doesn't
        need to (it's already global, so "same tile, different floor" falls
        out for free). No assembly (single-room mode) or nothing below at
        all: falls out of the map entirely (see the "flagged, not decided"
        note on _game_over -- this ends the whole session today, not just
        this player)."""
        if self.assembly is None:
            self._game_over("Chute hors de la carte")
            return

        hitbox = session.player.get_hitbox()
        grid_x, grid_y = self._feet_grid_cell(hitbox)
        current_floor = session.current_placed_room.floor

        for floor in sorted((f for f in self.assembly.floors() if f < current_floor), reverse=True):
            room = self.assembly.locate_room(grid_x, grid_y, floor)
            if room is not None:
                session.current_placed_room = room
                session.last_door_obj = None  # new room/floor -- re-arm the door edge-trigger
                session.player.play_fall()
                return

        self._game_over("Chute hors de la carte")

    def _game_over(self, reason):
        """No floor anywhere below catches a fall, or a player's health hit
        0 -- either way, game over for the whole session (see the "flagged,
        not decided" notes -- whether a single player's death/fall should
        instead only remove that one player is an open Phase 2+ question).
        The real "monde de base" (étage system) doesn't exist yet, so this
        respawns everyone at home instead (see _return_to_home) rather than
        detouring through the main Menu, which has no real purpose here --
        this used to set game_manager.state = MENU, which also meant the
        SERVER's own headless GameManager left EXPLORATION and
        serve_forever's loop treated that as "stop hosting", ending the
        whole session for every connected player over one death. Staying
        in EXPLORATION and just reopening home keeps the session (and, for
        a hosted game, every other player's connection) alive instead."""
        print(f"[game] {reason} -- retour au home.")
        self._return_to_home()

    def _return_to_home(self):
        """Reopens home, staying in EXPLORATION -- shared by _game_over
        (death/falling out of the map) and clicking through the victory
        banner (see run()'s/run_networked's MOUSEBUTTONDOWN-while-victory
        handling, and GameServer._apply_message's MSG_RETURN_HOME for why
        a network client can't just do this locally). open_room already
        resets victory/every session's health/spawn position as part of
        loading a room, which is exactly what both callers need.

        Solo/local play (self.settings set, a real local_player_name) goes
        to that player's own home by name. The server -- self.settings is
        None, _HeadlessGameManager has no notion of a single "local"
        player at all -- only ever hosts a session that started from home
        in the first place (start_hosting's own hard requirement), but
        self.current_room itself is NOT a reliable stand-in for "home"
        there: it's reset to None the moment a generated dungeon is
        entered (_enter_assembly), which is exactly when death/victory
        actually happen in practice. self._home_room_name (set once by
        GameServer.__init__ at hosting time, before current_room could
        ever have drifted) is the server's own answer to that. Falls back
        to self.current_room only if neither of those applies (e.g. dying
        in a single-room test session opened straight from the menu,
        never through home at all)."""
        if self.settings is not None and self.settings.local_player_name:
            self.open_room(home_room_name(self.settings.local_player_name))
        elif self._home_room_name is not None:
            self.open_room(self._home_room_name)
        elif self.current_room is not None:
            self.open_room(self.current_room)

    def _update_current_room(self, session):
        """Edge-triggered room switch: session's player stepping onto a
        gate/wall entry-exit that connects to another room
        (door_target_room, stamped at generation time -- see
        DungeonAssembly.resolve_room_transition) flips session's own
        current_placed_room exactly once, on entry, whether that door
        happens to lead to a room on the same floor or a different one.
        Standing on the door doesn't re-trigger, and going back requires
        fully leaving the door cell and stepping onto it again from the
        other side.

        Per-session (not Explorator-level) precisely so that one player
        crossing a door doesn't affect any other session's own room/floor --
        see PlayerSession.current_placed_room.

        A border-floor seam (two rooms glued edge-to-edge with continuous
        floor and no gate/wall object at all -- see assembly._border_edges)
        has no door object for resolve_room_transition to key off of, so it
        never flips current_placed_room on its own. Falling back to
        whichever room's own FLOOR actually claims the player's cell
        (locate_room) keeps current_placed_room in sync there too. This
        can't undo a just-applied door transition: it re-queries on
        current_placed_room's (already updated) floor, and a door cell is
        WALL, not FLOOR, in both rooms, so locate_room's FLOOR-first check
        can't contradict it -- at worst it falls through to the same
        WALL-halo match resolve_room_transition already produced."""
        hitbox = session.player.get_hitbox()
        grid_x, grid_y = self._feet_grid_cell(hitbox)

        session.current_placed_room, session.last_door_obj = self.assembly.resolve_room_transition(
            session.current_placed_room, session.last_door_obj, grid_x, grid_y
        )

        same_floor_room = self.assembly.locate_room(
            grid_x, grid_y, session.current_placed_room.floor, prefer_room=session.current_placed_room
        )
        if same_floor_room is not None:
            session.current_placed_room = same_floor_room

    def load_spawn_room(self):

        rooms = sorted(ROOMS_DIRECTORY.glob("*.json"))

        if not rooms:
            print("Aucune salle trouvée.")
            return False

        for room in rooms:

            self.dungeon.load_from_json(room.stem)

            if self.dungeon.get_spawn_world_position() is not None:

                print(f"Spawn trouvé dans : {room.stem}")
                self.dungeon.spawn_mobs()
                return True

        print("Aucune salle ne contient de spawn.")
        return False
    # ------------------------------------------------------

    def _read_input(self):
        """Refreshes every session's InputState this frame, dispatching by
        input_source_kind (see core/engine/input.py) -- continuous
        movement/run polled fresh every frame per device, one-shot actions
        merged in from that session's own pending_actions (buffered by
        run()'s event loop since the last update())."""
        for session in self.players.values():
            if session.input_source_kind == "keyboard":
                state = read_local_keyboard_input(self.settings)
            elif session.input_source_kind == "secondary_keyboard":
                state = read_secondary_keyboard_input()
            elif session.input_source_kind == "network":
                # Server-side (Phase 3): no local device to poll -- reuse
                # whatever the connection reader thread last decoded from
                # this client's "input" messages (see
                # core/network/server.py), or an idle InputState() if
                # nothing has arrived yet (e.g. the very first tick after
                # join). requested_actions still flows through
                # session.pending_actions below like every other source --
                # the server appends decoded one-shot action ids there
                # itself, mirroring _handle_session_event's local buffering.
                state = session.network_input if session.network_input is not None else InputState()
            else:  # "gamepad"
                state = read_gamepad_input(session.joystick)
            state.requested_actions = tuple(session.pending_actions)
            session.pending_actions = []
            session.input = state

    def _player_refs(self):
        return [
            PlayerRef(session.player, session.player.get_hitbox(), session) for session in self.players.values()
        ]

    def _player_refs_by_floor(self):
        """Every session's PlayerRef, grouped by session.current_placed_room.
        floor -- assembly mode only (see _update_world/DungeonAssembly.update),
        since floor has no meaning in single-room mode. Two sessions on two
        different floors now genuinely happens (see PlayerSession.
        current_placed_room), so a room's animals/enemies must only ever see
        the players actually on that room's own floor, not every player
        regardless of where they are. Skips a session with no
        current_placed_room yet (shouldn't happen here -- only ever called
        from _update_world, never on a network client -- but matches
        _active_floors' own defensiveness rather than assuming it)."""
        grouped = {}
        for session in self.players.values():
            if session.current_placed_room is None:
                continue
            floor = session.current_placed_room.floor
            grouped.setdefault(floor, []).append(PlayerRef(session.player, session.player.get_hitbox(), session))
        return grouped

    def _apply_requested_actions(self, session):
        for action_id in session.input.requested_actions:
            self._trigger_action(session, action_id)

    @staticmethod
    def _direction_from_vector(direction):
        """8-way facing string (Player.direction's vocabulary) from a
        normalized movement vector -- extracted from _simulate_movement's
        per-frame animation-direction bookkeeping."""
        if direction.y > 0.5:
            if direction.x > 0.3:
                return "front_right"
            if direction.x < -0.3:
                return "front_left"
            return "front"

        if direction.y < -0.5:
            if direction.x > 0.3:
                return "back_right"
            if direction.x < -0.3:
                return "back_left"
            return "back"

        return "right" if direction.x > 0 else "left"

    def _update_footsteps(self, session, running, dt):
        """Footstep-audio cadence while actively moving -- suppressed
        mid-jump, same as the fall-check in _simulate_movement. Extracted
        from _simulate_movement's per-frame movement branch."""
        if session.player.action == "jump":
            return
        session.footstep_timer += dt
        interval = self.FOOTSTEP_INTERVAL_RUN if running else self.FOOTSTEP_INTERVAL_WALK
        if session.footstep_timer >= interval:
            session.footstep_timer = 0.0
            SoundManager().play(f"player_footstep_{session.footstep_alt + 1}")
            session.footstep_alt = 1 - session.footstep_alt

    def _resolve_movement_step(self, session, direction, running, dt, predicting=False, advance_animation=True, visible_mobs=None):
        """The collision-tested core of moving a player, shared by the real
        per-frame simulation (_simulate_movement, predicting=False) and Phase
        4's client-side prediction/replay (_predict_local_movement/
        _reconcile_local_player, predicting=True). `predicting=True` skips
        everything that must stay server-authoritative only -- room
        transitions, falling into the void, footstep audio -- so a
        speculative client-side replay never triggers a side effect the
        server hasn't actually confirmed yet; only position/facing/animation
        are ever computed speculatively. `_is_walkable`'s own wall/mob/
        other-player checks work unchanged under prediction, since the
        client's mirror world (static terrain loaded once at connect, plus
        mobs/other players kept in sync by apply_network_snapshot)
        already carries everything that check needs -- no duplicated
        collision logic between server tick and client prediction.

        `advance_animation=False` skips the final `player.update(dt)` call --
        used by _reconcile_local_player's replay, which can re-run the same
        buffered input several times (once per snapshot until the server
        acks it). Position replay is idempotent (each pass starts from a
        fresh authoritative baseline), but Player.update(dt) mutates a
        cumulative `animation_timer` that's never part of the snapshot and
        never reset between replay passes -- calling it more than once per
        real elapsed frame silently piles up extra animation time and was a
        real, visible bug (idle animation jumping/skipping frames). Real
        per-frame animation advancement only ever happens once, from
        _predict_local_movement's own (non-replayed) call.

        visible_mobs (see _is_walkable) is computed once here if not
        supplied, then shared by both the X and Y candidate move below
        instead of each _is_walkable call redoing its own room-wide mob
        scan -- callers running several of these steps back-to-back (the
        per-frame session loop in update(), or _reconcile_local_player's
        replay of buffered inputs) can pass one shared snapshot in to avoid
        repeating that scan per session/replay too."""
        player = session.player

        if visible_mobs is None:
            visible_mobs = self._visible_mobs_global()

        if direction.length_squared() > 0:

            direction = direction.normalize()

            speed = self.RUN_SPEED if running else self.MOVE_SPEED

            movement = (
                direction
                * speed
                * dt
            )

            # Void cells are traversable now (instead of a hard block) -- see
            # _is_walkable's per-corner void handling. A single consolidated
            # fall-check runs below (real simulation only), after both axes
            # and the door transition, rather than blocking movement at the
            # boundary of whatever room happens to own the active floor.
            future_hitbox = player.get_hitbox()
            future_hitbox.x += movement.x
            if self._is_walkable(future_hitbox, session, debug_label=None if predicting else "x",
                                  visible_mobs=visible_mobs):
                player.position.x += movement.x

            future_hitbox = player.get_hitbox()
            future_hitbox.y += movement.y
            if self._is_walkable(future_hitbox, session, debug_label=None if predicting else "y",
                                  visible_mobs=visible_mobs):
                player.position.y += movement.y

            if not predicting:
                if self.assembly is not None:
                    self._update_current_room(session)

                # Suppressed mid-jump so the player can actually clear a gap
                # by jumping over it instead of falling the instant their
                # feet pass over void while airborne -- the check resumes
                # the very next frame the one-shot jump animation ends
                # (Player.action reverts to None on its own), so landing on
                # void still falls normally.
                if player.action != "jump" and self._is_void(player.get_hitbox(), session.current_placed_room):
                    self._attempt_fall(session)

            player.direction = self._direction_from_vector(direction)

            if player.action is None:
                player.animation = "run" if running else "walk"

            if not predicting:
                self._update_footsteps(session, running, dt)

        else:

            if player.action is None:
                player.animation = "idle"

            if not predicting:
                session.footstep_timer = 0.0

        if advance_animation:
            player.update(dt)

    def _simulate_movement(self, session, dt, visible_mobs=None):
        self._resolve_movement_step(session, session.input.move_direction, session.input.running, dt,
                                     visible_mobs=visible_mobs)

    def _grant_xp(self, session, amount):
        """Awards XP earned from an already-authoritative event (enemy/animal
        kill, dungeon clear -- see call sites) and persists immediately via
        apply_to_fresh_profile (see its own docstring for why a fresh reload
        precedes the mutation+save -- a no-op for a session with no profile,
        local co-op's secondary device, or a network session that joined
        without a usable name). Saving right away rather than deferring to
        disconnect is deliberate: these are rare, discrete events, not a
        per-frame hot path, so there's no real cost to keeping the profile
        file always up to date."""
        apply_to_fresh_profile(session, lambda profile: profile.add_xp(amount))

    def _bank_found_cards(self, session):
        """Moves every card sitting in session.inventory.grid_slots (see
        core.world.inventory.Inventory.add_card/CardStub -- cards physically
        picked up this run) into the persisted Profile.card_stash, then
        empties grid_slots -- called only from _trigger_victory, once per
        session, the moment ANY session reaches the dungeon_exit (co-op is
        a shared win). Same apply_to_fresh_profile pattern as _grant_xp,
        for the exact same reason: a fresh reload before mutating avoids
        clobbering a card_stash/card_collection change Creator made
        mid-run. A no-op if grid_slots is empty or this session has no
        profile at all. Banking into card_stash, NOT card_collection --
        the player still has to manually drag each one into their
        permanent collection later, from core.editor.ui.stash_panel.
        StashPanelUI in the Home/Creator (see that panel's own docstring)."""
        gained = {stub.card_id: stub.count for stub in session.inventory.grid_slots if stub is not None}
        if not gained:
            return
        session.inventory.clear_cards()

        def _mutate(profile):
            for card_id, count in gained.items():
                profile.card_stash[card_id] = profile.card_stash.get(card_id, 0) + count

        apply_to_fresh_profile(session, _mutate)

    def _trigger_victory(self, session):
        """Sets self.victory (whole-session -- see its own field comment,
        co-op shares one win) and grants the triggering session's own
        XP_DUNGEON_CLEAR, same as before this existed -- plus banks EVERY
        connected session's own found cards (see _bank_found_cards), not
        just the triggering one's, since co-op is a shared win. A defeat
        (_game_over) never calls this, so cards found that run are simply
        never banked -- they vanish along with the rest of grid_slots on
        the next open_room/_enter_assembly reset, matching "garde
        l'inventaire en cas de victoire, le perd en cas de defaite."
        Shared by both dungeon_exit triggers (_check_dungeon_exit and
        _interact_with_chest's own chest branch)."""
        self.victory = True
        self._grant_xp(session, XP_DUNGEON_CLEAR)
        for other_session in self.players.values():
            self._bank_found_cards(other_session)

    def _resolve_player_attacks(self):
        """Every session's attack, checked against the same one
        _visible_mobs_global() snapshot (computed once, shared across
        sessions -- was already implicitly frame-shared with 1 player).
        Every mob takes the same take_damage(1) call -- a no-op for a
        non-combat-capable one (see Mob.take_damage), so there's no need
        to separately gate a PNJ/plain decorative mob out of this loop.
        self.pvp_enabled additionally checks every *other* session's hitbox
        -- off by default (see run()'s F4 toggle), since normal co-op play
        shouldn't have players accidentally hurting each other. Also checks
        the wall cell right in front of the attack hitbox (see
        Dungeon.destroy_wall_cell) -- a swing that breaks a wall still only
        counts as one hit for _hit_delivered_this_swing, same "once per
        swing" rule as hitting a mob."""
        mobs = self._visible_mobs_global()
        for session in self.players.values():
            player = session.player
            if not player.is_attack_active():
                continue
            attack_hitbox = player.get_attack_hitbox()
            hit_landed = False

            dungeon, offset_x, offset_y = self._current_room_and_offset(session)
            tile_size = dungeon.tile_size
            local_x = attack_hitbox.centerx - offset_x * tile_size
            local_y = attack_hitbox.centery - offset_y * tile_size
            grid_x, grid_y = dungeon.world_to_grid(local_x, local_y)
            broke, card_ids = dungeon.destroy_wall_cell(grid_x, grid_y)
            if broke:
                hit_landed = True
                # grid_to_world returns room-LOCAL coordinates, matching
                # what DestructionSpark itself stores as self.position --
                # room_offset (below) is what lets it compare that against
                # player.position (always GLOBAL) each frame it homes, see
                # DestructionSpark's own docstring.
                local_wall_x, local_wall_y = dungeon.grid_to_world(grid_x, grid_y)
                # player=player/dungeon=dungeon/card_ids=card_ids default
                # the closures' arguments at definition time -- without it,
                # every spark spawned across different iterations of this
                # loop would share the same late-bound values, ending up
                # all reading whichever session happened to be last once
                # this whole loop finishes (the classic Python
                # closure-in-a-loop pitfall).
                def _on_arrival(position, dungeon=dungeon, card_ids=card_ids):
                    _spawn_loot_pickups(dungeon, position, card_ids)

                dungeon.effect_manager.spawn_destruction_spark(
                    local_wall_x, local_wall_y,
                    lambda player=player: player.position,
                    room_offset=(offset_x * tile_size, offset_y * tile_size),
                    on_arrival=_on_arrival,
                )

            for mob, mob_rect, mob_dungeon in mobs:
                if attack_hitbox.colliderect(mob_rect):
                    was_alive = mob.alive
                    mob.take_damage(1)
                    hit_landed = True
                    if was_alive and not mob.alive:
                        if mob.combat_capable:
                            self._spawn_loot(mob, mob_dungeon)
                        if mob.aggro_capable:
                            self._grant_xp(session, XP_ENEMY_KILL)
                        else:
                            self._grant_xp(session, XP_ANIMAL_KILL)

            if self.pvp_enabled:
                for other_session in self.players.values():
                    if other_session is session:
                        continue
                    if attack_hitbox.colliderect(other_session.player.get_hitbox()):
                        other_session.player.take_damage(1)
                        hit_landed = True

            if hit_landed:
                player._hit_delivered_this_swing = True

    def _resolve_pickups(self):
        for session in self.players.values():
            self._collect_pickups(session.player.get_hitbox(), session.inventory)

    def _resolve_buttons_and_health(self):
        """Per-session button-trigger check plus the death check -- merged
        into one pass since neither depends on the other's order (unlike
        _resolve_player_attacks, which must fully finish for every session
        first, using one shared enemy/animal snapshot, before anything else
        reads pickups/health that frame). Returns True if a session's death
        ended the game (see _game_over) -- update() returns immediately when
        it does, same as before."""
        for session in self.players.values():
            grid_x, grid_y = self._feet_grid_cell(session.player.get_hitbox())
            if self.assembly is not None:
                self.assembly.check_button_trigger(
                    grid_x, grid_y, session.current_placed_room.floor, prefer_room=session.current_placed_room
                )
            else:
                self.dungeon.object_manager.check_button_trigger(grid_x, grid_y)

            if session.player.health <= 0:
                self._game_over("Le joueur est mort")
                return True
        return False

    def _local_sessions(self):
        """Sessions this machine actually drives (input_source_kind !=
        "network"), sorted by player_id so player 1/_local_player_id is
        always first -- and therefore always the left/first viewport in
        _viewport_rects, deterministic and consistent with the existing
        _spawn_offset_x convention. A networked client's self.players also
        holds one mirrored PlayerSession per REMOTE player (see
        apply_network_snapshot) -- those never get a viewport or a camera of
        their own; they're drawn (if in view) as ordinary entities inside
        whichever local viewport currently shows their room/floor, exactly
        like solo play already draws other live entities."""
        return sorted(
            (session for session in self.players.values() if session.input_source_kind != "network"),
            key=lambda session: session.player_id,
        )

    def _viewport_rects(self):
        """{player_id: pygame.Rect} for every local session, splitting
        self.screen into equal vertical (left-right) slices -- what each
        local session's viewport WOULD be under real split-screen. Only
        actually used to render/position things that way when _merged_view
        is False (see render()) -- callers that need "the rect(s) sessions
        are currently viewing" while merge could be active should go
        through render()'s own panel_rects instead of this directly."""
        sessions = self._local_sessions()
        width = self.screen.get_width()
        height = self.screen.get_height()
        count = max(1, len(sessions))
        slice_width = width // count

        rects = {}
        for index, session in enumerate(sessions):
            left = index * slice_width
            # Last slice absorbs the rounding remainder so the rects always
            # exactly tile the full screen width.
            this_width = width - left if index == count - 1 else slice_width
            rects[session.player_id] = pygame.Rect(left, 0, this_width, height)
        return rects

    def _merged_view(self):
        """True when every local session should share ONE camera/viewport
        (self.camera) instead of real split-screen: solo, single-room mode
        (only one room ever exists there, so "same room" is trivially
        always true), or 2+ local co-op sessions all currently in the exact
        same room of an assembly. Flips to real split-screen the instant one
        of them crosses into a different room -- a "merge screen" that
        cancels the per-player camera and falls back to the shared one
        whenever they're back together, per the user's explicit request
        (real split-screen alone, unconditionally, was judged too
        disorienting to stay on permanently once players regroup)."""
        local_sessions = self._local_sessions()
        if len(local_sessions) <= 1 or self.assembly is None:
            return True
        rooms = {session.current_placed_room for session in local_sessions}
        return len(rooms) == 1

    CAMERA_FIT_PADDING_TILES = 4  # margin kept around every player's bounding box when the merged camera is zoomed to fit

    # Convergence rate (per second) for the merged camera's zoom-to-fit AND
    # its center point -- see _update_shared_camera's own note on why both
    # are smoothed rather than snapped. Both the target fit-zoom and the
    # players' midpoint shift continuously as they move relative to each
    # other, and applying either directly every single frame made the
    # shared camera visibly judder in ordinary play (reported as "laggy"/
    # "sautillante" on the shared/merged camera) instead of reading as one
    # deliberate camera move. Higher = snappier/less smoothing; tuned to
    # still feel responsive within well under a second, not a slow drift.
    CAMERA_SMOOTHING_RATE = 8.0

    def _smoothed_zoom_toward(self, target_zoom, dt):
        """Exponential ease of self.camera.zoom toward target_zoom, frame-
        rate independent (uses dt rather than a fixed per-frame step, so
        this converges at the same real-world speed regardless of the
        current framerate -- see CAMERA_SMOOTHING_RATE). dt <= 0 (a
        degenerate/first frame) snaps directly rather than risking a
        divide-by-zero-flavored no-op."""
        if dt <= 0:
            return target_zoom
        blend = 1.0 - math.exp(-self.CAMERA_SMOOTHING_RATE * dt)
        return self.camera.zoom + (target_zoom - self.camera.zoom) * blend

    def _smoothed_center_toward(self, target_x, target_y, dt):
        """Same exponential ease as _smoothed_zoom_toward, applied to the
        merged camera's center point instead of its zoom -- the players'
        midpoint shifts continuously as they move relative to each other,
        and _update_shared_camera used to center_on() it directly every
        frame, which juddered the same way the zoom did before it got this
        same treatment (see CAMERA_SMOOTHING_RATE's own note). Lazily
        seeded from the very first target it's ever given (self.
        _shared_camera_center starts None) so the first frame two players
        share a room doesn't visibly slide in from some arbitrary prior
        point -- and dt <= 0 re-seeds the same way, for the same reason
        _smoothed_zoom_toward snaps outright rather than risking a
        divide-by-zero-flavored no-op."""
        if self._shared_camera_center is None or dt <= 0:
            self._shared_camera_center = (target_x, target_y)
            return self._shared_camera_center
        blend = 1.0 - math.exp(-self.CAMERA_SMOOTHING_RATE * dt)
        cx, cy = self._shared_camera_center
        self._shared_camera_center = (cx + (target_x - cx) * blend, cy + (target_y - cy) * blend)
        return self._shared_camera_center

    def _update_shared_camera(self, positions, dt):
        """Zoom-to-fit self.camera across `positions` (1 or more world
        points) -- the merged view's camera. A single position is a plain
        follow (zoom untouched, manual mouse-wheel zoom fully respected,
        byte-for-byte solo behavior); 2+ positions derive a TARGET center
        (their midpoint) and a TARGET zoom (from their bounding box +
        padding, so nobody goes off-screen, clamped to the camera's own
        min/max), both eased toward rather than snapped (see
        _smoothed_zoom_toward/_smoothed_center_toward) -- this *overrides*
        manual zoom for as long as the merge is active. This is the
        original Phase 2 zoom-to-fit camera, now used only while
        _merged_view is True instead of unconditionally."""
        if not positions:
            return

        if len(positions) == 1:
            pos = positions[0]
            self.camera.center_on(pos.x, pos.y, self.screen.get_width(), self.screen.get_height())
            return

        min_x = min(pos.x for pos in positions)
        max_x = max(pos.x for pos in positions)
        min_y = min(pos.y for pos in positions)
        max_y = max(pos.y for pos in positions)
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2

        padding = self.CAMERA_FIT_PADDING_TILES * Dungeon.TILE_SIZE
        span_x = max(max_x - min_x + padding * 2, 1)
        span_y = max(max_y - min_y + padding * 2, 1)

        zoom_x = self.screen.get_width() / span_x
        zoom_y = self.screen.get_height() / span_y
        target_zoom = max(self.camera.min_zoom, min(self.camera.max_zoom, min(zoom_x, zoom_y)))
        self.camera.zoom = self._smoothed_zoom_toward(target_zoom, dt)
        smoothed_x, smoothed_y = self._smoothed_center_toward(center_x, center_y, dt)
        self.camera.center_on(smoothed_x, smoothed_y, self.screen.get_width(), self.screen.get_height())

    def _update_camera(self, dt):
        """Merged (self.camera, zoom-to-fit) or real split-screen (each
        local session's own camera, simple follow) depending on
        _merged_view -- see both for details."""
        local_sessions = self._local_sessions()

        if self._merged_view():
            self._update_shared_camera([session.player.position for session in local_sessions], dt)
            return

        viewport_rects = self._viewport_rects()
        for session in local_sessions:
            rect = viewport_rects[session.player_id]
            session.camera.center_on(session.player.position.x, session.player.position.y, rect.width, rect.height)

    # ------------------------------------------------------
    # Networking (Phase 3) -- server-side: bringing a connected client's
    # session into self.players (see core/network/server.py, which owns an
    # Explorator exactly like this one, minus rendering).
    # ------------------------------------------------------

    def _spawn_new_session_at_start(self, session):
        """Positions a brand-new session (not yet part of the world) at the
        world's own spawn point/room -- shared by add_network_session (a
        client just connected) and _maybe_join_secondary_keyboard_player (a
        second local device just started being used), which both need
        exactly this "place a session that's joining after the fact, not at
        open_room/open_donjon load time" treatment, including setting
        session.current_placed_room (without it, this session's own render
        viewport would have no floor to render -- see render/_render_viewport)."""
        if self.assembly is not None:
            room = self.current_placed_room
            spawn_local = room.dungeon.get_spawn_world_position() or (
                room.dungeon.tile_size, room.dungeon.tile_size
            )
            tile_size = room.dungeon.tile_size
            session.player.position.update(
                room.offset_x * tile_size + spawn_local[0] + self._spawn_offset_x(session, tile_size),
                room.offset_y * tile_size + spawn_local[1],
            )
            session.current_placed_room = room
        else:
            self._position_player_at_spawn(session)

    def _handle_shared_debug_event(self, event):
        """QUIT/mouse-wheel-zoom/F3 toggle -- byte-for-byte identical in
        run() and run_networked(), so both share this one implementation
        instead of two copies. Returns "stop" if this event means the
        caller's own `while running` loop should end (QUIT only), "handled"
        if it was consumed but the loop continues, or None if `event` isn't
        one of these and the caller should keep checking its own event
        chain."""
        if event.type == pygame.QUIT:
            self.game_manager.running = False
            return "stop"

        if event.type == pygame.MOUSEWHEEL:
            # The mouse is only ever used by the primary local player
            # (attack/interact bindings, the secondary local co-op scheme
            # has no mouse). Which camera that actually zooms depends on
            # which one render() is currently using for the view the mouse
            # is over: self.camera (merged -- solo, or 2+ local co-op still
            # in the same room) or that session's own camera (real
            # split-screen, once merge is off) -- converting the
            # window-space mouse position into that view's own local
            # coordinates either way (matters once split-screen puts a
            # viewport somewhere other than the screen's own top-left).
            mouse_x, mouse_y = pygame.mouse.get_pos()
            if self._merged_view():
                self.camera.zoom_at(mouse_x, mouse_y, event.y, self.screen.get_width(), self.screen.get_height())
            else:
                local_session = self.players.get(self._local_player_id)
                rect = self._viewport_rects().get(self._local_player_id) if local_session is not None else None
                if rect is not None:
                    local_session.camera.zoom_at(mouse_x - rect.x, mouse_y - rect.y, event.y, rect.width, rect.height)
            return "handled"

        if event.type == pygame.KEYDOWN and event.key == pygame.K_F3:
            self.debug_mode = not self.debug_mode
            self._last_debug_message = None
            print(f"[debug] debug mode {'ON' if self.debug_mode else 'OFF'} (grid + hitboxes)")
            return "handled"

        return None

    def update(self, dt):

        self._read_input()

        if self.victory:
            # Player input is frozen (no movement/combat), but the room
            # itself keeps updating so the chest's own opening animation
            # actually finishes playing instead of freezing mid-swing. Whole
            # session, not per-player -- victory is a session-wide win
            # condition, unlike a single player's own inventory below.
            for session in self.players.values():
                session.update_frozen(dt)
            self._update_world(dt, self._player_refs())
            return

        # Per-player freeze: a session with its own inventory open, or
        # already waiting at a dungeon_entrance for the rest of the party
        # (see _check_dungeon_entrance's sync barrier), only pauses itself
        # (idle animation ticking) -- everyone else (other sessions,
        # animals/enemies/the world) keeps going.
        #
        # One shared visible-mob snapshot for the whole loop below (see
        # _resolve_movement_step) instead of every session's own X/Y move
        # recomputing the same room-wide scan. A session crossing a door
        # mid-loop (_update_current_room) can technically add a floor to
        # the active set after this snapshot was taken, so a session
        # processed later in the same frame could miss one frame's worth of
        # collision against whatever's on that newly-entered floor --
        # accepted the same way _resolve_player_attacks below already
        # shares one frame-stale snapshot across every session's attack.
        # Self-corrects the very next frame either way.
        visible_mobs = self._visible_mobs_global()
        for session in self.players.values():
            if session.inventory_open:
                session.update_frozen(dt)
                session.inventory_panel.update(dt)
                continue
            if session.player_id in self.dungeon_entrance_ready:
                # Any movement input backs a waiting player out of the
                # barrier on their own (see _cancel_dungeon_entrance_wait)
                # instead of leaving them with no way back -- falls
                # straight through to normal movement this same frame
                # rather than waiting an extra one, so backing out feels
                # immediate.
                if session.input.move_direction.length_squared() > 0:
                    self._cancel_dungeon_entrance_wait(session)
                else:
                    session.update_frozen(dt)
                    continue
            self._apply_requested_actions(session)
            self._simulate_movement(session, dt, visible_mobs=visible_mobs)

        self._resolve_dungeon_transitions()

        # -----------------------------
        # Combat -- joueurs attaquent un ennemi
        # -----------------------------

        self._resolve_player_attacks()

        # -----------------------------
        # Ramassage des pièces au sol
        # -----------------------------

        self._resolve_pickups()

        # -----------------------------
        # Monde (objets/animaux/ennemis/projectiles) + boutons / portes
        # -----------------------------

        self._update_world(dt, self._player_refs())
        if self._resolve_buttons_and_health():
            return

        # -----------------------------
        # Camera suit le joueur
        # -----------------------------

        self._update_camera(dt)

    # ------------------------------------------------------

    def render(self):

        self.screen.fill((20, 20, 20))

        local_sessions = self._local_sessions()
        merged = self._merged_view()

        if merged:
            room = local_sessions[0].current_placed_room if local_sessions and self.assembly is not None else None
            self._render_viewport(self.screen, self.camera, room)
            panel_rects = {session.player_id: self.screen.get_rect() for session in local_sessions}
        else:
            viewport_rects = self._viewport_rects()
            for session in local_sessions:
                rect = viewport_rects[session.player_id]
                self._render_viewport(self.screen.subsurface(rect), session.camera, session.current_placed_room)
            panel_rects = viewport_rects

        if self.debug_mode:
            self._draw_debug_hitboxes()

        self._render_inventory_panels(panel_rects)

        if self.victory:
            self._draw_victory_banner()

        self._render_dungeon_entrance_barrier()

        self._render_chat()

        self.multiplayer_panel.update(self.game_manager.network_client is not None)
        self.multiplayer_panel.render(self.screen, self)

        if self.game_manager.settings_panel.is_open:
            self.game_manager.settings_panel.render(self.screen)

        pygame.display.flip()

    def _render_dungeon_entrance_barrier(self):
        """A small top-center banner while the dungeon-entry sync barrier
        (_check_dungeon_entrance) is active -- at least one player has
        crossed home's dungeon_entrance but not everyone currently
        connected has yet. Never shows in solo play: with exactly one
        session, the barrier always completes the same frame it's first
        crossed, so self.dungeon_entrance_ready never holds at a
        partial/nonzero-but-incomplete state long enough to render."""
        ready_count = len(self.dungeon_entrance_ready)
        total = len(self.players)
        if ready_count == 0 or ready_count >= total:
            return

        if self._chat_font is None:
            self._chat_font = pygame.font.SysFont("arial", 16)
        text = f"En attente des autres joueurs : {ready_count}/{total} prets"
        surface = self._chat_font.render(text, True, (255, 255, 255))
        x = self.screen.get_width() / 2 - surface.get_width() / 2
        y = 16
        backing = pygame.Surface((surface.get_width() + 16, surface.get_height() + 10), pygame.SRCALPHA)
        backing.fill((0, 0, 0, 160))
        self.screen.blit(backing, (x - 8, y - 5))
        self.screen.blit(surface, (x, y))

    def _render_chat(self):
        """A simple Minecraft-style scrollback overlay in the bottom-left
        corner -- last CHAT_VISIBLE_LINES messages, plus a live input line
        while chat_open. Deliberately not a new widget class (unlike
        InventoryPanel) -- just a handful of left-aligned text lines over a
        translucent backing strip, simple enough not to earn one. No-op
        with an empty log and the box closed (the common case in solo
        play, which never opens or receives chat at all)."""
        if not self.chat_log and not self.chat_open:
            return
        if self._chat_font is None:
            self._chat_font = pygame.font.SysFont("arial", 16)
        font = self._chat_font

        x = 12
        y = self.screen.get_height() - (34 if not self.chat_open else 56)

        for entry in reversed(self.chat_log[-self.CHAT_VISIBLE_LINES:]):
            if entry["system"]:
                text, color = entry["text"], (255, 210, 90)
            else:
                text, color = f"{entry['name']}: {entry['text']}", (255, 255, 255)
            surface = font.render(text, True, color)
            backing = pygame.Surface((surface.get_width() + 8, surface.get_height() + 4), pygame.SRCALPHA)
            backing.fill((0, 0, 0, 140))
            self.screen.blit(backing, (x - 4, y - 2))
            self.screen.blit(surface, (x, y))
            y -= surface.get_height() + 4

        if self.chat_open:
            cursor = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else ""
            surface = font.render("> " + self.chat_input + cursor, True, (255, 255, 255))
            input_y = self.screen.get_height() - 30
            backing = pygame.Surface((surface.get_width() + 8, surface.get_height() + 4), pygame.SRCALPHA)
            backing.fill((0, 0, 0, 180))
            self.screen.blit(backing, (x - 4, input_y - 2))
            self.screen.blit(surface, (x, input_y))

    def _render_inventory_panels(self, panel_rects):
        """Each open panel renders within its own player's viewport rect
        (panel_rects, from render() -- the whole screen when merged, that
        session's own split-screen viewport otherwise). Panels that happen
        to share the exact same rect (any number of players sharing one
        merged view) subdivide it between themselves instead of exactly
        overlapping -- the same "N panels open at once" case Phase 2
        already had to handle, just keyed off whichever rect a session's
        viewport actually is this frame instead of always the whole screen."""
        open_sessions = [session for session in self.players.values() if session.inventory_open]
        groups = {}
        for session in open_sessions:
            rect = panel_rects.get(session.player_id)
            key = (rect.x, rect.y, rect.width, rect.height) if rect is not None else None
            groups.setdefault(key, []).append(session)

        for key, sessions_in_group in groups.items():
            if key is None:
                # No viewport of its own (a "network"-kind session -- can't
                # happen locally, only relevant if this were ever a server,
                # which never renders at all).
                for session in sessions_in_group:
                    session.inventory_panel.render(self.screen, session.player, region=None)
                continue

            rect = panel_rects[sessions_in_group[0].player_id]
            count = len(sessions_in_group)
            slice_width = rect.width / count
            for index, session in enumerate(sessions_in_group):
                region = (rect.left + index * slice_width, slice_width)
                session.inventory_panel.render(self.screen, session.player, region=region)

    def _render_viewport(self, target, camera, room):
        """Draws the world into `target` (either the whole screen, when
        merged, or one local session's own split-screen subsurface) using
        `camera`, scoped to `room`'s floor (None in single-room mode).
        Shared by both the merged path (one call: target=self.screen,
        camera=self.camera, room=whichever room the merged sessions all
        share) and the real split-screen path (one call per local session:
        target=that session's own subsurface, camera/room=that session's
        own) -- neither needs to know which specific session is "looking,"
        only which room/floor and camera to render with. Any player whose
        own current_placed_room is on this same floor is drawn too, same as
        normal co-presence in a shared room already worked before real
        split-screen existed -- a network mirror with no current_placed_room
        of its own (the client never tracks which room/floor a remote
        player is actually on, see apply_network_snapshot) is drawn
        regardless of floor, same simplification as before this phase."""
        if self.assembly is not None:
            floor = room.floor
            players_on_floor = [
                other.player for other in self.players.values()
                if other.player_id not in self.dungeon_entrance_ready
                and (other.current_placed_room is None or other.current_placed_room.floor == floor)
            ]
            # Wherever the camera is actually centered, in world space --
            # the vision-hole punch-out on floors above should always be
            # centered on what's actually in view, whether that's a single
            # player's own follow or the merged view's zoom-to-fit midpoint.
            center_world = camera.screen_to_world(target.get_width() / 2, target.get_height() / 2)

            self.assembly.render(
                target, camera,
                active_floor=floor,
                player_world_pos=center_world,
                hide_object_types=hidden_object_types(),
                skip_active_floor_foreground=True,
                skip_active_floor_mobs=True,
                show_grid=self.debug_mode,
            )

            self.assembly.render_active_floor_entities(target, camera, floor, players_on_floor)

            self.assembly.render_active_floor_foreground(
                target, camera, floor, hide_object_types=hidden_object_types(),
            )

        else:

            self.dungeon.render(
                target, camera,
                hide_object_types=hidden_object_types(),
                skip_foreground_objects=True,
                skip_mobs=True,
                show_grid=self.debug_mode,
            )

            entities = (
                list(self.dungeon.mob_manager.mobs)
                + [
                    other.player for other in self.players.values()
                    if other.player_id not in self.dungeon_entrance_ready
                ]
            )
            entities.sort(key=lambda entity: entity.position.y)
            for entity in entities:
                entity.draw(target, camera)

            self.dungeon.render_foreground(target, camera, hide_object_types=hidden_object_types())

    def _draw_victory_banner(self):
        """The only win condition that exists right now (see
        _interact_with_chest) -- a plain centered text overlay, no dedicated
        art. Drawn every frame the flag stays set; ESC still returns to the
        menu normally, same as any other time in Exploration."""
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        self.screen.blit(overlay, (0, 0))

        font = pygame.font.SysFont("arial", 64)
        text = font.render("VICTOIRE !", True, (255, 220, 90))
        rect = text.get_rect(center=(self.screen.get_width() / 2, self.screen.get_height() / 2))
        self.screen.blit(text, rect)

    DEBUG_VOID_RADIUS_TILES = 3

    def _draw_debug_hitboxes(self):
        """F3 overlay, once per view (see render()'s own merged/split
        branching -- one shared view when merged, one per local session's
        own viewport otherwise): every hitbox in red (plus its attack reach
        in orange while actually active) for every player on THAT view's
        own floor, a non-aggro_capable mob in yellow, an aggro_capable one
        in purple (plus each attacking one's own melee reach in magenta,
        same idea as a player's orange one) -- all already in the exact world coordinates
        _is_walkable/combat compare, so any gap between "what looks like
        it's touching" and "what's actually colliding" is directly visible
        instead of guessed. Also outlines every cell _is_void_at considers
        void (cyan) within a few tiles of each viewing session's own player."""
        local_sessions = self._local_sessions()

        if self._merged_view():
            room = local_sessions[0].current_placed_room if local_sessions and self.assembly is not None else None
            self._draw_debug_hitboxes_for_view(self.screen, self.camera, room, local_sessions)
            return

        viewport_rects = self._viewport_rects()
        for session in local_sessions:
            rect = viewport_rects[session.player_id]
            target = self.screen.subsurface(rect)
            self._draw_debug_hitboxes_for_view(target, session.camera, session.current_placed_room, [session])

    def _draw_debug_hitboxes_for_view(self, target, camera, room, viewer_sessions):
        floor = room.floor if self.assembly is not None else None

        for viewer in viewer_sessions:
            self._draw_debug_void_grid(target, camera, viewer)

        for other_session in self.players.values():
            other_floor = (
                other_session.current_placed_room.floor
                if self.assembly is not None and other_session.current_placed_room is not None
                else floor
            )
            if other_floor != floor:
                continue
            player = other_session.player
            self._draw_debug_rect(target, camera, player.get_hitbox(), (255, 60, 60))
            if player.is_attack_active():
                self._draw_debug_rect(target, camera, player.get_attack_hitbox(), (255, 150, 30))

        floors = {floor}
        for dungeon, offset_x, offset_y in self._rooms_with_offset(floors):
            for mob in dungeon.mob_manager.mobs:
                if not mob.alive:
                    continue
                mob_rect = mob.get_hitbox().move(offset_x, offset_y)
                self._draw_debug_rect(target, camera, mob_rect, (200, 60, 255) if mob.aggro_capable else (255, 220, 60))
                if mob.aggro_capable and mob.state == "attack":
                    # get_attack_hitbox() is local to the mob's own room's
                    # Dungeon (same convention as get_hitbox()) -- mob_rect
                    # is that same body hitbox already shifted to
                    # global/world coordinates, so re-using the delta
                    # between the two gets the attack hitbox into global
                    # coordinates too, without needing this method to know
                    # the room's offset directly.
                    local_hitbox = mob.get_hitbox()
                    offset = (mob_rect.x - local_hitbox.x, mob_rect.y - local_hitbox.y)
                    self._draw_debug_rect(target, camera, mob.get_attack_hitbox().move(offset), (255, 60, 220))

    def _draw_debug_void_grid(self, target, camera, session):
        """Centered on `session`'s own player -- called once per local
        viewport now (see _draw_debug_hitboxes), each showing its own
        player's local void-grid instead of only ever the primary local
        player's (Phase 1 notes, superseded by real split-screen)."""
        hitbox = session.player.get_hitbox()
        center_grid_x, center_grid_y = self._feet_grid_cell(hitbox)
        tile_size = Dungeon.TILE_SIZE
        radius = self.DEBUG_VOID_RADIUS_TILES

        for grid_y in range(center_grid_y - radius, center_grid_y + radius + 1):
            for grid_x in range(center_grid_x - radius, center_grid_x + radius + 1):
                if self._is_void_at(grid_x, grid_y, session.current_placed_room):
                    world_rect = pygame.Rect(grid_x * tile_size, grid_y * tile_size, tile_size, tile_size)
                    self._draw_debug_rect(target, camera, world_rect, (60, 220, 220))

    def _draw_debug_rect(self, target, camera, world_rect, color):
        top_left = camera.world_to_screen(world_rect.left, world_rect.top)
        bottom_right = camera.world_to_screen(world_rect.right, world_rect.bottom)
        screen_rect = pygame.Rect(
            int(top_left[0]), int(top_left[1]),
            int(bottom_right[0] - top_left[0]), int(bottom_right[1] - top_left[1]),
        )
        pygame.draw.rect(target, color, screen_rect, 2)

    # ------------------------------------------------------

    def _session_matches_action(self, session, action_id, event):
        """Dispatches to whichever device `session` is driven from -- see
        core/engine/input.py for the actual per-device matching logic."""
        if session.input_source_kind == "keyboard":
            return self.settings.matches_event(action_id, event)
        if session.input_source_kind == "secondary_keyboard":
            return secondary_keyboard_matches_event(action_id, event)
        return gamepad_matches_event(session.joystick, action_id, event)  # "gamepad"

    def _maybe_join_secondary_keyboard_player(self, event):
        """Drop-in join: the second keyboard scheme has no dedicated "press
        start" -- player 2 simply comes into existence the first time any of
        its own keys is pressed, as long as no gamepad-driven session
        already owns player_id 1 (a real controller always wins the slot;
        this exists purely as a same-machine fallback for testing without
        one). Solo keyboard play is unaffected until this actually fires."""
        if 1 in self.players or event.type != pygame.KEYDOWN:
            return
        if event.key in SECONDARY_KEYBOARD_BINDINGS.values():
            session = PlayerSession(1, "secondary_keyboard")
            self.players[1] = session
            self._spawn_new_session_at_start(session)

    def _handle_session_event(self, session, event):
        """Per-session one-shot action handling: this session's own
        "inventory" binding toggles its own panel (and swallows the rest of
        this event for this session -- see below); while that session's
        panel is open, no further action of *its own* gets buffered (other
        sessions still process this same event independently, since this is
        called once per session, not globally)."""
        if self._session_matches_action(session, "inventory", event):
            session.inventory_open = not session.inventory_open
            return

        if session.inventory_open:
            return

        for action_id in self.ONE_SHOT_ACTIONS:
            if self._session_matches_action(session, action_id, event):
                session.pending_actions.append(action_id)

    def run(self):

        pygame.display.set_caption(
            "Dungeon Architect - Exploration"
        )

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
                    # Fully modal, same treatment as Creator's chest/role/
                    # autotile_theme panels -- a pure local-settings
                    # overlay (no server round-trip needed, unlike victory),
                    # so this works identically whether this Explorator is
                    # solo, hosting, or -- see run_networked's own copy of
                    # this same check -- a network client.
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
                        if result == "connected":
                            running = False  # let GameManager's dispatch route into run_networked
                        continue
                    continue  # swallow everything else (movement, TAB...) while open

                local_session = self.players[self._local_player_id]
                if (
                    local_session.inventory_open
                    and event.type == pygame.MOUSEBUTTONDOWN
                    and local_session.inventory_panel.handle_click(self.screen, event.pos)
                ):
                    self.game_manager.settings_panel.open()
                    continue

                if self.victory and event.type == pygame.MOUSEBUTTONDOWN:
                    # Solo/local co-op IS the authoritative simulation
                    # itself, so this can just act directly -- see
                    # run_networked's own version, which has to ask the
                    # server instead (victory/the world reset it triggers
                    # are shared, whole-session state).
                    self._return_to_home()
                    continue

                if event.type == pygame.KEYDOWN and event.key == pygame.K_m:
                    if self._is_home_room():
                        self.multiplayer_panel.open()
                    continue

                if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
                    self.game_manager.state = GameState.CREATOR
                    running = False
                    continue

                if event.type == pygame.KEYDOWN and event.key == pygame.K_F4:
                    self.pvp_enabled = not self.pvp_enabled
                    print(f"[debug] PvP {'ON' if self.pvp_enabled else 'OFF'} (players can damage each other)")
                    continue

                # ESC is a physical-keyboard-only gesture -- scoped to player
                # 1's own session (closes just their inventory if open, else
                # quits to menu), same as before player 2 existed. Player 2's
                # device (gamepad/second keyboard scheme) has no equivalent
                # key; its own "inventory" binding is its only close gesture
                # (a second press of an already-open toggle).
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    local_session = self.players[self._local_player_id]
                    if local_session.inventory_open:
                        local_session.inventory_open = False
                    else:
                        self.game_manager.state = GameState.MENU
                        running = False
                    continue

                self._maybe_join_secondary_keyboard_player(event)

                for session in self.players.values():
                    self._handle_session_event(session, event)

            self.update(dt)
            self._check_home_zoom_switch()

            # Only _game_over()/_check_home_zoom_switch() can change
            # game_manager.state during update() -- same clean exit
            # TAB/ECHAP already do (no stale frame rendered into a state
            # we're about to leave).
            if self.game_manager.state != GameState.EXPLORATION:
                break

            self.render()