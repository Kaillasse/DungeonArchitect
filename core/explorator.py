# Contient toute la logique du game state Exploration

from __future__ import annotations

import pygame
import random
from core.world.dungeon import Dungeon
from core.data.ressources import ROOMS_DIRECTORY
from core.world.entities import Player
from core.engine.gamestate import GameState
from core.engine.camera import Camera
from pathlib import Path

class Explorator:

    MOVE_SPEED = 180  # pixels/seconde

    def __init__(self, game_manager):

        self.game_manager = game_manager
        self.screen = game_manager.screen

        # -----------------------------
        # Monde
        # -----------------------------

        self.dungeon = Dungeon(width=22, height=18)

        self.grid_offset_x = 0
        self.grid_offset_y = 0
        self.grid_zoom = 1

        # -----------------------------
        # Joueur
        # -----------------------------

        self.player = Player()

        if not self.load_spawn_room():
            print("Aucune salle avec un spawn n'a été trouvée.")

        spawn = self.dungeon.get_spawn_world_position()
        print("spawn =", spawn)

        if spawn is None:
            print("Spawn invalide.")
            spawn = (
                self.dungeon.tile_size,
                self.dungeon.tile_size,
            )

        self.player.position.update(*spawn)
        print("player =", self.player.position)

        # -----------------------------
        # Camera
        # -----------------------------

        self.camera = Camera(zoom=1.0)

        self.clock = pygame.time.Clock()
        
    def load_spawn_room(self):

        rooms = sorted(ROOMS_DIRECTORY.glob("*.json"))

        if not rooms:
            print("Aucune salle trouvée.")
            return False

        for room in rooms:

            self.dungeon.load_from_json(room.stem)

            if self.dungeon.get_spawn_world_position() is not None:

                print(f"Spawn trouvé dans : {room.stem}")
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

        if direction.length_squared() > 0:

            direction = direction.normalize()

            movement = (
                direction
                * self.MOVE_SPEED
                * dt
            )

            future_hitbox = self.player.get_hitbox()
            future_hitbox.x += movement.x
            print("X ->", self.dungeon.is_rect_walkable(future_hitbox))
            if self.dungeon.is_rect_walkable(future_hitbox):
                self.player.position.x += movement.x

            future_hitbox = self.player.get_hitbox()
            future_hitbox.y += movement.y
            print("Y ->", self.dungeon.is_rect_walkable(future_hitbox))
            if self.dungeon.is_rect_walkable(future_hitbox):
                self.player.position.y += movement.y

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

            self.player.animation = "walk"

        else:

            self.player.animation = "idle"

        self.player.update(dt)

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

        self.dungeon.render(
            self.screen,
            self.camera,
        )

        self.player.draw(
            self.screen,
            self.camera,
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

                elif event.type == pygame.KEYDOWN:

                    if event.key == pygame.K_TAB:
                        self.game_manager.state = GameState.CREATOR
                        running = False

                    elif event.key == pygame.K_ESCAPE:
                        self.game_manager.state = GameState.MENU
                        running = False

            self.update(dt)

            self.render()