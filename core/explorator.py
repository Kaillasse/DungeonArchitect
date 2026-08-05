# Contient toute la logique du game state Exploration

from __future__ import annotations

import random

import pygame
from core.world.dungeon import Dungeon
from core.world.assembly import load_assembly
from core.data.ressources import ROOMS_DIRECTORY
from core.world.entities import Player
from core.world.object_manager import ANIMAL_TYPES, ENEMY_TYPES, ENEMY_STATS
from core.world.inventory import Inventory, Item
from core.inventory_ui import InventoryPanel
from core.editor.autotile import EMPTY
from core.engine.gamestate import GameState
from core.engine.camera import Camera

# Placed objects that are only ever markers during exploration -- a spawn
# point and each animal's/enemy's placement cell -- and get replaced by a
# live entity (the Player, an AnimalManager-owned Animal, an
# EnemyManager-owned Enemy) instead of being drawn as a static object sprite.
HIDDEN_OBJECT_TYPES = {"spawn", *ANIMAL_TYPES, *ENEMY_TYPES}

class Explorator:

    MOVE_SPEED = 180  # pixels/seconde
    RUN_SPEED = 260  # pixels/seconde -- held with SHIFT

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

        self.grid_offset_x = 0
        self.grid_offset_y = 0
        self.grid_zoom = 1

        # -----------------------------
        # Joueur
        # -----------------------------

        self.player = Player()

        if not self.load_spawn_room():
            print("Aucune salle avec un spawn n'a été trouvée.")

        self._position_player_at_spawn()

        # -----------------------------
        # Inventaire (overlay -- pas de GameState dédié, juste met le monde
        # en pause pendant que le panel est affiché, voir update()/run())
        # -----------------------------

        self.inventory = Inventory()
        # Objets de test TEMPORAIRES pour vérifier visuellement le panel --
        # aucun système de loot/ramassage n'existe encore ; à retirer une
        # fois qu'un vrai système d'objets existe.
        self.inventory.main_slots["attack"] = Item("torch_test", "Torche (test)", "tiles/Torch Yellow.png")
        self.inventory.grid_slots[0] = Item("vase_test", "Vase (test)", "tiles/Vase.png")
        self.inventory.grid_slots[7] = Item("button_test", "Bouton (test)", "tiles/Button.png")

        self.inventory_panel = InventoryPanel(self.inventory)
        self.inventory_open = False

        # -----------------------------
        # Camera
        # -----------------------------

        self.camera = Camera(zoom=1.0)

        self.clock = pygame.time.Clock()

    def open_room(self, name):
        """Load a specific room (chosen from the menu) and spawn the player in it."""
        self.assembly = None
        self.current_placed_room = None
        self._last_door_obj = None
        self.dungeon.load_from_json(name)
        self.dungeon.spawn_animals()
        self.dungeon.spawn_enemies()
        self._position_player_at_spawn()

    def open_donjon(self, name):
        """Load a saved procedurally-assembled dungeon and spawn the player in its starting room."""
        self.assembly = load_assembly(name)
        self._last_door_obj = None

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
        self.player.position.update(
            start_room.offset_x * tile_size + spawn_local[0],
            start_room.offset_y * tile_size + spawn_local[1],
        )

    def _position_player_at_spawn(self):
        spawn = self.dungeon.get_spawn_world_position()

        if spawn is None:
            print("Spawn invalide.")
            spawn = (
                self.dungeon.tile_size,
                self.dungeon.tile_size,
            )

        self.player.position.update(*spawn)

    def _visible_animals_global(self):
        """(animal, hitbox) pairs for every animal that could plausibly collide
        with the player right now, hitbox already in global/world coordinates
        -- current room's animals in single-room mode, every animal on the
        player's current floor (shifted by each room's offset) in assembly
        mode, since DungeonAssembly.update already hands the player's hitbox
        to all of them regardless of which specific room the player is
        registered as standing in."""
        if self.assembly is not None:
            tile_size = Dungeon.TILE_SIZE
            pairs = []
            for room in self.assembly.rooms_on_floor(self.current_placed_room.floor):
                offset = (room.offset_x * tile_size, room.offset_y * tile_size)
                for animal in room.dungeon.animal_manager.animals:
                    pairs.append((animal, animal.get_hitbox().move(offset)))
            return pairs
        return [(animal, animal.get_hitbox()) for animal in self.dungeon.animal_manager.animals]

    def _visible_enemies_global(self):
        """Same idea as _visible_animals_global, but for live (alive) Enemy
        entities -- a corpse doesn't block the player, mirroring
        EnemyManager._is_free's own "other.alive" check for enemy-vs-enemy.
        Yields (enemy, hitbox, dungeon) rather than just (enemy, hitbox) --
        the third element is whichever room's own Dungeon actually owns this
        enemy, needed by the combat code below to drop loot into the right
        room's PickupManager rather than always self.dungeon (wrong in
        assembly mode whenever the enemy isn't in current_placed_room)."""
        if self.assembly is not None:
            tile_size = Dungeon.TILE_SIZE
            triples = []
            for room in self.assembly.rooms_on_floor(self.current_placed_room.floor):
                offset = (room.offset_x * tile_size, room.offset_y * tile_size)
                for enemy in room.dungeon.enemy_manager.enemies:
                    if enemy.alive:
                        triples.append((enemy, enemy.get_hitbox().move(offset), room.dungeon))
            return triples
        return [
            (enemy, enemy.get_hitbox(), self.dungeon)
            for enemy in self.dungeon.enemy_manager.enemies
            if enemy.alive
        ]

    @staticmethod
    def _spawn_loot(enemy, enemy_dungeon):
        """Drops ENEMY_STATS[enemy.enemy_type]["loot"] as individual coin
        Pickups (2 gold + 1 blue -> 3 separate coins, not one "x2" stack),
        scattered a few pixels around the death spot. enemy.position is
        already local to enemy_dungeon (never offset-translated -- see
        Animal/Enemy's own coordinate convention), so no conversion is
        needed before handing it to that same dungeon's PickupManager."""
        loot = ENEMY_STATS[enemy.enemy_type].get("loot", {})
        for currency_type, count in loot.items():
            for _ in range(count):
                enemy_dungeon.pickup_manager.spawn(
                    currency_type,
                    enemy.position.x + random.uniform(-10, 10),
                    enemy.position.y + random.uniform(-10, 10),
                )

    def _collect_pickups(self, player_hitbox):
        """Credits self.inventory.currency for every ground Pickup the
        player's hitbox touches this frame, across whichever room(s) that's
        meaningful for -- same per-floor scope as _visible_animals_global."""
        if self.assembly is not None:
            tile_size = Dungeon.TILE_SIZE
            for room in self.assembly.rooms_on_floor(self.current_placed_room.floor):
                local_hitbox = player_hitbox.move(-room.offset_x * tile_size, -room.offset_y * tile_size)
                room.dungeon.pickup_manager.collect(local_hitbox, self.inventory)
        else:
            self.dungeon.pickup_manager.collect(player_hitbox, self.inventory)

    def _is_walkable(self, rect, debug_label=None):
        """debug_label, only used when self.debug_mode is True, tags a
        printed message identifying which candidate move (e.g. "x"/"y") this
        check was for, so a blocked move's cause (wall vs. animal/enemy) shows
        up in the console instead of only being inferred from what's on
        screen.

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
        the wall check removes that gap entirely."""
        tile_size = Dungeon.TILE_SIZE
        corners = (
            (rect.left, rect.top),
            (rect.right - 1, rect.top),
            (rect.left, rect.bottom - 1),
            (rect.right - 1, rect.bottom - 1),
        )
        for x, y in corners:
            grid_x, grid_y = x // tile_size, y // tile_size
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

        self._last_debug_message = None  # unblocked -- next block (even the same reason) should log again
        return True

    def _is_cell_walkable(self, grid_x, grid_y):
        """Real wall/closed-door/etc. walkability for a single global cell on
        the player's current floor -- ignores void (see _is_void_at, checked
        separately by _is_walkable's caller) and other entities (also
        checked separately), so it's exactly the "is there a real obstacle
        here" half of the corner check."""
        if self.assembly is not None:
            room = self.assembly.locate_room(
                grid_x, grid_y, self.current_placed_room.floor, prefer_room=self.current_placed_room
            )
            if room is None:
                return False
            return room.dungeon.object_manager.is_cell_walkable(grid_x - room.offset_x, grid_y - room.offset_y)
        return self.dungeon.object_manager.is_cell_walkable(grid_x, grid_y)

    def _debug_log(self, label, reason):
        if not self.debug_mode or label is None:
            return
        message = f"[debug] move '{label}' blocked by {reason}"
        if message != self._last_debug_message:
            print(message)
            self._last_debug_message = message

    def _is_void(self, rect):
        """True if no room claims the cell under the player's feet on the
        active floor -- distinct from being blocked by an actual wall/closed
        door/animal/enemy, which _is_walkable already covers. Single point
        (feet anchor), same convention as _update_current_room/
        check_button_trigger, not the 4-corner check is_rect_walkable uses --
        falling is about where the player's feet are, not a strict hitbox
        overlap test."""
        grid_x = int(rect.centerx // Dungeon.TILE_SIZE)
        grid_y = int((rect.bottom - 1) // Dungeon.TILE_SIZE)
        return self._is_void_at(grid_x, grid_y)

    def _is_void_at(self, grid_x, grid_y):
        if self.assembly is not None:
            return self.assembly.locate_room(
                grid_x, grid_y, self.current_placed_room.floor, prefer_room=self.current_placed_room
            ) is None

        if not (0 <= grid_x < self.dungeon.width and 0 <= grid_y < self.dungeon.height):
            return True
        return self.dungeon.logical_grid[grid_y][grid_x] == EMPTY

    def _attempt_fall(self):
        """Called once the player's feet actually end up over void (see
        _is_void): looks for the nearest floor below (within the same
        assembly) that owns this exact global cell and lands there --
        current_placed_room changes, player.position doesn't need to (it's
        already global, so "same tile, different floor" falls out for
        free). No assembly (single-room mode) or nothing below at all: falls
        out of the map entirely."""
        if self.assembly is None:
            self._fall_out_of_map()
            return

        hitbox = self.player.get_hitbox()
        grid_x = int(hitbox.centerx // Dungeon.TILE_SIZE)
        grid_y = int((hitbox.bottom - 1) // Dungeon.TILE_SIZE)
        current_floor = self.current_placed_room.floor

        for floor in sorted((f for f in self.assembly.floors() if f < current_floor), reverse=True):
            room = self.assembly.locate_room(grid_x, grid_y, floor)
            if room is not None:
                self.current_placed_room = room
                self._last_door_obj = None  # new room/floor -- re-arm the door edge-trigger
                self.player.play_fall()
                return

        self._fall_out_of_map()

    def _fall_out_of_map(self):
        """No floor anywhere below catches the fall -- game over. The real
        "monde de base" (étage system) doesn't exist yet, so this returns to
        the main Menu for now, same as ECHAP."""
        print("[game] Chute hors de la carte -- retour au menu.")
        self.game_manager.state = GameState.MENU

    def _update_current_room(self):
        """Edge-triggered room switch: stepping onto a gate/wall entry-exit
        that connects to another room (door_target_room, stamped at
        generation time -- see DungeonAssembly.resolve_room_transition) flips
        current_placed_room exactly once, on entry, whether that door happens
        to lead to a room on the same floor or a different one. Standing on
        the door doesn't re-trigger, and going back requires fully leaving
        the door cell and stepping onto it again from the other side.

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
        hitbox = self.player.get_hitbox()
        grid_x = int(hitbox.centerx // Dungeon.TILE_SIZE)
        grid_y = int((hitbox.bottom - 1) // Dungeon.TILE_SIZE)

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

    def update(self, dt):

        if self.inventory_open:
            # Monde entièrement en pause -- seule l'anim idle du joueur (pour
            # la preview du panel) et le panel lui-même continuent de tourner.
            if self.player.action is None:
                self.player.animation = "idle"
            self.player.update(dt)
            self.inventory_panel.update(dt)
            return

        keys = pygame.key.get_pressed()

        direction = pygame.Vector2()

        if self.settings.is_action_pressed("move_up", keys):
            direction.y -= 1

        if self.settings.is_action_pressed("move_down", keys):
            direction.y += 1

        if self.settings.is_action_pressed("move_left", keys):
            direction.x -= 1

        if self.settings.is_action_pressed("move_right", keys):
            direction.x += 1

        # A single rebindable "run" binding replaces the old hardcoded
        # "either shift key" check -- a deliberate scope trade-off, see
        # core/data/settings.py.
        running = self.settings.is_action_pressed("run", keys)

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
            future_hitbox = self.player.get_hitbox()
            future_hitbox.x += movement.x
            if self._is_walkable(future_hitbox, debug_label="x"):
                self.player.position.x += movement.x

            future_hitbox = self.player.get_hitbox()
            future_hitbox.y += movement.y
            if self._is_walkable(future_hitbox, debug_label="y"):
                self.player.position.y += movement.y

            if self.assembly is not None:
                self._update_current_room()

            if self._is_void(self.player.get_hitbox()):
                self._attempt_fall()

            # -----------------------------
            # Choix direction animation
            # -----------------------------

            if direction.y > 0.5:

                if direction.x > 0.3:
                    self.player.direction = "front_right"

                elif direction.x < -0.3:
                    self.player.direction = "front_left"

                else:
                    self.player.direction = "front"

            elif direction.y < -0.5:

                if direction.x > 0.3:
                    self.player.direction = "back_right"

                elif direction.x < -0.3:
                    self.player.direction = "back_left"

                else:
                    self.player.direction = "back"

            else:

                if direction.x > 0:
                    self.player.direction = "right"

                else:
                    self.player.direction = "left"

            if self.player.action is None:
                self.player.animation = "run" if running else "walk"

        else:

            if self.player.action is None:
                self.player.animation = "idle"

        self.player.update(dt)

        # -----------------------------
        # Combat -- joueur attaque un ennemi
        # -----------------------------

        if self.player.is_attack_active():
            attack_hitbox = self.player.get_attack_hitbox()
            hit_landed = False
            for enemy, enemy_rect, enemy_dungeon in self._visible_enemies_global():
                if attack_hitbox.colliderect(enemy_rect):
                    was_alive = enemy.alive
                    enemy.take_damage(1)
                    hit_landed = True
                    if was_alive and not enemy.alive:
                        self._spawn_loot(enemy, enemy_dungeon)
            if hit_landed:
                self.player._hit_delivered_this_swing = True

        # -----------------------------
        # Ramassage des pièces au sol
        # -----------------------------

        self._collect_pickups(self.player.get_hitbox())

        # -----------------------------
        # Boutons / portes
        # -----------------------------

        hitbox = self.player.get_hitbox()

        if self.assembly is not None:
            self.assembly.update(
                dt, player=self.player, player_hitbox=hitbox, player_floor=self.current_placed_room.floor
            )
            player_grid_x = int(hitbox.centerx // Dungeon.TILE_SIZE)
            player_grid_y = int((hitbox.bottom - 1) // Dungeon.TILE_SIZE)
            self.assembly.check_button_trigger(
                player_grid_x, player_grid_y, self.current_placed_room.floor, prefer_room=self.current_placed_room
            )
        else:
            self.dungeon.update(dt, player=self.player, player_hitbox=hitbox)
            player_grid_x, player_grid_y = self.dungeon.world_to_grid(
                hitbox.centerx,
                hitbox.bottom - 1,
            )
            self.dungeon.object_manager.check_button_trigger(player_grid_x, player_grid_y)

        # -----------------------------
        # Camera suit le joueur
        # -----------------------------

        self.camera.center_on(
            self.player.position.x,
            self.player.position.y,
            self.screen.get_width(),
            self.screen.get_height(),
        )

    # ------------------------------------------------------

    def render(self):

        self.screen.fill((20, 20, 20))

        if self.assembly is not None:

            self.assembly.render(
                self.screen,
                self.camera,
                active_floor=self.current_placed_room.floor,
                player_world_pos=(self.player.position.x, self.player.position.y),
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
                self.player,
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
                + [self.player]
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

        if self.inventory_open:
            self.inventory_panel.render(self.screen, self.player)

        pygame.display.flip()

    DEBUG_VOID_RADIUS_TILES = 3

    def _draw_debug_hitboxes(self):
        """F3 overlay: the player's hitbox in red (plus its attack reach in
        orange while actually active), animals in yellow, enemies in purple
        (plus each attacking enemy's own melee reach in magenta, same idea as
        the player's orange one) -- all already in the exact world
        coordinates _is_walkable/combat compare, so any gap between "what
        looks like it's touching" and "what's actually colliding" is
        directly visible instead of guessed. Also outlines every cell
        _is_void_at considers void (cyan) within a few tiles of the player --
        to diagnose exactly which cells near a gate/wall entry-exit read as
        void vs not, rather than guessing."""
        self._draw_debug_void_grid()
        self._draw_debug_rect(self.player.get_hitbox(), (255, 60, 60))
        if self.player.is_attack_active():
            self._draw_debug_rect(self.player.get_attack_hitbox(), (255, 150, 30))
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
        hitbox = self.player.get_hitbox()
        center_grid_x = int(hitbox.centerx // Dungeon.TILE_SIZE)
        center_grid_y = int((hitbox.bottom - 1) // Dungeon.TILE_SIZE)
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

                elif event.type == pygame.KEYDOWN and self.settings.matches_event("inventory", event):
                    self.inventory_open = not self.inventory_open

                elif self.inventory_open and event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self.inventory_open = False

                elif self.inventory_open:
                    continue  # avale tout le reste (clics, TAB, F3...) tant que le panel est ouvert

                elif event.type == pygame.MOUSEWHEEL:
                    mouse_x, mouse_y = pygame.mouse.get_pos()
                    self.camera.zoom_at(mouse_x, mouse_y, event.y, self.screen.get_width(), self.screen.get_height())

                elif event.type == pygame.MOUSEBUTTONDOWN:

                    for action_id in self.ONE_SHOT_ACTIONS:
                        if self.settings.matches_event(action_id, event):
                            self.player.play_action(action_id)

                elif event.type == pygame.KEYDOWN:

                    if event.key == pygame.K_TAB:
                        self.game_manager.state = GameState.CREATOR
                        running = False

                    elif event.key == pygame.K_ESCAPE:
                        self.game_manager.state = GameState.MENU
                        running = False

                    elif event.key == pygame.K_F3:
                        self.debug_mode = not self.debug_mode
                        self._last_debug_message = None
                        print(f"[debug] debug mode {'ON' if self.debug_mode else 'OFF'} (grid + hitboxes)")

                    else:
                        for action_id in self.ONE_SHOT_ACTIONS:
                            if self.settings.matches_event(action_id, event):
                                self.player.play_action(action_id)

            self.update(dt)

            # Only _fall_out_of_map() can change game_manager.state during
            # update() -- same clean exit TAB/ECHAP already do (no stale
            # frame rendered into a state we're about to leave).
            if self.game_manager.state != GameState.EXPLORATION:
                break

            self.render()