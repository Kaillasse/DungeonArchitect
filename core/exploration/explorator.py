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

    def __init__(self, game_manager):

        self.game_manager = game_manager
        self.screen = game_manager.screen
        self.settings = game_manager.settings

        # -----------------------------
        # Monde
        # -----------------------------

        self.dungeon = Dungeon(width=22, height=18)
        self.assembly = None
        self.current_placed_room = None
        self._last_door_obj = None

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

        self.camera = Camera(zoom=1.0)

        self.clock = pygame.time.Clock()

    def open_room(self, name):
        """Load a specific room (chosen from the menu) and spawn every current
        session's player in it."""
        self.assembly = None
        self.current_placed_room = None
        self._last_door_obj = None
        self.dungeon.load_from_json(name)
        self.dungeon.spawn_animals()
        self.dungeon.spawn_enemies()
        for session in self.players.values():
            self._position_player_at_spawn(session)
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
        self._last_door_obj = None
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

    def _rooms_with_offset(self):
        """(dungeon, offset_x, offset_y) -- pixel offset -- for every room
        relevant to a global query right now: every room on the active
        floor in assembly mode (DungeonAssembly.update already hands every
        player's hitbox to all of them regardless of which specific room
        each player is registered as standing in, so combat/pickups/etc.
        need to look at all of them too), or just self.dungeon (offset
        (0, 0)) in single-room mode. Shared by _visible_animals_global/
        _visible_enemies_global/_collect_pickups, which otherwise each
        re-derive this identically."""
        if self.assembly is not None:
            tile_size = Dungeon.TILE_SIZE
            for room in self.assembly.rooms_on_floor(self.current_placed_room.floor):
                yield room.dungeon, room.offset_x * tile_size, room.offset_y * tile_size
        else:
            yield self.dungeon, 0, 0

    def _visible_animals_global(self):
        """(animal, hitbox) pairs for every animal that could plausibly
        collide with a player right now, hitbox already in global/world
        coordinates."""
        pairs = []
        for dungeon, offset_x, offset_y in self._rooms_with_offset():
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
        assembly mode whenever the enemy isn't in current_placed_room)."""
        triples = []
        for dungeon, offset_x, offset_y in self._rooms_with_offset():
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
        for dungeon, offset_x, offset_y in self._rooms_with_offset():
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

    def _current_room_and_offset(self):
        """(dungeon, offset_x, offset_y) for whichever room is currently
        active -- offset is (0, 0) in single-room mode. Shared by anything
        that needs to convert a player's (always-global) position/hitbox
        into that room's own local coordinates, the same way every other
        per-room live entity's position already works (see
        _throw_interact_item/_interact_with_chest)."""
        if self.assembly is not None:
            room = self.current_placed_room
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

        dungeon, offset_x, offset_y = self._current_room_and_offset()
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
        dungeon, offset_x, offset_y = self._current_room_and_offset()
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
        for grid_x, grid_y in corner_cells(rect, Dungeon.TILE_SIZE):
            if self._is_void_at(grid_x, grid_y) or self._is_cell_walkable(grid_x, grid_y):
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
            self.assembly.update(
                dt, player_refs=player_refs, player_floor=self.current_placed_room.floor
            )
        else:
            self.dungeon.update(dt, player_refs=player_refs)

    def _is_cell_walkable(self, grid_x, grid_y):
        """Real wall/closed-door/etc. walkability for a single global cell on
        the active floor -- ignores void (see _is_void_at, checked
        separately by _is_walkable's caller) and other entities (also
        checked separately), so it's exactly the "is there a real obstacle
        here" half of the corner check."""
        if self.assembly is not None:
            return self.assembly.is_global_cell_walkable(
                grid_x, grid_y, self.current_placed_room.floor, prefer_room=self.current_placed_room
            )
        return self.dungeon.object_manager.is_cell_walkable(grid_x, grid_y)

    def _debug_log(self, label, reason):
        if not self.debug_mode or label is None:
            return
        message = f"[debug] move '{label}' blocked by {reason}"
        if message != self._last_debug_message:
            print(message)
            self._last_debug_message = message

    def _is_void(self, rect):
        """True if no room claims the cell under a player's feet on the
        active floor -- distinct from being blocked by an actual wall/closed
        door/animal/enemy, which _is_walkable already covers. Single point
        (feet anchor), same convention as _update_current_room/
        check_button_trigger, not the 4-corner check is_rect_walkable uses --
        falling is about where a player's feet are, not a strict hitbox
        overlap test."""
        grid_x, grid_y = self._feet_grid_cell(rect)
        return self._is_void_at(grid_x, grid_y)

    def _is_void_at(self, grid_x, grid_y):
        if self.assembly is not None:
            return self.assembly.locate_room(
                grid_x, grid_y, self.current_placed_room.floor, prefer_room=self.current_placed_room
            ) is None

        return self.dungeon.is_void_at(grid_x, grid_y)

    def _attempt_fall(self, session):
        """Called once session's player's feet actually end up over void (see
        _is_void): looks for the nearest floor below (within the same
        assembly) that owns this exact global cell and lands there --
        current_placed_room changes, the player's position doesn't need to
        (it's already global, so "same tile, different floor" falls out for
        free). No assembly (single-room mode) or nothing below at all: falls
        out of the map entirely (see the "flagged, not decided" note on
        _game_over -- this ends the whole session today, not just this
        player)."""
        if self.assembly is None:
            self._game_over("Chute hors de la carte")
            return

        hitbox = session.player.get_hitbox()
        grid_x, grid_y = self._feet_grid_cell(hitbox)
        current_floor = self.current_placed_room.floor

        for floor in sorted((f for f in self.assembly.floors() if f < current_floor), reverse=True):
            room = self.assembly.locate_room(grid_x, grid_y, floor)
            if room is not None:
                self.current_placed_room = room
                self._last_door_obj = None  # new room/floor -- re-arm the door edge-trigger
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
        DungeonAssembly.resolve_room_transition) flips current_placed_room
        exactly once, on entry, whether that door happens to lead to a room
        on the same floor or a different one. Standing on the door doesn't
        re-trigger, and going back requires fully leaving the door cell and
        stepping onto it again from the other side.

        current_placed_room/the active floor stay singular/Explorator-level
        (see PlayerSession/Phase 1 notes) -- with a real second player in a
        different room/floor, this has no representation yet.

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

        self.current_placed_room, self._last_door_obj = self.assembly.resolve_room_transition(
            self.current_placed_room, self._last_door_obj, grid_x, grid_y
        )

        same_floor_room = self.assembly.locate_room(
            grid_x, grid_y, self.current_placed_room.floor, prefer_room=self.current_placed_room
        )
        if same_floor_room is not None:
            self.current_placed_room = same_floor_room

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

    def _simulate_movement(self, session, dt):
        player = session.player
        direction = session.input.move_direction
        running = session.input.running

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
            # fall-check runs below, after both axes and the door transition,
            # rather than blocking movement at the boundary of whatever room
            # happens to own the active floor.
            future_hitbox = player.get_hitbox()
            future_hitbox.x += movement.x
            if self._is_walkable(future_hitbox, session, debug_label="x"):
                player.position.x += movement.x

            future_hitbox = player.get_hitbox()
            future_hitbox.y += movement.y
            if self._is_walkable(future_hitbox, session, debug_label="y"):
                player.position.y += movement.y

            if self.assembly is not None:
                self._update_current_room(session)

            # Suppressed mid-jump so the player can actually clear a gap by
            # jumping over it instead of falling the instant their feet pass
            # over void while airborne -- the check resumes the very next
            # frame the one-shot jump animation ends (Player.action reverts
            # to None on its own), so landing on void still falls normally.
            if player.action != "jump" and self._is_void(player.get_hitbox()):
                self._attempt_fall(session)

            player.direction = self._direction_from_vector(direction)

            if player.action is None:
                player.animation = "run" if running else "walk"

            self._update_footsteps(session, running, dt)

        else:

            if player.action is None:
                player.animation = "idle"

            session.footstep_timer = 0.0

        player.update(dt)

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

            for animal, animal_rect in animals:
                if attack_hitbox.colliderect(animal_rect):
                    animal.take_damage(1)
                    hit_landed = True

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
                    grid_x, grid_y, self.current_placed_room.floor, prefer_room=self.current_placed_room
                )
            else:
                self.dungeon.object_manager.check_button_trigger(grid_x, grid_y)

            if session.player.health <= 0:
                self._game_over("Le joueur est mort")
                return True
        return False

    CAMERA_FIT_PADDING_TILES = 4  # margin kept around every player's bounding box when zoom-to-fit is active

    def _camera_frame(self):
        """(center_x, center_y, zoom) the camera should use this frame.

        With a single active player: today's simple follow, self.camera.zoom
        untouched -- manual mouse-wheel zoom is fully respected, exactly as
        before Phase 2. With 2+ players (Phase 2's local co-op): centers on
        the midpoint of every player's position and computes a zoom level
        from their bounding box (+ padding) so nobody goes off-screen,
        clamped to the camera's own configured min_zoom/max_zoom. This
        *overrides* manual zoom for as long as 2+ players are active --
        blending auto-fit with the existing zoom_at() input was the riskier
        option and was deliberately not attempted (see Phase 2 notes);
        mouse-wheel zoom simply has no effect while this is in control."""
        positions = [session.player.position for session in self.players.values()]

        if len(positions) == 0:
            # A headless server (Phase 3) keeps ticking the world even
            # before any client has joined, unlike every local mode, which
            # always has at least the local player -- there's nothing to
            # center on yet, so this frame is simply unused (the server
            # never renders).
            return 0.0, 0.0, self.camera.zoom

        if len(positions) <= 1:
            pos = positions[0]
            return pos.x, pos.y, self.camera.zoom

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
        zoom = max(self.camera.min_zoom, min(self.camera.max_zoom, min(zoom_x, zoom_y)))

        return center_x, center_y, zoom

    def _update_camera(self):
        target_x, target_y, zoom = self._camera_frame()
        self.camera.zoom = zoom
        self.camera.center_on(target_x, target_y, self.screen.get_width(), self.screen.get_height())

    # ------------------------------------------------------
    # Networking (Phase 3) -- server-side: bringing a connected client's
    # session into self.players (see core/network/server.py, which owns an
    # Explorator exactly like this one, minus rendering).
    # ------------------------------------------------------

    def add_network_session(self, player_id):
        """A client just connected -- create its PlayerSession, add it to
        self.players (simulated/rendered exactly like any local session, see
        Phase 1/2's players dict), and spawn it the same way every other
        session gets spawned. Mirrors open_room/open_donjon's own per-session
        spawn loop, just for a single session joining after the fact rather
        than every session at room-load time."""
        session = PlayerSession(player_id, "network")
        self.players[player_id] = session

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
        else:
            self._position_player_at_spawn(session)

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

    @staticmethod
    def _sync_mirror_list(mirror_map, live_list, entries, factory, updater):
        """Reconciles one dungeon's live entity list (e.g.
        animal_manager.animals) against this tick's snapshot entries for it:
        creates a local mirror object the first time a network id is seen,
        updates it every time, and drops any mirror whose id no longer
        appears (despawned/died server-side). `mirror_map` is
        {network_id: local_object}, persisted across ticks on
        self._network_mirrors."""
        seen_ids = set()
        for entry in entries:
            seen_ids.add(entry["id"])
            obj = mirror_map.get(entry["id"])
            if obj is None:
                obj = factory(entry)
                mirror_map[entry["id"]] = obj
                live_list.append(obj)
            updater(obj, entry)
        for stale_id in [network_id for network_id in mirror_map if network_id not in seen_ids]:
            stale_obj = mirror_map.pop(stale_id)
            if stale_obj in live_list:
                live_list.remove(stale_obj)

    @staticmethod
    def _apply_animal_entry(animal, entry):
        animal.position.update(entry["x"], entry["y"])
        animal.state = entry["state"]
        animal.direction = pygame.Vector2(entry["dir_x"], entry["dir_y"])
        animal.flip = entry["flip"]
        animal.frame = entry["frame"]
        animal.health = entry["health"]

    @staticmethod
    def _apply_enemy_entry(enemy, entry):
        enemy.position.update(entry["x"], entry["y"])
        enemy.state = entry["state"]
        enemy.direction = pygame.Vector2(entry["dir_x"], entry["dir_y"])
        enemy.flip = entry["flip"]
        enemy.frame = entry["frame"]
        enemy.health = entry["health"]
        enemy.alive = entry["alive"]

    @staticmethod
    def _apply_pickup_entry(pickup, entry):
        pickup.position.update(entry["x"], entry["y"])
        pickup.state = entry["state"]
        pickup.frame = entry["frame"]

    @staticmethod
    def _apply_item_pickup_entry(item_pickup, entry):
        item_pickup.position.update(entry["x"], entry["y"])

    @staticmethod
    def _apply_projectile_entry(projectile, entry):
        projectile.position.update(entry["x"], entry["y"])
        projectile.frame = entry["frame"]

    def apply_network_snapshot(self, payload):
        """Client-side only (Phase 3): writes a server snapshot's fields
        straight onto this Explorator's local mirror world."""
        self.pvp_enabled = payload["pvp_enabled"]
        self.victory = payload["victory"]
        if payload.get("game_over") and self.game_manager.state == GameState.EXPLORATION:
            self.game_manager.state = GameState.MENU

        seen_players = set()
        for entry in payload["players"]:
            seen_players.add(entry["id"])
            session = self.players.get(entry["id"])
            if session is None:
                session = PlayerSession(entry["id"], "network")
                self.players[entry["id"]] = session
            player = session.player
            player.position.update(entry["x"], entry["y"])
            player.direction = entry["direction"]
            player.animation = entry["animation"]
            player.action = entry["action"]
            player.frame = entry["frame"]
            player.health = entry["health"]
        for stale_id in [pid for pid in self.players if pid not in seen_players and pid != self._local_player_id]:
            del self.players[stale_id]

        if not hasattr(self, "_network_mirrors"):
            self._network_mirrors = {}  # room_ref -> {"animals": {...}, ...}

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

    def run_networked(self, client):
        """Client-side main loop for Phase 3's networked play -- the
        network-driven counterpart to run(): same event handling for
        QUIT/mouse-wheel-zoom/F3/ESC (TAB has nothing to switch to here, no
        local editor on a network client), but F4 sends a pvp_toggle request
        instead of flipping the flag locally (must stay server-authoritative
        -- it gates real damage), and every frame sends this session's own
        input to the server and applies whatever snapshot(s) arrived instead
        of calling update() -- no local simulation of the shared world (the
        confirmed "thin client, no prediction" decision)."""
        pygame.display.set_caption("Dungeon Architect - Exploration (reseau)")

        local_session = self.players[self._local_player_id]
        running = True

        while running:
            dt = self.clock.tick(60) / 1000  # noqa: F841 -- kept for parity with run(); unused, server owns simulation dt

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.game_manager.running = False
                    running = False
                    continue

                if event.type == pygame.MOUSEWHEEL:
                    mouse_x, mouse_y = pygame.mouse.get_pos()
                    self.camera.zoom_at(mouse_x, mouse_y, event.y, self.screen.get_width(), self.screen.get_height())
                    continue

                if event.type == pygame.KEYDOWN and event.key == pygame.K_F3:
                    self.debug_mode = not self.debug_mode
                    self._last_debug_message = None
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
            client.send(protocol.MSG_INPUT, **protocol.input_state_to_fields(local_session.input))

            for payload in client.drain():
                if payload["type"] == protocol.MSG_SNAPSHOT:
                    self.apply_network_snapshot(payload)

            if self.game_manager.state != GameState.EXPLORATION:
                break

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

        if self.assembly is not None:

            self.assembly.render(
                self.screen,
                self.camera,
                active_floor=self.current_placed_room.floor,
                player_world_pos=self._camera_frame()[:2],
                hide_object_types=HIDDEN_OBJECT_TYPES,
                skip_active_floor_foreground=True,
                skip_active_floor_animals=True,
                skip_active_floor_enemies=True,
                show_grid=self.debug_mode,
            )

            self.assembly.render_active_floor_entities(
                self.screen,
                self.camera,
                self.current_placed_room.floor,
                [session.player for session in self.players.values()],
            )

            self.assembly.render_active_floor_foreground(
                self.screen,
                self.camera,
                self.current_placed_room.floor,
                hide_object_types=HIDDEN_OBJECT_TYPES,
            )

        else:

            self.dungeon.render(
                self.screen,
                self.camera,
                hide_object_types=HIDDEN_OBJECT_TYPES,
                skip_foreground_objects=True,
                skip_animals=True,
                skip_enemies=True,
                show_grid=self.debug_mode,
            )

            entities = (
                list(self.dungeon.animal_manager.animals)
                + list(self.dungeon.enemy_manager.enemies)
                + [session.player for session in self.players.values()]
            )
            entities.sort(key=lambda entity: entity.position.y)
            for entity in entities:
                entity.draw(self.screen, self.camera)

            self.dungeon.render_foreground(
                self.screen,
                self.camera,
                hide_object_types=HIDDEN_OBJECT_TYPES,
            )

        if self.debug_mode:
            self._draw_debug_hitboxes()

        open_sessions = [session for session in self.players.values() if session.inventory_open]
        if len(open_sessions) == 1:
            session = open_sessions[0]
            session.inventory_panel.render(self.screen, session.player)
        elif len(open_sessions) > 1:
            # More than one panel open at once (per-player freeze lets this
            # happen) -- side by side instead of exactly overlapping.
            region_width = self.screen.get_width() / len(open_sessions)
            for index, session in enumerate(open_sessions):
                session.inventory_panel.render(
                    self.screen, session.player, region=(index * region_width, region_width)
                )

        if self.victory:
            self._draw_victory_banner()

        pygame.display.flip()

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
        """F3 overlay: every player's hitbox in red (plus its attack reach in
        orange while actually active), animals in yellow, enemies in purple
        (plus each attacking enemy's own melee reach in magenta, same idea as
        a player's orange one) -- all already in the exact world coordinates
        _is_walkable/combat compare, so any gap between "what looks like it's
        touching" and "what's actually colliding" is directly visible
        instead of guessed. Also outlines every cell _is_void_at considers
        void (cyan) within a few tiles of the local player -- to diagnose
        exactly which cells near a gate/wall entry-exit read as void vs not,
        rather than guessing."""
        self._draw_debug_void_grid()
        for session in self.players.values():
            player = session.player
            self._draw_debug_rect(player.get_hitbox(), (255, 60, 60))
            if player.is_attack_active():
                self._draw_debug_rect(player.get_attack_hitbox(), (255, 150, 30))
        for _animal, animal_rect in self._visible_animals_global():
            self._draw_debug_rect(animal_rect, (255, 220, 60))
        for enemy, enemy_rect, _dungeon in self._visible_enemies_global():
            self._draw_debug_rect(enemy_rect, (200, 60, 255))
            if enemy.state == "attack":
                # get_attack_hitbox() is local to the enemy's own room's
                # Dungeon (same convention as get_hitbox()) -- enemy_rect is
                # that same body hitbox already shifted to global/world
                # coordinates, so re-using the delta between the two gets the
                # attack hitbox into global coordinates too, without needing
                # this method to know the room's offset directly.
                local_hitbox = enemy.get_hitbox()
                offset = (enemy_rect.x - local_hitbox.x, enemy_rect.y - local_hitbox.y)
                self._draw_debug_rect(enemy.get_attack_hitbox().move(offset), (255, 60, 220))

    def _draw_debug_void_grid(self):
        """Centered on the local player only -- not extended to show every
        player's own local void-grid (see Phase 1 notes)."""
        hitbox = self.players[self._local_player_id].player.get_hitbox()
        center_grid_x, center_grid_y = self._feet_grid_cell(hitbox)
        tile_size = Dungeon.TILE_SIZE
        radius = self.DEBUG_VOID_RADIUS_TILES

        for grid_y in range(center_grid_y - radius, center_grid_y + radius + 1):
            for grid_x in range(center_grid_x - radius, center_grid_x + radius + 1):
                if self._is_void_at(grid_x, grid_y):
                    world_rect = pygame.Rect(grid_x * tile_size, grid_y * tile_size, tile_size, tile_size)
                    self._draw_debug_rect(world_rect, (60, 220, 220))

    def _draw_debug_rect(self, world_rect, color):
        top_left = self.camera.world_to_screen(world_rect.left, world_rect.top)
        bottom_right = self.camera.world_to_screen(world_rect.right, world_rect.bottom)
        screen_rect = pygame.Rect(
            int(top_left[0]), int(top_left[1]),
            int(bottom_right[0] - top_left[0]), int(bottom_right[1] - top_left[1]),
        )
        pygame.draw.rect(self.screen, color, screen_rect, 2)

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
            self.players[1] = PlayerSession(1, "secondary_keyboard")

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

                if event.type == pygame.QUIT:
                    self.game_manager.running = False
                    running = False
                    continue

                if event.type == pygame.MOUSEWHEEL:
                    mouse_x, mouse_y = pygame.mouse.get_pos()
                    self.camera.zoom_at(mouse_x, mouse_y, event.y, self.screen.get_width(), self.screen.get_height())
                    continue

                if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
                    self.game_manager.state = GameState.CREATOR
                    running = False
                    continue

                if event.type == pygame.KEYDOWN and event.key == pygame.K_F3:
                    self.debug_mode = not self.debug_mode
                    self._last_debug_message = None
                    print(f"[debug] debug mode {'ON' if self.debug_mode else 'OFF'} (grid + hitboxes)")
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
