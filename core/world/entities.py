#Containt all player command and enemies/npc behaviour
from __future__ import annotations
import math
import random
from pathlib import Path
import pygame

from core.data.ressources import WORLD_SCALE, TILE_SIZE
from core.data.sound_manager import SoundManager
from core.world.object_manager import (
    ANIMAL_TYPES, load_animal_frames, ENEMY_TYPES, ENEMY_STATS, load_enemy_frames, load_currency_frames,
    load_dynamite_frames, load_explosion_frames,
)

def _draw_cached_sprite(screen, camera, cache, key_prefix, sprite, position, frame_w, frame_h, flip=False, anchor_feet=False):
    """Scale+cache `sprite` at the camera's current zoom and blit it in world
    space. `key_prefix` plus a zoom bucket forms the cache key -- shared by
    every live entity/VFX's draw() (Player, Animal/Enemy, Pickup/ItemPickup,
    ThrownDynamite, Explosion), which otherwise each re-derive this
    identically. `anchor_feet=True` anchors at (bottom-center) == position,
    matching a live entity's feet; the default (center) matches ground
    VFX/pickups."""
    render_scale = camera.zoom * WORLD_SCALE
    zoom_key = max(1, int(round(render_scale * 100)))
    cache_key = key_prefix + (zoom_key,)
    if cache_key not in cache:
        scaled = pygame.transform.scale_by(sprite, render_scale)
        if flip:
            scaled = pygame.transform.flip(scaled, True, False)
        cache[cache_key] = scaled
    scaled = cache[cache_key]

    top_frac = 1.0 if anchor_feet else 0.5
    sprite_left_world = position.x - frame_w * WORLD_SCALE / 2
    sprite_top_world = position.y - frame_h * WORLD_SCALE * top_frac
    sx, sy = camera.world_to_screen(sprite_left_world, sprite_top_world)
    screen.blit(scaled, (int(sx), int(sy)))


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

    # Play once and hand control back to idle/walk/run instead of looping --
    # see play_action()/update().
    ONE_SHOT_ANIMATIONS = ("attack", "interact", "jump")

    MAX_HEALTH = 2

    # 0-based frames (3, 4, 5) == the to-do's 1-based "frames 4, 5, 6" of the
    # 6-frame attack.png -- the window during which a swing actually deals
    # damage (see is_attack_active/_hit_delivered_this_swing).
    ACTIVE_ATTACK_FRAMES = (3, 4, 5)

    # Facing vector per Player.direction (8 values Explorator can set,
    # not just the 5 sprite rows DIRECTIONS covers -- get_sprite_direction
    # mirrors left/right for rendering, but the attack hitbox needs the real
    # facing, not the mirrored sprite row).
    DIRECTION_VECTORS = {
        "front": (0, 1),
        "front_right": (0.7071, 0.7071),
        "front_left": (-0.7071, 0.7071),
        "back": (0, -1),
        "back_right": (0.7071, -0.7071),
        "back_left": (-0.7071, -0.7071),
        "right": (1, 0),
        "left": (-1, 0),
    }

    def __init__(self):

        self.position = pygame.Vector2(200, 200)
        self.direction = "front"
        self.animation = "idle"
        self.action = None  # currently-playing one-shot animation name, or None
        self.frame = 0
        self.animation_speed = 0.15
        self.animation_timer = 0
        self.sprites = {}
        self._render_cache = {}
        self.load_assets()
        self.hitbox_width = 16
        self.hitbox_height = 10
        self.sprite_scale = 1

        self.health = self.MAX_HEALTH
        self._hit_delivered_this_swing = False
        self._attack_sound_played = False


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

    def get_attack_hitbox(self):
        """The melee reach checked against enemies while is_attack_active():
        the player's own hitbox shifted one tile in the direction they're
        facing -- a simple reach zone, not a directional arc."""
        dx, dy = self.DIRECTION_VECTORS.get(self.direction, (0, 1))
        reach = TILE_SIZE * WORLD_SCALE
        hitbox = self.get_hitbox()
        hitbox.x += int(dx * reach)
        hitbox.y += int(dy * reach)
        return hitbox

    def is_attack_active(self):
        """True on the frames of the current attack swing that actually deal
        damage (see ACTIVE_ATTACK_FRAMES), and only once per swing --
        _hit_delivered_this_swing (reset in play_action) stops a multi-frame
        active window from registering more than one hit."""
        return (
            self.action == "attack"
            and self.frame in self.ACTIVE_ATTACK_FRAMES
            and not self._hit_delivered_this_swing
        )

    def take_damage(self, amount):
        self.health = max(0, self.health - amount)
        print(f"[combat] Player took {amount} damage (health: {self.health}/{self.MAX_HEALTH})")

    def play_action(self, name):
        """Trigger a one-shot action animation (attack/interact/jump) --
        ignored while another action is already mid-playback, and while a
        sheet exists for every direction on idle/walk/run, jump.png only
        has 4 of the 5 DIRECTIONS rows (see _frames_for's fallback), which
        this doesn't need to know about."""
        if self.action is not None or name not in self.sprites:
            return
        self.action = name
        self.animation = name
        self.frame = 0
        self.animation_timer = 0
        self._hit_delivered_this_swing = False
        self._attack_sound_played = False

    def play_fall(self):
        """One-shot fall animation played on a successful landing after
        dropping through void (see Explorator._attempt_fall) -- reuses
        jump.png (the last 3 frames read as a distinct "falling" pose) and
        the same ONE_SHOT_ANIMATIONS machinery as play_action, just starting
        partway through the sheet instead of at frame 0."""
        if "jump" not in self.sprites:
            return
        self.action = "jump"
        self.animation = "jump"
        direction, _ = self.get_sprite_direction()
        frames = self._frames_for("jump", direction)
        self.frame = max(0, len(frames) - 3)
        self.animation_timer = 0
        self._hit_delivered_this_swing = False

    def _frames_for(self, animation, direction):
        """Frame list for (animation, direction), falling back to "front" and
        then to whatever direction the sheet does have -- not every animation
        sheet has a row for all 5 DIRECTIONS (jump.png is missing "back")."""
        directions = self.sprites[animation]
        return directions.get(direction) or directions.get("front") or next(iter(directions.values()))

    def update(self, dt):

        direction, _ = self.get_sprite_direction()

        frames = self._frames_for(self.animation, direction)

        self.animation_timer += dt

        if self.animation_timer >= self.animation_speed:

            self.animation_timer = 0

            self.frame += 1

            if self.frame >= len(frames):
                self.frame = 0
                if self.action is not None and self.animation == self.action:
                    # One-shot finished; caller picks idle/walk/run again next frame.
                    self.action = None
            elif (
                self.action == "attack"
                and self.frame in self.ACTIVE_ATTACK_FRAMES
                and not self._attack_sound_played
            ):
                # Right as the swing's actual hit-frame window begins, not
                # at the start of the animation -- matches when
                # is_attack_active()/the real hitbox actually becomes live.
                SoundManager().play("player_attack")
                self._attack_sound_played = True

    def draw(self, screen, camera):
        direction, flip = self.get_sprite_direction()
        frames = self._frames_for(self.animation, direction)
        sprite = frames[min(self.frame, len(frames) - 1)]
        _draw_cached_sprite(
            screen, camera, self._render_cache,
            (self.animation, direction, flip, self.frame),
            sprite, self.position, sprite.get_width(), sprite.get_height(),
            flip=flip, anchor_feet=True,
        )


class _WanderingEntity:
    """Shared plumbing for Animal and Enemy: both are live NPCs that wander a
    room on a random idle/move timer with per-axis collision-tested
    movement, and both draw a cached, zoom-scaled sprite anchored to their
    feet position. Subclasses own their own state machine and __init__ (only
    Enemy has chase/attack/damaged/death on top of idle/move) and must set:
    HITBOX_WIDTH/HEIGHT, FRAME_SIZE, IDLE_DURATION/MOVE_DURATION,
    ANIMATION_SPEED, LOOPING_STATES, MOVE_STATE_NAME (the wandering "moving"
    state's key into self.frames -- "move" for Animal, "movement" for
    Enemy), and FACES_RIGHT_BY_DEFAULT (whether the sprite sheet's unflipped
    pose already faces right -- flips the sign of the direction.x check
    below; the animal sheets face left by default, the skeleton sheets face
    right)."""

    def _hitbox_at(self, x, y):
        """Hitbox for a given (feet-anchored) position, using the exact same
        rounding get_hitbox() will later re-derive from self.position once
        that candidate is accepted -- see _move_toward's comment for why
        this single shared formula matters."""
        return pygame.Rect(
            int(round(x - self.HITBOX_WIDTH / 2)),
            int(round(y - self.HITBOX_HEIGHT)),
            self.HITBOX_WIDTH,
            self.HITBOX_HEIGHT,
        )

    def get_hitbox(self):
        return self._hitbox_at(self.position.x, self.position.y)

    def _enter_wander_state(self, state):
        self.state = state
        self.frame = 0
        self.animation_timer = 0

        if state == self.MOVE_STATE_NAME:
            angle = random.uniform(0, 2 * math.pi)
            self.direction = pygame.Vector2(math.cos(angle), math.sin(angle))
            self.flip = (self.direction.x < 0) if self.FACES_RIGHT_BY_DEFAULT else (self.direction.x > 0)
            self.state_timer = random.uniform(*self.MOVE_DURATION)
        else:
            self.direction = pygame.Vector2()
            self.state_timer = random.uniform(*self.IDLE_DURATION)

    def _wander_tick(self, dt, is_walkable, speed):
        """Ambient idle/move(ment) alternation on a random timer: shared by
        Animal.update and Enemy._update_wander. Doesn't call
        _advance_animation -- callers do that themselves, since Enemy needs
        to regardless of which state (wander/chase/attack) it lands in this
        frame."""
        self.state_timer -= dt
        if self.state_timer <= 0:
            self._enter_wander_state(self.MOVE_STATE_NAME if self.state == "idle" else "idle")

        if self.state == self.MOVE_STATE_NAME:
            self._move_toward(dt, is_walkable, self.direction, speed)

    def _move_toward(self, dt, is_walkable, direction, speed):
        """Per-axis collision-tested movement toward `direction` (any
        length) at `speed` px/s. Candidate positions are built straight from
        the prospective float position via _hitbox_at, rather than mutating
        a live pygame.Rect in place (hitbox.x += movement.x): Rect coerces a
        float assignment by rounding, while get_hitbox() truncates from the
        live float position -- two different roundings of the same quantity
        could disagree by a pixel, letting a validated move settle into a
        position whose *actual* hitbox pokes into a wall. Testing the very
        same formula we'll settle on eliminates that."""
        if direction.length_squared() == 0:
            return
        direction = direction.normalize()
        self.flip = (direction.x < 0) if self.FACES_RIGHT_BY_DEFAULT else (direction.x > 0)
        movement = direction * speed * dt

        candidate_x = self.position.x + movement.x
        if is_walkable(self._hitbox_at(candidate_x, self.position.y)):
            self.position.x = candidate_x

        candidate_y = self.position.y + movement.y
        if is_walkable(self._hitbox_at(self.position.x, candidate_y)):
            self.position.y = candidate_y

    def _advance_animation(self, dt):
        """Looping states wrap forever (Animal's idle/move both do); a
        non-looping state advances toward its last frame and then calls a
        hook once it gets there instead of wrapping -- Animal has no
        non-looping states so these hooks are never reached for it, Enemy
        overrides them for its attack/damaged/death states."""
        frames = self.frames[self.state]
        self.animation_timer += dt
        if self.animation_timer < self.ANIMATION_SPEED:
            return
        self.animation_timer = 0

        if self.state in self.LOOPING_STATES:
            self.frame = (self.frame + 1) % len(frames)
            self._on_loop_frame_advanced()
        elif self.frame < len(frames) - 1:
            self.frame += 1
        else:
            self._on_final_frame_reached()

    def _on_loop_frame_advanced(self):
        """Hook: called after a LOOPING_STATES frame wraps forward. No-op by
        default (Animal doesn't need it); Enemy overrides it to re-arm its
        attack window at the start of each swing."""

    def _on_final_frame_reached(self):
        """Hook: called once a non-looping animation has reached its last
        frame instead of advancing further. No-op by default (holds on the
        last frame forever); Enemy overrides it for "damaged" -> "idle"."""

    def draw(self, screen, camera):
        frames = self.frames[self.state]
        sprite = frames[min(self.frame, len(frames) - 1)]
        _draw_cached_sprite(
            screen, camera, self._render_cache,
            (self.state, self.flip, self.frame),
            sprite, self.position, self.FRAME_SIZE, self.FRAME_SIZE,
            flip=self.flip, anchor_feet=True,
        )


class Animal(_WanderingEntity):
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
    LOOPING_STATES = ("idle", "move")
    MOVE_STATE_NAME = "move"
    FACES_RIGHT_BY_DEFAULT = False  # the animal sheets face left by default

    HITBOX_WIDTH = 14
    HITBOX_HEIGHT = 8

    # A tuning default, not from any design doc (mirrors ENEMY_STATS' own
    # comment) -- animals have no death animation, so unlike Enemy this is
    # the only thing standing between "hit" and "gone" (see take_damage/
    # AnimalManager.update's dead-animal filter).
    HEALTH = 2

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

        self.health = self.HEALTH
        self.alive = True

        self._render_cache = {}

    def take_damage(self, amount):
        """No "damaged"/"death" states or animation like Enemy -- an animal
        that runs out of health just disappears (see AnimalManager.update's
        dead-animal filter), there's nothing else to play out."""
        if not self.alive:
            return
        self.health -= amount
        if self.health <= 0:
            self.alive = False

    def update(self, dt, is_walkable):
        self._wander_tick(dt, is_walkable, self.MOVE_SPEED)
        self._advance_animation(dt)


def _entity_rect_is_free(dungeon, rect, entities, moving_entity, player_hitbox):
    """Shared by AnimalManager/EnemyManager._is_free: walls/closed gates
    first (cheapest, most likely to reject), then every other live entity in
    `entities` (a dead Enemy -- getattr(other, "alive", True) -- doesn't
    block; Animal has no "alive" attribute at all, so it defaults to always
    blocking), then the player if they're actually standing on this room's
    floor right now (player_hitbox is None otherwise -- see Dungeon.update)."""
    if not dungeon.is_rect_walkable(rect):
        return False

    for other in entities:
        if other is not moving_entity and getattr(other, "alive", True) and rect.colliderect(other.get_hitbox()):
            return False

    if player_hitbox is not None and rect.colliderect(player_hitbox):
        return False

    return True


class _EntityManager:
    """Shared shape for AnimalManager/EnemyManager: both own a list of live,
    per-frame NPCs (stored under LIST_ATTR -- "animals"/"enemies", kept as a
    plain attribute rather than a property since callers across
    explorator.py/assembly.py read it directly) spawned from a dungeon's
    currently-placed objects of ENTITY_TYPES, testing free space and drawing
    identically. Only update() -- each entity's own per-frame behavior
    signature -- differs, so that's all subclasses define."""

    ENTITY_CLASS = None
    ENTITY_TYPES = ()
    LIST_ATTR = ""

    def __init__(self, dungeon):
        self.dungeon = dungeon
        setattr(self, self.LIST_ATTR, [])

    def spawn(self):
        """(Re)build the live entity list from the dungeon's currently-placed
        objects of ENTITY_TYPES. Only called by Explorator when it loads a
        room -- never during editing, which would reset wandering/chase state
        on every paint stroke, and never by Creator, whose static preview
        only ever shows placed objects' frame-0 icon."""
        setattr(self, self.LIST_ATTR, [
            self.ENTITY_CLASS(obj["type"], obj["x"], obj["y"], self.dungeon)
            for obj in self.dungeon.object_manager.objects
            if obj["type"] in self.ENTITY_TYPES
        ])

    def _is_free(self, rect, moving_entity, player_hitbox):
        return _entity_rect_is_free(
            self.dungeon, rect, getattr(self, self.LIST_ATTR), moving_entity, player_hitbox
        )

    def draw(self, screen, camera):
        for entity in getattr(self, self.LIST_ATTR):
            entity.draw(screen, camera)


class AnimalManager(_EntityManager):
    """Owns the live Animal entities wandering a room, spawned from its placed
    animal objects (ObjectManager.OBJECT_TYPES entries flagged "animal": True).
    Mirrors ObjectManager's dungeon-owned-component role, but for per-frame NPC
    behavior instead of static placement rules -- kept as a separate list
    rather than folded into ObjectManager.objects so a wandering Animal's live
    position/state never gets confused with its origin object's fixed grid
    cell (which stays put and is what actually gets saved to room.json)."""

    ENTITY_CLASS = Animal
    ENTITY_TYPES = ANIMAL_TYPES
    LIST_ATTR = "animals"

    def update(self, dt, player_hitbox=None):
        for animal in self.animals:
            animal.update(
                dt,
                lambda rect, _animal=animal: self._is_free(rect, _animal, player_hitbox),
            )
        # No death animation to play out (unlike Enemy) -- a dead animal
        # just disappears the moment its health runs out.
        self.animals = [animal for animal in self.animals if animal.alive]


class Enemy(_WanderingEntity):
    """A combat-capable wandering NPC (skeleton1/skeleton2): behaves exactly
    like an Animal when the player is out of range (idle/move alternation,
    same per-axis collision-tested movement), but switches to chasing once
    the player enters its aggro_range and to attacking once in attack_range
    -- both distances (in tiles, from core.world.object_manager.ENEMY_STATS)
    checked fresh every frame, so stepping back out of range mid-swing just
    drops back to chasing/wandering rather than committing to a swing.

    self.state doubles as the key into self.frames (the ENEMY_ANIMATIONS
    set: "idle"/"movement"/"attack"/"damaged"/"death"), same idea as
    Animal's "idle"/"move" states matching load_animal_frames's keys.
    """

    FRAME_SIZE = 32
    ANIMATION_SPEED = 0.2
    IDLE_DURATION = (1.0, 2.5)
    MOVE_DURATION = (1.0, 2.0)
    LOOPING_STATES = ("idle", "movement", "attack")
    MOVE_STATE_NAME = "movement"
    FACES_RIGHT_BY_DEFAULT = True  # the skeleton sheets face right by default

    HITBOX_WIDTH = 16
    HITBOX_HEIGHT = 10

    def __init__(self, enemy_type, grid_x, grid_y, dungeon):
        self.enemy_type = enemy_type
        self.frames = load_enemy_frames(enemy_type)
        self.stats = ENEMY_STATS[enemy_type]
        self.tile_size = dungeon.tile_size

        self.position = pygame.Vector2(*dungeon.grid_to_world(grid_x, grid_y))

        self.health = self.stats["health"]
        self.alive = True

        self.state = "idle"
        self.direction = pygame.Vector2()
        self.flip = False

        self.frame = 0
        self.animation_timer = 0
        self.state_timer = random.uniform(*self.IDLE_DURATION)
        self._hit_delivered_this_swing = False
        self._attack_sound_played = False

        self._render_cache = {}

    def get_attack_hitbox(self):
        """Melee reach checked against the player during the active-frame
        window (see update()) -- the enemy's own hitbox inflated by one tile
        in every direction, rather than translated toward the player like
        Player.get_attack_hitbox (a fixed reach-ahead swing, which fits a
        sprite with a discrete 8-way facing). An enemy only ever flips
        left/right, with no such discrete facing to translate along, and a
        translated box would overshoot past an already-adjacent player
        entirely (a full tile's shift moving clean past a target closer than
        that) -- inflating in place instead always covers the player whether
        they're standing right against the enemy or up to a tile away."""
        reach = self.tile_size
        return self.get_hitbox().inflate(reach * 2, reach * 2)

    def take_damage(self, amount):
        if not self.alive:
            return
        self.health -= amount
        self.frame = 0
        self.animation_timer = 0
        if self.health <= 0:
            self.alive = False
            self.state = "death"
        else:
            self.state = "damaged"
            SoundManager().play("skeleton_damaged")

    def _enter_state(self, state):
        if self.state == state:
            return
        self.state = state
        self.frame = 0
        self.animation_timer = 0
        if state == "attack":
            self._hit_delivered_this_swing = False
            self._attack_sound_played = False

    def _update_wander(self, dt, is_walkable):
        """Ambient background behavior, identical in spirit to Animal.update:
        alternates idle/movement on a random timer, random direction each
        time movement starts."""
        if self.state not in ("idle", "movement"):
            self._enter_wander_state("idle")

        self._wander_tick(dt, is_walkable, self.stats["move_speed"])

    def _update_chase(self, dt, is_walkable, player_hitbox):
        self._enter_state("movement")
        target = pygame.Vector2(player_hitbox.centerx, player_hitbox.centery)
        self._move_toward(dt, is_walkable, target - self.position, self.stats["move_speed"])

    def _on_loop_frame_advanced(self):
        if self.state != "attack":
            return
        # A fresh attack swing starts its own new active-frame window.
        if self.frame == 0:
            self._hit_delivered_this_swing = False
            self._attack_sound_played = False
        # Right as the swing's actual hit-frame window begins, not at the
        # start of the animation -- matches when the real hitbox
        # (active_attack_frames, checked in update() below) actually
        # becomes live.
        if self.frame in self.stats["active_attack_frames"] and not self._attack_sound_played:
            SoundManager().play(f"{self.enemy_type}_attack")
            self._attack_sound_played = True

    def _on_final_frame_reached(self):
        if self.state == "damaged":
            # Played once; return to a neutral state and let the next
            # update() re-evaluate distance to pick idle/movement/attack.
            self.state = "idle"
            self.frame = 0
        # else state == "death": holds on the last frame forever.

    def update(self, dt, is_walkable, player, player_hitbox):
        if not self.alive:
            self._advance_animation(dt)
            return

        if self.state == "damaged":
            self._advance_animation(dt)
            return

        distance_px = None
        if player_hitbox is not None:
            dx = player_hitbox.centerx - self.position.x
            dy = player_hitbox.centery - self.position.y
            distance_px = math.hypot(dx, dy)

        if distance_px is not None and distance_px <= self.stats["attack_range"] * self.tile_size:
            self._enter_state("attack")
            self.flip = player_hitbox.centerx < self.position.x
        elif distance_px is not None and distance_px <= self.stats["aggro_range"] * self.tile_size:
            self._update_chase(dt, is_walkable, player_hitbox)
        else:
            self._update_wander(dt, is_walkable)

        self._advance_animation(dt)

        if (
            self.state == "attack"
            and self.frame in self.stats["active_attack_frames"]
            and not self._hit_delivered_this_swing
            and player_hitbox is not None
            and self.get_attack_hitbox().colliderect(player_hitbox)
        ):
            player.take_damage(1)
            self._hit_delivered_this_swing = True


class EnemyManager(_EntityManager):
    """Owns the live Enemy entities in a room, spawned from its placed enemy
    objects (ENEMY_TYPES) -- mirrors AnimalManager's shape exactly (see
    _EntityManager/AnimalManager's docstrings for why this stays a separate
    list rather than folding into ObjectManager.objects). Unlike
    AnimalManager.update, a dead Enemy is never filtered out here -- it stays
    to play out its death animation and hold on the last frame."""

    ENTITY_CLASS = Enemy
    ENTITY_TYPES = ENEMY_TYPES
    LIST_ATTR = "enemies"

    def update(self, dt, player=None, player_hitbox=None):
        for enemy in self.enemies:
            enemy.update(
                dt,
                lambda rect, _enemy=enemy: self._is_free(rect, _enemy, player_hitbox),
                player,
                player_hitbox,
            )


def _advance_frame_once(entity, dt, duration, frame_count):
    """Ticks entity.animation_timer/frame toward frame_count-1 and holds
    there once reached, returning True the frame it arrives -- the caller
    sets its own "finished"/"exploded" flag then. Shared "play once" timer
    tail for Pickup's "collect" state, ThrownDynamite, and Explosion (each
    otherwise re-derives this identically)."""
    entity.animation_timer += dt
    if entity.animation_timer < duration:
        return False
    entity.animation_timer = 0
    if entity.frame < frame_count - 1:
        entity.frame += 1
        return False
    return True


class Pickup:
    """A currency pickup dropped by a dead enemy (see Explorator._spawn_loot)
    -- never saved to room.json (created at runtime, not authored), never
    blocks movement (not consulted by is_rect_walkable/_is_free). Two states:
    "spin" loops forever until the player's hitbox touches it
    (PickupManager.collect calls begin_collect()), then "collect" plays once
    -- the sprite's own row 1 -- before PickupManager removes it (self.finished)."""

    FRAME_SIZE = 16
    HITBOX_SIZE = 16
    ANIMATION_SPEED = 0.15

    def __init__(self, currency_type, world_x, world_y):
        self.currency_type = currency_type
        self.position = pygame.Vector2(world_x, world_y)
        self.frames = load_currency_frames(currency_type)  # {"spin": [...], "collect": [...]}

        self.state = "spin"
        self.frame = 0
        self.animation_timer = 0.0
        self.finished = False

        self._render_cache = {}

    def get_hitbox(self):
        return pygame.Rect(
            int(self.position.x - self.HITBOX_SIZE / 2),
            int(self.position.y - self.HITBOX_SIZE / 2),
            self.HITBOX_SIZE,
            self.HITBOX_SIZE,
        )

    def begin_collect(self):
        if self.state == "collect":
            return
        self.state = "collect"
        self.frame = 0
        self.animation_timer = 0.0

    def update(self, dt):
        frames = self.frames[self.state]
        if self.state == "spin":
            self.animation_timer += dt
            if self.animation_timer < self.ANIMATION_SPEED:
                return
            self.animation_timer = 0
            self.frame = (self.frame + 1) % len(frames)
        elif _advance_frame_once(self, dt, self.ANIMATION_SPEED, len(frames)):
            self.finished = True

    def draw(self, screen, camera):
        sprite = self.frames[self.state][self.frame]
        _draw_cached_sprite(
            screen, camera, self._render_cache,
            (self.state, self.frame),
            sprite, self.position, self.FRAME_SIZE, self.FRAME_SIZE,
        )


class ItemPickup:
    """A dropped real inventory Item waiting on the ground (e.g. dynamite
    dropped by a dead enemy, see ENEMY_STATS' "item_loot") -- unlike Pickup
    (currency), there's no spin/collect animation, just a single static
    frame (Item.get_icon(), already cropped to frame 0 via its icon_rect --
    "avant pickup" per spec). Removes itself and drops `item` into
    inventory.main_slots[slot] the instant the player's hitbox touches it,
    but only if that slot is actually empty -- an already-equipped slot
    leaves the pickup exactly where it is, untouched, for the player to
    come back to once the slot frees up."""

    HITBOX_SIZE = 16

    def __init__(self, item, slot, world_x, world_y):
        self.item = item
        self.slot = slot
        self.position = pygame.Vector2(world_x, world_y)
        self.collected = False
        self._render_cache = {}

    def get_hitbox(self):
        return pygame.Rect(
            int(self.position.x - self.HITBOX_SIZE / 2),
            int(self.position.y - self.HITBOX_SIZE / 2),
            self.HITBOX_SIZE,
            self.HITBOX_SIZE,
        )

    def draw(self, screen, camera):
        icon = self.item.get_icon()
        _draw_cached_sprite(
            screen, camera, self._render_cache,
            (),
            icon, self.position, icon.get_width(), icon.get_height(),
        )


class PickupManager:
    """Owns the live Pickup/ItemPickup entities dropped in a room. Unlike
    Animal/EnemyManager there's no spawn() from placed objects -- pickups
    only ever come from Explorator._spawn_loot calling spawn()/spawn_item()
    directly at an enemy's death position, and are never persisted."""

    def __init__(self, dungeon):
        self.dungeon = dungeon
        self.pickups = []
        self.item_pickups = []

    def spawn(self, currency_type, world_x, world_y):
        self.pickups.append(Pickup(currency_type, world_x, world_y))

    def spawn_item(self, item, slot, world_x, world_y):
        self.item_pickups.append(ItemPickup(item, slot, world_x, world_y))

    def update(self, dt):
        for pickup in self.pickups:
            pickup.update(dt)
        self.pickups = [pickup for pickup in self.pickups if not pickup.finished]
        self.item_pickups = [pickup for pickup in self.item_pickups if not pickup.collected]

    def collect(self, player_hitbox, inventory):
        """Credits inventory.currency[pickup.currency_type] += 1 the instant
        the player touches a still-"spin" Pickup, then starts its "collect"
        animation -- removal itself happens in update() once that finishes,
        so the coin visually plays its pickup animation instead of just
        vanishing. Already-collecting pickups are left alone (no double
        credit if the player's hitbox keeps overlapping it). ItemPickups
        have no such animation -- see ItemPickup's own docstring for why a
        full inventory slot leaves one on the ground untouched instead."""
        for pickup in self.pickups:
            if pickup.state == "spin" and player_hitbox.colliderect(pickup.get_hitbox()):
                inventory.currency[pickup.currency_type] += 1
                pickup.begin_collect()
                SoundManager().play(f"{pickup.currency_type}_collect")

        for item_pickup in self.item_pickups:
            if (
                not item_pickup.collected
                and inventory.main_slots.get(item_pickup.slot) is None
                and player_hitbox.colliderect(item_pickup.get_hitbox())
            ):
                inventory.main_slots[item_pickup.slot] = item_pickup.item
                item_pickup.collected = True

    def draw(self, screen, camera):
        for pickup in self.pickups:
            pickup.draw(screen, camera)
        for item_pickup in self.item_pickups:
            item_pickup.draw(screen, camera)


class ThrownDynamite:
    """A player-thrown dynamite stick (see Explorator._throw_interact_item):
    flies in a straight line at THROW_SPEED in the direction the player was
    facing at throw time, playing through its 4 frames once -- reaching the
    last frame is literally what triggers detonation (see `exploded`,
    checked by ProjectileManager.update), rather than a separate timer, so
    the explosion always lines up with "the end of the animation" exactly as
    specified. No mid-flight collision with walls/entities -- it's a lobbed
    throw arcing over obstacles to wherever the animation runs out, not a
    line-of-sight projectile."""

    FRAME_SIZE = 16
    THROW_SPEED = 220  # pixels/second
    FRAME_DURATION = 0.15  # seconds per frame -- 4 frames = 0.6s flight
    BLAST_RADIUS_TILES = 2
    BLAST_DAMAGE = 1  # dealt to the player and any live Animal/Enemy in range

    def __init__(self, world_x, world_y, direction):
        self.position = pygame.Vector2(world_x, world_y)
        self.direction = direction
        self.frames = load_dynamite_frames()

        self.frame = 0
        self.animation_timer = 0.0
        self.exploded = False

        self._render_cache = {}

    def update(self, dt):
        if self.exploded:
            return

        self.position += self.direction * self.THROW_SPEED * dt

        if _advance_frame_once(self, dt, self.FRAME_DURATION, len(self.frames)):
            self.exploded = True

    def draw(self, screen, camera):
        sprite = self.frames[self.frame]
        _draw_cached_sprite(
            screen, camera, self._render_cache,
            (self.frame,),
            sprite, self.position, self.FRAME_SIZE, self.FRAME_SIZE,
        )


class Explosion:
    """Purely visual VFX: plays assets/effect/smallexplosion's 9 frames once
    at a fixed world position, then self.finished -- no hitbox, no gameplay
    effect of its own (the actual terrain destruction is
    Dungeon.destroy_area, triggered directly by ProjectileManager alongside
    spawning one of these, not by the animation itself)."""

    FRAME_SIZE = 48
    ANIMATION_SPEED = 0.05

    def __init__(self, world_x, world_y):
        self.position = pygame.Vector2(world_x, world_y)
        self.frames = load_explosion_frames()
        self.frame = 0
        self.animation_timer = 0.0
        self.finished = False
        self._render_cache = {}

    def update(self, dt):
        if self.finished:
            return
        if _advance_frame_once(self, dt, self.ANIMATION_SPEED, len(self.frames)):
            self.finished = True

    def draw(self, screen, camera):
        sprite = self.frames[self.frame]
        _draw_cached_sprite(
            screen, camera, self._render_cache,
            (self.frame,),
            sprite, self.position, self.FRAME_SIZE, self.FRAME_SIZE,
        )


class ProjectileManager:
    """Owns live thrown-item projectiles and their resulting VFX for a room
    (currently just thrown dynamite/its explosion) -- mirrors PickupManager's
    shape: nothing is ever placed via the editor or persisted, entries only
    ever come from Explorator spawning one directly when the player throws
    an equipped item. Detonating a ThrownDynamite (see its own docstring for
    exactly when that happens) is handled right here in update() --
    self.dungeon is already the right Dungeon to carve a hole into, no need
    to bounce this back up to Explorator."""

    def __init__(self, dungeon):
        self.dungeon = dungeon
        self.dynamites = []
        self.explosions = []

    def throw_dynamite(self, world_x, world_y, direction):
        self.dynamites.append(ThrownDynamite(world_x, world_y, direction))

    def update(self, dt, player=None, player_hitbox=None):
        for dynamite in self.dynamites:
            dynamite.update(dt)
            if dynamite.exploded:
                grid_x, grid_y = self.dungeon.world_to_grid(dynamite.position.x, dynamite.position.y)
                self.dungeon.destroy_area(grid_x, grid_y, dynamite.BLAST_RADIUS_TILES)
                self._apply_blast_damage(dynamite, player, player_hitbox)
                self.explosions.append(Explosion(dynamite.position.x, dynamite.position.y))
        self.dynamites = [dynamite for dynamite in self.dynamites if not dynamite.exploded]

        for explosion in self.explosions:
            explosion.update(dt)
        self.explosions = [explosion for explosion in self.explosions if not explosion.finished]

    def _apply_blast_damage(self, dynamite, player, player_hitbox):
        """Deals dynamite.BLAST_DAMAGE to the player (if in this room right
        now -- player_hitbox is None otherwise, see Dungeon.update) and every
        live Animal/Enemy in this room, whenever their hitbox center falls
        within the same circular radius destroy_area just carved into the
        terrain. No immunity for whoever threw it -- standing too close to
        your own blast hurts just the same."""
        radius_px = dynamite.BLAST_RADIUS_TILES * self.dungeon.tile_size

        def _in_blast(hitbox):
            dx = hitbox.centerx - dynamite.position.x
            dy = hitbox.centery - dynamite.position.y
            return dx * dx + dy * dy <= radius_px * radius_px

        if player_hitbox is not None and _in_blast(player_hitbox):
            player.take_damage(dynamite.BLAST_DAMAGE)

        for animal in self.dungeon.animal_manager.animals:
            if animal.alive and _in_blast(animal.get_hitbox()):
                animal.take_damage(dynamite.BLAST_DAMAGE)

        for enemy in self.dungeon.enemy_manager.enemies:
            if enemy.alive and _in_blast(enemy.get_hitbox()):
                enemy.take_damage(dynamite.BLAST_DAMAGE)

    def draw(self, screen, camera):
        for dynamite in self.dynamites:
            dynamite.draw(screen, camera)
        for explosion in self.explosions:
            explosion.draw(screen, camera)