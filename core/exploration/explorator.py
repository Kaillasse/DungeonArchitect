# Contient toute la logique du game state Exploration

from __future__ import annotations

import random

import pygame
from core.world.dungeon import Dungeon, corner_cells
from core.world.assembly import load_assembly
from core.data.ressources import ROOMS_DIRECTORY
from core.world.entities import Player, PlayerRef, Animal, Enemy, Pickup, ItemPickup, ThrownDynamite, Explosion
from core.world.object_manager import ANIMAL_TYPES, ENEMY_TYPES, ENEMY_STATS, ITEM_DEFINITIONS, make_item, OBJECT_TYPES
from core.exploration.player_session import PlayerSession
from core.engine.input import (
    InputState, read_local_keyboard_input,
    read_secondary_keyboard_input, secondary_keyboard_matches_event, SECONDARY_KEYBOARD_BINDINGS,
    read_gamepad_input, gamepad_matches_event,
)
from core.engine.gamestate import GameState
from core.engine.camera import Camera
from core.data.sound_manager import SoundManager
from core.data.profile_manager import Profile, ProfileManager
from core.data.progression import XP_ENEMY_KILL, XP_ANIMAL_KILL, XP_DUNGEON_CLEAR
from core.network import protocol

# Placed objects that are only ever markers during exploration -- a spawn
# point and each animal's/enemy's placement cell -- and get replaced by a
# live entity (the Player, an AnimalManager-owned Animal, an
# EnemyManager-owned Enemy) instead of being drawn as a static object sprite.
HIDDEN_OBJECT_TYPES = {"spawn", *ANIMAL_TYPES, *ENEMY_TYPES}

class Explorator:

    MOVE_SPEED = 180  # pixels/seconde
    RUN_SPEED = 260  # pixels/seconde -- held with SHIFT

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

        self.grid_offset_x = 0
        self.grid_offset_y = 0
        self.grid_zoom = 1

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

        self.clock = pygame.time.Clock()

        # Networking (Phase 3+4), client-side only -- see
        # apply_network_snapshot/_smooth_network_entities. Initialized here
        # (not lazily) so a client's very first render, before any snapshot
        # has arrived, has an empty-but-real dict to iterate rather than
        # needing an AttributeError guard.
        self._network_mirrors = {}  # room_ref -> {"animals": {...}, ...}
        self._network_targets = {}  # id(entity) -> (entity, target_x, target_y)

    def open_room(self, name):
        """Load a specific room (chosen from the menu) and spawn every current
        session's player in it."""
        self.assembly = None
        self.current_placed_room = None
        self.dungeon.load_from_json(name)
        self.dungeon.spawn_animals()
        self.dungeon.spawn_enemies()
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
        # Same reasoning for victory (see _interact_with_chest) -- otherwise
        # re-entering exploration would start right back on the frozen
        # victory screen from last time.
        self.victory = False

    def open_donjon(self, name):
        """Load a saved procedurally-assembled dungeon and spawn every
        current session's player in its starting room."""
        self.assembly = load_assembly(name)
        self.victory = False

        for room in self.assembly.rooms:
            room.dungeon.spawn_animals()
            room.dungeon.spawn_enemies()

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
        _visible_animals_global -> here)."""
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
        _visible_animals_global/_visible_enemies_global/_collect_pickups,
        which otherwise each re-derive this identically."""
        if self.assembly is not None:
            tile_size = Dungeon.TILE_SIZE
            for floor in floors:
                for room in self.assembly.rooms_on_floor(floor):
                    yield room.dungeon, room.offset_x * tile_size, room.offset_y * tile_size
        else:
            yield self.dungeon, 0, 0

    def _visible_animals_global(self):
        """(animal, hitbox) pairs for every animal that could plausibly
        collide with a player right now, hitbox already in global/world
        coordinates."""
        pairs = []
        for dungeon, offset_x, offset_y in self._rooms_with_offset(self._active_floors()):
            for animal in dungeon.animal_manager.animals:
                pairs.append((animal, animal.get_hitbox().move(offset_x, offset_y)))
        return pairs

    def _visible_enemies_global(self):
        """Same idea as _visible_animals_global, but for live (alive) Enemy
        entities -- a corpse doesn't block a player, mirroring
        EnemyManager._is_free's own "other.alive" check for enemy-vs-enemy.
        Yields (enemy, hitbox, dungeon) rather than just (enemy, hitbox) --
        the third element is whichever room's own Dungeon actually owns this
        enemy, needed by the combat code below to drop loot into the right
        room's PickupManager rather than always self.dungeon (wrong in
        assembly mode for any enemy outside whichever room the attacking
        session itself is currently in)."""
        triples = []
        for dungeon, offset_x, offset_y in self._rooms_with_offset(self._active_floors()):
            for enemy in dungeon.enemy_manager.enemies:
                if enemy.alive:
                    triples.append((enemy, enemy.get_hitbox().move(offset_x, offset_y), dungeon))
        return triples

    @staticmethod
    def _spawn_loot(enemy, enemy_dungeon):
        """Drops ENEMY_STATS[enemy.enemy_type]["loot"] as individual coin
        Pickups (2 gold + 1 blue -> 3 separate coins, not one "x2" stack) and
        ["item_loot"] as individual ItemPickups (e.g. dynamite), scattered a
        few pixels around the death spot. enemy.position is already local to
        enemy_dungeon (never offset-translated -- see Animal/Enemy's own
        coordinate convention), so no conversion is needed before handing it
        to that same dungeon's PickupManager."""
        stats = ENEMY_STATS[enemy.enemy_type]

        for currency_type, count in stats.get("loot", {}).items():
            for _ in range(count):
                enemy_dungeon.pickup_manager.spawn(
                    currency_type,
                    enemy.position.x + random.uniform(-10, 10),
                    enemy.position.y + random.uniform(-10, 10),
                )

        for item_id, count in stats.get("item_loot", {}).items():
            for _ in range(count):
                enemy_dungeon.pickup_manager.spawn_item(
                    make_item(item_id),
                    ITEM_DEFINITIONS[item_id]["slot"],
                    enemy.position.x + random.uniform(-10, 10),
                    enemy.position.y + random.uniform(-10, 10),
                )

    def _collect_pickups(self, player_hitbox, inventory):
        """Credits inventory.currency for every ground Pickup player_hitbox
        touches this frame, across whichever room(s) that's meaningful for --
        same per-floor scope as _visible_animals_global. `inventory` is the
        calling session's own Inventory (see _resolve_pickups), not a shared
        singleton."""
        for dungeon, offset_x, offset_y in self._rooms_with_offset(self._active_floors()):
            local_hitbox = player_hitbox.move(-offset_x, -offset_y)
            dungeon.pickup_manager.collect(local_hitbox, inventory)

    def _trigger_action(self, session, action_id):
        """Fires action_id's one-shot behavior for `session` -- normally just
        Player.play_action, but "interact" is intercepted first for a chest
        the player is facing (see _interact_with_chest), then for a
        throwable item equipped in the interact slot (see
        _throw_interact_item), either of which repurposes the interact input
        instead of just playing the plain interact animation. A facing chest
        wins over a held item -- interacting with the world takes priority
        over the player's own inventory."""
        if action_id == "interact" and (self._interact_with_chest(session) or self._throw_interact_item(session)):
            return
        session.player.play_action(action_id)

    def _current_room_and_offset(self, session):
        """(dungeon, offset_x, offset_y) for session's own current room --
        offset is (0, 0) in single-room mode. Shared by anything that needs
        to convert a player's (always-global) position/hitbox into that
        room's own local coordinates, the same way every other per-room live
        entity's position already works (see
        _throw_interact_item/_interact_with_chest)."""
        if self.assembly is not None:
            room = session.current_placed_room
            return room.dungeon, room.offset_x, room.offset_y
        return self.dungeon, 0, 0

    def _throw_interact_item(self, session):
        """Returns True if session's interact slot held a throwable item (see
        ITEM_DEFINITIONS' "throwable" flag -- currently just dynamite) and it
        was thrown: consumes the item, spawns a live ThrownDynamite in the
        current room (converted to that room's local coordinates, same
        convention as every other per-room live entity) at the player's
        position, in the direction they're currently facing, and plays the
        interact animation for visual feedback. Returns False (no-op) if the
        slot is empty or holds a non-throwable item, leaving _trigger_action
        to fall back to the plain interact animation."""
        item = session.inventory.main_slots["interact"]
        if item is None or not ITEM_DEFINITIONS.get(item.item_id, {}).get("throwable"):
            return False

        session.inventory.main_slots["interact"] = None

        dx, dy = Player.DIRECTION_VECTORS.get(session.player.direction, (0, 1))
        direction = pygame.Vector2(dx, dy)

        dungeon, offset_x, offset_y = self._current_room_and_offset(session)
        tile_size = dungeon.tile_size
        local_x = session.player.position.x - offset_x * tile_size
        local_y = session.player.position.y - offset_y * tile_size
        dungeon.projectile_manager.throw_dynamite(local_x, local_y, direction)
        SoundManager().play("dynamite_interact")

        session.player.play_action("interact")
        return True

    def _interact_with_chest(self, session):
        """Returns True if session's player was facing an unopened chest
        (e.g. lilchest) within melee reach and interacted with it: starts its
        opening animation (frame 4, the first frame of row 1 -- see
        OBJECT_TYPES["lilchest"] -- ObjectManager.update takes it from there
        and holds on the last frame once reached, same mechanism as any
        other blocks_until_open object), spawns its configured currency/item
        loot scattered around its own position, and triggers the victory
        screen -- the only win condition that exists right now. Reuses the
        player's own melee reach (get_attack_hitbox: their hitbox shifted one
        tile in their facing direction) rather than a separate "interact
        range", since a chest blocks movement (blocks_movement) so a player
        can only ever be standing right next to it, never on top of it.
        Returns False (no-op) if there's no such chest in reach or it's
        already open, leaving _trigger_action to fall back to throwing/the
        plain interact animation."""
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

        chest_x, chest_y = dungeon.grid_to_world(obj["x"], obj["y"])
        for currency_type, count in obj.get("loot", {}).items():
            for _ in range(count):
                dungeon.pickup_manager.spawn(
                    currency_type,
                    chest_x + random.uniform(-12, 12),
                    chest_y + random.uniform(-12, 12),
                )
        for item_id, count in obj.get("item_loot", {}).items():
            for _ in range(count):
                dungeon.pickup_manager.spawn_item(
                    make_item(item_id),
                    ITEM_DEFINITIONS[item_id]["slot"],
                    chest_x + random.uniform(-12, 12),
                    chest_y + random.uniform(-12, 12),
                )

        session.player.play_action("interact")
        self.victory = True
        self._grant_xp(session, XP_DUNGEON_CLEAR)
        return True

    def _is_walkable(self, rect, moving_session, debug_label=None):
        """debug_label, only used when self.debug_mode is True, tags a
        printed message identifying which candidate move (e.g. "x"/"y") this
        check was for, so a blocked move's cause (wall vs. animal/enemy/
        another player) shows up in the console instead of only being
        inferred from what's on screen.

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

        for animal, animal_rect in self._visible_animals_global():
            if rect.colliderect(animal_rect):
                self._debug_log(debug_label, f"animal({animal.animal_type} at {animal_rect.center})")
                return False

        for enemy, enemy_rect, _dungeon in self._visible_enemies_global():
            if rect.colliderect(enemy_rect):
                self._debug_log(debug_label, f"enemy({enemy.enemy_type} at {enemy_rect.center})")
                return False

        for other_session in self.players.values():
            if other_session is moving_session:
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

    def _update_world(self, dt, player_refs):
        """Advances the room(s) any player can currently affect -- objects,
        animals/enemies, pickups -- via whichever of assembly/single-dungeon
        mode is active. Shared by the frozen victory/inventory tick and the
        normal per-frame update, which additionally runs button-trigger
        checks this helper deliberately leaves out (not meaningful while
        input is frozen)."""
        if self.assembly is not None:
            self.assembly.update(dt, player_refs_by_floor=self._player_refs_by_floor())
        else:
            self.dungeon.update(dt, player_refs=player_refs)

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
        returns to the main Menu for now, same as ECHAP."""
        print(f"[game] {reason} -- retour au menu.")
        self.game_manager.state = GameState.MENU

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
                self.dungeon.spawn_animals()
                self.dungeon.spawn_enemies()
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
        return [PlayerRef(session.player, session.player.get_hitbox()) for session in self.players.values()]

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
            grouped.setdefault(floor, []).append(PlayerRef(session.player, session.player.get_hitbox()))
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

    def _resolve_movement_step(self, session, direction, running, dt, predicting=False, advance_animation=True):
        """The collision-tested core of moving a player, shared by the real
        per-frame simulation (_simulate_movement, predicting=False) and Phase
        4's client-side prediction/replay (_predict_local_movement/
        _reconcile_local_player, predicting=True). `predicting=True` skips
        everything that must stay server-authoritative only -- room
        transitions, falling into the void, footstep audio -- so a
        speculative client-side replay never triggers a side effect the
        server hasn't actually confirmed yet; only position/facing/animation
        are ever computed speculatively. `_is_walkable`'s own wall/animal/
        enemy/other-player checks work unchanged under prediction, since the
        client's mirror world (static terrain loaded once at connect, plus
        animals/enemies/other players kept in sync by apply_network_snapshot)
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
        _predict_local_movement's own (non-replayed) call."""
        player = session.player

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
            if self._is_walkable(future_hitbox, session, debug_label=None if predicting else "x"):
                player.position.x += movement.x

            future_hitbox = player.get_hitbox()
            future_hitbox.y += movement.y
            if self._is_walkable(future_hitbox, session, debug_label=None if predicting else "y"):
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

    def _simulate_movement(self, session, dt):
        self._resolve_movement_step(session, session.input.move_direction, session.input.running, dt)

    def _grant_xp(self, session, amount):
        """Awards XP earned from an already-authoritative event (enemy/animal
        kill, dungeon clear -- see call sites) and persists immediately. A
        no-op for a session with no profile (local co-op's secondary device,
        or a network session that joined without a usable name). Saving right
        away rather than deferring to disconnect is deliberate: these are
        rare, discrete events, not a per-frame hot path, so there's no real
        cost to keeping the profile file always up to date."""
        if session.profile is None:
            return
        session.profile.add_xp(amount)
        ProfileManager().save(session.profile)

    def _resolve_player_attacks(self):
        """Every session's attack, checked against the same one
        _visible_enemies_global()/_visible_animals_global() snapshots
        (computed once, shared across sessions -- was already implicitly
        frame-shared with 1 player). Animals take damage the same as
        enemies (no loot table of their own, so no _spawn_loot call for
        them) -- previously only enemies were ever checked here, so a
        melee swing could never actually kill an animal, only a dynamite
        blast could (see ProjectileManager._apply_blast_damage).
        self.pvp_enabled additionally checks every *other* session's hitbox
        -- off by default (see run()'s F4 toggle), since normal co-op play
        shouldn't have players accidentally hurting each other."""
        enemies = self._visible_enemies_global()
        animals = self._visible_animals_global()
        for session in self.players.values():
            player = session.player
            if not player.is_attack_active():
                continue
            attack_hitbox = player.get_attack_hitbox()
            hit_landed = False

            for enemy, enemy_rect, enemy_dungeon in enemies:
                if attack_hitbox.colliderect(enemy_rect):
                    was_alive = enemy.alive
                    enemy.take_damage(1)
                    hit_landed = True
                    if was_alive and not enemy.alive:
                        self._spawn_loot(enemy, enemy_dungeon)
                        self._grant_xp(session, XP_ENEMY_KILL)

            for animal, animal_rect in animals:
                if attack_hitbox.colliderect(animal_rect):
                    was_alive = animal.alive
                    animal.take_damage(1)
                    hit_landed = True
                    if was_alive and not animal.alive:
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

    def _update_shared_camera(self, positions):
        """Zoom-to-fit self.camera across `positions` (1 or more world
        points) -- the merged view's camera. A single position is a plain
        follow (zoom untouched, manual mouse-wheel zoom fully respected,
        byte-for-byte solo behavior); 2+ positions center on their midpoint
        and derive zoom from their bounding box (+ padding) so nobody goes
        off-screen, clamped to the camera's own min/max -- this *overrides*
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
        self.camera.zoom = max(self.camera.min_zoom, min(self.camera.max_zoom, min(zoom_x, zoom_y)))
        self.camera.center_on(center_x, center_y, self.screen.get_width(), self.screen.get_height())

    def _update_camera(self):
        """Merged (self.camera, zoom-to-fit) or real split-screen (each
        local session's own camera, simple follow) depending on
        _merged_view -- see both for details."""
        local_sessions = self._local_sessions()

        if self._merged_view():
            self._update_shared_camera([session.player.position for session in local_sessions])
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
        animal_manager.animals) against this tick's snapshot entries for it:
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

    def _apply_animal_entry(self, animal, entry):
        self._register_network_target(animal, entry["x"], entry["y"])
        animal.state = entry["state"]
        animal.direction = pygame.Vector2(entry["dir_x"], entry["dir_y"])
        animal.flip = entry["flip"]
        animal.frame = entry["frame"]
        animal.health = entry["health"]

    def _apply_enemy_entry(self, enemy, entry):
        self._register_network_target(enemy, entry["x"], entry["y"])
        enemy.state = entry["state"]
        enemy.direction = pygame.Vector2(entry["dir_x"], entry["dir_y"])
        enemy.flip = entry["flip"]
        enemy.frame = entry["frame"]
        enemy.health = entry["health"]
        enemy.alive = entry["alive"]

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
        for _seq, direction, running, replay_dt in session.pending_inputs:
            self._resolve_movement_step(session, direction, running, replay_dt, predicting=True, advance_animation=False)

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
        self.pvp_enabled = payload["pvp_enabled"]
        self.victory = payload["victory"]
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
        for category in ("animals", "enemies", "pickups", "dynamites", "explosions"):
            for entry in payload[category]:
                grouped.setdefault(entry["room"], {}).setdefault(category, []).append(entry)

        for room_ref, categories in grouped.items():
            dungeon = self._dungeon_for_room(room_ref)
            if dungeon is None:
                continue
            mirrors = self._network_mirrors.setdefault(room_ref, {
                "animals": {}, "enemies": {}, "pickups": {}, "item_pickups": {},
                "dynamites": {}, "explosions": {},
            })

            currency_entries = [e for e in categories.get("pickups", []) if e["kind"] == "currency"]
            item_entries = [e for e in categories.get("pickups", []) if e["kind"] == "item"]

            self._sync_mirror_list(
                mirrors["animals"], dungeon.animal_manager.animals, categories.get("animals", []),
                factory=lambda e, d=dungeon: Animal(e["animal_type"], 0, 0, d),
                updater=self._apply_animal_entry,
            )
            self._sync_mirror_list(
                mirrors["enemies"], dungeon.enemy_manager.enemies, categories.get("enemies", []),
                factory=lambda e, d=dungeon: Enemy(e["enemy_type"], 0, 0, d),
                updater=self._apply_enemy_entry,
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

            if self.game_manager.state != GameState.EXPLORATION:
                break

            self._smooth_network_entities(dt)
            self._update_camera()
            self.render()

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

        # Per-player freeze: a session with its own inventory open only
        # pauses itself (idle animation + its own panel ticking) -- everyone
        # else (other sessions, animals/enemies/the world) keeps going, so
        # one player checking their bag doesn't stop the other from playing.
        for session in self.players.values():
            if session.inventory_open:
                session.update_frozen(dt)
                session.inventory_panel.update(dt)
                continue
            self._apply_requested_actions(session)
            self._simulate_movement(session, dt)

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

        self._update_camera()

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

        pygame.display.flip()

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
                if other.current_placed_room is None or other.current_placed_room.floor == floor
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
                hide_object_types=HIDDEN_OBJECT_TYPES,
                skip_active_floor_foreground=True,
                skip_active_floor_animals=True,
                skip_active_floor_enemies=True,
                show_grid=self.debug_mode,
            )

            self.assembly.render_active_floor_entities(target, camera, floor, players_on_floor)

            self.assembly.render_active_floor_foreground(
                target, camera, floor, hide_object_types=HIDDEN_OBJECT_TYPES,
            )

        else:

            self.dungeon.render(
                target, camera,
                hide_object_types=HIDDEN_OBJECT_TYPES,
                skip_foreground_objects=True,
                skip_animals=True,
                skip_enemies=True,
                show_grid=self.debug_mode,
            )

            entities = (
                list(self.dungeon.animal_manager.animals)
                + list(self.dungeon.enemy_manager.enemies)
                + [other.player for other in self.players.values()]
            )
            entities.sort(key=lambda entity: entity.position.y)
            for entity in entities:
                entity.draw(target, camera)

            self.dungeon.render_foreground(target, camera, hide_object_types=HIDDEN_OBJECT_TYPES)

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
        own floor, animals in yellow, enemies in purple (plus each
        attacking enemy's own melee reach in magenta, same idea as a
        player's orange one) -- all already in the exact world coordinates
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
            for animal in dungeon.animal_manager.animals:
                animal_rect = animal.get_hitbox().move(offset_x, offset_y)
                self._draw_debug_rect(target, camera, animal_rect, (255, 220, 60))
            for enemy in dungeon.enemy_manager.enemies:
                if not enemy.alive:
                    continue
                enemy_rect = enemy.get_hitbox().move(offset_x, offset_y)
                self._draw_debug_rect(target, camera, enemy_rect, (200, 60, 255))
                if enemy.state == "attack":
                    # get_attack_hitbox() is local to the enemy's own
                    # room's Dungeon (same convention as get_hitbox()) --
                    # enemy_rect is that same body hitbox already
                    # shifted to global/world coordinates, so re-using
                    # the delta between the two gets the attack hitbox
                    # into global coordinates too, without needing this
                    # method to know the room's offset directly.
                    local_hitbox = enemy.get_hitbox()
                    offset = (enemy_rect.x - local_hitbox.x, enemy_rect.y - local_hitbox.y)
                    self._draw_debug_rect(target, camera, enemy.get_attack_hitbox().move(offset), (255, 60, 220))

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

            # Only _game_over() can change game_manager.state during
            # update() -- same clean exit TAB/ECHAP already do (no stale
            # frame rendered into a state we're about to leave).
            if self.game_manager.state != GameState.EXPLORATION:
                break

            self.render()