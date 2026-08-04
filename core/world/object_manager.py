from pathlib import Path

import pygame

from core.editor.autotile import FLOOR

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


def load_object_frames(object_type):
    """Slice an object's sprite sheet into its animation frames."""
    config = OBJECT_TYPES[object_type]
    asset = PROJECT_ROOT / "assets" / config["asset"]
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

        if self.dungeon.logical_grid[grid_y][grid_x] != FLOOR:
            return False

        self.objects.append({
            "type": object_type,
            "x": grid_x,
            "y": grid_y,
        })

        return True
