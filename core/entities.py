#Containt all player command and enemies/npc behaviour
from __future__ import annotations
from pathlib import Path
import pygame

class SpriteAnimation:
    def __init__(self, image, frame_w, frame_h, animations):
        self.frames = []

        cols = image.get_width() // frame_w
        rows = image.get_height() // frame_h

        for y in range(rows):
            for x in range(cols):
                rect = pygame.Rect(
                    x * frame_w,
                    y * frame_h,
                    frame_w,
                    frame_h
                )
                self.frames.append(image.subsurface(rect).convert_alpha())

        self.animations = animations

        self.current = "idle"

        self.frame = 0
        self.timer = 0

class Player:

    ASSET_PATH = (
        Path(__file__).resolve().parents[1]
        / "assets"
        / "characters"
        / "Player"
    )

    DIRECTIONS = (
        "front",
        "front_right",
        "right",
        "back_right",
        "back",
    )

    ANIMATIONS = (
        "idle",
        "walk",
        "attack",
        "interact",
        "jump",
        "run",
    )

    FRAME_WIDTH = 24
    FRAME_HEIGHT = 24

    def __init__(self):

        self.position = pygame.Vector2(200, 200)
        self.direction = "front"
        self.animation = "idle"
        self.frame = 0
        self.animation_speed = 0.15
        self.animation_timer = 0
        self.sprites = {}
        self._render_cache = {}
        self.load_assets()
        self.hitbox_width = 16
        self.hitbox_height = 10
        self.sprite_scale = 1


    def load_assets(self):

        for animation in self.ANIMATIONS:
            path = self.ASSET_PATH / f"{animation}.png"
            if not path.exists():
                continue
            sheet = pygame.image.load(path).convert_alpha()
            self.sprites[animation] = self.cut_sheet(sheet)
            


    def cut_sheet(self, sheet):

        frames = {}

        columns = sheet.get_width() // self.FRAME_WIDTH
        rows = sheet.get_height() // self.FRAME_HEIGHT

        for row in range(rows):

            # Sécurité si une animation ne possède qu'une seule ligne
            if row >= len(self.DIRECTIONS):
                break

            direction = self.DIRECTIONS[row]
            frames[direction] = []

            for col in range(columns):

                rect = pygame.Rect(
                    col * self.FRAME_WIDTH,
                    row * self.FRAME_HEIGHT,
                    self.FRAME_WIDTH,
                    self.FRAME_HEIGHT,
                )

                frames[direction].append(
                    sheet.subsurface(rect).copy()
                )

        return frames
    
    def get_sprite_direction(self):

        flip = False
        direction = self.direction

        if direction == "left":
            direction = "right"
            flip = True

        elif direction == "front_left":
            direction = "front_right"
            flip = True

        elif direction == "back_left":
            direction = "back_right"
            flip = True

        return direction, flip

    def get_hitbox(self):
        """Return the collision box anchored to the player's feet position."""
        return pygame.Rect(
            int(self.position.x - self.hitbox_width / 2),
            int(self.position.y - self.hitbox_height),
            self.hitbox_width,
            self.hitbox_height,
        )

    def update(self, dt):

        direction, _ = self.get_sprite_direction()

        frames = self.sprites[self.animation][direction]

        self.animation_timer += dt

        if self.animation_timer >= self.animation_speed:

            self.animation_timer = 0

            self.frame += 1

            if self.frame >= len(frames):
                self.frame = 0

    def draw(self, screen, camera):
        direction, flip = self.get_sprite_direction()
        print(self.frame)
        base_sprite = self.sprites[self.animation][direction][self.frame]
        if flip:
            base_sprite = pygame.transform.flip(base_sprite, True, False)

        zoom_key = max(1, int(round(camera.zoom * 100)))
        cache_key = (self.animation, direction, flip,self.frame, zoom_key)
        if cache_key not in self._render_cache:
            scaled = pygame.transform.scale_by(base_sprite, camera.zoom)
            self._render_cache[cache_key] = scaled
        sprite = self._render_cache[cache_key]

        sprite_left_world = self.position.x - base_sprite.get_width() / 2
        sprite_top_world = self.position.y - base_sprite.get_height()
        sprite_screen_x, sprite_screen_y = camera.world_to_screen(sprite_left_world, sprite_top_world)

        screen.blit(sprite, (int(sprite_screen_x), int(sprite_screen_y)))


class NPC:
    def __init__(self, name, health, sprite_path, bust_path):
        self.name = name
        self.health = health
        self.sprite_path = sprite_path
        self.bust_path = bust_path

class Enemies:
    def __init__(self, name, health, sprite_path, bust_path):
        self.name = name
        self.health = health
        self.sprite_path = sprite_path
        self.bust_path = bust_path