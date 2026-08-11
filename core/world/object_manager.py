from pathlib import Path

import pygame

from core.editor.autotile import EMPTY, FLOOR, WALL
from core.data.ressources import DEFAULT_ANIM_SPEED
from core.data.sound_manager import SoundManager

PROJECT_ROOT = Path(__file__).resolve().parents[2]

OBJECT_TYPES = {
    "spawn": {
        "asset": "characters/Player/rotate.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 8,
    },
    "button": {
        "asset": "tiles/Button.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 3,
        "linkable": True,
        "walkable": True,
    },
    "gate": {
        "asset": "tiles/gateopenclose.png",
        # Custom placement, not a plain "floor"/"wall" lookup -- see
        # ObjectManager._resolve_placement/is_valid_doorway: a gate/wall must
        # sit on a WALL cell that reads as a clean break in a straight wall
        # segment (one FLOOR neighbor, the room interior, directly opposite
        # one EMPTY neighbor, the void beyond, with WALL flanking the other
        # two sides). This is what makes a placed entry-exit unambiguous for
        # both the player (no ordinary floor tile doubles as a doorway) and
        # the procedural assembler (core.world.assembly), which additionally
        # only treats a gate/wall with this pattern as a connectable exit.
        "placement": "doorway",
        "size": (1, 1),
        "frames": 8,
        "linkable": True,
        "blocks_until_open": True,
    },
    "wall": {
        "asset": "tiles/wallopenclose.png",
        "placement": "doorway",
        "size": (2, 1),
        "frames": 7,
        "linkable": True,
        "blocks_until_open": True,
    },
    "torch": {
        "asset": "tiles/Torch Yellow.png",
        # "wall" here is just the fallback/default variant's placement (a
        # torch mounted flat on a plain wall cell, e.g. a back wall). The
        # L/R variants use custom placement logic instead (see
        # ObjectManager._resolve_placement/_torch_variant): they go on a
        # FLOOR cell that has a WALL immediately beside it (right -> R,
        # left -> L), since they're meant to sit at a side wall the player
        # walks past, not block a whole cell -- that's also why only L/R
        # are walkable/drawn in front of the player
        # (ObjectManager.is_foreground_object), not the plain variant.
        "placement": "wall",
        "size": (1, 1),
        "frames": 8,
        "variants": {
            "L": "tiles/Torch Yellow L.png",
            "R": "tiles/Torch Yellow R.png",
        },
    },
    "vase": {
        "asset": "tiles/Vase.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 16,
        "blocks_movement": True,
    },
    "chicken": {
        "asset": "characters/Animals/Chicken.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 2,
        "frame_size": 32,
        "animal": True,
    },
    "cow": {
        "asset": "characters/Animals/Cow.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 2,
        "frame_size": 32,
        "animal": True,
    },
    "pig": {
        "asset": "characters/Animals/Pig.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 2,
        "frame_size": 32,
        "animal": True,
    },
    "sheep": {
        "asset": "characters/Animals/Sheep.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 2,
        "frame_size": 32,
        "animal": True,
    },
    "skeleton1": {
        # "asset" here is just skeleton1's idle sheet -- the static editor
        # palette/placed-object icon only ever needs the idle row, same as
        # animals (load_object_frames). Live combat behavior reads the full
        # idle/movement/attack/damaged/death set via load_enemy_frames
        # instead, using ENEMY_ANIMATION_FILES below.
        "asset": "characters/Ennemies/skeleton1/idle.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 6,
        "frame_size": 32,
        "enemy": True,
    },
    "skeleton2": {
        "asset": "characters/Ennemies/skeleton2/idle.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 6,
        "frame_size": 32,
        "enemy": True,
    },
    "stairs": {
        # Sourced from basictileset.png frame 26, not a dedicated
        # per-object sheet like every other entry here -- cropped once into
        # its own small file (Phase 6a) to keep load_object_frames'
        # one-sheet-per-type convention rather than teaching it to read a
        # sub-region of a shared tileset. Custom placement (see
        # ObjectManager._resolve_placement/_stairs_orientation): valid on an
        # ordinary FLOOR cell, or on an EMPTY cell that has a FLOOR neighbor
        # (a room's void-facing edge) -- "variant"="flip" mirrors the sprite
        # horizontally when that floor neighbor is specifically to the west,
        # so a single asset covers both orientations without a second file.
        "asset": "tiles/stairs.png",
        "placement": "stairs",
        "size": (1, 1),
        "frames": 1,
    },
    "cave_entrance": {
        # basictileset.png frame 27. Same doorway shape/validity as
        # gate/wall (ObjectManager.is_valid_doorway) -- see
        # _resolve_placement -- but always open: no "linkable"/
        # "blocks_until_open", just "walkable" like a button, since this is
        # meant as a level-exit marker, not a lockable door.
        "asset": "tiles/cave_entrance.png",
        "placement": "doorway",
        "size": (1, 1),
        "frames": 1,
        "walkable": True,
    },
    "big_entrance": {
        # basictileset.png frames 17 (left half) + 23 (right half), composed
        # side-by-side once into one 32x16 static asset (Phase 6a). "frames":
        # 1 with a non-square asset is why load_object_frames gained its
        # whole-image branch. Promoted from purely-decorative wall dressing
        # to a real functional E/S (role system, see get_role/set_role
        # below): same doorway shape/validity as gate/wall/cave_entrance
        # (ObjectManager.is_valid_doorway, checked off its origin cell only
        # -- already proven to work for a 2-wide footprint by "wall"), and
        # always open like cave_entrance (no "linkable"/"blocks_until_open"
        # -- there's no button-linking use case for a 2-wide entrance).
        "asset": "tiles/big_entrance.png",
        "placement": "doorway",
        "size": (2, 1),
        "frames": 1,
        "walkable": True,
    },
    "pillar": {
        # basictileset.png frame 18 (base). A single ordinary object, placed
        # on FLOOR exactly like "vase" -- move/erase/click-drag all reuse the
        # generic single-cell machinery unchanged, so a pillar is always
        # destroyed/moved as one block, never split. Its "top" half (frame
        # 12, via the "variants" override below) is *not* a second object at
        # all: WorldRenderer._draw_pillar_tops draws it purely decoratively,
        # one cell north of wherever this object currently is, every frame
        # -- no placement rule, no independent existence, so it can never be
        # individually selected, moved, or orphaned. It's skipped only where
        # an entry-exit object (gate/wall/cave_entrance/stairs) sits, so it
        # never visually covers a doorway; it renders in front of anything
        # else (including the player), same z-order slot an L/R torch uses.
        "asset": "tiles/pillar.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 1,
        "blocks_movement": True,
        "variants": {
            "top": "tiles/pillar_top.png",
        },
    },
    "lilchest": {
        # 4 columns x 2 rows: row 0 idle/closed, row 1 the opening animation
        # -- "frames" is the TOTAL flat count load_object_frames slices into
        # (4 * 2 = 8), "rows" tells it to read both rows instead of just row
        # 0 (see load_object_frames). A freshly-placed chest just sits at
        # frame 0 (idle) forever until opened -- see
        # ObjectManager.add_object seeding "loot"/"item_loot" from
        # default_loot/default_item_loot below, and
        # Explorator._interact_with_chest, which sets "open": True and
        # "frame": 4 (the start of row 1) so ObjectManager.update's existing
        # activated/open animation-advance takes it from there and holds on
        # frame 7 (row 1's last frame) once open, exactly like any other
        # blocks_until_open object.
        "asset": "tiles/lilchest.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 8,
        "rows": 2,
        "frame_size": 16,
        "blocks_movement": True,
        "chest": True,
        # Reuses the indicator-dot rendering/hit-testing "linkable" already
        # drives (Creator draws/hit-tests it identically), but a chest's dot
        # opens ChestPanelUI instead of starting a link-drag -- see
        # Creator's indicator-click handler, which checks is_chest() first.
        "linkable": True,
        "default_loot": {"gold": 5, "blue": 5},
        "default_item_loot": {"dynamite": 2},
    },
}
OBJECT_LIST = [
    "spawn",
    "button",
    "gate",
    "wall",
    "torch",
    "vase",
    "chicken",
    "cow",
    "pig",
    "sheep",
    "skeleton1",
    "skeleton2",
    "lilchest",
    "stairs",
    "cave_entrance",
    "big_entrance",
    "pillar",
]

# Object types backed by a live, wandering entity (core.world.entities.Animal)
# during exploration rather than just a static placed sprite -- see
# entities.AnimalManager. Derived from the "animal" flag above instead of a
# separately-maintained list, so OBJECT_TYPES stays the single registry.
ANIMAL_TYPES = tuple(name for name, config in OBJECT_TYPES.items() if config.get("animal"))

# Same idea as ANIMAL_TYPES, for core.world.entities.Enemy/EnemyManager.
ENEMY_TYPES = tuple(name for name, config in OBJECT_TYPES.items() if config.get("enemy"))

# Object types that function as an entry/exit (a doorway between rooms, or
# the boundary of a room's void edge) -- the only types get_role/set_role
# below accept a "connector"/"dungeon_entrance"/"dungeon_exit" role for, and
# what core.world.assembly's procedural generator treats as a possible
# room-to-room connector (imported there instead of a second, separately
# maintained tuple).
ES_TYPES = ("gate", "wall", "cave_entrance", "big_entrance")

# Allowed "role" values (ObjectManager.get_role/set_role) per object kind --
# an E/S (ES_TYPES) or a chest (is_chest()). Each kind's first entry is its
# default when a placed object carries no "role" key at all (old saves,
# every object placed before this system existed) -- "connector"/"loot" are
# both exactly today's pre-role behavior, so nothing needs migrating.
ES_ROLES = ("connector", "dungeon_entrance", "dungeon_exit")
CHEST_ROLES = ("loot", "dungeon_exit")

# Each enemy type has its own assets/characters/Ennemies/<folder>/ directory
# with one fixed-name sheet per animation (idle/movement/attack/damaged/death.png).
ENEMY_FOLDERS = {
    "skeleton1": "skeleton1",
    "skeleton2": "skeleton2",
}
ENEMY_ANIMATIONS = ("idle", "movement", "attack", "damaged", "death")

# health/move_speed/aggro_range/attack_range are tuning defaults, not values
# given by any design doc -- easy to retune here without touching Enemy's
# logic. active_attack_frames (0-based) is the window during which a swing
# actually deals damage: skeleton1's is as specified (frames 7-8 of 9,
# 1-based); skeleton2 has a different attack frame count (15) with no given
# mapping, so its window is derived from skeleton1's *relative* position
# (~75%-87% through the swing) rather than guessed outright. "loot" (currency
# type -> count) is read once, on death, by Explorator._spawn_loot -- an
# enemy with no "loot" key (or an empty one) simply drops nothing. "item_loot"
# (item id -> count, see ITEM_DEFINITIONS) is the same idea for real
# inventory items (currently just dynamite) rather than currency.
ENEMY_STATS = {
    "skeleton1": {
        "health": 3, "move_speed": 45, "aggro_range": 6.0, "attack_range": 1.2,
        "active_attack_frames": (6, 7),
        "loot": {"gold": 2, "blue": 1},
        "item_loot": {"dynamite": 1},
    },
    "skeleton2": {
        "health": 3, "move_speed": 45, "aggro_range": 6.0, "attack_range": 1.2,
        "active_attack_frames": (11, 12),
        "loot": {"gold": 2, "blue": 1},
    },
}

# Currency pickup sheets (assets/item/, alongside dynamite.png): two rows
# of 16x16 frames -- row 0 is the idle "spinning coin" loop, row 1 plays once
# when the player actually picks it up (core.world.entities.Pickup). Shared
# by InventoryPanel's counter icon (which only ever uses "spin") and Pickup,
# so both stay visually identical to a single source of truth.
CURRENCY_FILES = {"gold": "item/Coin Sheet.png", "blue": "item/BlueCoin Sheet.png"}
CURRENCY_FRAME_SIZE = 16


def load_currency_frames(currency_type):
    """Returns {"spin": [...], "collect": [...]}, each a list of 16x16 frames."""
    sheet = pygame.image.load(PROJECT_ROOT / "assets" / CURRENCY_FILES[currency_type]).convert_alpha()
    size = CURRENCY_FRAME_SIZE
    columns = sheet.get_width() // size

    def _row(row_index):
        return [sheet.subsurface((i * size, row_index * size, size, size)).copy() for i in range(columns)]

    return {"spin": _row(0), "collect": _row(1)}


# Real inventory items (as opposed to currency, see CURRENCY_FILES above) --
# each entry is enough for both a ground ItemPickup's static icon and an
# InventoryPanel slot's icon (same "icon_rect" crop, see Item.get_icon), plus
# which main_slots key it belongs in and whether pressing "interact" while
# it's equipped there should throw it (see Explorator._throw_interact_item)
# instead of just playing the plain interact animation.
ITEM_DEFINITIONS = {
    "dynamite": {
        "name": "Dynamite",
        "icon_path": "item/dynamite.png",
        "icon_rect": (0, 0, 16, 16),  # frame 0 -- "avant pickup" / inventory display
        "slot": "interact",
        "throwable": True,
    },
}

DYNAMITE_FRAME_SIZE = 16
DYNAMITE_FRAME_COUNT = 4


def load_dynamite_frames():
    """The 4 throw-animation frames (16x16 each), sliced from the single-row
    64x16 dynamite.png sheet -- used by core.world.entities.ThrownDynamite,
    not by the static ground/inventory icon (that's just frame 0, read
    directly via ITEM_DEFINITIONS["dynamite"]["icon_rect"])."""
    sheet = pygame.image.load(PROJECT_ROOT / "assets" / ITEM_DEFINITIONS["dynamite"]["icon_path"]).convert_alpha()
    size = DYNAMITE_FRAME_SIZE
    return [sheet.subsurface((i * size, 0, size, size)).copy() for i in range(DYNAMITE_FRAME_COUNT)]


# Explosion VFX (assets/effect/smallexplosion/) -- one 48x48 PNG per frame,
# not a sliced sheet like everything else in this module, since that's how
# it was authored. Played once by core.world.entities.Explosion wherever a
# ThrownDynamite detonates.
EXPLOSION_FOLDER = "effect/smallexplosion"
EXPLOSION_FRAME_COUNT = 9


def load_explosion_frames():
    return [
        pygame.image.load(PROJECT_ROOT / "assets" / EXPLOSION_FOLDER / f"frame{i:04d}.png").convert_alpha()
        for i in range(EXPLOSION_FRAME_COUNT)
    ]


def make_item(item_id):
    """Builds a core.world.inventory.Item from ITEM_DEFINITIONS -- kept here
    (not in inventory.py) since ITEM_DEFINITIONS lives alongside every other
    asset registry in this module (OBJECT_TYPES, CURRENCY_FILES)."""
    from core.world.inventory import Item
    definition = ITEM_DEFINITIONS[item_id]
    return Item(item_id, definition["name"], definition["icon_path"], definition.get("icon_rect"))


def load_object_frames(object_type, variant=None):
    """Slice an object's sprite sheet into its animation frames -- a flat
    list, "frames" cells read left-to-right then row by row. Almost every
    object type is a single row ("rows" defaults to 1, in which case this is
    exactly the old behavior: "frames" columns from row 0). A chest-like
    type with "rows": 2 instead has "frames" as the TOTAL count across both
    rows (e.g. 8 for lilchest's 4-idle + 4-open sheet), so row 1 continues
    the flat list right where row 0 left off -- obj["frame"] can then just
    keep counting upward across the "seam" between rows without needing to
    know rows exist at all (see OBJECT_TYPES["lilchest"])."""
    config = OBJECT_TYPES[object_type]
    asset_path = config.get("variants", {}).get(variant, config["asset"])
    asset = PROJECT_ROOT / "assets" / asset_path
    sheet = pygame.image.load(asset).convert_alpha()

    if config["frames"] == 1:
        # A single static frame whose asset is pre-sized exactly to its
        # final footprint (e.g. "big_entrance", a 2-wide object with a 32x16
        # asset) -- no frame_size/rows slicing makes sense here, since every
        # other type assumes SQUARE frame_size x frame_size cells. Every
        # existing type sets "frames" to its actual per-row column count
        # (always >= 1 for an animated/static-but-square sprite), so this
        # only ever affects a type that deliberately opts into it.
        return [sheet]

    frame_size = config.get("frame_size", 24 if object_type == "spawn" else 16)
    rows = config.get("rows", 1)
    columns = config["frames"] // rows

    frames = []
    for row in range(rows):
        for col in range(columns):
            rect = pygame.Rect(col * frame_size, row * frame_size, frame_size, frame_size)
            frames.append(sheet.subsurface(rect).copy())
    return frames


def load_animal_frames(object_type):
    """Full idle+move animation set for an animal NPC sheet (a 2x2 grid: row 0
    idle, row 1 move, each row 2 frames of frame_size px). Used by
    core.world.entities.Animal for live wandering during exploration -- the
    static editor palette/placed-object preview keeps using
    load_object_frames, which only reads the idle row (config["frames"])."""
    config = OBJECT_TYPES[object_type]
    asset = PROJECT_ROOT / "assets" / config["asset"]
    sheet = pygame.image.load(asset).convert_alpha()
    frame_size = config["frame_size"]

    def _row(row_index):
        return [
            sheet.subsurface(
                pygame.Rect(i * frame_size, row_index * frame_size, frame_size, frame_size)
            ).copy()
            for i in range(2)
        ]

    return {"idle": _row(0), "move": _row(1)}


ENEMY_FRAME_SIZE = 32


def load_enemy_frames(enemy_type):
    """Full idle/movement/attack/damaged/death animation set for an enemy --
    unlike animals, each is its own single-row sheet, so the frame count per
    sheet is derived from its own pixel width (sheet.get_width() //
    ENEMY_FRAME_SIZE, same approach as Player.cut_sheet) rather than
    assumed -- skeleton1 and skeleton2 don't share frame counts for any of
    their animations despite sharing a folder layout."""
    folder = ENEMY_FOLDERS[enemy_type]
    frames = {}
    for animation in ENEMY_ANIMATIONS:
        path = PROJECT_ROOT / "assets" / "characters" / "Ennemies" / folder / f"{animation}.png"
        sheet = pygame.image.load(path).convert_alpha()
        columns = sheet.get_width() // ENEMY_FRAME_SIZE
        frames[animation] = [
            sheet.subsurface(
                pygame.Rect(i * ENEMY_FRAME_SIZE, 0, ENEMY_FRAME_SIZE, ENEMY_FRAME_SIZE)
            ).copy()
            for i in range(columns)
        ]
    return frames


class ObjectManager:
    """Owns the placed-object list and the rules for placing them. The grid/size data it needs belongs to the Dungeon it's attached to."""

    ANIM_SPEED = DEFAULT_ANIM_SPEED  # seconds per frame -- see ressources.DEFAULT_ANIM_SPEED's own docstring

    def __init__(self, dungeon):
        self.dungeon = dungeon
        # _cell_index/objects_version back get_object_at -- see the `objects`
        # property setter below and _index_object/_deindex_object. Kept in
        # sync incrementally by add_object/move_object (the only two methods
        # that ever add a cell or move one without replacing the whole list);
        # any wholesale replacement of `self.objects` (prune_invalid,
        # SaveManager.apply_json's direct `object_manager.objects = ...`)
        # goes through the property setter instead, which just rebuilds the
        # index from scratch -- simpler and safe for an infrequent, already
        # O(n)-anyway operation, and it means an external assignment can
        # never silently leave the index stale.
        self._cell_index = {}
        self.objects_version = 0
        # id(obj) -> obj, every object currently animating (activated/open
        # and not yet holding on its last frame) -- see begin_animation/
        # update() below. Rebuilt from scratch on any wholesale replacement
        # of `self.objects` (the property setter), same reasoning as
        # _cell_index: a fresh load can arrive with objects already
        # activated/open mid-animation (see SaveManager's "additive field"
        # docs), and prune_invalid dropping an animating object must drop it
        # from here too.
        self._animating = {}
        self._objects = []

    @property
    def objects(self):
        return self._objects

    @objects.setter
    def objects(self, value):
        self._objects = value
        self._rebuild_cell_index()
        self._rebuild_animating()
        self.objects_version += 1

    def _rebuild_animating(self):
        self._animating = {}
        for obj in self._objects:
            if obj.get("activated") or obj.get("open"):
                self.begin_animation(obj)

    def begin_animation(self, obj):
        """Registers `obj` as currently animating -- call right after
        setting "activated"/"open" True for the first time, from wherever
        that happens: this class's own check_button_trigger, or
        core.world.assembly's cross-room button/door-sync logic (each
        against the ObjectManager that actually owns the target object, not
        necessarily `self`), or Explorator._interact_with_chest opening a
        chest. update() below only ever iterates this set instead of every
        placed object, and self-removes an entry once it reaches its last
        frame -- calling this again for an already-registered or
        already-finished object is harmless (dict keyed by id(obj), and a
        finished one is simply re-pruned on the very next update() tick)."""
        self._animating[id(obj)] = obj

    def _footprint_cells_of(self, obj):
        size_x, size_y = OBJECT_TYPES[obj["type"]]["size"]
        for dx in range(size_x):
            for dy in range(size_y):
                yield obj["x"] + dx, obj["y"] + dy

    def _index_object(self, obj):
        # setdefault, not a plain assignment: if two objects' footprints ever
        # overlapped (shouldn't happen through ordinary placement, but
        # nothing here re-validates a hand-edited save), this preserves the
        # exact same "first in self.objects order wins" result the old
        # linear scan in get_object_at used to produce.
        for cell in self._footprint_cells_of(obj):
            self._cell_index.setdefault(cell, obj)

    def _deindex_object(self, obj):
        for cell in self._footprint_cells_of(obj):
            if self._cell_index.get(cell) is obj:
                del self._cell_index[cell]

    def _rebuild_cell_index(self):
        self._cell_index = {}
        for obj in self._objects:
            self._index_object(obj)

    def _in_bounds(self, grid_x, grid_y):
        return 0 <= grid_x < self.dungeon.width and 0 <= grid_y < self.dungeon.height

    def add_object(self, object_type, grid_x, grid_y):
        if not self._in_bounds(grid_x, grid_y):
            return False

        valid, variant = self._resolve_placement(object_type, grid_x, grid_y)
        if not valid:
            return False

        placed = {
            "type": object_type,
            "x": grid_x,
            "y": grid_y,
        }

        if variant is not None:
            placed["variant"] = variant

        config = OBJECT_TYPES[object_type]
        if config.get("chest"):
            # Own dict copies, not the OBJECT_TYPES default objects themselves
            # -- ChestPanelUI mutates these per-placed-chest (see Creator),
            # which must never leak back into the shared registry entry.
            placed["loot"] = dict(config.get("default_loot", {}))
            placed["item_loot"] = dict(config.get("default_item_loot", {}))

        self._objects.append(placed)
        self._index_object(placed)
        self.objects_version += 1

        return True

    def get_object_at(self, grid_x, grid_y):
        """The object whose footprint (OBJECT_TYPES[type]["size"]) covers this
        cell -- not just its origin, so a 2-wide "wall" is found from either
        cell it occupies. O(1) via _cell_index rather than a linear scan --
        this is the hottest call in the collision path (is_cell_walkable, up
        to 4 corners x every entity x every frame), so an O(n) scan here
        multiplied badly with entity count."""
        return self._cell_index.get((grid_x, grid_y))

    def is_chest(self, object_type):
        """True for a chest-like type (currently just lilchest) -- its
        indicator dot (drawn/hit-tested via is_linkable, which chest types
        also set) opens ChestPanelUI in Creator instead of starting a
        link-drag; see Creator's indicator-click handler."""
        return OBJECT_TYPES[object_type].get("chest", False)

    def is_linkable(self, object_type):
        return OBJECT_TYPES[object_type].get("linkable", False)

    def is_es_type(self, object_type):
        """True for gate/wall/cave_entrance/big_entrance -- the object
        kinds that carry a role (get_role/set_role below) and that
        core.world.assembly's generator can treat as a room-to-room
        connector. Used by Creator's right-click role-picker dispatch."""
        return object_type in ES_TYPES

    def get_role(self, obj):
        """The object's role -- "connector"/"dungeon_entrance"/
        "dungeon_exit" for an E/S, "loot"/"dungeon_exit" for a chest.
        Missing "role" key (every object placed before this system
        existed, or a fresh default placement) reads as that kind's
        default -- "connector" for an E/S, "loot" for a chest -- so old
        saves need no migration. Object kinds with no role concept at all
        just get None."""
        role = obj.get("role")
        if role is not None:
            return role
        if self.is_es_type(obj["type"]):
            return "connector"
        if self.is_chest(obj["type"]):
            return "loot"
        return None

    def set_role(self, obj, role):
        """Assigns a role, validated against the allowed set for this
        object's kind (ES_ROLES/CHEST_ROLES) -- an invalid value (not
        offered by the editor UI, but this is also the one place a future
        network-facing admin command would come through) is silently
        ignored rather than corrupting the object dict. Returns True if
        the role was actually applied."""
        if self.is_es_type(obj["type"]):
            allowed = ES_ROLES
        elif self.is_chest(obj["type"]):
            allowed = CHEST_ROLES
        else:
            return False
        if role not in allowed:
            return False
        obj["role"] = role
        return True

    def is_foreground_object(self, obj):
        """Drawn after (in front of) the player, and walkable despite sitting on a WALL cell -- currently just L/R wall-mounted torches; a straight torch stays a plain blocking wall decoration. (A pillar's decorative top half gets the same front-of-player treatment, but it isn't a real object -- see WorldRenderer._draw_pillar_tops -- so it never reaches this method.)"""
        return obj["type"] == "torch" and obj.get("variant") in ("L", "R")

    def is_cell_walkable(self, grid_x, grid_y):
        if not self._in_bounds(grid_x, grid_y):
            return False

        obj = self.get_object_at(grid_x, grid_y)

        if obj is not None:
            config = OBJECT_TYPES[obj["type"]]

            if config.get("blocks_movement"):
                return False

            if config.get("blocks_until_open"):
                return obj.get("open", False)

            if config.get("walkable"):
                return True

        return self.dungeon.logical_grid[grid_y][grid_x] != WALL

    def check_button_trigger(self, grid_x, grid_y):
        """Call every frame the player occupies (grid_x, grid_y); no-ops unless a fresh button is there."""
        obj = self.get_object_at(grid_x, grid_y)

        if obj is None or obj["type"] != "button" or obj.get("activated"):
            return

        obj["activated"] = True
        obj["frame"] = 0
        obj["anim_timer"] = 0.0
        self.begin_animation(obj)
        SoundManager().play("button_pressed")

        for link_target in obj.get("links", []):
            target = self.get_object_at(link_target["x"], link_target["y"])

            if target is not None and OBJECT_TYPES[target["type"]].get("blocks_until_open") and not target.get("open"):
                target["open"] = True
                target["frame"] = 0
                target["anim_timer"] = 0.0
                self.begin_animation(target)

    def update(self, dt):
        """Advance animation for any currently-animating object (see
        begin_animation), holding on its last frame once reached and
        dropping out of _animating right then -- iterates only that set
        instead of every placed object, since most of a room's objects are
        never activated/open at all and the ones that are eventually finish
        and stop needing per-frame work."""
        finished_ids = []

        for object_id, obj in self._animating.items():
            last_frame = OBJECT_TYPES[obj["type"]]["frames"] - 1
            frame = obj.get("frame", 0)

            if frame >= last_frame:
                finished_ids.append(object_id)
                continue

            timer = obj.get("anim_timer", 0.0) + dt

            while timer >= self.ANIM_SPEED and frame < last_frame:
                timer -= self.ANIM_SPEED
                frame += 1

            obj["frame"] = frame
            obj["anim_timer"] = timer

            if frame >= last_frame:
                finished_ids.append(object_id)

        for object_id in finished_ids:
            del self._animating[object_id]

    def link(self, obj_a, obj_b):
        """Symmetric link between two linkable objects (e.g. a button and the gate/wall it opens)."""
        if obj_a is obj_b:
            return

        a_target = {"x": obj_b["x"], "y": obj_b["y"]}
        b_target = {"x": obj_a["x"], "y": obj_a["y"]}

        a_links = obj_a.setdefault("links", [])
        if a_target not in a_links:
            a_links.append(a_target)

        b_links = obj_b.setdefault("links", [])
        if b_target not in b_links:
            b_links.append(b_target)

    def move_object(self, obj, grid_x, grid_y):
        """Reposition an already-placed object. Returns True if the new cell was valid."""
        if not self._in_bounds(grid_x, grid_y):
            return False

        valid, variant = self._resolve_placement(obj["type"], grid_x, grid_y)
        if not valid:
            return False

        self._deindex_object(obj)

        old_x, old_y = obj["x"], obj["y"]
        obj["x"], obj["y"] = grid_x, grid_y

        if variant is not None:
            obj["variant"] = variant
        else:
            obj.pop("variant", None)

        self._index_object(obj)
        self.objects_version += 1

        self._retarget_links(old_x, old_y, grid_x, grid_y)

        return True

    def _retarget_links(self, old_x, old_y, new_x, new_y):
        for obj in self.objects:
            for link_target in obj.get("links", []):
                if link_target["x"] == old_x and link_target["y"] == old_y:
                    link_target["x"], link_target["y"] = new_x, new_y

    def _resolve_placement(self, object_type, grid_x, grid_y):
        """Returns (is_valid, variant) for placing/moving object_type at this cell."""
        if object_type == "torch":
            variant = self._torch_variant(grid_x, grid_y)
            if variant is not None:
                return True, variant
            if self.dungeon.logical_grid[grid_y][grid_x] == WALL:
                return True, None
            return False, None

        if object_type in ES_TYPES:
            return self.is_valid_doorway(grid_x, grid_y), None

        if object_type == "stairs":
            return self._stairs_orientation(grid_x, grid_y)

        is_valid = self.dungeon.logical_grid[grid_y][grid_x] == self._required_cell(object_type)
        return is_valid, None

    def _stairs_orientation(self, grid_x, grid_y):
        """(is_valid, variant) for stairs: valid directly on a FLOOR cell (no
        flip -- an ordinary interior placement), or on an EMPTY cell that has
        at least one FLOOR neighbor (a room's void-facing edge) -- "flip"
        mirrors the single stairs.png asset horizontally when that floor
        neighbor is specifically to the west, so it visually faces back
        toward the room regardless of which side of it the floor is on."""
        cell = self.dungeon.logical_grid[grid_y][grid_x]
        if cell == FLOOR:
            return True, None
        if cell != EMPTY:
            return False, None

        if grid_x > 0 and self.dungeon.logical_grid[grid_y][grid_x - 1] == FLOOR:
            return True, "flip"

        for nx, ny in ((grid_x + 1, grid_y), (grid_x, grid_y - 1), (grid_x, grid_y + 1)):
            if self._in_bounds(nx, ny) and self.dungeon.logical_grid[ny][nx] == FLOOR:
                return True, None

        return False, None

    def _torch_variant(self, grid_x, grid_y):
        """L/R variant for a torch on a floor cell with an adjacent wall: wall to the right -> R, wall to the left -> L. None if this isn't a valid floor-beside-a-wall spot."""
        if self.dungeon.logical_grid[grid_y][grid_x] != FLOOR:
            return None
        if grid_x + 1 < self.dungeon.width and self.dungeon.logical_grid[grid_y][grid_x + 1] == WALL:
            return "R"
        if grid_x > 0 and self.dungeon.logical_grid[grid_y][grid_x - 1] == WALL:
            return "L"
        return None

    def _cell_or_empty(self, grid_x, grid_y):
        if self._in_bounds(grid_x, grid_y):
            return self.dungeon.logical_grid[grid_y][grid_x]
        return EMPTY

    def is_valid_doorway(self, grid_x, grid_y):
        """True if (grid_x, grid_y) is a WALL cell that reads as a clean break in a
        straight wall segment: exactly one FLOOR neighbor (the room interior)
        directly opposite exactly one EMPTY neighbor (the void beyond), with
        WALL flanking the other two sides. Off-grid neighbors count as EMPTY.

        This is the only shape a gate/wall entry-exit is ever allowed to
        occupy (enforced here, at placement/move time) -- it can't end up in
        the middle of a room, which is what made it ambiguous whether a given
        floor tile was "just floor" or a doorway to another room. The
        procedural assembler (core.world.assembly) also re-checks this same
        pattern before treating a gate/wall as a connectable exit, so a
        gate/wall lacking a void neighbor (interior-only, e.g. a locked door
        gating a side room) is simply never picked as a room-to-room
        connection -- it still works as an ordinary in-room obstacle.
        """
        if not self._in_bounds(grid_x, grid_y):
            return False
        if self.dungeon.logical_grid[grid_y][grid_x] != WALL:
            return False

        up = self._cell_or_empty(grid_x, grid_y - 1)
        down = self._cell_or_empty(grid_x, grid_y + 1)
        left = self._cell_or_empty(grid_x - 1, grid_y)
        right = self._cell_or_empty(grid_x + 1, grid_y)

        if {up, down} == {FLOOR, EMPTY}:
            return left == WALL and right == WALL
        if {left, right} == {FLOOR, EMPTY}:
            return up == WALL and down == WALL
        return False

    def prune_invalid(self):
        """Drop objects whose underlying cell no longer matches their placement rule (e.g. the floor/wall they sat on got erased), and any links left dangling by that."""
        self.objects = [
            obj for obj in self.objects
            if self._resolve_placement(obj["type"], obj["x"], obj["y"])[0]
        ]

        existing = {(obj["x"], obj["y"]) for obj in self.objects}
        for obj in self.objects:
            if "links" not in obj:
                continue
            obj["links"] = [
                link_target for link_target in obj["links"]
                if (link_target["x"], link_target["y"]) in existing
            ]
            if not obj["links"]:
                del obj["links"]

    def _required_cell(self, object_type):
        return FLOOR if OBJECT_TYPES[object_type]["placement"] == "floor" else WALL
