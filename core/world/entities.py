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
    load_animal_frames, load_enemy_frames, load_currency_frames, mob_kind,
    load_dynamite_frames, load_explosion_frames, load_star_frames,
    OBJECT_TYPES, load_npc_frames, mob_types, NPC_DIRECTIONS, effective_loot_cards,
    ITEM_DEFINITIONS, make_item,
)

def _draw_cached_sprite(screen, camera, cache, key_prefix, sprite, position, frame_w, frame_h, flip=False, anchor_feet=False):
    """Scale+cache `sprite` at the camera's current zoom and blit it in world
    space. `key_prefix` plus a zoom bucket forms the cache key -- shared by
    every live entity/VFX's draw() (Player, Mob, Pickup/ItemPickup,
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

    def heal(self, amount):
        """Applies a "heal" card effect (see ITEM_DEFINITIONS' "effects" list
        / Explorator._use_interact_item) -- clamped at MAX_HEALTH, same
        clamp direction as take_damage's own floor at 0."""
        self.health = min(self.MAX_HEALTH, self.health + amount)

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
        """Frame list for (animation, direction), falling back to the
        sheet's LAST row when that exact direction isn't there -- not every
        animation sheet has a row for all 5 DIRECTIONS (jump.png is missing
        "back", cut_sheet only populates up through "back_right"). Falling
        back to "front" used to make jumping while facing "back" (moving
        y-negative) render identically to jumping while facing "front"
        (moving y-positive) -- the same silent-substitution bug would hit
        any other missing-row animation, not just jump. jump.png is
        currently the only sheet short a row, and only ever misses "back"
        (the last of the 5 DIRECTIONS), so falling back to the last row
        that IS there is the correct fix rather than a coincidence."""
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
    """Shared plumbing for Mob (see below): a live entity that wanders a room
    on a random idle/move timer with per-axis collision-tested movement, and
    draws a cached, zoom-scaled sprite anchored to its feet position. Mob
    owns its own state machine (which of the optional combat/aggro/rest-chain
    capabilities are active depends entirely on its OBJECT_TYPES data, see
    Mob's own docstring) and sets, per-instance rather than as class
    constants (since the same class now covers what used to be three with
    different values each): HITBOX_WIDTH/HEIGHT, FRAME_SIZE, IDLE_DURATION/
    MOVE_DURATION, ANIMATION_SPEED, LOOPING_STATES, MOVE_STATE_NAME (the
    wandering "moving" state's key into self.frames -- "move" for an
    animal-style/entity-pack mob, "movement" for an enemy-style one), and
    FACES_RIGHT_BY_DEFAULT (whether the sprite sheet's unflipped pose already
    faces right -- flips the sign of the direction.x check below)."""

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
        Mob.update's plain-wander path and Mob._update_wander (aggro_capable).
        Doesn't call _advance_animation -- callers do that themselves, since
        an aggro_capable mob needs to regardless of which state (wander/
        chase/attack) it lands in this
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
        if self._entity_pack is not None:
            # An entity-pack mob's sprite direction is a real 8-way bucket
            # (current_direction), not flip -- _enter_move already sets it
            # once from a random wander angle, but a directed chase (see
            # Mob._update_chase) never went through _enter_move at all, so
            # it stayed frozen facing wherever the mob last idled. Updating
            # it here covers wander, chase, and rest-chain movement alike
            # in one place, every frame movement actually happens.
            self.current_direction = _bucket_direction(direction)
        movement = direction * speed * dt

        candidate_x = self.position.x + movement.x
        if is_walkable(self._hitbox_at(candidate_x, self.position.y)):
            self.position.x = candidate_x

        candidate_y = self.position.y + movement.y
        if is_walkable(self._hitbox_at(self.position.x, candidate_y)):
            self.position.y = candidate_y

    def _current_frames(self):
        """Hook: the current animation's frame list. Default is exactly
        `self.frames[self.state]` -- a flat-frame mob (animal/enemy-style)
        never overrides this. Mob overrides it for an entity-pack-backed
        mob instead, since those frames are nested by (action, direction)
        rather than a flat state key -- see Mob._current_frames."""
        return self.frames[self.state]

    def _advance_animation(self, dt):
        """Looping states wrap forever; a non-looping state advances toward
        its last frame and then calls a hook once it gets there instead of
        wrapping -- a wander-only mob has no non-looping states so these
        hooks are never reached for it, a combat-capable one overrides them
        for its attack/damaged/death states (see Mob)."""
        frames = self._current_frames()
        if not frames:
            # Only reachable for an entity-pack-backed mob whose pack has
            # nothing tagged at all for the current (action, direction) or
            # any fallback (see Mob._current_frames) -- a flat-frame mob's
            # frame dict is always fully populated at import time and never
            # hits this. Nothing to animate yet, not a crash.
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
        """Hook: called after a LOOPING_STATES frame wraps forward. No-op by
        default (a wander-only mob doesn't need it); a combat-capable Mob
        overrides it to re-arm its attack window at the start of each
        swing."""

    def _on_final_frame_reached(self):
        """Hook: called once a non-looping animation has reached its last
        frame instead of advancing further. No-op by default (holds on the
        last frame forever); a combat-capable Mob overrides it for
        "damaged" -> "idle"."""

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
    (already a unit vector itself -- see _WanderingEntity._enter_wander_state),
    by dot product -- the entity-pack equivalent of Player.get_sprite_
    direction, but for a real (non-mirrored) 8-way lookup: an entity pack's
    regions already have all 8 real directions hand-drawn and tagged (see
    object_manager.NPC_DIRECTIONS/build_entity_pack_lookup), so there's no
    need for Player's own 5-row-plus-horizontal-flip storage trick here."""
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
    """Shared by MobManager._is_free: walls/closed gates first (cheapest,
    most likely to reject), then every other live Mob in `entities` (a dead
    one, `other.alive is False`, doesn't block -- every Mob always carries
    `alive`, so this reads it directly rather than the getattr-with-default
    the old Animal/Enemy/Npc split needed, back when Npc had no such
    attribute at all), then every player actually standing on this room's
    floor right now (`player_refs` is empty otherwise -- see
    Dungeon.update)."""
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
    """True if `entity`'s feet position now sits over an EMPTY cell in
    `dungeon` -- destroyed terrain (see Dungeon.destroy_area) or simply
    having wandered off the room's edge. Shared by MobManager/
    PickupManager's own per-frame void-culling (see each's update())."""
    return dungeon.is_void_at(*dungeon.world_to_grid(entity.position.x, entity.position.y))


def _prune(dungeon, entities, is_done):
    """Drops every entity that's either finished/dead per `is_done(entity)`
    or has fallen over destroyed/void terrain (see _is_over_void) -- the
    two-part cleanup rule shared by MobManager and PickupManager's own
    per-frame list-filtering (mobs, currency pickups, item pickups, card
    pickups), so a future pickup kind can't forget the void check."""
    return [entity for entity in entities if not is_done(entity) and not _is_over_void(dungeon, entity)]


def _nearest_player_ref(player_refs, position):
    """(ref, distance_px) for whichever PlayerRef in `player_refs` sits
    closest to `position`, or (None, None) if there are none. Shared by
    Mob's own aggro/attack/chase targeting, MobManager's death-reward
    spark, and ProjectileManager's destruction sparks -- all four pick
    "whichever player is nearest right now" the same way; PickupManager's
    ground-loot magnetism layers its own radius check on top of this same
    nearest-ref result instead of re-searching independently."""
    nearest = None
    nearest_distance = None
    for ref in player_refs:
        distance = pygame.Vector2(ref.hitbox.center).distance_to(position)
        if nearest_distance is None or distance < nearest_distance:
            nearest, nearest_distance = ref, distance
    return nearest, nearest_distance


class _EntityManager:
    """Shared shape for MobManager (and, historically, NpcManager before it
    -- kept generic rather than folded directly into MobManager in case a
    second live-entity kind is ever added again): owns a list of live,
    per-frame entities spawned from a dungeon's currently-placed objects of
    ENTITY_TYPES, testing free space and drawing identically. Only update()
    -- each entity's own per-frame behavior signature -- differs, so that's
    all subclasses define. Each subclass declares its own list as a plain,
    statically-visible attribute (self.mobs -- callers across
    explorator.py/assembly.py read it directly) and exposes it to the base
    class through the `_entities` property, rather than this base class
    assembling the attribute itself via getattr/setattr on a name string."""

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
        exactly ENTITY_TYPES -- overridden by MobManager to call
        object_manager.mob_types() fresh instead, since a mob type is
        created entirely in-session via the sprite editor's PNJ-style
        registration -- a frozen tuple would never see one registered
        after this module's own import time (see mob_types' own docstring
        for why it's a function and not a tuple, for exactly this
        reason)."""
        return self.ENTITY_TYPES

    def spawn(self):
        """(Re)build the live entity list from the dungeon's currently-placed
        objects of ENTITY_TYPES. Only called by Explorator when it loads a
        room -- never during editing, which would reset wandering/chase state
        on every paint stroke, and never by Creator, whose static preview
        only ever shows placed objects' frame-0 icon."""
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
    -- replaces the old Animal/Enemy/Npc split. Which capabilities a given
    Mob actually has is driven entirely by its OBJECT_TYPES data, not by a
    Python subclass (confirmed with the user -- "toutes les entites ont
    les memes proprietes, elles ne sont differenciees que par leur
    complexite"):

    - Wander (idle/move alternation): always present, via _WanderingEntity.
    - Combat (health/alive/take_damage/damaged+death states/despawn-hold):
      present iff "health" in stats (self.combat_capable). Absent -> alive
      stays True forever, take_damage is a no-op -- exactly today's PNJ
      behavior (solid, unkillable), now reached by DATA absence rather than
      Npc simply having no such attribute at all.
    - Aggro/chase/attack: present iff "aggro_range" AND "attack_range" are
      both in stats (self.aggro_capable) -- only meaningful alongside
      combat, though nothing enforces that pairing. A combat-capable mob
      with no aggro/attack stats can be killed but never fights back
      (today's animal profile, generalized -- see chicken/cow/pig/sheep's
      own "stats": {"health": 2} in object_manager.py).
    - Rest/posture chain (sit/lie): present iff wander_actions has a
      "sitting" role actually tagged in the entity pack (see _has_action)
      -- only reachable for an entity-pack-backed mob (self._entity_pack
      is not None) that is NOT aggro_capable; an aggro_capable entity-pack
      mob drops the rest chain entirely and fights instead (see update()'s
      own comment) -- no sensible interleaving of "sits down" and "chases
      the player" was ever asked for, so the two stay mutually exclusive
      rather than attempting one.
    - Interaction/dialogue ("is this a PNJ"): self.interactable, read once
      from OBJECT_TYPES[type_id].get("interactable") -- purely
      informational here (a future dialogue system is what would branch on
      it), matches the card's own Forge-edited flag exactly.
    - Loot at death: object_manager.effective_loot_cards/
      _spawn_loot_pickups, already fully data-driven from a prior pass --
      unaffected by this one beyond now firing for ANY combat-capable mob
      that dies, not just a former "enemy"/"animal".

    Frame source (decided once, at construction, from data shape -- see
    __init__): "entity_pack" present -> action x direction lookup
    (load_npc_frames, formerly Npc-only); else mob_type in ENEMY_FOLDERS ->
    5-state sheet (load_enemy_frames, formerly Enemy-only); else -> flat
    2-state idle/move sheet (load_animal_frames, formerly Animal-only).
    self._current_frames() falls back to "idle" whenever the logical state
    (e.g. "attack"/"damaged"/"death") has no frames of its own in a
    flat-frame mob's dict -- a mob given combat stats without a matching
    ENEMY_FOLDERS entry (e.g. a chicken made damageable/aggressive purely
    via the Forge) still fights/dies mechanically correctly, it just
    visually keeps playing idle/move throughout until real art exists for
    it.

    An entity-pack-backed (interactable PNJ-style) mob CAN also fight, once
    aggro_capable (aggro_range/attack_range fused onto it via Coller --
    see mechanics_panel._tearable_fragments) -- the combat state machine
    reads frames through _action_frames_for/_current_action_name rather
    than a flat self.frames[state] lookup either way, so update()'s whole
    aggro/chase/attack branch is identical for both frame sources. Its
    "attack"/"damaged"/"death" states resolve to a literal tagged action
    name of the same name (e.g. tag a region "attack" with the pack's own
    free-text action box) rather than a 4th wander_actions role -- nothing
    new to configure beyond the idle/move tagging a PNJ already needs.
    Interaction/dialogue (self.interactable) is untouched by any of this --
    a fighting PNJ can still be "interactable" in the data sense, a future
    dialogue system would just need its own judgment call about talking to
    something that's currently trying to kill the player."""

    FRAME_SIZE = 32
    REST_DURATION = (2.0, 4.5)  # how long "sit"/"lie" hold before the next decision (entity-pack mobs only)
    LIE_CHANCE = 0.35  # probability "sit" deepens into "lie" rather than heading back to "move"
    RUN_CHANCE = 0.4  # probability "move" picks "run" over "move" when both are tagged (entity-pack mobs only)
    RUN_SPEED = 55  # only used if "run" is tagged (see _enter_move)
    # Single-pass states, advanced by _advance_transition (never by the
    # state_timer -- see update()): "to_sit"/"to_move" play the "sitting"
    # action (forward / reversed), "to_lie"/"to_sit_from_lie" play "laying".
    _TRANSITION_STATES = ("to_sit", "to_lie", "to_sit_from_lie", "to_move")

    # Seconds to hold on the death animation's own last frame (see
    # _on_final_frame_reached/update()) before the corpse is worth
    # despawning -- see MobManager.update, which is what actually removes
    # it and spawns the reward spark once despawn_ready flips True.
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
            # Direction shown until the first move -- arbitrary but stable
            # (only _enter_move recomputes it -- a mob keeps facing its
            # last movement direction through however deep a rest goes).
            self.current_direction = NPC_DIRECTIONS[0]
            self._move_action = "move"  # "move" or "run", chosen fresh each _enter_move
            self._transition_role = None  # "sitting" or "laying" during a _TRANSITION_STATES state
            self._transition_reverse = False
            self.IDLE_DURATION = (2.0, 4.5)
            self.MOVE_DURATION = (1.5, 3.0)
            self.ANIMATION_SPEED = 0.2
            self._move_speed = self.stats.get("move_speed", 30)
            self.FACES_RIGHT_BY_DEFAULT = False  # inert here -- draw() always uses flip=False, see below
            # "attack" only ever actually reached if this PNJ is ALSO
            # aggro_capable (a stats/aggressivity fragment fused onto it,
            # see _tearable_fragments in mechanics_panel.py) -- harmless to
            # always include, same reasoning as the enemy-style branch
            # below already including it unconditionally.
            self.LOOPING_STATES = ("idle", "move", "attack")
            self.MOVE_STATE_NAME = "move"
        else:
            # Flat-frame path (formerly Animal/Enemy) -- state names must
            # match whichever loader's own frame-dict keys, so they're
            # picked per-source rather than one shared naming scheme (a
            # plain animal's frames dict only ever has "idle"/"move" keys,
            # never "movement" -- using the wrong name here would silently
            # never play its move animation at all).
            self._entity_pack = None
            self.wander_actions = {}
            uses_enemy_states = mob_kind(mob_type) == "enemy"
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
        # math, get_attack_hitbox, was tuned against these dimensions);
        # everything else keeps the old Animal/Npc hitbox (they happened
        # to already agree on 14x8).
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
        # Death-despawn bookkeeping -- see DEATH_DESPAWN_DELAY/update()/
        # MobManager.update. _death_animation_done flips True the moment
        # the death animation's own last frame is FIRST reached (not every
        # frame it holds there after, see _on_final_frame_reached); only
        # then does death_hold_timer start counting toward despawn_ready.
        # reward_spawned guards MobManager against spawning the reward
        # spark more than once for the same corpse. Both stay permanently
        # unused/False for a non-combat-capable mob, same effect as old
        # Npc never having them at all.
        self._death_animation_done = False
        self.death_hold_timer = 0.0
        self.despawn_ready = False
        self.reward_spawned = False

        self._render_cache = {}

    # -- frame lookup / draw --------------------------------------------

    def _has_action(self, role):
        """True if wander_actions[role] (or, absent an explicit mapping,
        `role` itself -- 2026-08-19, see _current_action_name's own
        docstring on why) points at an action ACTUALLY tagged in this
        pack -- a wander_actions entry can name an action never actually
        tagged (mob registered, then pack edited since), so this isn't
        just `role in wander_actions`. Entity-pack mobs only."""
        action = self.wander_actions.get(role, role)
        return bool(action) and action in self.frames

    def _action_frames_for(self, action_name):
        """Frames for `action_name` (a raw action name, not a role) at
        self.current_direction, with a cascading fallback instead of
        crashing if the exact direction isn't tagged yet -- a mob only
        needs ONE tile tagged to register; filling all 8 directions of
        every action is routinely still in progress. Tries: the exact
        direction; any other direction of the SAME action; a direction of
        ANY action in the pack. Returns [] only if nothing at all is
        tagged (see the empty-list guards in update()/draw())."""
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
        return self._action_frames_for(self.wander_actions.get(role, role))

    def _current_action_name(self):
        """Every reserved role (sitting/laying/move/idle) defaults to
        USING ITS OWN NAME as the tagged action to look up (2026-08-19)
        when wander_actions has no explicit override for it -- a card
        built purely in Assembler (tag a region literally "move",
        "idle", ...) works immediately with no wander_actions mapping
        step at all needed; an EXISTING PNJ whose role points at a
        differently-named tag (e.g. "idle" -> "walkfront") is completely
        unaffected, since an explicit wander_actions entry always wins
        over this fallback (dict.get's default only applies when the key
        is truly absent)."""
        if self.state in self._TRANSITION_STATES:
            return self.wander_actions.get(self._transition_role, self._transition_role)
        if self.state == "sit":
            return self.wander_actions.get("sitting", "sitting")
        if self.state == "lie":
            return self.wander_actions.get("laying", "laying")
        if self.state == "move":
            return self.wander_actions.get(self._move_action, self._move_action)
        if self.state == "idle":
            return self.wander_actions.get("idle", "idle")
        # Combat states (attack/damaged/death, only reachable for an
        # aggro_capable mob, see update()) AND any freely-named custom
        # ambient state (see _stationary_state_options/_enter_custom_state,
        # 2026-08-19) both use the LITERAL state name as the action name
        # directly -- e.g. tag a region "attack", or "roar", with the
        # pack's own free-text action box, same tool already used for
        # "walkfront" -- rather than a wander_actions role needing its own
        # dedicated Forge UI per state. No new property/registration step:
        # ANY action already tagged on the pack (see _stationary_state_
        # options) is automatically playable this way. _action_frames_for
        # already falls back gracefully (eventually to idle) if nothing's
        # tagged for a given state yet, same as a flat-frame mob given
        # combat stats without matching ENEMY_FOLDERS art (see class
        # docstring).
        return self.state

    def _current_frames(self):
        """Overrides _WanderingEntity's default flat `self.frames[state]`
        lookup for an entity-pack mob (nested by action x direction
        instead); for a flat-frame mob, falls back to "idle" whenever the
        current state has no frames of its own (see class docstring on
        combat states with no dedicated art)."""
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
        """Fallback simple rest -- used while "sitting" isn't tagged at all
        for this mob, so a minimal one (just move + idle, as before this
        feature existed) keeps behaving exactly as before."""
        self.direction = pygame.Vector2()
        self.state = "idle"
        self.frame = 0
        self.animation_timer = 0
        self.state_timer = random.uniform(*self.IDLE_DURATION)

    def _stationary_state_options(self):
        """Every action already tagged on this mob's own pack that can be
        landed on as a stationary ambient pose -- "idle" (this class's own
        built-in default, via wander_actions, unchanged) plus ANY OTHER
        action name tagged on the pack (2026-08-19 -- confirmed with the
        user: "il ne sert a rien de creer une nouvelle propriete, il suffit
        d'utiliser celle qui existe deja" -- no new field on the card, no
        registration step, this reads straight from self.frames, i.e.
        whatever the pack already has tagged via the SAME free-text action
        box used for "walkfront"/"attack" etc. Add a tile tagged "roar" to
        the pack and it's playable the very next time this is read, no
        re-registering the card at all). Excludes whatever's already
        claimed by move/run/sitting/laying (their own dedicated roles) and
        the reserved combat names (attack/damaged/death, entered only by
        update()'s aggro logic, never by this wander chain)."""
        claimed = {
            self.wander_actions.get(role) for role in ("idle", "move", "run", "sitting", "laying")
        }
        claimed.discard(None)
        return ["idle"] + [
            action_name for action_name in self.frames
            if action_name not in claimed and action_name not in ("attack", "damaged", "death")
        ]

    def _enter_custom_state(self, action_name):
        """Enters a freely-named stationary ambient state (see
        _stationary_state_options) -- no dedicated enter/leave transition
        animation the way sitting/laying get (those need to know which
        frame means "fully seated" to freeze on; an arbitrary custom
        state has no such contract), just holds on frame 0 of its own
        tagged action and loops it like idle (see _advance_loop_
        animation)."""
        self.direction = pygame.Vector2()
        self.state = action_name
        self.frame = 0
        self.animation_timer = 0
        self.state_timer = random.uniform(*self.IDLE_DURATION)

    def _enter_next_ambient_state(self):
        """Called when "idle" or a custom ambient state's timer expires
        (see _advance_state) -- picks what's next: "move" (always
        available) or, uniformly likely, any OTHER stationary option
        (_stationary_state_options), excluding whichever one is currently
        active so a mob never just re-picks the pose it's already leaving.
        For a mob with no custom states tagged at all, this reduces to
        exactly {"move"} from "idle" -- i.e. always moves next, identical
        to the original idle->move behavior, so nothing already-placed
        changes just because this method now exists."""
        options = [name for name in (["move"] + self._stationary_state_options()) if name != self.state]
        if not options:
            options = ["move"]
        choice = random.choice(options)
        if choice == "move":
            self._enter_move()
        elif choice == "idle":
            self._enter_idle()
        else:
            self._enter_custom_state(choice)

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
        """A single-pass, reversible state: forward, starts at frame 0 and
        advances to the last; reversed, starts at the last frame and counts
        down to 0. `role` names which wander_actions entry ("sitting" or
        "laying") supplies the frames."""
        self.direction = pygame.Vector2()
        self.state = state
        self._transition_role = role
        self._transition_reverse = reverse
        frames = self._action_frames(role)
        self.frame = max(0, len(frames) - 1) if reverse else 0
        self.animation_timer = 0

    def _advance_state(self):
        """Called when state_timer hits 0 -- picks the next link in
        move <-> [sitting] <-> sit <-> [laying] <-> lie, unchanged. From
        "move" with no "sitting" tagged, or from "idle"/any custom ambient
        state (see _stationary_state_options), delegates to
        _enter_next_ambient_state instead of a fixed idle<->move
        alternation -- see that method's own docstring for why this is
        behavior-identical to the old fixed alternation whenever nothing
        custom is tagged. Never called during a _TRANSITION_STATES state --
        those end via _advance_transition reaching their last frame
        instead, not this timer (see update())."""
        if self.state == "move":
            if self._has_action("sitting"):
                self._enter_transition("to_sit", "sitting", reverse=False)
            else:
                self._enter_next_ambient_state()
        elif self.state == "sit":
            if self._has_action("laying") and random.random() < self.LIE_CHANCE:
                self._enter_transition("to_lie", "laying", reverse=False)
            else:
                self._enter_transition("to_move", "sitting", reverse=True)
        elif self.state == "lie":
            self._enter_transition("to_sit_from_lie", "laying", reverse=True)
        else:
            # "idle", or any custom ambient state -- both decide what's
            # next the same way.
            self._enter_next_ambient_state()

    def _advance_transition(self, dt):
        """Advances the active _TRANSITION_STATES state frame by frame, in
        the right direction, and hands off to the real next state once it
        reaches the end."""
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
        """Loops the animation for "idle"/"move"/any custom ambient state
        (see _stationary_state_options) -- "sit"/"lie"/a _TRANSITION_
        STATES one stay frozen on whatever frame their own entry left
        them at instead, no loop of their own. Excluding those (rather
        than enumerating "idle"/"move" only, the old check) is what makes
        an open-ended, freely-named custom state loop correctly too,
        without needing to know its name in advance."""
        if self.state in ("sit", "lie") or self.state in self._TRANSITION_STATES:
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
        window (see update()) -- this mob's own hitbox inflated by one
        tile in every direction, rather than translated toward the player
        like Player.get_attack_hitbox (a fixed reach-ahead swing, which
        fits a sprite with a discrete 8-way facing). A combat mob only
        ever flips left/right, with no such discrete facing to translate
        along, and a translated box would overshoot past an already-
        adjacent player entirely -- inflating in place instead always
        covers the player whether they're standing right against the mob
        or up to a tile away."""
        reach = self.tile_size
        return self.get_hitbox().inflate(reach * 2, reach * 2)

    def take_damage(self, amount):
        """A no-op for a non-combat-capable mob (no "health" in stats) --
        exactly how a PNJ/plain decorative mob stays unkillable, now via
        data instead of Npc simply lacking this method at all."""
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
        """Ambient background behavior for an aggro_capable mob out of
        range -- alternates idle/movement on a random timer, random
        direction each time movement starts."""
        if self.state not in ("idle", self.MOVE_STATE_NAME):
            self._enter_wander_state("idle")
        self._wander_tick(dt, is_walkable, self._move_speed)

    def _update_chase(self, dt, is_walkable, target_hitbox):
        self._enter_state(self.MOVE_STATE_NAME)
        target = pygame.Vector2(target_hitbox.centerx, target_hitbox.centery)
        self._move_toward(dt, is_walkable, target - self.position, self._move_speed)

    def _face_target(self, target_hitbox):
        """Turns to face `target_hitbox` without moving -- entering
        "attack" range on its own doesn't change position, but the mob
        should still visibly turn toward the player. Sets self.flip (the
        flat-frame mob's own facing) and, for an entity-pack mob,
        current_direction too (see _bucket_direction) -- draw() only ever
        reads whichever one actually matters for its own frame source, so
        setting both unconditionally is harmless."""
        direction = pygame.Vector2(target_hitbox.centerx, target_hitbox.centery) - self.position
        self.flip = target_hitbox.centerx < self.position.x
        if direction.length_squared() > 0 and self._entity_pack is not None:
            self.current_direction = _bucket_direction(direction.normalize())

    def _nearest_player_ref(self, player_refs):
        """(ref, distance_px) for whichever player in `player_refs` is
        closest to this mob right now, or (None, None) if there are none
        -- aggro/attack-range/chase all target whichever player is
        nearest."""
        return _nearest_player_ref(player_refs, self.position)

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
        if self.frame in self.stats.get("active_attack_frames", ()) and not self._attack_sound_played:
            config = OBJECT_TYPES.get(self.mob_type, {})
            play_card_sound(
                config.get("sounds", {}), "attack", fallback_event=f"{self.mob_type}_attack",
                pitch_range=config.get("sound_pitch", {}).get("attack"),
            )
            self._attack_sound_played = True

    def _on_final_frame_reached(self):
        if self.state == "damaged":
            # Played once; return to a neutral state and let the next
            # update() re-evaluate distance to pick idle/movement/attack.
            self.state = "idle"
            self.frame = 0
        elif self.state == "death":
            # Holds on the last frame (this fires again every
            # ANIMATION_SPEED tick after, not just once -- _death_animation_done
            # itself only needs to flip True the first time, see update()).
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

        # aggro_capable takes priority over the entity-pack rest/wander
        # chain below -- an entity-pack (PNJ-style) mob given aggro_range/
        # attack_range stats (Coller-fused from a true mob, see
        # mechanics_panel._tearable_fragments) becomes a fighter first,
        # same as a flat-frame one; it drops its sit/lie posture chain
        # entirely while aggro-capable rather than trying to interleave
        # the two (no sensible combined behavior was ever asked for).
        # Frame source is fully abstracted behind _current_frames/
        # _current_action_name at this point, so this whole branch is
        # identical for a flat-frame OR an entity-pack mob -- this is the
        # "deeper unification" the class docstring used to flag as a
        # future pass; _move_toward/_face_target keep current_direction in
        # sync for the entity-pack case, _current_action_name resolves
        # "attack"/"damaged"/"death" to literal tagged action names.
        if self.aggro_capable:
            nearest_ref, distance_px = self._nearest_player_ref(player_refs)
            if nearest_ref is not None and distance_px <= self.stats["attack_range"] * self.tile_size:
                self._enter_state("attack")
                self._face_target(nearest_ref.hitbox)
            elif nearest_ref is not None and distance_px <= self.stats["aggro_range"] * self.tile_size:
                self._update_chase(dt, is_walkable, nearest_ref.hitbox)
            else:
                self._update_wander(dt, is_walkable)

            self._advance_animation(dt)

            if (
                self.state == "attack"
                and self.frame in self.stats.get("active_attack_frames", ())
                and not self._hit_delivered_this_swing
            ):
                # Mirrors the player's own attack, which already hits every
                # overlapping mob in one swing rather than just the nearest.
                attack_hitbox = self.get_attack_hitbox()
                hit_landed = False
                for ref in player_refs:
                    if attack_hitbox.colliderect(ref.hitbox):
                        ref.player.take_damage(1)
                        hit_landed = True
                if hit_landed:
                    self._hit_delivered_this_swing = True
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

        self._wander_tick(dt, is_walkable, self._move_speed)
        self._advance_animation(dt)


class MobManager(_EntityManager):
    """Owns every live Mob wandering a room, spawned from its placed mob
    objects (mob_types()) -- replaces the old AnimalManager/EnemyManager/
    NpcManager trio now that a single Mob class covers what all three used
    to (see Mob's own docstring). A non-combat-capable mob is never
    filtered out for "having died" (it never can -- take_damage no-ops for
    it); a combat-capable one plays out its death animation and holds on
    the last frame for Mob.DEATH_DESPAWN_DELAY seconds before removal,
    exactly like the old EnemyManager did -- unified here since
    AnimalManager/EnemyManager used to duplicate this reward-spawning logic
    almost verbatim. One standing over void is still removed outright with
    no reward at all -- no sensible corpse (or spark destination) for
    something that fell through the floor."""

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
                # Guarded by reward_spawned, not just removing the mob
                # immediately here, since despawn_ready can stay True for
                # more than one frame before the list comprehension below
                # actually drops it (were update() ever called twice before
                # that happened) -- the spark must only ever spawn once per
                # corpse.
                mob.reward_spawned = True
                self._spawn_death_reward(mob, player_refs, room_offset)
        self.mobs = _prune(self.dungeon, self.mobs, lambda mob: mob.despawn_ready)

    def _spawn_death_reward(self, mob, player_refs, room_offset):
        """Magnetic star toward whichever player is nearest, spawning the
        mob's own loot table (mob.mob_type, see object_manager.
        effective_loot_cards) as ground pickups once it arrives (see
        _spawn_loot_pickups). No-op (corpse just vanishes, no reward) if
        the room has no players in it right now."""
        if not player_refs:
            return
        nearest, _ = _nearest_player_ref(player_refs, mob.position)
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


def _move_toward(position, target, speed, dt):
    """Moves `position` at most `speed*dt` toward `target`, without
    overshooting -- the one magnetism calculation shared by
    DestructionSpark (destroyed-tile VFX homing to whoever caused it) and
    PickupManager's own currency/item homing (see its update()), so both
    "pull toward the player" behaviors move identically instead of each
    hand-rolling their own easing."""
    delta = target - position
    distance = delta.length()
    if distance <= speed * dt or distance == 0:
        return pygame.Vector2(target)
    return position + delta.normalize() * speed * dt


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
    dropped by a dead mob, see object_manager.effective_loot_cards/
    _spawn_loot_pickups) -- unlike Pickup
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


class CardPickup:
    """A card waiting on the ground -- what a DestructionSpark becomes the
    instant it reaches its target (see EffectManager.spawn_destruction_spark/
    _spawn_loot_pickups), rather than crediting anything invisibly. Same
    static-single-frame shape as ItemPickup, but there's no inventory SLOT
    to fill -- collecting one calls Inventory.add_card(card_id) instead
    (see PickupManager.collect), which stacks onto grid_slots rather than
    main_slots. Icon resolved once at construction via
    core.data.cards.resolve_card_sprite (deferred import -- same cycle
    concern as core.world.inventory.CardStub)."""

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
    room. Unlike MobManager there's no spawn() from placed
    objects -- pickups only ever come from Explorator._spawn_loot calling
    spawn()/spawn_item() directly at an enemy's death position, or from
    _spawn_loot_pickups (a DestructionSpark's on_arrival hook -- enemy/
    animal death, terrain destruction) calling spawn()/spawn_item()/
    spawn_card(), and are never persisted."""

    # Slower than DestructionSpark.HOMING_SPEED -- a gentle "pull toward the
    # player" once in range, not a projectile snapping onto them instantly.
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
        or None -- magnet_radius <= 0 (no players in the room, or the caller
        didn't pass one, see Dungeon.update's own default) always returns
        None, same as "no magnetism" outright rather than a radius of zero
        somehow still matching a player standing exactly on top of it.

        Uses ref.hitbox.center, NOT ref.player.position -- pickup.position
        lives in room-LOCAL coordinates (see PickupManager.spawn's callers,
        always local_x/local_y), but Player.position is always GLOBAL (see
        Explorator._use_interact_item's own local_x/y conversion). ref.hitbox
        is already shifted to this room's local space by whoever built
        player_refs (Assembly.update for a multi-room dungeon, or the
        single-Dungeon case where local==global since there's no offset) --
        comparing it directly to pickup.position is correct in both cases
        with no extra conversion needed, unlike DestructionSpark's
        target_getter (which must track a live Player across future frames,
        not just this one, so it can't reuse this same shortcut)."""
        if magnet_radius <= 0:
            return None
        ref, distance = _nearest_player_ref(player_refs, pickup.position)
        if ref is None or distance > magnet_radius:
            return None
        return pygame.Vector2(ref.hitbox.center)

    def update(self, dt, player_refs=(), magnet_radius=0):
        for pickup in self.pickups:
            # Only a still-"spin" coin gets pulled -- one already playing
            # its one-shot "collect" animation (see Pickup.begin_collect)
            # is about to be removed below regardless of where it sits.
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
        # A pickup sitting where the terrain got destroyed out from under it
        # (see Dungeon.destroy_area) falls through and is lost, same as
        # every other live entity's void-culling (AnimalManager/
        # EnemyManager) -- ground loot has no "recover it" mechanic.
        self.pickups = _prune(self.dungeon, self.pickups, lambda pickup: pickup.finished)
        self.item_pickups = _prune(self.dungeon, self.item_pickups, lambda pickup: pickup.collected)
        self.card_pickups = _prune(self.dungeon, self.card_pickups, lambda pickup: pickup.collected)

    def collect(self, player_hitbox, inventory):
        """Credits inventory.currency[pickup.currency_type] += 1 the instant
        the player touches a still-"spin" Pickup, then starts its "collect"
        animation -- removal itself happens in update() once that finishes,
        so the coin visually plays its pickup animation instead of just
        vanishing. Already-collecting pickups are left alone (no double
        credit if the player's hitbox keeps overlapping it). ItemPickups
        have no such animation -- see ItemPickup's own docstring for why a
        full inventory slot leaves one on the ground untouched instead.

        Returns the list of card_id collected THIS call (possibly empty) --
        unlike currency/items, a card can't just be credited into
        `inventory` here: it needs to reach Profile.card_collection
        eventually (see Explorator._resolve_pickups/_return_to_home), which
        this method has no access to. inventory.add_card still handles the
        immediate, visible part (stacking into grid_slots, see
        core.world.inventory.Inventory.add_card) -- a full grid leaves the
        pickup on the ground untouched, same spirit as a full main_slot."""
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
    """A player-thrown dynamite stick (see Explorator._use_interact_item):
    flies in a straight line at `speed` in the direction the player was
    facing at throw time, playing through its 4 frames once -- reaching the
    last frame is literally what triggers detonation (see `exploded`,
    checked by ProjectileManager.update), rather than a separate timer, so
    the explosion always lines up with "the end of the animation" exactly as
    specified. No mid-flight collision with walls/entities -- it's a lobbed
    throw arcing over obstacles to wherever the animation runs out, not a
    line-of-sight projectile.

    `speed`/`blast_radius_tiles`/`blast_damage` come from whichever card's
    "throwable"/"explosive" capabilities triggered this throw (see
    ProjectileManager.throw_dynamite/ITEM_DEFINITIONS["dynamite"]) rather
    than being fixed to dynamite specifically -- the DEFAULT_* class
    constants are just today's dynamite values, kept as fallbacks so a
    direct ThrownDynamite(...) construction without capability params still
    behaves exactly as before."""

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

    def throw_dynamite(self, world_x, world_y, direction, capabilities=None):
        """`capabilities` is the throwing card's own capabilities dict (see
        ITEM_DEFINITIONS["dynamite"]/Explorator._use_interact_item) --
        this manager stays free of any object_manager/ITEM_DEFINITIONS
        dependency, it just reads whichever "throwable"/"explosive" params
        the caller resolved. Missing/empty falls back to ThrownDynamite's
        own DEFAULT_* constants (today's dynamite values)."""
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
        """Deals dynamite.blast_damage to every player in this room right now
        (`player_refs` is empty otherwise, see Dungeon.update) and every live
        Mob in this room, whenever their hitbox center falls within the same
        circular radius destroy_area just carved into the terrain. No
        immunity for whoever threw it -- standing too close to your own
        blast hurts just the same. A single loop over every mob rather than
        two separate animal/enemy ones now (Mob.take_damage already no-ops
        for a non-combat-capable one, e.g. an interactable PNJ standing too
        close -- no separate branch needed to exclude it)."""
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
        """One DestructionSpark per grid cell destroy_area actually
        cleared, all homing toward whichever player in this room is
        closest to the blast right now -- an explosion doesn't "change
        target" mid-flight (see EffectManager.spawn_destruction_spark's
        own docstring for why target_getter is a closure, not a live
        search, once captured here). No-op if the room is empty of
        players (shouldn't happen -- a thrown dynamite implies someone's
        here to have thrown it -- but destroy_area's return is still
        honored either way).

        Nearest-player selection compares ref.hitbox (already room-local,
        see PickupManager._nearest_target_within's own docstring for the
        same local-vs-global distinction) against blast_position (also
        local, dynamite.position always is) -- correct with no conversion.
        The closure itself reads ref.player.position instead (the actual
        persistent Player, needed since it must stay live across many
        FUTURE frames, unlike the ref wrapper which is rebuilt fresh every
        frame) -- room_offset is what lets DestructionSpark convert that
        global position back to this room's local space each frame it
        homes (see its own update()). Each cell's own card_ids_by_cell
        entry (see Dungeon.destroy_area) spawns pickups of its own loot
        table once ITS OWN spark arrives (see _spawn_loot_pickups) --
        every cell's spark shares one target player, but each still carries
        its own card(s)."""
        if not destroyed_cells or not player_refs:
            return
        nearest, _ = _nearest_player_ref(player_refs, blast_position)
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
    """Spawns ground pickups for the full, combined loot table (see
    object_manager.effective_loot_cards) of every id in `card_ids` -- a
    single card id (a dead mob's own type) or an iterable of them
    (every card a destroyed cell is worth: tile plus whatever object sat on
    it). The shared "what happens once a reward's DestructionSpark lands"
    step (see MobManager._spawn_death_reward,
    ProjectileManager._spawn_destruction_sparks, and Explorator._resolve_
    player_attacks' melee wall-break) -- a card is only ever earned by
    physically collecting a CardPickup (see core.world.inventory.Inventory.
    add_card / Explorator._resolve_pickups), never credited invisibly.
    An entry that ALSO names a real inventory item (loot_id in
    ITEM_DEFINITIONS) additionally spawns a physical ItemPickup (usable
    THIS run, same as the old item_loot mechanic it replaces) -- both
    happen together for an item, confirmed with the user."""
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
    """assets/effect/star's 4 frames play once (same "play once" shape as
    Explosion) while homing toward a live target -- the feedback for a tile
    actually being destroyed (a broken wall from the player's own melee, or
    one cell of an explosion's blast) or a mob corpse despawning, spawned
    by Dungeon.destroy_wall_cell's/destroy_area's callers (Explorator._
    resolve_player_attacks, ProjectileManager._spawn_destruction_sparks) or
    MobManager's own despawn handling, never by the destruction/death
    logic itself (Dungeon/Mob have no notion of "which player is nearby"
    -- that's the caller's job, see EffectManager.spawn_destruction_spark).
    `on_arrival(position)`, if given, fires exactly once, the frame this
    actually finishes (see update()), passed this spark's own final
    room-local position -- the caller's own hook to spawn loot pickups
    (see _spawn_loot_pickups) exactly where the star lands, the instant it
    visually reaches the player, not at the moment of destruction/death
    itself. The star effectively BECOMES the pickup at that point."""

    FRAME_SIZE = 32
    ANIMATION_SPEED = 0.08
    HOMING_SPEED = 260  # world px/sec -- fast enough to usually reach the player within the 4-frame animation

    def __init__(self, world_x, world_y, target_getter, room_offset=(0, 0), on_arrival=None):
        # self.position lives in the SAME room-local space as world_x/
        # world_y always already are (see grid_to_world's own callers --
        # never true global coordinates once inside a multi-room assembly).
        # target_getter, however, always returns a live Player.position,
        # which is ALWAYS global -- room_offset (this room's fixed
        # (offset_x, offset_y) * tile_size within the assembly, 0 outside
        # one) is what update() subtracts to convert that global reading
        # back into this room's local space every frame it homes.
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
    DestructionSpark, but a deliberately generic name/shape (mirrors
    PickupManager/ProjectileManager) rather than "SparkManager", in case a
    future one-shot homing effect wants the same home instead of yet
    another near-identical manager."""

    def __init__(self, dungeon):
        self.dungeon = dungeon
        self.sparks = []

    def spawn_destruction_spark(self, world_x, world_y, target_getter, room_offset=(0, 0), on_arrival=None):
        """`target_getter` is a callable () -> Vector2-like | None, read
        EVERY frame (see DestructionSpark.update) -- true magnetism toward
        the target's CURRENT position, not a trajectory computed once at
        spawn time. Callers capture whichever player they've already
        picked (nearest to a blast, or whoever swung the melee hit) in a
        closure rather than passing a live reference this manager would
        have to track itself. `room_offset` is this room's own (offset_x,
        offset_y) * tile_size within a multi-room assembly (0 outside one)
        -- see DestructionSpark's own docstring for why it's needed at all
        (world_x/world_y here are room-local, but target_getter always
        reads a Player's global position). `on_arrival`, see
        DestructionSpark's own docstring, is this manager's own passthrough
        for the reward hook -- EffectManager itself never inspects it."""
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