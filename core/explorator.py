# Contient toute la logique du game state Exploration

from __future__ import annotations

import pygame
from core.world.dungeon import Dungeon
from core.world.assembly import load_assembly
from core.data.ressources import ROOMS_DIRECTORY
from core.world.entities import Player
from core.world.object_manager import ANIMAL_TYPES
from core.engine.gamestate import GameState
from core.engine.camera import Camera

# Placed objects that are only ever markers during exploration -- a spawn
# point and each animal's placement cell -- and get replaced by a live entity
# (the Player, an AnimalManager-owned Animal) instead of being drawn as a
# static object sprite.
HIDDEN_OBJECT_TYPES = {"spawn", *ANIMAL_TYPES}

class Explorator:

    MOVE_SPEED = 180  # pixels/seconde
    RUN_SPEED = 260  # pixels/seconde -- held with SHIFT

    def __init__(self, game_manager):

        self.game_manager = game_manager
        self.screen = game_manager.screen

        # -----------------------------
        # Monde
        # -----------------------------

        self.dungeon = Dungeon(width=22, height=18)
        self.assembly = None
        self.current_placed_room = None

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
        # Camera
        # -----------------------------

        self.camera = Camera(zoom=1.0)

        self.clock = pygame.time.Clock()

    def open_room(self, name):
        """Load a specific room (chosen from the menu) and spawn the player in it."""
        self.assembly = None
        self.current_placed_room = None
        self.dungeon.load_from_json(name)
        self.dungeon.spawn_animals()
        self._position_player_at_spawn()

    def open_donjon(self, name):
        """Load a saved procedurally-assembled dungeon and spawn the player in its starting room."""
        self.assembly = load_assembly(name)

        for room in self.assembly.rooms:
            room.dungeon.spawn_animals()

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

    def _is_walkable(self, rect):
        if self.assembly is not None:
            if not self.assembly.is_rect_walkable(
                rect, self.current_placed_room.floor, prefer_room=self.current_placed_room
            ):
                return False
            animals = self.current_placed_room.dungeon.animal_manager.animals
        else:
            if not self.dungeon.is_rect_walkable(rect):
                return False
            animals = self.dungeon.animal_manager.animals

        return not any(rect.colliderect(animal.get_hitbox()) for animal in animals)

    def _update_current_room(self):
        """Resolve which room the player occupies now: same-floor room-crossing
        via locate_room, then a portal check to actually flip floors (see
        DungeonAssembly.locate_room/find_portal for why these are separate)."""
        hitbox = self.player.get_hitbox()
        grid_x = int(hitbox.centerx // Dungeon.TILE_SIZE)
        grid_y = int((hitbox.bottom - 1) // Dungeon.TILE_SIZE)

        located = self.assembly.locate_room(
            grid_x, grid_y, self.current_placed_room.floor, prefer_room=self.current_placed_room
        )
        if located is not None:
            self.current_placed_room = located

        target_floor = self.assembly.find_portal(self.current_placed_room, grid_x, grid_y)
        if target_floor is not None:
            target_room = self.assembly.room_at(target_floor, grid_x, grid_y)
            if target_room is not None:
                self.current_placed_room = target_room

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
                return True

        print("Aucune salle ne contient de spawn.")
        return False
    # ------------------------------------------------------

    def update(self, dt):

        keys = pygame.key.get_pressed()

        direction = pygame.Vector2()

        if keys[pygame.K_z]:
            direction.y -= 1

        if keys[pygame.K_s]:
            direction.y += 1

        if keys[pygame.K_q]:
            direction.x -= 1

        if keys[pygame.K_d]:
            direction.x += 1

        running = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]

        if direction.length_squared() > 0:

            direction = direction.normalize()

            speed = self.RUN_SPEED if running else self.MOVE_SPEED

            movement = (
                direction
                * speed
                * dt
            )

            future_hitbox = self.player.get_hitbox()
            future_hitbox.x += movement.x
            if self._is_walkable(future_hitbox):
                self.player.position.x += movement.x

            future_hitbox = self.player.get_hitbox()
            future_hitbox.y += movement.y
            if self._is_walkable(future_hitbox):
                self.player.position.y += movement.y

            if self.assembly is not None:
                self._update_current_room()

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
        # Boutons / portes
        # -----------------------------

        hitbox = self.player.get_hitbox()

        if self.assembly is not None:
            self.assembly.update(dt, player_hitbox=hitbox, player_floor=self.current_placed_room.floor)
            player_grid_x = int(hitbox.centerx // Dungeon.TILE_SIZE)
            player_grid_y = int((hitbox.bottom - 1) // Dungeon.TILE_SIZE)
            self.assembly.check_button_trigger(
                player_grid_x, player_grid_y, self.current_placed_room.floor, prefer_room=self.current_placed_room
            )
        else:
            self.dungeon.update(dt, player_hitbox=hitbox)
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
            )

            entities = list(self.dungeon.animal_manager.animals) + [self.player]
            entities.sort(key=lambda entity: entity.position.y)
            for entity in entities:
                entity.draw(self.screen, self.camera)

            self.dungeon.render_foreground(
                self.screen,
                self.camera,
                hide_object_types=HIDDEN_OBJECT_TYPES,
            )

        pygame.display.flip()

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

                elif event.type == pygame.MOUSEWHEEL:
                    mouse_x, mouse_y = pygame.mouse.get_pos()
                    self.camera.zoom_at(mouse_x, mouse_y, event.y, self.screen.get_width(), self.screen.get_height())

                elif event.type == pygame.MOUSEBUTTONDOWN:

                    if event.button == 1:
                        self.player.play_action("attack")

                    elif event.button == 3:
                        self.player.play_action("interact")

                elif event.type == pygame.KEYDOWN:

                    if event.key == pygame.K_TAB:
                        self.game_manager.state = GameState.CREATOR
                        running = False

                    elif event.key == pygame.K_ESCAPE:
                        self.game_manager.state = GameState.MENU
                        running = False

                    elif event.key == pygame.K_SPACE:
                        self.player.play_action("jump")

            self.update(dt)

            self.render()