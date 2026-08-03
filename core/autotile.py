from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

# --------------------------------------------------------------------
# Types logiques
# --------------------------------------------------------------------

EMPTY = 0
FLOOR = 1
WALL = 2

DEFAULT_FLOOR_SPRITE = 14
DEFAULT_WALL_SPRITE = 3

_CARDINAL_OFFSETS = (
    (0, -1),
    (1, 0),
    (0, 1),
    (-1, 0),
)

# --------------------------------------------------------------------
# Chargement du JSON
# --------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = PROJECT_ROOT / "assets" / "tiles" / "tile_categories.json"

with JSON_PATH.open(encoding="utf8") as f:
    TILE_DATA = json.load(f)

# lookup ultra rapide :
# ("wall","0212") -> 3

AUTOTILE_LOOKUP = {}

for tile_id, data in TILE_DATA.items():
    AUTOTILE_LOOKUP[
        (
            data["category"],
            data["value"],
        )
    ] = int(tile_id)

# --------------------------------------------------------------------
# Construction des murs
# --------------------------------------------------------------------

def build_walls(logical_grid: List[List[int]]) -> None:

    h = len(logical_grid)
    if h == 0:
        return

    w = len(logical_grid[0])

    # suppression anciens murs

    for y in range(h):
        for x in range(w):
            if logical_grid[y][x] == WALL:
                logical_grid[y][x] = EMPTY

    # reconstruction

    for y in range(h):
        for x in range(w):

            if logical_grid[y][x] != FLOOR:
                continue

            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):

                    if dx == 0 and dy == 0:
                        continue

                    nx = x + dx
                    ny = y + dy

                    if (
                        0 <= nx < w
                        and 0 <= ny < h
                        and logical_grid[ny][nx] == EMPTY
                    ):
                        logical_grid[ny][nx] = WALL

# --------------------------------------------------------------------
# Effacement
# --------------------------------------------------------------------

def erase_at(
    logical_grid: List[List[int]],
    grid_x: int,
    grid_y: int,
) -> None:

    h = len(logical_grid)
    w = len(logical_grid[0])

    if not (0 <= grid_x < w and 0 <= grid_y < h):
        return

    if logical_grid[grid_y][grid_x] == WALL:

        for dx, dy in _CARDINAL_OFFSETS:

            nx = grid_x + dx
            ny = grid_y + dy

            if (
                0 <= nx < w
                and 0 <= ny < h
                and logical_grid[ny][nx] == FLOOR
            ):
                logical_grid[ny][nx] = EMPTY

    else:

        logical_grid[grid_y][grid_x] = EMPTY

# --------------------------------------------------------------------
# Voisins
# --------------------------------------------------------------------

def get_logical_neighbors(
    logical_grid,
    x,
    y,
):

    h = len(logical_grid)
    w = len(logical_grid[0])

    def get(px, py):

        if 0 <= px < w and 0 <= py < h:
            return logical_grid[py][px]

        return EMPTY

    return {

        "up": get(x, y - 1),
        "right": get(x + 1, y),
        "down": get(x, y + 1),
        "left": get(x - 1, y),

    }

# --------------------------------------------------------------------
# Conversion voisins -> "0212"
# --------------------------------------------------------------------

def get_neighbor_value(neighbors):

    return "".join(

        str(neighbors[d])

        for d in (
            "up",
            "right",
            "down",
            "left",
        )

    )

# --------------------------------------------------------------------
# Choix sprite
# --------------------------------------------------------------------

def select_sprite(
    logical: int,
    neighbors: Dict[str, int],
):

    category = "floor" if logical == FLOOR else "wall"

    value = get_neighbor_value(neighbors)

    return AUTOTILE_LOOKUP.get(

        (category, value),

        DEFAULT_FLOOR_SPRITE
        if logical == FLOOR
        else DEFAULT_WALL_SPRITE,

    )

# --------------------------------------------------------------------
# Génération sprite grid
# --------------------------------------------------------------------

def resolve_sprite_grid(
    logical_grid: List[List[int]],
):

    h = len(logical_grid)

    if h == 0:
        return []

    w = len(logical_grid[0])

    sprite_grid = [

        [-1] * w

        for _ in range(h)

    ]

    for y in range(h):
        for x in range(w):

            logical = logical_grid[y][x]

            if logical == EMPTY:
                continue

            neighbors = get_logical_neighbors(
                logical_grid,
                x,
                y,
            )

            sprite_grid[y][x] = select_sprite(
                logical,
                neighbors,
            )

    return sprite_grid