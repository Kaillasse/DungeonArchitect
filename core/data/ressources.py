"""Tileset loading and sprite extraction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, TypedDict

import pygame

from core.editor.autotile import FLOOR

TILE_SIZE = 16
WORLD_SCALE = 2  # world grid cells render source art at 2x (16px art -> 32px cells)

# Shared default frame-advance speed (seconds/frame) for small looping UI/
# object animations -- ObjectManager's activated/open object animation
# (button/gate/wall), ObjectPalette's hovered-icon animation, and ObjectTool's
# dragged-icon animation all use this same default. They're conceptually
# independent systems that simply happened to hardcode the identical literal
# three times each; this constant exists so that coincidence doesn't quietly
# rot into drift (one call site retuned without the others) -- not because
# they're required to move in lockstep. A caller that genuinely needs a
# different speed should just use its own local value instead of this one.
DEFAULT_ANIM_SPEED = 0.12
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TILESET_PATH = PROJECT_ROOT / "assets" / "tiles" / "tileset.png"
DEFAULT_TILE_METADATA_PATH = PROJECT_ROOT / "assets" / "tiles" / "tile_categories.json"

ROOMS_DIRECTORY = PROJECT_ROOT / "assets" / "rooms"
ROOMS_DIRECTORY.mkdir(parents=True, exist_ok=True)

DONJONS_DIRECTORY = PROJECT_ROOT / "assets" / "donjons"
DONJONS_DIRECTORY.mkdir(parents=True, exist_ok=True)

# Packs de tuiles autotilables extraits via l'editeur de sprite (voir
# core.editor.ui.SpriteEditorPanelUI, mode "Pack autotile") -- une extraction
# brute, numerotee sequentiellement, d'un bloc de tuiles 1x1 individuelles
# depuis un tileset source. Volontairement PAS branche sur
# core.editor.autotile.AUTOTILE_LOOKUP/tile_categories.json : associer
# chaque tuile numerotee a son motif de voisins (bitmask) reste une etape
# manuelle separee, exactement comme pour le tileset interieur aujourd'hui
# -- ce mecanisme retire seulement l'etape de recadrage manuel par script.
AUTOTILE_PACKS_DIRECTORY = PROJECT_ROOT / "assets" / "tiles" / "autotile_packs"
AUTOTILE_PACKS_DIRECTORY.mkdir(parents=True, exist_ok=True)


def list_autotile_packs():
    """Noms (sans .json) de chaque pack enregistre, tries."""
    return [path.stem for path in sorted(AUTOTILE_PACKS_DIRECTORY.glob("*.json"))]


def save_autotile_pack(pack_name, role, tileset, tiles):
    """Persiste un pack : `tiles` est une liste de rects (x, y, w, h) dans
    l'ordre de selection, numerotes 0..N-1 a l'ecriture. `role` ("floor"/
    "wall") filtre quels packs core.editor.ui.AutotileThemePanelUI propose
    pour le bouton Sol vs Mur. Chaque tuile part sans assignation (voir
    update_autotile_pack_tile) -- c'est core.editor.ui.SpriteEditorPanelUI's
    mode "Editeur de bitmap" qui les remplit ensuite."""
    path = get_autotile_pack_path(pack_name)
    payload = {
        "role": role,
        "tileset": tileset,
        "tiles": [{"index": i, "rect": list(rect)} for i, rect in enumerate(tiles)],
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path


def get_autotile_pack_path(pack_name):
    return AUTOTILE_PACKS_DIRECTORY / f"{pack_name}.json"


def load_autotile_pack(pack_name):
    """The parsed pack payload ({"role", "tileset", "tiles"}), or None if
    `pack_name` doesn't exist / isn't valid JSON -- same tolerant-load
    convention as every other optional JSON reader in this project."""
    path = get_autotile_pack_path(pack_name)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def update_autotile_pack_tile(pack_name, index, **fields):
    """Loads the pack, merges `fields` into tile `index`'s own dict (e.g.
    bitmask=.../default=True/variant_of=.../probability=...), rewrites the
    whole file -- the only way core.editor.ui's bitmap editor ever touches
    a pack file, so `rect`/`role`/`tileset`/every other tile are always
    carried through untouched. `default=True` clears any other tile's own
    `default` flag first (at most one default tile per pack -- see the
    format's own docstring on save_autotile_pack). A field passed as None
    is POPPED instead of stored (e.g. variant_of=None, probability=None to
    fully un-assign a variant back to a blank tile -- see
    core.editor.ui.SpriteEditorPanelUI._bm_set_variant_pct) rather than
    persisting a stray `null`. Raises ValueError if the pack or tile index
    doesn't exist."""
    payload = load_autotile_pack(pack_name)
    if payload is None:
        raise ValueError(f"Pack inconnu : {pack_name}")

    tiles = payload.get("tiles", [])
    if not (0 <= index < len(tiles)):
        raise ValueError(f"Index de tuile invalide : {index}")

    if fields.get("default") is True:
        for tile in tiles:
            tile.pop("default", None)

    for key, value in fields.items():
        if value is None:
            tiles[index].pop(key, None)
        else:
            tiles[index][key] = value

    path = get_autotile_pack_path(pack_name)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path

DEFAULT_ROOM_NAME = "room_001"


def list_rooms():
    """Names (no .json) of every saved room, sorted."""
    return [path.stem for path in sorted(ROOMS_DIRECTORY.glob("*.json"))]


def next_new_room_name():
    """First unused "room_NNN" name, following the DEFAULT_ROOM_NAME convention."""
    existing = set(list_rooms())
    index = 1
    while f"room_{index:03d}" in existing:
        index += 1
    return f"room_{index:03d}"


def list_donjons():
    """Names (no .json) of every saved procedurally-assembled dungeon, sorted."""
    return [path.stem for path in sorted(DONJONS_DIRECTORY.glob("*.json"))]


def next_new_donjon_name():
    """First unused "donjon_NNN" name."""
    existing = set(list_donjons())
    index = 1
    while f"donjon_{index:03d}" in existing:
        index += 1
    return f"donjon_{index:03d}"

class TileMetadata(TypedDict):
    category: str


def _find_tileset_path(tileset_path: Optional[Path] = None) -> Path:
    if tileset_path is not None:
        candidate = Path(tileset_path)
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Tileset not found: {candidate}")

    tiles_dir = PROJECT_ROOT / "assets" / "tiles"
    candidates = [
        DEFAULT_TILESET_PATH,
        tiles_dir / "basictileset.png",
    ]
    for entry in tiles_dir.iterdir():
        if entry.is_file() and entry.suffix.lower() == ".png":
            candidates.append(entry)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "Tileset not found. Tried: " + ", ".join(str(path) for path in candidates)
    )


def load_tileset(tileset_path: Optional[Path] = None) -> pygame.Surface:
    """Load the shared tileset image used by the dungeon editor."""
    path = _find_tileset_path(tileset_path)

    if not pygame.get_init():
        pygame.init()
    if pygame.display.get_surface() is None:
        pygame.display.set_mode((1, 1))

    surface = pygame.image.load(str(path))
    return surface.convert_alpha()


def _load_tile_metadata(path: Path) -> Dict[int, TileMetadata]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    metadata: Dict[int, TileMetadata] = {}
    for key, value in raw.items():
        metadata[int(key)] = {"category": str(value.get("category", "other")).lower()}
    return metadata

def load_tile_metadata(config_path: Optional[Path] = None) -> Dict[int, TileMetadata]:
    """Load tile category metadata used for legacy save migration."""
    path = Path(config_path or DEFAULT_TILE_METADATA_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return _load_tile_metadata(path)


def get_tile_surface(
    tileset: pygame.Surface,
    tile_index: int,
    tile_size: int = TILE_SIZE,
    columns: Optional[int] = None,
) -> pygame.Surface:
    """Return a subsurface for a tile index from the shared tileset."""
    if columns is None:
        columns = tileset.get_width() // tile_size

    if tile_index < 0:
        return pygame.Surface((tile_size, tile_size), pygame.SRCALPHA)

    row = tile_index // columns
    col = tile_index % columns
    rect = pygame.Rect(col * tile_size, row * tile_size, tile_size, tile_size)

    if rect.right > tileset.get_width() or rect.bottom > tileset.get_height():
        return pygame.Surface((tile_size, tile_size), pygame.SRCALPHA)

    return tileset.subsurface(rect).copy()


# ---------------------------------------------------------------------
# Sourcing par region libre dans un tileset nomme (sprite editor)
# ---------------------------------------------------------------------

_named_tileset_cache: Dict[str, pygame.Surface] = {}


def load_tileset_by_name(filename: str) -> pygame.Surface:
    """Charge (et met en cache par nom de fichier) n'importe quel PNG sous
    assets/tiles/ -- contrairement a load_tileset (qui resout "LE" tileset
    partage via la chaine de repli de _find_tileset_path), c'est une
    recherche explicite pour un fichier precis, utilisee par
    load_tileset_region pour sourcer une region depuis un tileset
    secondaire (ex: une feuille de props decoratifs) sans passer par cette
    logique de repli. Le cache evite de relire le fichier depuis le disque
    a chaque nouvelle carte qui reference la meme feuille."""
    if filename not in _named_tileset_cache:
        path = PROJECT_ROOT / "assets" / "tiles" / filename
        if not pygame.get_init():
            pygame.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((1, 1))
        surface = pygame.image.load(str(path))
        _named_tileset_cache[filename] = surface.convert_alpha()
    return _named_tileset_cache[filename]


def load_tileset_region(filename: str, rect) -> pygame.Surface:
    """Recadre un rectangle pixel arbitraire (x, y, w, h) dans
    assets/tiles/<filename> -- contrairement a get_tile_surface (qui suppose
    une grille reguliere de tile_size), c'est pour une feuille qui n'est pas
    uniformement gridee (ex: tileset2.png, un empilement de props de tailles
    variables). Utilise par toute entree OBJECT_TYPES dont "asset" est un
    dict {"tileset": ..., "rect": [...]} plutot qu'un chemin de fichier brut
    -- voir core.world.object_manager.load_object_frames."""
    tileset = load_tileset_by_name(filename)
    x, y, w, h = rect
    bounds = pygame.Rect(0, 0, tileset.get_width(), tileset.get_height())
    clipped = pygame.Rect(x, y, w, h).clip(bounds)
    if clipped.width <= 0 or clipped.height <= 0:
        return pygame.Surface((max(1, w), max(1, h)), pygame.SRCALPHA)
    return tileset.subsurface(clipped).copy()