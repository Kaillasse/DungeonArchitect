#Containt all player command and enemies/npc behaviour
from __future__ import annotations
import math
import random
from pathlib import Path
import pygame

from core.data.ressources import WORLD_SCALE
from core.world.object_manager import ANIMAL_TYPES, load_animal_frames

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
        Path(__file__).resolve().parents[2]
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
        base_sprite = self.sprites[self.animation][direction][self.frame]
        if flip:
            base_sprite = pygame.transform.flip(base_sprite, True, False)

        render_scale = camera.zoom * WORLD_SCALE
        zoom_key = max(1, int(round(render_scale * 100)))
        cache_key = (self.animation, direction, flip,self.frame, zoom_key)
        if cache_key not in self._render_cache:
            scaled = pygame.transform.scale_by(base_sprite, render_scale)
            self._render_cache[cache_key] = scaled
        sprite = self._render_cache[cache_key]

        sprite_left_world = self.position.x - base_sprite.get_width() * WORLD_SCALE / 2
        sprite_top_world = self.position.y - base_sprite.get_height() * WORLD_SCALE
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


class Animal:
    """A wandering NPC (chicken/cow/pig/sheep): alternates idle/move on a random
    timer, picking a random direction each time it starts moving, and collides
    like the player (per-axis, via the is_walkable callback its AnimalManager
    passes in -- walls/closed gates plus every other animal and the player,
    see AnimalManager._is_free)."""

    FRAME_SIZE = 32
    MOVE_SPEED = 40  # pixels/second -- slower than the player
    ANIMATION_SPEED = 0.25
    IDLE_DURATION = (1.0, 2.5)
    MOVE_DURATION = (1.0, 2.0)

    HITBOX_WIDTH = 14
    HITBOX_HEIGHT = 8

    def __init__(self, animal_type, grid_x, grid_y, dungeon):
        self.animal_type = animal_type
        self.frames = load_animal_frames(animal_type)

        self.position = pygame.Vector2(*dungeon.grid_to_world(grid_x, grid_y))

        self.state = "idle"
        self.direction = pygame.Vector2()
        self.flip = False

        self.frame = 0
        self.animation_timer = 0
        self.state_timer = random.uniform(*self.IDLE_DURATION)

        self._render_cache = {}

    def _hitbox_at(self, x, y):
        """Hitbox for a given (feet-anchored) position, using the exact same
        rounding get_hitbox() will later re-derive from self.position once
        that candidate is accepted -- see update()'s comment for why this
        single shared formula matters."""
        return pygame.Rect(
            int(round(x - self.HITBOX_WIDTH / 2)),
            int(round(y - self.HITBOX_HEIGHT)),
            self.HITBOX_WIDTH,
            self.HITBOX_HEIGHT,
        )

    def get_hitbox(self):
        return self._hitbox_at(self.position.x, self.position.y)

    def _enter_state(self, state):
        self.state = state
        self.frame = 0
        self.animation_timer = 0

        if state == "move":
            angle = random.uniform(0, 2 * math.pi)
            self.direction = pygame.Vector2(math.cos(angle), math.sin(angle))
            # The source sheets face left by default, so a rightward
            # (positive x) direction is the one that needs flipping.
            self.flip = self.direction.x > 0
            self.state_timer = random.uniform(*self.MOVE_DURATION)
        else:
            self.direction = pygame.Vector2()
            self.state_timer = random.uniform(*self.IDLE_DURATION)

    def update(self, dt, is_walkable):
        self.state_timer -= dt
        if self.state_timer <= 0:
            self._enter_state("move" if self.state == "idle" else "idle")

        if self.state == "move":
            movement = self.direction * self.MOVE_SPEED * dt

            # Build each candidate hitbox straight from the prospective float
            # position via _hitbox_at, rather than mutating the current
            # pygame.Rect in place (hitbox.x += movement.x): Rect coerces a
            # float assignment by rounding, while get_hitbox() truncates from
            # the live float position -- two different roundings of the same
            # quantity could disagree by a pixel, letting a validated move
            # settle into a position whose *actual* hitbox pokes into a wall.
            # Testing the very same formula we'll settle on eliminates that.
            candidate_x = self.position.x + movement.x
            if is_walkable(self._hitbox_at(candidate_x, self.position.y)):
                self.position.x = candidate_x

            candidate_y = self.position.y + movement.y
            if is_walkable(self._hitbox_at(self.position.x, candidate_y)):
                self.position.y = candidate_y

        self.animation_timer += dt
        if self.animation_timer >= self.ANIMATION_SPEED:
            self.animation_timer = 0
            frames = self.frames[self.state]
            self.frame = (self.frame + 1) % len(frames)

    def draw(self, screen, camera):
        frames = self.frames[self.state]
        sprite = frames[min(self.frame, len(frames) - 1)]

        render_scale = camera.zoom * WORLD_SCALE
        zoom_key = max(1, int(round(render_scale * 100)))
        cache_key = (self.state, self.flip, self.frame, zoom_key)
        if cache_key not in self._render_cache:
            scaled = pygame.transform.scale_by(sprite, render_scale)
            if self.flip:
                scaled = pygame.transform.flip(scaled, True, False)
            self._render_cache[cache_key] = scaled
        sprite = self._render_cache[cache_key]

        sprite_left_world = self.position.x - self.FRAME_SIZE * WORLD_SCALE / 2
        sprite_top_world = self.position.y - self.FRAME_SIZE * WORLD_SCALE
        sx, sy = camera.world_to_screen(sprite_left_world, sprite_top_world)

        screen.blit(sprite, (int(sx), int(sy)))


class AnimalManager:
    """Owns the live Animal entities wandering a room, spawned from its placed
    animal objects (ObjectManager.OBJECT_TYPES entries flagged "animal": True).
    Mirrors ObjectManager's dungeon-owned-component role, but for per-frame NPC
    behavior instead of static placement rules -- kept as a separate list
    rather than folded into ObjectManager.objects so a wandering Animal's live
    position/state never gets confused with its origin object's fixed grid
    cell (which stays put and is what actually gets saved to room.json)."""

    def __init__(self, dungeon):
        self.dungeon = dungeon
        self.animals = []

    def spawn(self):
        """(Re)build the live Animal list from the dungeon's currently-placed
        animal objects. Only called by Explorator when it loads a room --
        never during editing, which would reset wandering state on every
        paint stroke, and never by Creator, whose static preview only ever
        shows placed objects' frame-0 icon."""
        self.animals = [
            Animal(obj["type"], obj["x"], obj["y"], self.dungeon)
            for obj in self.dungeon.object_manager.objects
            if obj["type"] in ANIMAL_TYPES
        ]

    def _is_free(self, rect, moving_animal, player_hitbox):
        """Walls/closed gates first (cheapest, most likely to reject), then
        every other live animal in this room, then the player if they're
        actually standing on this room's floor right now (player_hitbox is
        None otherwise -- see Dungeon.update)."""
        if not self.dungeon.is_rect_walkable(rect):
            return False

        for other in self.animals:
            if other is not moving_animal and rect.colliderect(other.get_hitbox()):
                return False

        if player_hitbox is not None and rect.colliderect(player_hitbox):
            return False

        return True

    def update(self, dt, player_hitbox=None):
        for animal in self.animals:
            animal.update(
                dt,
                lambda rect, _animal=animal: self._is_free(rect, _animal, player_hitbox),
            )

    def draw(self, screen, camera):
        for animal in self.animals:
            animal.draw(screen, camera)