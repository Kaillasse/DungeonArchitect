"""Tileset loading and sprite extraction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, TypedDict

import pygame

from core.autotile import FLOOR

TILE_SIZE = 16
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TILESET_PATH = PROJECT_ROOT / "assets" / "tiles" / "tileset.png"
DEFAULT_TILE_METADATA_PATH = PROJECT_ROOT / "assets" / "tiles" / "tile_categories.json"

ROOMS_DIRECTORY = PROJECT_ROOT / "assets" / "rooms"
ROOMS_DIRECTORY.mkdir(parents=True, exist_ok=True)

DEFAULT_ROOM_NAME = "room_001"

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

#class Tool(Enum):
    PAINT = 0
    ERASE = 1
    SPAWN = 2

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


def set_spawn_from_screen(
    self,
    screen_x,
    screen_y,
    offset_x,
    offset_y,
    zoom,
):

    grid_x = (screen_x - offset_x) // (self.tile_size * zoom)
    grid_y = (screen_y - offset_y) // (self.tile_size * zoom)

    self.set_spawn(grid_x, grid_y)