from __future__ import annotations

import json
import zlib
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

def build_walls_around(logical_grid: List[List[int]], x: int, y: int, gate=None) -> None:
    """Mure les voisins EMPTY (8 directions) de la case (x, y) qui vient
    d'être peinte en FLOOR. Ne touche à aucune autre case de la grille.

    gate: callable optionnel (nx, ny) -> bool, consulté juste avant de murer
    chaque voisin candidat -- False laisse cette case telle quelle (vide) au
    lieu de la murer, True/gate=None (comportement d'origine, inchangé) la
    mure normalement. Ce module reste volontairement ignorant de tout ce
    qui motive un refus (ex: core.editor.creator.Creator branche ici une
    verification de stock de cartes) -- gate est un simple predicat
    generique, pas une notion propre a autotile.py."""

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
                if gate is None or gate(nx, ny):
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
# Packs autotile custom (core.editor.ui.SpriteEditorPanelUI's mode "Editeur
# de bitmap" / core.data.ressources.save_autotile_pack, update_autotile_
# pack_tile) -- une room peut peindre son sol et/ou son mur avec un pack a
# la place du tileset interieur par defaut (voir Dungeon.floor_theme/
# wall_theme). Deliberement a cote de AUTOTILE_LOOKUP/select_sprite
# ci-dessus, rien n'y est retire/renomme -- une room sans theme (le cas par
# defaut, floor_pack=wall_pack=None partout) suit exactement le meme chemin
# qu'avant cette section.
# --------------------------------------------------------------------

# Sentinel `variant_of` value (never a real bitmask -- those are always 4
# digits from {0,1,2}, this is a plain word) meaning "a variant of the
# pack's own default/fallback tile" rather than of one specific assigned
# shape. Lets a pack offer cosmetic variety (core.editor.ui.SpriteEditorPanelUI's
# Variante mode, "+" cell) without the player ever having to compose/assign
# a bitmask at all -- confirmed with the user after they got stuck manually
# building an unreachable shape ("0000", impossible for a real floor cell
# since build_walls always walls in an empty neighbor) trying to do exactly
# this. Marking a tile default (SpriteEditorPanelUI._bm_mark_default) never
# required a bitmask to begin with, so this only needed a resolution-side
# change (_resolve_pack_sprite below) plus the editor letting a
# default-only tile anchor a family too.
DEFAULT_VARIANT_KEY = "default"

_pack_lookup_cache: Dict[str, tuple] = {}


def build_pack_lookup(pack_name: str):
    """(lookup: {bitmask: tile_index}, default_index, variants:
    {bitmask: [(variant_tile_index, probability), ...]}) built from the
    pack's own saved bitmask/default/variant_of/probability fields (see
    core.data.ressources.update_autotile_pack_tile). `variants` is keyed by
    the BITMASK a variant stands in for, not a tile index -- the base tile
    assigned to that bitmask can be repointed later without needing to
    update every variant that references the shape. Cached per
    (pack_name, file mtime) -- a stat() call, not a full reparse, on every
    call after the first; reloaded automatically the moment the bitmap
    editor saves a new assignment (the file's mtime advances)."""
    from core.data.ressources import load_autotile_pack, get_autotile_pack_path

    try:
        mtime = get_autotile_pack_path(pack_name).stat().st_mtime
    except OSError:
        mtime = None

    cached = _pack_lookup_cache.get(pack_name)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    payload = load_autotile_pack(pack_name) or {"tiles": []}
    lookup: Dict[str, int] = {}
    default_index = 0
    variants: Dict[str, list] = {}
    for tile in payload.get("tiles", []):
        index = tile.get("index")
        if index is None:
            continue
        bitmask = tile.get("bitmask")
        if bitmask:
            lookup[bitmask] = index
        if tile.get("default"):
            default_index = index
        variant_of = tile.get("variant_of")
        if variant_of:
            variants.setdefault(variant_of, []).append((index, float(tile.get("probability", 0.0))))

    result = (lookup, default_index, variants)
    _pack_lookup_cache[pack_name] = (mtime, result)
    return result


def _stable_roll(*parts) -> float:
    """A deterministic [0, 1) float from `parts`, stable across process
    restarts -- unlike `random.Random((...)).random()` (this module's
    previous approach) when the seed tuple contains a str: random.seed()
    falls back to hash() for a non-int/float seed, and Python randomizes
    str hashing per-process by default (PYTHONHASHSEED), so a pack tile's
    variant roll silently came out DIFFERENT every time the game
    restarted, or between a multiplayer server and a client -- even though
    nothing was ever repainted (found while optimizing this away from
    constructing a fresh random.Random per cell; both _resolve_pack_sprite
    and _pick_variant use this now). An int-only seed (_pick_variant's own
    (x, y, sprite_index)) was never actually affected -- int hashing isn't
    randomized -- but sharing one helper avoids allocating a Random object
    per cell either way, which is what actually matters on a full-grid
    resync. CRC32 over a stable string encoding: not cryptographic, but
    plenty uniform for picking among a handful of weighted variants."""
    key = "|".join(str(part) for part in parts).encode("utf-8")
    return zlib.crc32(key) / 0xFFFFFFFF


def _resolve_pack_sprite(pack_name: str, value: str, x: int, y: int) -> int:
    """The pack tile index for neighbor pattern `value` at (x, y) -- picks
    among build_pack_lookup's variants for this bitmask via one weighted
    deterministic roll (generalizes _pick_variant's single hardcoded
    alternate to any number of pack-declared variants), falling back to the
    base/default tile if nothing rolls or no variants exist.

    If `value` has no tile explicitly claiming it as its own bitmask (the
    common case for a pack the player never bothered autotiling shape by
    shape -- every cell falls through to the plain default tile), the
    default tile's OWN variants (registered under DEFAULT_VARIANT_KEY) get
    a roll too, instead of always returning the bare default sprite. A
    shape that DOES have its own explicit bitmask keeps using only that
    shape's own variants, unaffected."""
    lookup, default_index, variants = build_pack_lookup(pack_name)
    base_index = lookup.get(value, default_index)

    variant_list = variants.get(value)
    if not variant_list and value not in lookup:
        variant_list = variants.get(DEFAULT_VARIANT_KEY)
    if not variant_list:
        return base_index

    roll = _stable_roll(x, y, pack_name, value)
    cumulative = 0.0
    for variant_index, probability in variant_list:
        cumulative += probability
        if roll < cumulative:
            return variant_index
    return base_index


# --------------------------------------------------------------------
# Génération sprite grid
# --------------------------------------------------------------------

def _resolve_cell_sprite(
    logical_grid: List[List[int]], x: int, y: int, floor_pack=None, wall_pack=None,
) -> int:
    """The sprite index for a single cell -- shared by resolve_sprite_grid's
    full-grid rebuild and resolve_sprite_grid_region's bounded one, so the
    two never risk drifting into computing a cell's sprite differently.

    floor_pack/wall_pack (Dungeon.floor_theme/wall_theme, see dungeon.py)
    default to None -- the exact pre-theme code path (select_sprite +
    _pick_variant's interior-only variant) runs unchanged whenever both are
    unset, which is every room until it explicitly opts into a theme."""
    logical = logical_grid[y][x]
    if logical == EMPTY:
        return -1

    neighbors = get_logical_neighbors(logical_grid, x, y)
    pack_name = floor_pack if logical == FLOOR else wall_pack
    if pack_name is not None:
        return _resolve_pack_sprite(pack_name, get_neighbor_value(neighbors), x, y)

    sprite = select_sprite(logical, neighbors)
    return _pick_variant(sprite, x, y)


def resolve_sprite_grid(
    logical_grid: List[List[int]],
    floor_pack=None,
    wall_pack=None,
):

    h = len(logical_grid)

    if h == 0:
        return []

    w = len(logical_grid[0])

    return [
        [_resolve_cell_sprite(logical_grid, x, y, floor_pack, wall_pack) for x in range(w)]
        for y in range(h)
    ]


# A cell's sprite only ever depends on its own 4 cardinal neighbors (see
# get_logical_neighbors/select_sprite) -- so a logical-grid edit confined to
# a bounded neighborhood only ever needs a correspondingly bounded
# neighborhood of sprites recomputed, never resolve_sprite_grid's full
# O(width*height) rescan. Dungeon.paint_cell's autotile cascade
# (build_walls_around/unbuild_walls_around, each strictly local to the
# clicked cell's own 8-neighborhood, chained at most one further hop by
# paint_cell's erase-a-wall branch) never mutates the logical grid beyond
# Chebyshev distance 2 of the clicked cell -- +1 more for the cardinal-
# neighbor sprite dependency above gives a safe upper bound of 3.
LOCAL_EDIT_SPRITE_RADIUS = 3


def resolve_sprite_grid_region(
    logical_grid: List[List[int]],
    sprite_grid: List[List[int]],
    center_x: int,
    center_y: int,
    radius: int = LOCAL_EDIT_SPRITE_RADIUS,
    floor_pack=None,
    wall_pack=None,
) -> None:
    """Recomputes sprite_grid IN PLACE for every cell within `radius`
    (Chebyshev) of (center_x, center_y) instead of resolve_sprite_grid's
    full-grid rebuild -- see the module comment above LOCAL_EDIT_SPRITE_RADIUS
    for why a bounded neighborhood is exactly as correct. `sprite_grid` must
    already have the same dimensions as `logical_grid` (true throughout
    Dungeon.paint_cell/destroy_area's lifetime -- only a load/resize ever
    changes dimensions, and those go through resolve_sprite_grid's full
    rebuild instead, see Dungeon.resync_sprite_grid). floor_pack/wall_pack:
    see _resolve_cell_sprite."""
    h = len(logical_grid)
    if h == 0:
        return
    w = len(logical_grid[0])

    for y in range(max(0, center_y - radius), min(h, center_y + radius + 1)):
        for x in range(max(0, center_x - radius), min(w, center_x + radius + 1)):
            sprite_grid[y][x] = _resolve_cell_sprite(logical_grid, x, y, floor_pack, wall_pack)


def _pick_variant(sprite_index: int, x: int, y: int) -> int:
    """Cosmetic alternate for the plain interior floor/wall tile (see
    FLOOR_VARIANT_SPRITE/WALL_VARIANT_SPRITE) -- deterministic per cell
    position (_stable_roll, not the module-level random state) so
    repainting elsewhere in the room, which re-runs resolve_sprite_grid,
    never reshuffles a variant already chosen for an untouched cell."""
    if sprite_index == DEFAULT_FLOOR_SPRITE:
        alt = FLOOR_VARIANT_SPRITE
    elif sprite_index == DEFAULT_WALL_SPRITE:
        alt = WALL_VARIANT_SPRITE
    else:
        return sprite_index

    if _stable_roll(x, y, sprite_index) < VARIANT_PROBABILITY:
        return alt
    return sprite_index