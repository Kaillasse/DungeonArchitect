#Containt all player command and enemies/npc behaviour
from __future__ import annotations
import math
import random
from collections import namedtuple
from pathlib import Path
import pygame

from core.data.ressources import WORLD_SCALE, TILE_SIZE
from core.data.sound_manager import SoundManager, play_card_sound
from core.world.object_manager import (
    load_animal_frames, load_enemy_frames, load_currency_frames, ENEMY_FOLDERS,
    load_dynamite_frames, load_explosion_frames, load_star_frames,
    OBJECT_TYPES, load_npc_frames, mob_types, NPC_DIRECTIONS, effective_loot_cards,
    ITEM_DEFINITIONS, make_item,
)

def _draw_cached_sprite(screen, camera, cache, key_prefix, sprite, position, frame_w, frame_h, flip=False, anchor_feet=False):
    """Scale+cache `sprite` at the camera's current zoom and blit it in world
    space. `key_prefix` + a zoom bucket forms the cache key -- shared by every
    live entity/VFX's draw(). `anchor_feet=True` anchors at (bottom-center) ==
    position, matching a live entity's feet; default (center) matches ground VFX/pickups."""
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

    MAX_HEALTH = 2

    # 0-based frames (3, 4, 5) == the 6-frame attack.png's frames 4-6 -- the
    # window during which a swing actually deals damage.
    ACTIVE_ATTACK_FRAMES = (3, 4, 5)

    # Facing vector per Player.direction (8 values Explorator can set, not
    # just the 5 sprite rows DIRECTIONS covers -- get_sprite_direction mirrors
    # left/right for rendering, but the attack hitbox needs real facing).
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
        the player's own hitbox shifted one tile toward their facing -- a
        simple reach zone, not a directional arc."""
        dx, dy = self.DIRECTION_VECTORS.get(self.direction, (0, 1))
        reach = TILE_SIZE * WORLD_SCALE
        hitbox = self.get_hitbox()
        hitbox.x += int(dx * reach)
        hitbox.y += int(dy * reach)
        return hitbox

    def is_attack_active(self):
        """True on the frames of the current swing that deal damage
        (ACTIVE_ATTACK_FRAMES), once per swing -- _hit_delivered_this_swing
        (reset in play_action) stops a multi-frame window from double-hitting."""
        return (
            self.action == "attack"
            and self.frame in self.ACTIVE_ATTACK_FRAMES
            and not self._hit_delivered_this_swing
        )

    def take_damage(self, amount):
        self.health = max(0, self.health - amount)
        print(f"[combat] Player took {amount} damage (health: {self.health}/{self.MAX_HEALTH})")

    def heal(self, amount):
        """Applies a "heal" card effect (ITEM_DEFINITIONS' "effects" list /
        Explorator._use_interact_item) -- clamped at MAX_HEALTH."""
        self.health = min(self.MAX_HEALTH, self.health + amount)

    def play_action(self, name):
        """Trigger a one-shot action animation (attack/interact/jump) --
        ignored while another action is already playing. jump.png only has 4
        of the 5 DIRECTIONS rows (see _frames_for's fallback)."""
        if self.action is not None or name not in self.sprites:
            return
        self.action = name
        self.animation = name
        self.frame = 0
        self.animation_timer = 0
        self._hit_delivered_this_swing = False
        self._attack_sound_played = False

    def play_fall(self):
        """One-shot fall animation on a successful landing after dropping
        through void (Explorator._attempt_fall) -- reuses jump.png's last 3
        frames as a "falling" pose, starting partway through instead of frame 0."""
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
        """Frame list for (animation, direction), falling back to the
        sheet's LAST row when that direction isn't there -- not every sheet
        has all 5 DIRECTIONS rows (jump.png is missing "back"). Falling back
        to the last row rather than "front" avoids a silent facing-swap bug;
        jump.png is currently the only sheet short a row, always "back"."""
        directions = self.sprites[animation]
        if direction in directions:
            return directions[direction]
        return next(reversed(directions.values()))

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
                # Right as the swing's hit-frame window begins, matching is_attack_active().
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
    """Shared plumbing for Mob (below): a live entity that wanders a room on
    a random idle/move timer with per-axis collision-tested movement, and
    draws a cached zoom-scaled sprite anchored to its feet. Mob owns its own
    state machine (which optional combat/aggro/rest capabilities are active
    depends entirely on its OBJECT_TYPES data) and sets per-instance (not
    class constants, since one class now covers what used to be three):
    HITBOX_WIDTH/HEIGHT, FRAME_SIZE, IDLE_DURATION/MOVE_DURATION,
    ANIMATION_SPEED, LOOPING_STATES, MOVE_STATE_NAME ("move" for
    animal/entity-pack, "movement" for enemy-style), and
    FACES_RIGHT_BY_DEFAULT (whether the unflipped sheet already faces right)."""

    def _hitbox_at(self, x, y):
        """Hitbox for a given (feet-anchored) position, using the exact same
        rounding get_hitbox() re-derives once a candidate is accepted -- see
        _move_toward for why sharing this one formula matters."""
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
        Mob.update's plain-wander path and Mob._update_wander (aggro_capable).
        Doesn't call _advance_animation -- callers do that themselves."""
        self.state_timer -= dt
        if self.state_timer <= 0:
            self._enter_wander_state(self.MOVE_STATE_NAME if self.state == "idle" else "idle")

        if self.state == self.MOVE_STATE_NAME:
            self._move_toward(dt, is_walkable, self.direction, speed)

    def _move_toward(self, dt, is_walkable, direction, speed):
        """Per-axis collision-tested movement toward `direction` (any length)
        at `speed` px/s. Candidate positions are built from the prospective
        float position via _hitbox_at rather than mutating a live Rect in
        place: Rect rounds a float assignment while get_hitbox() truncates
        from the live float -- disagreeing roundings could let a validated
        move settle where its *actual* hitbox pokes into a wall. Using the
        same formula for both eliminates that."""
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

    def _current_frames(self):
        """Hook: current animation's frame list. Default is `self.frames[self.state]`
        -- Mob overrides for an entity-pack mob, whose frames are nested by (action, direction)."""
        return self.frames[self.state]

    def _advance_animation(self, dt):
        """Looping states wrap forever; a non-looping state advances toward
        its last frame then calls a hook instead of wrapping -- a
        wander-only mob never reaches these hooks, a combat-capable one
        overrides them for attack/damaged/death (see Mob)."""
        frames = self._current_frames()
        if not frames:
            # Only reachable for an entity-pack mob with nothing tagged for
            # the current (action, direction) or any fallback. Nothing to animate yet.
            return
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
        """Hook: after a LOOPING_STATES frame wraps forward. No-op by
        default; a combat-capable Mob overrides it to re-arm its attack window."""

    def _on_final_frame_reached(self):
        """Hook: once a non-looping animation reaches its last frame. No-op
        by default (holds forever); Mob overrides it for damaged -> idle."""

    def draw(self, screen, camera):
        frames = self._current_frames()
        if not frames:
            return
        sprite = frames[min(self.frame, len(frames) - 1)]
        _draw_cached_sprite(
            screen, camera, self._render_cache,
            (self.state, self.flip, self.frame),
            sprite, self.position, self.FRAME_SIZE, self.FRAME_SIZE,
            flip=self.flip, anchor_feet=True,
        )


def _bucket_direction(vector):
    """The nearest of Player.DIRECTION_VECTORS' 8 unit vectors to `vector`
    (already unit-length), by dot product -- the entity-pack equivalent of
    Player.get_sprite_direction, but a real (non-mirrored) 8-way lookup since
    an entity pack has all 8 directions hand-drawn and tagged."""
    best_direction = None
    best_dot = -2.0  # lower than any possible dot product of two unit vectors
    for direction, (dx, dy) in Player.DIRECTION_VECTORS.items():
        dot = vector.x * dx + vector.y * dy
        if dot > best_dot:
            best_dot = dot
            best_direction = direction
    return best_direction


PlayerRef = namedtuple("PlayerRef", ("player", "hitbox", "session"))


def _entity_rect_is_free(dungeon, rect, entities, moving_entity, player_refs):
    """Shared by MobManager._is_free: walls/closed gates first (cheapest),
    then every other live Mob in `entities` (dead ones don't block -- every
    Mob always carries `alive`), then every player standing on this room's
    floor right now (`player_refs` empty otherwise, see Dungeon.update)."""
    if not dungeon.is_rect_walkable(rect):
        return False

    for other in entities:
        if other is not moving_entity and other.alive and rect.colliderect(other.get_hitbox()):
            return False

    for ref in player_refs:
        if rect.colliderect(ref.hitbox):
            return False

    return True


def _is_over_void(dungeon, entity):
    """True if `entity`'s feet now sit over an EMPTY cell (destroyed terrain
    or wandered off the room's edge). Shared by MobManager/PickupManager's own void-culling."""
    return dungeon.is_void_at(*dungeon.world_to_grid(entity.position.x, entity.position.y))


class _EntityManager:
    """Shared shape for MobManager: owns a list of live, per-frame entities
    spawned from a dungeon's placed objects of ENTITY_TYPES, testing free
    space and drawing identically. Only update() differs, so that's all
    subclasses define. Each subclass exposes its own list (e.g. self.mobs,
    read directly by explorator.py/assembly.py) through the `_entities` property."""

    ENTITY_CLASS = None
    ENTITY_TYPES = ()

    def __init__(self, dungeon):
        self.dungeon = dungeon

    @property
    def _entities(self):
        raise NotImplementedError

    @_entities.setter
    def _entities(self, value):
        raise NotImplementedError

    def _entity_types(self):
        """Hook: which OBJECT_TYPES ids this manager spawns. Default is
        ENTITY_TYPES -- MobManager overrides to call mob_types() fresh each
        time instead, since a mob type can be registered mid-session via the sprite editor."""
        return self.ENTITY_TYPES

    def spawn(self):
        """(Re)build the live entity list from the dungeon's currently-placed
        objects of ENTITY_TYPES. Only called by Explorator on room load --
        never during editing (would reset wander/chase state every paint stroke)."""
        entity_types = self._entity_types()
        self._entities = [
            self.ENTITY_CLASS(obj["type"], obj["x"], obj["y"], self.dungeon)
            for obj in self.dungeon.object_manager.objects
            if obj["type"] in entity_types
        ]

    def _is_free(self, rect, moving_entity, player_refs):
        return _entity_rect_is_free(self.dungeon, rect, self._entities, moving_entity, player_refs)

    def draw(self, screen, camera):
        for entity in self._entities:
            entity.draw(screen, camera)


class Mob(_WanderingEntity):
    """The single live-entity class for every wandering, placeable creature
    -- replaces the old Animal/Enemy/Npc split. Which capabilities a Mob has
    is driven entirely by its OBJECT_TYPES data, not a Python subclass:

    - Wander (idle/move alternation): always present, via _WanderingEntity.
    - Combat (health/alive/take_damage/damaged+death states/despawn-hold):
      present iff "health" in stats (self.combat_capable). Absent -> alive
      stays True forever, take_damage no-ops (today's unkillable-PNJ behavior,
      now via data absence).
    - Aggro/chase/attack: present iff "aggro_range" AND "attack_range" are
      both in stats (self.aggro_capable). A combat-capable mob with neither
      can be killed but never fights back (chicken/cow/pig/sheep's profile, generalized).
    - Rest/posture chain (sit/lie): present iff wander_actions has a "sitting"
      role actually tagged in the entity pack (_has_action) -- only reachable
      for an entity-pack mob; never interleaves with the aggro/attack path (see below).
    - Interaction/dialogue: self.interactable, from OBJECT_TYPES[type_id]["interactable"]
      -- purely informational here.
    - Loot at death: object_manager.effective_loot_cards/_spawn_loot_pickups,
      now firing for ANY combat-capable mob that dies.

    Frame source (decided once at construction from data shape): "entity_pack"
    present -> action x direction lookup (load_npc_frames); else mob_type in
    ENEMY_FOLDERS -> 5-state sheet (load_enemy_frames); else -> flat 2-state
    idle/move sheet (load_animal_frames). _current_frames() falls back to
    "idle" whenever the logical state (attack/damaged/death) has no frames of
    its own in a flat-frame mob's dict -- a mob given combat stats without a
    matching ENEMY_FOLDERS entry still fights/dies mechanically correctly,
    just visually stays on idle/move until real art exists.

    Known scope limit: an entity-pack mob never enters the aggro/attack
    machinery even with combat stats -- wander/rest takes full priority.
    Unifying the two would need the combat state machine to read frames
    through _action_frames_for instead of a flat self.frames[state] lookup --
    left for a future pass."""

    FRAME_SIZE = 32
    REST_DURATION = (2.0, 4.5)  # how long "sit"/"lie" hold before the next decision (entity-pack mobs only)
    LIE_CHANCE = 0.35  # probability "sit" deepens into "lie" rather than heading back to "move"
    RUN_CHANCE = 0.4  # probability "move" picks "run" over "move" when both are tagged (entity-pack mobs only)
    RUN_SPEED = 55  # only used if "run" is tagged (see _enter_move)
    # Single-pass states, advanced by _advance_transition (never by
    # state_timer): "to_sit"/"to_move" play "sitting" (forward/reversed),
    # "to_lie"/"to_sit_from_lie" play "laying".
    _TRANSITION_STATES = ("to_sit", "to_lie", "to_sit_from_lie", "to_move")

    # Seconds to hold the death animation's last frame before the corpse is
    # despawn-worthy -- MobManager.update removes it and spawns the reward spark.
    DEATH_DESPAWN_DELAY = 3.0

    def __init__(self, mob_type, grid_x, grid_y, dungeon):
        config = OBJECT_TYPES[mob_type]
        self.mob_type = mob_type
        self.stats = config.get("stats", {})
        self.interactable = bool(config.get("interactable"))
        self.tile_size = dungeon.tile_size
        self.position = pygame.Vector2(*dungeon.grid_to_world(grid_x, grid_y))

        self.combat_capable = "health" in self.stats
        self.aggro_capable = "aggro_range" in self.stats and "attack_range" in self.stats

        entity_pack = config.get("entity_pack")
        if entity_pack is not None:
            # Rest/posture chain path (formerly Npc) -- see class docstring
            # on why this never interleaves with the aggro/attack path.
            self._entity_pack = entity_pack
            self.frames = load_npc_frames(entity_pack)
            self.wander_actions = config.get("wander_actions", {})
            # Direction shown until the first move -- a mob keeps facing its
            # last movement direction through however deep a rest goes.
            self.current_direction = NPC_DIRECTIONS[0]
            self._move_action = "move"  # "move" or "run", chosen fresh each _enter_move
            self._transition_role = None  # "sitting" or "laying" during a _TRANSITION_STATES state
            self._transition_reverse = False
            self.IDLE_DURATION = (2.0, 4.5)
            self.MOVE_DURATION = (1.5, 3.0)
            self.ANIMATION_SPEED = 0.2
            self._move_speed = self.stats.get("move_speed", 30)
            self.FACES_RIGHT_BY_DEFAULT = False  # inert here -- draw() always uses flip=False, see below
            self.LOOPING_STATES = ("idle", "move")
            self.MOVE_STATE_NAME = "move"
        else:
            # Flat-frame path (formerly Animal/Enemy) -- state names must
            # match whichever loader's own frame-dict keys (a plain animal's
            # frames only ever has "idle"/"move", never "movement").
            self._entity_pack = None
            self.wander_actions = {}
            uses_enemy_states = mob_type in ENEMY_FOLDERS
            self.frames = load_enemy_frames(mob_type) if uses_enemy_states else load_animal_frames(mob_type)
            if uses_enemy_states:
                self.LOOPING_STATES = ("idle", "movement", "attack")
                self.MOVE_STATE_NAME = "movement"
                self.FACES_RIGHT_BY_DEFAULT = True  # the skeleton sheets face right by default
                self.ANIMATION_SPEED = 0.2
            else:
                self.LOOPING_STATES = ("idle", "move")
                self.MOVE_STATE_NAME = "move"
                self.FACES_RIGHT_BY_DEFAULT = False  # the animal sheets face left by default
                self.ANIMATION_SPEED = 0.25
            self.IDLE_DURATION = (1.0, 2.5)
            self.MOVE_DURATION = (1.0, 2.0)
            self._move_speed = self.stats.get("move_speed", 40)

        # A combat-capable mob gets the old Enemy hitbox (its attack-reach
        # math is tuned against these dimensions); everything else keeps the
        # old Animal/Npc hitbox (both already agreed on 14x8).
        self.HITBOX_WIDTH, self.HITBOX_HEIGHT = (16, 10) if self.combat_capable else (14, 8)

        self.state = "idle"
        self.direction = pygame.Vector2()
        self.flip = False
        self.frame = 0
        self.animation_timer = 0
        self.state_timer = random.uniform(*self.IDLE_DURATION)

        self.health = self.stats.get("health", 0)
        self.alive = True  # every Mob always carries this -- see _entity_rect_is_free's own comment
        self._hit_delivered_this_swing = False
        self._attack_sound_played = False
        # Death-despawn bookkeeping (see DEATH_DESPAWN_DELAY/update()/
        # MobManager.update). _death_animation_done flips True the moment the
        # death anim's last frame is FIRST reached; only then does
        # death_hold_timer start counting toward despawn_ready.
        # reward_spawned guards against spawning the reward spark twice.
        # Both stay permanently unused/False for a non-combat-capable mob.
        self._death_animation_done = False
        self.death_hold_timer = 0.0
        self.despawn_ready = False
        self.reward_spawned = False

        self._render_cache = {}

    # -- frame lookup / draw --------------------------------------------

    def _has_action(self, role):
        """True if wander_actions[role] points at an action ACTUALLY tagged
        in this pack (a role can name an action never tagged, e.g. mob
        registered then pack edited since). Entity-pack mobs only."""
        action = self.wander_actions.get(role)
        return bool(action) and action in self.frames

    def _action_frames_for(self, action_name):
        """Frames for `action_name` at self.current_direction, cascading
        instead of crashing if the exact direction isn't tagged yet (a mob
        only needs ONE tile tagged to register). Tries: exact direction; any
        other direction of the same action; a direction of ANY action in the
        pack. [] only if nothing at all is tagged."""
        action_frames = self.frames.get(action_name, {}) if action_name else {}
        if self.current_direction in action_frames:
            return action_frames[self.current_direction]
        if action_frames:
            return next(iter(action_frames.values()))
        for other_action_frames in self.frames.values():
            if self.current_direction in other_action_frames:
                return other_action_frames[self.current_direction]
            if other_action_frames:
                return next(iter(other_action_frames.values()))
        return []

    def _action_frames(self, role):
        return self._action_frames_for(self.wander_actions.get(role))

    def _current_action_name(self):
        if self.state in self._TRANSITION_STATES:
            return self.wander_actions.get(self._transition_role)
        if self.state == "sit":
            return self.wander_actions.get("sitting")
        if self.state == "lie":
            return self.wander_actions.get("laying")
        if self.state == "move":
            return self.wander_actions.get(self._move_action)
        return self.wander_actions.get("idle")

    def _current_frames(self):
        """Overrides _WanderingEntity's flat lookup for an entity-pack mob
        (nested by action x direction); for a flat-frame mob, falls back to
        "idle" whenever the current state has no frames of its own."""
        if self._entity_pack is not None:
            return self._action_frames_for(self._current_action_name())
        frames = self.frames.get(self.state)
        if frames:
            return frames
        return self.frames.get("idle", [])

    def draw(self, screen, camera):
        frames = self._current_frames()
        if not frames:
            return
        sprite = frames[min(self.frame, len(frames) - 1)]
        if self._entity_pack is not None:
            # A PNJ-style sheet already has all 8 real directions drawn --
            # never mirrored, unlike a flat-frame mob's single-facing sheet.
            cache_key = (self._current_action_name(), self.current_direction, self.frame)
            flip = False
        else:
            cache_key = (self.state, self.flip, self.frame)
            flip = self.flip
        _draw_cached_sprite(
            screen, camera, self._render_cache, cache_key,
            sprite, self.position, self.FRAME_SIZE, self.FRAME_SIZE,
            flip=flip, anchor_feet=True,
        )

    # -- rest/posture chain (entity-pack mobs only) ----------------------

    def _enter_move(self):
        angle = random.uniform(0, 2 * math.pi)
        self.direction = pygame.Vector2(math.cos(angle), math.sin(angle))
        self.current_direction = _bucket_direction(self.direction)
        self._move_action = "run" if self._has_action("run") and random.random() < self.RUN_CHANCE else "move"
        self.state = "move"
        self.frame = 0
        self.animation_timer = 0
        self.state_timer = random.uniform(*self.MOVE_DURATION)

    def _enter_idle(self):
        """Fallback simple rest -- used while "sitting" isn't tagged at all, matching pre-rest-chain behavior."""
        self.direction = pygame.Vector2()
        self.state = "idle"
        self.frame = 0
        self.animation_timer = 0
        self.state_timer = random.uniform(*self.IDLE_DURATION)

    def _enter_sit(self):
        self.direction = pygame.Vector2()
        self.state = "sit"
        frames = self._action_frames("sitting")
        self.frame = max(0, len(frames) - 1)  # freeze on the full "seated" pose
        self.animation_timer = 0
        self.state_timer = random.uniform(*self.REST_DURATION)

    def _enter_lie(self):
        self.direction = pygame.Vector2()
        self.state = "lie"
        frames = self._action_frames("laying")
        self.frame = max(0, len(frames) - 1)  # freeze on the full "lying" pose
        self.animation_timer = 0
        self.state_timer = random.uniform(*self.REST_DURATION)

    def _enter_transition(self, state, role, reverse):
        """A single-pass, reversible state: forward starts at frame 0 and
        advances to the last; reversed starts at the last and counts down.
        `role` names which wander_actions entry supplies the frames."""
        self.direction = pygame.Vector2()
        self.state = state
        self._transition_role = role
        self._transition_reverse = reverse
        frames = self._action_frames(role)
        self.frame = max(0, len(frames) - 1) if reverse else 0
        self.animation_timer = 0

    def _advance_state(self):
        """Called when state_timer hits 0 -- picks the next link in
        move <-> [sitting] <-> sit <-> [laying] <-> lie, or falls back to
        simple idle <-> move if "sitting" isn't tagged. Never called during a
        _TRANSITION_STATES state (those end via _advance_transition instead)."""
        if self.state == "move":
            if self._has_action("sitting"):
                self._enter_transition("to_sit", "sitting", reverse=False)
            else:
                self._enter_idle()
        elif self.state == "idle":
            self._enter_move()
        elif self.state == "sit":
            if self._has_action("laying") and random.random() < self.LIE_CHANCE:
                self._enter_transition("to_lie", "laying", reverse=False)
            else:
                self._enter_transition("to_move", "sitting", reverse=True)
        elif self.state == "lie":
            self._enter_transition("to_sit_from_lie", "laying", reverse=True)

    def _advance_transition(self, dt):
        """Advances the active _TRANSITION_STATES state frame by frame in the
        right direction, handing off to the real next state once it reaches the end."""
        frames = self._action_frames(self._transition_role)
        self.animation_timer += dt
        if self.animation_timer < self.ANIMATION_SPEED or not frames:
            return
        self.animation_timer = 0

        if self._transition_reverse:
            if self.frame > 0:
                self.frame -= 1
                return
        elif self.frame < len(frames) - 1:
            self.frame += 1
            return

        if self.state == "to_sit":
            self._enter_sit()
        elif self.state == "to_lie":
            self._enter_lie()
        elif self.state == "to_sit_from_lie":
            self._enter_sit()
        elif self.state == "to_move":
            self._enter_move()

    def _advance_loop_animation(self, dt):
        """Loops "idle"/"move" (the only two truly-looping states) -- "sit"/"lie" stay frozen where their entry transition left them."""
        if self.state not in ("idle", "move"):
            return
        frames = self._current_frames()
        if not frames:
            return
        self.animation_timer += dt
        if self.animation_timer < self.ANIMATION_SPEED:
            return
        self.animation_timer = 0
        self.frame = (self.frame + 1) % len(frames)

    # -- combat/aggro/attack (combat_capable/aggro_capable mobs only) ---

    def get_attack_hitbox(self):
        """Melee reach checked against the player during the active-frame
        window -- this mob's own hitbox inflated by one tile in every
        direction, rather than translated toward the player like
        Player.get_attack_hitbox: a combat mob only flips left/right with no
        discrete facing to translate along, and a translated box would
        overshoot an already-adjacent player."""
        reach = self.tile_size
        return self.get_hitbox().inflate(reach * 2, reach * 2)

    def take_damage(self, amount):
        """A no-op for a non-combat-capable mob (no "health" in stats) --
        how a PNJ/decorative mob stays unkillable, now via data."""
        if not self.combat_capable or not self.alive:
            return
        self.health -= amount
        self.frame = 0
        self.animation_timer = 0
        config = OBJECT_TYPES.get(self.mob_type, {})
        sounds, pitch = config.get("sounds", {}), config.get("sound_pitch", {})
        if self.health <= 0:
            self.alive = False
            self.state = "death"
            play_card_sound(sounds, "death", pitch_range=pitch.get("death"))
        else:
            self.state = "damaged"
            play_card_sound(sounds, "damaged", fallback_event="skeleton_damaged", pitch_range=pitch.get("damaged"))

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
        """Ambient background behavior for an aggro_capable mob out of range
        -- alternates idle/movement on a random timer, random direction each time."""
        if self.state not in ("idle", self.MOVE_STATE_NAME):
            self._enter_wander_state("idle")
        self._wander_tick(dt, is_walkable, self._move_speed)

    def _update_chase(self, dt, is_walkable, target_hitbox):
        self._enter_state(self.MOVE_STATE_NAME)
        target = pygame.Vector2(target_hitbox.centerx, target_hitbox.centery)
        self._move_toward(dt, is_walkable, target - self.position, self._move_speed)

    def _nearest_player_ref(self, player_refs):
        """(ref, distance_px) for whichever player in `player_refs` is
        closest to this mob right now, or (None, None)."""
        nearest = None
        nearest_distance = None
        for ref in player_refs:
            dx = ref.hitbox.centerx - self.position.x
            dy = ref.hitbox.centery - self.position.y
            distance = math.hypot(dx, dy)
            if nearest_distance is None or distance < nearest_distance:
                nearest, nearest_distance = ref, distance
        return nearest, nearest_distance

    def _on_loop_frame_advanced(self):
        if self.state != "attack":
            return
        # A fresh attack swing starts its own new active-frame window.
        if self.frame == 0:
            self._hit_delivered_this_swing = False
            self._attack_sound_played = False
        # Right as the swing's hit-frame window begins (matches active_attack_frames in update()).
        if self.frame in self.stats.get("active_attack_frames", ()) and not self._attack_sound_played:
            config = OBJECT_TYPES.get(self.mob_type, {})
            play_card_sound(
                config.get("sounds", {}), "attack", fallback_event=f"{self.mob_type}_attack",
                pitch_range=config.get("sound_pitch", {}).get("attack"),
            )
            self._attack_sound_played = True

    def _on_final_frame_reached(self):
        if self.state == "damaged":
            # Played once; return to neutral and let the next update() re-evaluate distance.
            self.state = "idle"
            self.frame = 0
        elif self.state == "death":
            # Holds on the last frame (this fires again every tick after --
            # _death_animation_done only needs to flip True the first time).
            self._death_animation_done = True

    # -- top-level update -------------------------------------------------

    def update(self, dt, is_walkable, player_refs=()):
        if not self.alive:
            self._advance_animation(dt)
            if self._death_animation_done and not self.despawn_ready:
                self.death_hold_timer += dt
                if self.death_hold_timer >= self.DEATH_DESPAWN_DELAY:
                    self.despawn_ready = True
            return

        if self.combat_capable and self.state == "damaged":
            self._advance_animation(dt)
            return

        if self._entity_pack is not None:
            if self.state in self._TRANSITION_STATES:
                self._advance_transition(dt)
                return
            self.state_timer -= dt
            if self.state_timer <= 0:
                self._advance_state()
            if self.state == "move":
                speed = self.RUN_SPEED if self._move_action == "run" else self._move_speed
                self._move_toward(dt, is_walkable, self.direction, speed)
            self._advance_loop_animation(dt)
            return

        if self.aggro_capable:
            nearest_ref, distance_px = self._nearest_player_ref(player_refs)
            if nearest_ref is not None and distance_px <= self.stats["attack_range"] * self.tile_size:
                self._enter_state("attack")
                self.flip = nearest_ref.hitbox.centerx < self.position.x
            elif nearest_ref is not None and distance_px <= self.stats["aggro_range"] * self.tile_size:
                self._update_chase(dt, is_walkable, nearest_ref.hitbox)
            else:
                self._update_wander(dt, is_walkable)
        else:
            self._wander_tick(dt, is_walkable, self._move_speed)

        self._advance_animation(dt)

        if (
            self.aggro_capable and self.state == "attack"
            and self.frame in self.stats["active_attack_frames"]
            and not self._hit_delivered_this_swing
        ):
            # Mirrors the player's own attack: hits every overlapping mob, not just the nearest.
            attack_hitbox = self.get_attack_hitbox()
            hit_landed = False
            for ref in player_refs:
                if attack_hitbox.colliderect(ref.hitbox):
                    ref.player.take_damage(1)
                    hit_landed = True
            if hit_landed:
                self._hit_delivered_this_swing = True


class MobManager(_EntityManager):
    """Owns every live Mob wandering a room, spawned from its placed mob
    objects (mob_types()) -- replaces the old AnimalManager/EnemyManager/
    NpcManager trio. A non-combat-capable mob never "dies" (take_damage
    no-ops); a combat-capable one plays its death animation and holds the
    last frame for Mob.DEATH_DESPAWN_DELAY before removal. One standing over
    void is removed outright with no reward -- no sensible corpse for something that fell through the floor."""

    ENTITY_CLASS = Mob

    def __init__(self, dungeon):
        super().__init__(dungeon)
        self.mobs = []

    def _entity_types(self):
        return mob_types()

    @property
    def _entities(self):
        return self.mobs

    @_entities.setter
    def _entities(self, value):
        self.mobs = value

    def update(self, dt, player_refs=(), room_offset=(0, 0)):
        for mob in self.mobs:
            mob.update(
                dt,
                lambda rect, _mob=mob: self._is_free(rect, _mob, player_refs),
                player_refs,
            )
            if mob.despawn_ready and not mob.reward_spawned:
                # Guarded by reward_spawned since despawn_ready can stay True
                # for more than one frame before the comprehension below drops it.
                mob.reward_spawned = True
                self._spawn_death_reward(mob, player_refs, room_offset)
        self.mobs = [
            mob for mob in self.mobs
            if not mob.despawn_ready and not _is_over_void(self.dungeon, mob)
        ]

    def _spawn_death_reward(self, mob, player_refs, room_offset):
        """Magnetic star toward the nearest player, spawning the mob's own
        loot table (effective_loot_cards) as ground pickups on arrival.
        No-op if the room has no players in it right now."""
        if not player_refs:
            return
        nearest = min(
            player_refs, key=lambda ref: pygame.Vector2(ref.hitbox.center).distance_squared_to(mob.position),
        )
        target_player = nearest.player
        card_id = mob.mob_type

        def _on_arrival(position):
            _spawn_loot_pickups(self.dungeon, position, card_id)

        self.dungeon.effect_manager.spawn_destruction_spark(
            mob.position.x, mob.position.y, lambda: target_player.position,
            room_offset=room_offset, on_arrival=_on_arrival,
        )


def _advance_frame_once(entity, dt, duration, frame_count):
    """Ticks entity.animation_timer/frame toward frame_count-1 and holds
    there once reached, returning True the frame it arrives -- shared "play
    once" timer tail for Pickup's "collect" state, ThrownDynamite, and Explosion."""
    entity.animation_timer += dt
    if entity.animation_timer < duration:
        return False
    entity.animation_timer = 0
    if entity.frame < frame_count - 1:
        entity.frame += 1
        return False
    return True


def _move_toward(position, target, speed, dt):
    """Moves `position` at most `speed*dt` toward `target`, without
    overshooting -- shared by DestructionSpark and PickupManager's own homing, so both move identically."""
    delta = target - position
    distance = delta.length()
    if distance <= speed * dt or distance == 0:
        return pygame.Vector2(target)
    return position + delta.normalize() * speed * dt


class Pickup:
    """A currency pickup dropped by a dead enemy (Explorator._spawn_loot) --
    never saved to room.json, never blocks movement. Two states: "spin" loops
    until the player's hitbox touches it (PickupManager.collect calls
    begin_collect()), then "collect" plays once (row 1) before PickupManager removes it (self.finished)."""

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
    from a dead mob, see object_manager.effective_loot_cards/
    _spawn_loot_pickups) -- unlike Pickup, no spin/collect animation, just a
    single static frame (Item.get_icon(), frame 0 via icon_rect). Removes
    itself and drops `item` into inventory.main_slots[slot] the instant the
    player's hitbox touches it, but only if that slot is empty -- an
    already-equipped slot leaves the pickup untouched."""

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


class CardPickup:
    """A card waiting on the ground -- what a DestructionSpark becomes the
    instant it reaches its target (EffectManager.spawn_destruction_spark/
    _spawn_loot_pickups), rather than crediting anything invisibly. Same
    static-single-frame shape as ItemPickup, but there's no inventory slot to
    fill -- collecting calls Inventory.add_card(card_id) instead (stacks
    onto grid_slots, not main_slots). Icon resolved once at construction via
    core.data.cards.resolve_card_sprite (deferred import, same cycle concern as CardStub)."""

    HITBOX_SIZE = 16

    def __init__(self, card_id, world_x, world_y):
        from core.data.cards import resolve_card_sprite
        self.card_id = card_id
        self.position = pygame.Vector2(world_x, world_y)
        self.collected = False
        self._icon = resolve_card_sprite(card_id) or pygame.Surface((16, 16), pygame.SRCALPHA)
        self._render_cache = {}

    def get_hitbox(self):
        return pygame.Rect(
            int(self.position.x - self.HITBOX_SIZE / 2),
            int(self.position.y - self.HITBOX_SIZE / 2),
            self.HITBOX_SIZE,
            self.HITBOX_SIZE,
        )

    def draw(self, screen, camera):
        _draw_cached_sprite(
            screen, camera, self._render_cache,
            (),
            self._icon, self.position, self._icon.get_width(), self._icon.get_height(),
        )


class PickupManager:
    """Owns the live Pickup/ItemPickup/CardPickup entities dropped in a
    room. Unlike MobManager there's no spawn() from placed objects --
    pickups only come from Explorator._spawn_loot (enemy death) or
    _spawn_loot_pickups (a DestructionSpark's on_arrival hook), never persisted."""

    # Slower than DestructionSpark.HOMING_SPEED -- a gentle pull once in
    # range, not a projectile snapping onto the player instantly.
    MAGNET_SPEED = 140

    def __init__(self, dungeon):
        self.dungeon = dungeon
        self.pickups = []
        self.item_pickups = []
        self.card_pickups = []

    def spawn(self, currency_type, world_x, world_y):
        self.pickups.append(Pickup(currency_type, world_x, world_y))

    def spawn_item(self, item, slot, world_x, world_y):
        self.item_pickups.append(ItemPickup(item, slot, world_x, world_y))

    def spawn_card(self, card_id, world_x, world_y):
        self.card_pickups.append(CardPickup(card_id, world_x, world_y))

    def _nearest_target_within(self, pickup, player_refs, magnet_radius):
        """The closest player_refs position within magnet_radius of `pickup`,
        or None (magnet_radius <= 0 always returns None).

        Uses ref.hitbox.center, NOT ref.player.position: pickup.position is
        room-LOCAL, but Player.position is always GLOBAL. ref.hitbox is
        already shifted to this room's local space by whoever built
        player_refs, so comparing it directly is correct with no conversion
        -- unlike DestructionSpark's target_getter, which must track a live
        Player across future frames and can't reuse this shortcut."""
        if magnet_radius <= 0:
            return None
        best = None
        best_dist_sq = magnet_radius * magnet_radius
        for ref in player_refs:
            target = pygame.Vector2(ref.hitbox.center)
            dist_sq = pickup.position.distance_squared_to(target)
            if dist_sq <= best_dist_sq:
                best_dist_sq = dist_sq
                best = target
        return best

    def update(self, dt, player_refs=(), magnet_radius=0):
        for pickup in self.pickups:
            # Only a still-"spin" coin gets pulled -- one already collecting is about to be removed regardless.
            if pickup.state == "spin":
                target = self._nearest_target_within(pickup, player_refs, magnet_radius)
                if target is not None:
                    pickup.position = _move_toward(pickup.position, target, self.MAGNET_SPEED, dt)
            pickup.update(dt)
        for item_pickup in self.item_pickups:
            if not item_pickup.collected:
                target = self._nearest_target_within(item_pickup, player_refs, magnet_radius)
                if target is not None:
                    item_pickup.position = _move_toward(item_pickup.position, target, self.MAGNET_SPEED, dt)
        for card_pickup in self.card_pickups:
            if not card_pickup.collected:
                target = self._nearest_target_within(card_pickup, player_refs, magnet_radius)
                if target is not None:
                    card_pickup.position = _move_toward(card_pickup.position, target, self.MAGNET_SPEED, dt)
        # A pickup where the terrain got destroyed out from under it falls
        # through and is lost, same as every other entity's void-culling.
        self.pickups = [
            pickup for pickup in self.pickups
            if not pickup.finished and not _is_over_void(self.dungeon, pickup)
        ]
        self.item_pickups = [
            pickup for pickup in self.item_pickups
            if not pickup.collected and not _is_over_void(self.dungeon, pickup)
        ]
        self.card_pickups = [
            pickup for pickup in self.card_pickups
            if not pickup.collected and not _is_over_void(self.dungeon, pickup)
        ]

    def collect(self, player_hitbox, inventory):
        """Credits inventory.currency[pickup.currency_type] += 1 the instant
        the player touches a still-"spin" Pickup, then starts its "collect"
        animation -- removal happens in update() once that finishes.
        Already-collecting pickups are left alone. ItemPickups have no such
        animation (see ItemPickup's own docstring).

        Returns the list of card_id collected THIS call (possibly empty) --
        unlike currency/items, a card can't be credited here: it needs to
        reach Profile.card_stash eventually (Explorator._resolve_pickups/
        _trigger_victory), which this method can't access. inventory.add_card
        handles the immediate visible part (stacking grid_slots) -- a full grid leaves the pickup untouched."""
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

        collected_card_ids = []
        for card_pickup in self.card_pickups:
            if (
                not card_pickup.collected
                and player_hitbox.colliderect(card_pickup.get_hitbox())
                and inventory.add_card(card_pickup.card_id)
            ):
                card_pickup.collected = True
                collected_card_ids.append(card_pickup.card_id)
        return collected_card_ids

    def draw(self, screen, camera):
        for pickup in self.pickups:
            pickup.draw(screen, camera)
        for item_pickup in self.item_pickups:
            item_pickup.draw(screen, camera)
        for card_pickup in self.card_pickups:
            card_pickup.draw(screen, camera)


class ThrownDynamite:
    """A player-thrown dynamite stick (Explorator._use_interact_item): flies
    straight at `speed` in the direction the player faced at throw time,
    playing its 4 frames once -- reaching the last frame IS the detonation
    trigger (`exploded`, checked by ProjectileManager.update), not a separate
    timer, so the explosion lines up with the animation's end exactly. No
    mid-flight collision -- a lobbed throw, not a line-of-sight projectile.

    `speed`/`blast_radius_tiles`/`blast_damage` come from whichever card's
    "throwable"/"explosive" capabilities triggered this throw
    (ProjectileManager.throw_dynamite/ITEM_DEFINITIONS["dynamite"]) rather
    than being fixed to dynamite -- DEFAULT_* are just today's dynamite
    values, kept as fallbacks for a direct construction without capability params."""

    FRAME_SIZE = 16
    FRAME_DURATION = 0.15  # seconds per frame -- 4 frames = 0.6s flight
    DEFAULT_SPEED = 220  # pixels/second
    DEFAULT_BLAST_RADIUS_TILES = 2
    DEFAULT_BLAST_DAMAGE = 1  # dealt to the player and any live Mob in range

    def __init__(self, world_x, world_y, direction, speed=DEFAULT_SPEED,
                 blast_radius_tiles=DEFAULT_BLAST_RADIUS_TILES, blast_damage=DEFAULT_BLAST_DAMAGE):
        self.position = pygame.Vector2(world_x, world_y)
        self.direction = direction
        self.speed = speed
        self.blast_radius_tiles = blast_radius_tiles
        self.blast_damage = blast_damage
        self.frames = load_dynamite_frames()

        self.frame = 0
        self.animation_timer = 0.0
        self.exploded = False

        self._render_cache = {}

    def update(self, dt):
        if self.exploded:
            return

        self.position += self.direction * self.speed * dt

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
    effect (terrain destruction is Dungeon.destroy_area, triggered directly
    by ProjectileManager alongside spawning one of these, not by the animation)."""

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
    shape: nothing is placed via the editor or persisted, entries only come
    from Explorator spawning one when the player throws an equipped item.
    Detonating a ThrownDynamite is handled right here in update() --
    self.dungeon is already the right Dungeon to carve a hole into."""

    def __init__(self, dungeon):
        self.dungeon = dungeon
        self.dynamites = []
        self.explosions = []

    def throw_dynamite(self, world_x, world_y, direction, capabilities=None):
        """`capabilities` is the throwing card's own capabilities dict
        (ITEM_DEFINITIONS["dynamite"]/Explorator._use_interact_item) -- this
        manager stays free of any object_manager/ITEM_DEFINITIONS dependency,
        it just reads whichever "throwable"/"explosive" params the caller
        resolved. Missing/empty falls back to ThrownDynamite's own DEFAULT_* constants."""
        capabilities = capabilities or {}
        throwable = capabilities.get("throwable") or {}
        explosive = capabilities.get("explosive") or {}
        self.dynamites.append(ThrownDynamite(
            world_x, world_y, direction,
            speed=throwable.get("speed", ThrownDynamite.DEFAULT_SPEED),
            blast_radius_tiles=explosive.get("radius_tiles", ThrownDynamite.DEFAULT_BLAST_RADIUS_TILES),
            blast_damage=explosive.get("damage", ThrownDynamite.DEFAULT_BLAST_DAMAGE),
        ))

    def update(self, dt, player_refs=(), room_offset=(0, 0)):
        for dynamite in self.dynamites:
            dynamite.update(dt)
            if dynamite.exploded:
                grid_x, grid_y = self.dungeon.world_to_grid(dynamite.position.x, dynamite.position.y)
                destroyed_cells, card_ids_by_cell = self.dungeon.destroy_area(
                    grid_x, grid_y, dynamite.blast_radius_tiles,
                )
                self._apply_blast_damage(dynamite, player_refs)
                self.explosions.append(Explosion(dynamite.position.x, dynamite.position.y))
                self._spawn_destruction_sparks(
                    destroyed_cells, card_ids_by_cell, dynamite.position, player_refs, room_offset,
                )
        self.dynamites = [dynamite for dynamite in self.dynamites if not dynamite.exploded]

        for explosion in self.explosions:
            explosion.update(dt)
        self.explosions = [explosion for explosion in self.explosions if not explosion.finished]

    def _apply_blast_damage(self, dynamite, player_refs):
        """Deals dynamite.blast_damage to every player in this room and every
        live Mob whose hitbox center falls within the same circular radius
        destroy_area just carved. No immunity for whoever threw it. One loop
        over every mob (Mob.take_damage already no-ops for a
        non-combat-capable one, e.g. a PNJ standing too close)."""
        radius_px = dynamite.blast_radius_tiles * self.dungeon.tile_size

        def _in_blast(hitbox):
            dx = hitbox.centerx - dynamite.position.x
            dy = hitbox.centery - dynamite.position.y
            return dx * dx + dy * dy <= radius_px * radius_px

        for ref in player_refs:
            if _in_blast(ref.hitbox):
                ref.player.take_damage(dynamite.blast_damage)

        for mob in self.dungeon.mob_manager.mobs:
            if mob.alive and _in_blast(mob.get_hitbox()):
                mob.take_damage(dynamite.blast_damage)

    def _spawn_destruction_sparks(self, destroyed_cells, card_ids_by_cell, blast_position, player_refs, room_offset):
        """One DestructionSpark per grid cell destroy_area cleared, all
        homing toward whichever player is nearest right now -- an explosion
        doesn't retarget mid-flight (target_getter is a closure captured
        once here, not a live search). No-op if the room has no players.

        Nearest-player selection compares ref.hitbox (room-local, see
        PickupManager._nearest_target_within) against blast_position (also
        local) -- correct with no conversion. The closure itself reads
        ref.player.position (the persistent, GLOBAL Player, since it must
        stay live across future frames) -- room_offset is what lets
        DestructionSpark convert that back to this room's local space each
        frame it homes. Each cell's own card_ids_by_cell entry spawns
        pickups of its own loot table once ITS OWN spark arrives -- every
        cell's spark shares one target player, but each still carries its own card(s)."""
        if not destroyed_cells or not player_refs:
            return
        nearest = min(player_refs, key=lambda ref: pygame.Vector2(ref.hitbox.center).distance_squared_to(blast_position))
        target_player = nearest.player
        for grid_x, grid_y in destroyed_cells:
            local_x, local_y = self.dungeon.grid_to_world(grid_x, grid_y)
            card_ids = card_ids_by_cell.get((grid_x, grid_y), [])

            def _on_arrival(position, card_ids=card_ids):
                _spawn_loot_pickups(self.dungeon, position, card_ids)

            self.dungeon.effect_manager.spawn_destruction_spark(
                local_x, local_y, lambda: target_player.position, room_offset=room_offset,
                on_arrival=_on_arrival,
            )

    def draw(self, screen, camera):
        for dynamite in self.dynamites:
            dynamite.draw(screen, camera)
        for explosion in self.explosions:
            explosion.draw(screen, camera)


def _spawn_loot_pickups(dungeon, position, card_ids):
    """Spawns ground pickups for the full combined loot table
    (effective_loot_cards) of every id in `card_ids` -- a single card id or
    an iterable (a destroyed cell's tile plus whatever object sat on it).
    The shared "what happens once a reward's DestructionSpark lands" step
    (MobManager._spawn_death_reward, ProjectileManager._spawn_destruction_sparks,
    Explorator._resolve_player_attacks' melee wall-break) -- a card is only
    earned by physically collecting a CardPickup, never credited invisibly.
    An entry that ALSO names a real inventory item additionally spawns a
    physical ItemPickup (usable this run, replacing the old item_loot mechanic)."""
    if isinstance(card_ids, str):
        card_ids = [card_ids]
    for card_id in card_ids:
        for loot_id, loot_count in effective_loot_cards(card_id).items():
            for _ in range(loot_count):
                dungeon.pickup_manager.spawn_card(loot_id, position.x, position.y)
                item_def = ITEM_DEFINITIONS.get(loot_id)
                if item_def is not None:
                    dungeon.pickup_manager.spawn_item(
                        make_item(loot_id), item_def["slot"], position.x, position.y,
                    )


class DestructionSpark:
    """assets/effect/star's 4 frames play once (like Explosion) while homing
    toward a live target -- feedback for a tile actually destroyed (melee
    wall-break or one blast cell) or a mob corpse despawning, spawned by the
    caller (Explorator, ProjectileManager, MobManager), never by
    Dungeon/Mob's own destruction/death logic (they have no notion of "which
    player is nearby" -- see EffectManager.spawn_destruction_spark).
    `on_arrival(position)`, if given, fires exactly once, the frame this
    finishes, with this spark's final room-local position -- the caller's
    hook to spawn loot pickups exactly where the star lands. The star
    effectively BECOMES the pickup at that point."""

    FRAME_SIZE = 32
    ANIMATION_SPEED = 0.08
    HOMING_SPEED = 260  # world px/sec -- fast enough to usually reach the player within the 4-frame animation

    def __init__(self, world_x, world_y, target_getter, room_offset=(0, 0), on_arrival=None):
        # self.position is room-LOCAL (same space as world_x/world_y, never
        # true global once inside a multi-room assembly). target_getter
        # always returns a live Player.position, which is ALWAYS GLOBAL --
        # room_offset (this room's (offset_x, offset_y) * tile_size within
        # the assembly, 0 outside one) is what update() subtracts to convert
        # that back into local space every frame it homes.
        self.position = pygame.Vector2(world_x, world_y)
        self.target_getter = target_getter
        self.room_offset = pygame.Vector2(room_offset)
        self.on_arrival = on_arrival
        self.frames = load_star_frames()
        self.frame = 0
        self.animation_timer = 0.0
        self.finished = False
        self._render_cache = {}

    def update(self, dt):
        if self.finished:
            return
        target = self.target_getter()
        if target is not None:
            local_target = pygame.Vector2(target) - self.room_offset
            self.position = _move_toward(self.position, local_target, self.HOMING_SPEED, dt)
        if _advance_frame_once(self, dt, self.ANIMATION_SPEED, len(self.frames)):
            self.finished = True
            if self.on_arrival is not None:
                self.on_arrival(self.position)

    def draw(self, screen, camera):
        sprite = self.frames[self.frame]
        _draw_cached_sprite(
            screen, camera, self._render_cache,
            (self.frame,),
            sprite, self.position, self.FRAME_SIZE, self.FRAME_SIZE,
        )


class EffectManager:
    """Owns live one-shot VFX-with-motion for a room -- today just
    DestructionSpark, kept as a deliberately generic name/shape in case a
    future one-shot homing effect wants the same home."""

    def __init__(self, dungeon):
        self.dungeon = dungeon
        self.sparks = []

    def spawn_destruction_spark(self, world_x, world_y, target_getter, room_offset=(0, 0), on_arrival=None):
        """`target_getter` is a callable () -> Vector2-like | None, read
        EVERY frame -- true magnetism toward the target's CURRENT position,
        not a trajectory computed once at spawn. Callers capture whichever
        player they've picked in a closure. `room_offset` is this room's own
        (offset_x, offset_y) * tile_size within a multi-room assembly (0
        outside one) -- see DestructionSpark's docstring. `on_arrival` is
        this manager's passthrough for the reward hook -- never inspected here."""
        self.sparks.append(
            DestructionSpark(world_x, world_y, target_getter, room_offset=room_offset, on_arrival=on_arrival)
        )

    def update(self, dt):
        for spark in self.sparks:
            spark.update(dt)
        self.sparks = [spark for spark in self.sparks if not spark.finished]

    def draw(self, screen, camera):
        for spark in self.sparks:
            spark.draw(screen, camera)
