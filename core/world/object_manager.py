from pathlib import Path

import pygame

from core.editor.autotile import EMPTY, FLOOR, WALL

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
]

# Object types backed by a live, wandering entity (core.world.entities.Animal)
# during exploration rather than just a static placed sprite -- see
# entities.AnimalManager. Derived from the "animal" flag above instead of a
# separately-maintained list, so OBJECT_TYPES stays the single registry.
ANIMAL_TYPES = tuple(name for name, config in OBJECT_TYPES.items() if config.get("animal"))

# Same idea as ANIMAL_TYPES, for core.world.entities.Enemy/EnemyManager.
ENEMY_TYPES = tuple(name for name, config in OBJECT_TYPES.items() if config.get("enemy"))

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
# (~75%-87% through the swing) rather than guessed outright.
ENEMY_STATS = {
    "skeleton1": {
        "health": 3, "move_speed": 45, "aggro_range": 6.0, "attack_range": 1.2,
        "active_attack_frames": (6, 7),
    },
    "skeleton2": {
        "health": 3, "move_speed": 45, "aggro_range": 6.0, "attack_range": 1.2,
        "active_attack_frames": (11, 12),
    },
}


def load_object_frames(object_type, variant=None):
    """Slice an object's sprite sheet into its animation frames."""
    config = OBJECT_TYPES[object_type]
    asset_path = config.get("variants", {}).get(variant, config["asset"])
    asset = PROJECT_ROOT / "assets" / asset_path
    sheet = pygame.image.load(asset).convert_alpha()

    frame_size = config.get("frame_size", 24 if object_type == "spawn" else 16)

    frames = []
    for i in range(config["frames"]):
        rect = pygame.Rect(i * frame_size, 0, frame_size, frame_size)
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

    ANIM_SPEED = 0.12  # seconds per frame, matches the editor palette's hover animation

    def __init__(self, dungeon):
        self.dungeon = dungeon
        self.objects = []

    def add_object(self, object_type, grid_x, grid_y):
        if not (0 <= grid_x < self.dungeon.width and 0 <= grid_y < self.dungeon.height):
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

        self.objects.append(placed)

        return True

    def get_object_at(self, grid_x, grid_y):
        """The object whose footprint (OBJECT_TYPES[type]["size"]) covers this cell -- not just its origin, so a 2-wide "wall" is found from either cell it occupies."""
        for obj in self.objects:
            size_x, size_y = OBJECT_TYPES[obj["type"]]["size"]
            if obj["x"] <= grid_x < obj["x"] + size_x and obj["y"] <= grid_y < obj["y"] + size_y:
                return obj
        return None

    def is_linkable(self, object_type):
        return OBJECT_TYPES[object_type].get("linkable", False)

    def is_foreground_object(self, obj):
        """Drawn after (in front of) the player, and walkable despite sitting on a WALL cell -- currently just L/R wall-mounted torches; a straight torch stays a plain blocking wall decoration."""
        return obj["type"] == "torch" and obj.get("variant") in ("L", "R")

    def is_cell_walkable(self, grid_x, grid_y):
        if not (0 <= grid_x < self.dungeon.width and 0 <= grid_y < self.dungeon.height):
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

        for link_target in obj.get("links", []):
            target = self.get_object_at(link_target["x"], link_target["y"])

            if target is not None and OBJECT_TYPES[target["type"]].get("blocks_until_open") and not target.get("open"):
                target["open"] = True
                target["frame"] = 0
                target["anim_timer"] = 0.0

    def update(self, dt):
        """Advance animation for any activated/open object, holding on its last frame once reached."""
        for obj in self.objects:
            if not (obj.get("activated") or obj.get("open")):
                continue

            last_frame = OBJECT_TYPES[obj["type"]]["frames"] - 1
            frame = obj.get("frame", 0)

            if frame >= last_frame:
                continue

            timer = obj.get("anim_timer", 0.0) + dt

            while timer >= self.ANIM_SPEED and frame < last_frame:
                timer -= self.ANIM_SPEED
                frame += 1

            obj["frame"] = frame
            obj["anim_timer"] = timer

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
        if not (0 <= grid_x < self.dungeon.width and 0 <= grid_y < self.dungeon.height):
            return False

        valid, variant = self._resolve_placement(obj["type"], grid_x, grid_y)
        if not valid:
            return False

        old_x, old_y = obj["x"], obj["y"]
        obj["x"], obj["y"] = grid_x, grid_y

        if variant is not None:
            obj["variant"] = variant
        else:
            obj.pop("variant", None)

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

        if object_type in ("gate", "wall"):
            return self.is_valid_doorway(grid_x, grid_y), None

        is_valid = self.dungeon.logical_grid[grid_y][grid_x] == self._required_cell(object_type)
        return is_valid, None

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
        if 0 <= grid_x < self.dungeon.width and 0 <= grid_y < self.dungeon.height:
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
        if not (0 <= grid_x < self.dungeon.width and 0 <= grid_y < self.dungeon.height):
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
