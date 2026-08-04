from pathlib import Path

import pygame

from core.editor.autotile import FLOOR, WALL

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
        "placement": "floor",
        "size": (1, 1),
        "frames": 8,
        "linkable": True,
        "blocks_until_open": True,
    },
    "wall": {
        "asset": "tiles/wallopenclose.png",
        "placement": "floor",
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
}
OBJECT_LIST = [
    "spawn",
    "button",
    "gate",
    "wall",
    "torch",
    "vase",
]


def load_object_frames(object_type, variant=None):
    """Slice an object's sprite sheet into its animation frames."""
    config = OBJECT_TYPES[object_type]
    asset_path = config.get("variants", {}).get(variant, config["asset"])
    asset = PROJECT_ROOT / "assets" / asset_path
    sheet = pygame.image.load(asset).convert_alpha()

    frame_size = 24 if object_type == "spawn" else 16

    frames = []
    for i in range(config["frames"]):
        rect = pygame.Rect(i * frame_size, 0, frame_size, frame_size)
        frames.append(sheet.subsurface(rect).copy())
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
