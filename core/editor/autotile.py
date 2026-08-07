from __future__ import annotations

import json
import random
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

# Phase 6a: purely cosmetic alternates for the plain interior floor/wall
# tile -- basictileset.png frames 15/4, picked instead of 14/3 with fixed
# probability VARIANT_PROBABILITY. Only ever substituted for these two exact
# indices (see resolve_sprite_grid) -- every other autotile shape (corners,
# edges, doorway breaks) is untouched.
FLOOR_VARIANT_SPRITE = 15
WALL_VARIANT_SPRITE = 4
VARIANT_PROBABILITY = 0.3

_CARDINAL_OFFSETS = (
    (0, -1),
    (1, 0),
    (0, 1),
    (-1, 0),
)

# --------------------------------------------------------------------
# Chargement du JSON
# --------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
# Murs incrémentaux -- contrairement à build_walls (strip + rescan de toute
# la grille), ces deux fonctions ne touchent jamais qu'au voisinage immédiat
# de la case peinte/effacée. C'est ce que Dungeon.paint_cell utilise
# désormais : peindre une case avec l'autotile actif ne doit murer QUE ses
# propres voisins vides, jamais re-dériver les murs de tout le reste de la
# salle (ce que build_walls ferait, visible dès qu'on avait peint du sol
# sans mur pendant que l'autotile était désactivé puis qu'on le réactive).
# --------------------------------------------------------------------

def build_walls_around(logical_grid: List[List[int]], x: int, y: int) -> None:
    """Mure les voisins EMPTY (8 directions) de la case (x, y) qui vient
    d'être peinte en FLOOR. Ne touche à aucune autre case de la grille."""

    h = len(logical_grid)
    if h == 0:
        return
    w = len(logical_grid[0])

    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):

            if dx == 0 and dy == 0:
                continue

            nx = x + dx
            ny = y + dy

            if 0 <= nx < w and 0 <= ny < h and logical_grid[ny][nx] == EMPTY:
                logical_grid[ny][nx] = WALL


def unbuild_walls_around(logical_grid: List[List[int]], x: int, y: int) -> None:
    """Inverse local de build_walls_around, appelé après avoir effacé la case
    (x, y) : chacun de ses voisins WALL qui ne borde plus aucune case FLOOR
    (en vérifiant les 8 voisins de CE voisin) redevient EMPTY."""

    h = len(logical_grid)
    if h == 0:
        return
    w = len(logical_grid[0])

    def get(px, py):
        if 0 <= px < w and 0 <= py < h:
            return logical_grid[py][px]
        return EMPTY

    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):

            if dx == 0 and dy == 0:
                continue

            nx = x + dx
            ny = y + dy

            if not (0 <= nx < w and 0 <= ny < h) or logical_grid[ny][nx] != WALL:
                continue

            still_needed = any(
                get(nx + ddx, ny + ddy) == FLOOR
                for ddx in (-1, 0, 1)
                for ddy in (-1, 0, 1)
                if not (ddx == 0 and ddy == 0)
            )

            if not still_needed:
                logical_grid[ny][nx] = EMPTY

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

            sprite = select_sprite(
                logical,
                neighbors,
            )

            sprite_grid[y][x] = _pick_variant(sprite, x, y)

    return sprite_grid


def _pick_variant(sprite_index: int, x: int, y: int) -> int:
    """Cosmetic alternate for the plain interior floor/wall tile (see
    FLOOR_VARIANT_SPRITE/WALL_VARIANT_SPRITE) -- deterministic per cell
    position (a fresh Random(seed) instead of the module-level random state)
    so repainting elsewhere in the room, which re-runs resolve_sprite_grid,
    never reshuffles a variant already chosen for an untouched cell."""
    if sprite_index == DEFAULT_FLOOR_SPRITE:
        alt = FLOOR_VARIANT_SPRITE
    elif sprite_index == DEFAULT_WALL_SPRITE:
        alt = WALL_VARIANT_SPRITE
    else:
        return sprite_index

    if random.Random((x, y, sprite_index)).random() < VARIANT_PROBABILITY:
        return alt
    return sprite_index