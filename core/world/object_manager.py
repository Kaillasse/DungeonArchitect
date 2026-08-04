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
    },
    "gate": {
        "asset": "tiles/gateopenclose.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 8,
    },
    "wall": {
        "asset": "tiles/wallopenclose.png",
        "placement": "floor",
        "size": (2, 1),
        "frames": 7,
    },
    "torch": {
        "asset": "tiles/Torch Yellow.png",
        "placement": "wall",
        "size": (1, 1),
        "frames": 8,
        # Wall-mounted variants: chosen at placement time from which side
        # of the wall the room's floor is on (see ObjectManager._torch_variant).
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

    def __init__(self, dungeon):
        self.dungeon = dungeon
        self.objects = []

    def add_object(self, object_type, grid_x, grid_y):
        if not (0 <= grid_x < self.dungeon.width):
            return False

        if not (0 <= grid_y < self.dungeon.height):
            return False

        if self.dungeon.logical_grid[grid_y][grid_x] != self._required_cell(object_type):
            return False

        placed = {
            "type": object_type,
            "x": grid_x,
            "y": grid_y,
        }

        if "variants" in OBJECT_TYPES[object_type]:
            variant = self._wall_variant(grid_x, grid_y)
            if variant is not None:
                placed["variant"] = variant

        self.objects.append(placed)

        return True

    def _wall_variant(self, grid_x, grid_y):
        """L/R variant for an object mounted on a wall, from which side its room's floor is on."""
        if grid_x > 0 and self.dungeon.logical_grid[grid_y][grid_x - 1] == FLOOR:
            return "R"
        if grid_x + 1 < self.dungeon.width and self.dungeon.logical_grid[grid_y][grid_x + 1] == FLOOR:
            return "L"
        return None

    def prune_invalid(self):
        """Drop objects whose underlying cell no longer matches their placement rule (e.g. the floor/wall they sat on got erased)."""
        self.objects = [
            obj for obj in self.objects
            if self.dungeon.logical_grid[obj["y"]][obj["x"]] == self._required_cell(obj["type"])
        ]

    def _required_cell(self, object_type):
        return FLOOR if OBJECT_TYPES[object_type]["placement"] == "floor" else WALL
