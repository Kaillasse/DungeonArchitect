"""Tileset loading and sprite extraction."""

from __future__ import annotations

import json
import re
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

# Packs de tuiles/regions extraits via l'editeur de sprite (voir
# core.editor.ui.SpriteEditorPanelUI, modes "Pack") -- une extraction brute,
# numerotee sequentiellement, d'un bloc de regions individuelles depuis un
# tileset/feuille source. Deux "kind" partagent ce meme format de fichier
# (voir payload["kind"] ci-dessous) : "autotile" (le cas d'origine --
# volontairement PAS branche sur core.editor.autotile.AUTOTILE_LOOKUP/
# tile_categories.json, associer chaque tuile a son motif de voisins reste
# une etape manuelle separee) et "entity" (regions d'une feuille de
# personnage/PNJ, taguees action+direction+ordre au lieu d'un bitmask --
# voir object_manager.build_entity_pack_lookup). Le format `tiles: [{"index",
# "rect", ...metadonnees libres selon le kind...}]` est deja generique ;
# seule la nature des metadonnees change.
AUTOTILE_PACKS_DIRECTORY = PROJECT_ROOT / "assets" / "tiles" / "autotile_packs"
AUTOTILE_PACKS_DIRECTORY.mkdir(parents=True, exist_ok=True)


def list_autotile_packs(kind=None):
    """Noms (sans .json) de chaque pack enregistre, tries. kind=None (par
    defaut) liste tout ; kind="autotile"/"entity" filtre -- un pack sans
    champ "kind" du tout (tout pack enregistre avant l'ajout de ce champ)
    est traite comme "autotile", pour ne rien casser sur les packs deja sur
    disque."""
    names = [path.stem for path in sorted(AUTOTILE_PACKS_DIRECTORY.glob("*.json"))]
    if kind is None:
        return names
    return [name for name in names if (load_autotile_pack(name) or {}).get("kind", "autotile") == kind]


def save_autotile_pack(pack_name, role, tileset, tiles, kind="autotile", columns=None):
    """Persiste un pack : `tiles` est une liste de rects (x, y, w, h) dans
    l'ordre de selection, numerotes 0..N-1 a l'ecriture. `role` ("floor"/
    "wall") filtre quels packs core.editor.ui.AutotileThemePanelUI propose
    pour le bouton Sol vs Mur -- sans objet pour kind="entity" (laisse a
    None dans ce cas, rien ne le lit alors). Chaque tuile part sans
    assignation (voir update_autotile_pack_tile/update_autotile_pack_tiles)
    -- c'est core.editor.ui.SpriteEditorPanelUI's mode "Editeur de bitmap"
    qui les remplit ensuite.

    `columns` : le nombre de colonnes de la grille de decoupe d'origine
    (mode "pack", width_tiles au moment de l'enregistrement) -- utilise
    UNIQUEMENT par kind="entity" pour que le mode Bitmap affiche/ordonne
    les tuiles selon la MEME grille que celle du fichier source (une ligne
    affichee == une vraie ligne de la feuille, ex. une direction), au lieu
    d'un retour a la ligne pilote par la largeur (en pixels) du visualiseur
    -- sans quoi une feuille de personnage avec plus de colonnes reelles
    que le visualiseur n'en affiche par ligne se retrouve visuellement
    reorganisee, rendant la selection rectangulaire par action/direction
    fastidieuse. None (packs kind="autotile", ou un ancien pack "entity"
    enregistre avant l'ajout de ce champ) retombe sur l'ancien calcul
    base sur la largeur du visualiseur (voir SpriteEditorPanelUI.
    _bm_grid_columns) -- l'ordre n'a jamais eu d'importance fonctionnelle
    pour un pack autotile, chaque tuile y est taguee individuellement quel
    que soit son emplacement a l'ecran."""
    path = get_autotile_pack_path(pack_name)
    payload = {
        "kind": kind,
        "role": role,
        "tileset": tileset,
        "columns": columns,
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


def _merge_tile_fields(tiles, index, fields):
    """Shared by update_autotile_pack_tile/update_autotile_pack_tiles: merges
    `fields` into tiles[index]'s own dict (e.g. bitmask=.../default=True/
    variant_of=.../probability=..., or action=.../direction=.../order=... for
    an entity-kind pack). `default=True` clears any other tile's own
    `default` flag first (at most one default tile per pack -- see
    save_autotile_pack's own docstring). A field passed as None is POPPED
    instead of stored (e.g. variant_of=None to fully un-assign back to a
    blank tile) rather than persisting a stray `null`. Factored out so the
    single-tile and batch entry points can't drift on this convention."""
    if fields.get("default") is True:
        for tile in tiles:
            tile.pop("default", None)

    for key, value in fields.items():
        if value is None:
            tiles[index].pop(key, None)
        else:
            tiles[index][key] = value


def update_autotile_pack_tile(pack_name, index, **fields):
    """Loads the pack, merges `fields` into tile `index`'s own dict (see
    _merge_tile_fields), rewrites the whole file -- the only way
    core.editor.ui's bitmap editor ever touches a pack file for a single
    tile, so `rect`/`role`/`tileset`/every other tile are always carried
    through untouched. Raises ValueError if the pack or tile index doesn't
    exist. See update_autotile_pack_tiles for tagging several tiles in one
    write (e.g. batch action/direction tagging of an entity pack)."""
    payload = load_autotile_pack(pack_name)
    if payload is None:
        raise ValueError(f"Pack inconnu : {pack_name}")

    tiles = payload.get("tiles", [])
    if not (0 <= index < len(tiles)):
        raise ValueError(f"Index de tuile invalide : {index}")

    _merge_tile_fields(tiles, index, fields)

    path = get_autotile_pack_path(pack_name)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path


def update_autotile_pack_tiles(pack_name, updates):
    """Same merge convention as update_autotile_pack_tile, but for several
    tiles in ONE load+write instead of one round trip per tile -- e.g.
    tagging a whole selected action/direction block of an entity pack
    (dozens of tiles) as a single disk write instead of dozens. `updates`
    is {index: {field: value, ...}, ...}. Raises ValueError (without
    writing anything) if the pack or any index doesn't exist -- either the
    whole batch applies or none of it does."""
    payload = load_autotile_pack(pack_name)
    if payload is None:
        raise ValueError(f"Pack inconnu : {pack_name}")

    tiles = payload.get("tiles", [])
    for index in updates:
        if not (0 <= index < len(tiles)):
            raise ValueError(f"Index de tuile invalide : {index}")

    for index, fields in updates.items():
        _merge_tile_fields(tiles, index, fields)

    path = get_autotile_pack_path(pack_name)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path

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


# ---------------------------------------------------------------------
# Reference scanning + delete/rename for autotile/entity packs -- CRUD
# parity with core.engine.room_manager.RoomManager (rooms already have
# delete()/rename()). Unlike a room, a pack's name is a VALUE stored
# elsewhere (floor_theme/wall_theme on any room or dungeon that uses it
# as its terrain theme) rather than something only ever looked up by its
# own filename, so deleting/renaming one safely means checking -- and,
# for rename, updating -- every place that stores that name. See
# core.world.object_manager.delete_custom_type/
# rename_entity_pack_references for the equivalent on the custom-object-
# type side (which packs don't need to worry about: a custom type never
# references a pack by name, only a raw tileset path).
# ---------------------------------------------------------------------

_SAFE_PACK_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_PACK_NAME_LENGTH = 64  # a pack name doubles as a raw filename -- same cap as room names


def _sanitize_pack_name(name):
    """Restricts a pack name to [A-Za-z0-9_-], capped in length -- same
    convention as core.engine.room_manager._sanitize_room_name (a pack
    name is also used directly as a filename, see get_autotile_pack_path).
    Duplicated rather than imported: room_manager already imports FROM
    this module, so importing back from it here would be a cycle."""
    return _SAFE_PACK_NAME_RE.sub("_", str(name or "").strip())[:_MAX_PACK_NAME_LENGTH]


def _iter_room_payloads():
    """(room_name, parsed JSON payload) for every saved room -- skips a
    corrupt/unreadable file rather than raising, same tolerance as every
    other optional JSON reader in this module. Reads the raw dict directly
    instead of instantiating a Dungeon, since pack_references/
    type_references only ever need a couple of top-level fields."""
    for name in list_rooms():
        path = ROOMS_DIRECTORY / f"{name}.json"
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            yield name, payload


def _iter_donjon_room_payloads():
    """(donjon_name, room-within-donjon payload) for every room embedded in
    every saved dungeon assembly -- each entry already carries its own
    "objects"/"floor_theme"/"wall_theme" (core.world.assembly.
    save_assembly spreads a full room payload into each "rooms" entry), so
    the shape matches _iter_room_payloads' own yield exactly, just nested
    one level under "rooms". Yields the donjon's name (not the embedded
    room's own room_name) since that's the file a rename/delete cascade
    needs to rewrite."""
    for name in list_donjons():
        path = DONJONS_DIRECTORY / f"{name}.json"
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        for room_payload in payload.get("rooms", []):
            if isinstance(room_payload, dict):
                yield name, room_payload


def pack_references(pack_name):
    """Names of every room and saved dungeon whose floor_theme or
    wall_theme references `pack_name` -- checked before
    delete_autotile_pack acts (SpriteEditorPanelUI refuses the deletion
    and explains where it's used instead of calling delete at all) and by
    rename_autotile_pack to know which files its own cascade needs to
    rewrite."""
    found = set()
    for name, payload in _iter_room_payloads():
        if payload.get("floor_theme") == pack_name or payload.get("wall_theme") == pack_name:
            found.add(name)
    for name, room_payload in _iter_donjon_room_payloads():
        if room_payload.get("floor_theme") == pack_name or room_payload.get("wall_theme") == pack_name:
            found.add(name)
    return sorted(found)


def type_references(type_id):
    """Names of every room and saved dungeon with a placed object of
    `type_id` -- same purpose as pack_references, for
    core.world.object_manager.delete_custom_type. Rooms/dungeons are the
    only place a type_id is referenced outside OBJECT_TYPES itself;
    without this check, deleting a type still placed somewhere would leave
    that room's ObjectManager.is_cell_walkable (and friends) hitting a bare
    OBJECT_TYPES[obj["type"]] KeyError the next time it's loaded, not a
    graceful degradation."""
    found = set()
    for name, payload in _iter_room_payloads():
        if any(obj.get("type") == type_id for obj in payload.get("objects", [])):
            found.add(name)
    for name, room_payload in _iter_donjon_room_payloads():
        if any(obj.get("type") == type_id for obj in room_payload.get("objects", [])):
            found.add(name)
    return sorted(found)


def delete_autotile_pack(pack_name):
    """Unlinks the pack's JSON file if present -- mirrors
    core.engine.room_manager.RoomManager.delete exactly, including NOT
    checking pack_references itself (same split of responsibility as
    RoomManager.delete not checking whether a room is anyone's home) --
    the caller checks first and refuses with an explanation instead of
    ever calling this while something still depends on the pack."""
    path = get_autotile_pack_path(pack_name)
    if path.exists():
        path.unlink()


def rename_autotile_pack(old_name, new_name):
    """Renames a pack's JSON file AND cascades the change into every room/
    dungeon that referenced it by name (floor_theme/wall_theme) -- unlike
    a room rename (RoomManager.rename, which never needs this: nothing
    stores a room's OWN name inside its own payload), a pack's name is
    stored BY VALUE wherever it's selected as a terrain theme. Same
    refusal shape as RoomManager.rename (source missing, or sanitized
    target empty/identical/already-taken -> None, no exception) -- driven
    by freeform player text the caller can't fully trust. Returns the
    actual sanitized name on success, so the caller can update whatever
    else it holds (e.g. SpriteEditorPanelUI.bm_pack_name)."""
    old_path = get_autotile_pack_path(old_name)
    if not old_path.exists():
        return None

    safe_new_name = _sanitize_pack_name(new_name)
    if not safe_new_name or safe_new_name == old_name:
        return None

    new_path = get_autotile_pack_path(safe_new_name)
    if new_path.exists():
        return None

    affected_names = set(pack_references(old_name))
    old_path.rename(new_path)

    for room_name, payload in _iter_room_payloads():
        if room_name not in affected_names:
            continue
        changed = False
        if payload.get("floor_theme") == old_name:
            payload["floor_theme"] = safe_new_name
            changed = True
        if payload.get("wall_theme") == old_name:
            payload["wall_theme"] = safe_new_name
            changed = True
        if changed:
            with (ROOMS_DIRECTORY / f"{room_name}.json").open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)

    for donjon_name in list_donjons():
        if donjon_name not in affected_names:
            continue
        donjon_path = DONJONS_DIRECTORY / f"{donjon_name}.json"
        try:
            with donjon_path.open("r", encoding="utf-8") as handle:
                donjon_payload = json.load(handle)
        except (OSError, ValueError):
            continue
        changed = False
        for room_payload in donjon_payload.get("rooms", []):
            if room_payload.get("floor_theme") == old_name:
                room_payload["floor_theme"] = safe_new_name
                changed = True
            if room_payload.get("wall_theme") == old_name:
                room_payload["wall_theme"] = safe_new_name
                changed = True
        if changed:
            with donjon_path.open("w", encoding="utf-8") as handle:
                json.dump(donjon_payload, handle, indent=2, ensure_ascii=False)

    return safe_new_name

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


_tileset_cache: Dict[Path, pygame.Surface] = {}


def load_tileset(tileset_path: Optional[Path] = None) -> pygame.Surface:
    """Load (and cache by resolved path) the shared tileset image used by
    the dungeon editor. Every throwaway Dungeon() (assembly room scanning,
    card thumbnails/manifests) builds a WorldRenderer that calls this, so
    without a cache the same PNG gets reloaded/reconverted from disk over
    and over -- mirrors load_tileset_by_name's _named_tileset_cache."""
    path = _find_tileset_path(tileset_path)

    if path not in _tileset_cache:
        if not pygame.get_init():
            pygame.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((1, 1))

        surface = pygame.image.load(str(path))
        _tileset_cache[path] = surface.convert_alpha()

    return _tileset_cache[path]


def _load_tile_metadata(path: Path) -> Dict[int, TileMetadata]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    metadata: Dict[int, TileMetadata] = {}
    for key, value in raw.items():
        metadata[int(key)] = {"category": str(value.get("category", "other")).lower()}
    return metadata

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
    """Charge (et met en cache par chemin) n'importe quel PNG sous assets/ --
    contrairement a load_tileset (qui resout "LE" tileset partage via la
    chaine de repli de _find_tileset_path), c'est une recherche explicite
    pour un fichier precis, utilisee par load_tileset_region pour sourcer
    une region depuis un tileset secondaire (ex: une feuille de props
    decoratifs, ou -- depuis l'ajout des packs d'entite/PNJ -- une feuille
    de personnage sous assets/characters/) sans passer par cette logique de
    repli. `filename` est un chemin relatif a assets/ (ex.
    "characters/Animals/blackcat.png"), pas force sous assets/tiles/ comme
    avant -- mais un simple nom de fichier nu (ex. "tileset2.png", ce que
    tout pack autotile deja enregistre sur disque stocke) est retente sous
    assets/tiles/<filename> si assets/<filename> n'existe pas, pour rester
    compatible avec ces packs sans migration de donnees. Le cache evite de
    relire le fichier depuis le disque a chaque nouvelle carte qui
    reference la meme feuille."""
    if filename not in _named_tileset_cache:
        path = PROJECT_ROOT / "assets" / filename
        if not path.exists():
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
    assets/<filename> (voir load_tileset_by_name pour la resolution du
    chemin, y compris characters/) -- contrairement a get_tile_surface (qui suppose
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


def save_tileset_png(surface: pygame.Surface, relative_path: str) -> None:
    """Ecrit `surface` en PNG sous assets/<relative_path> (creant les
    dossiers parents au besoin) puis invalide l'entree correspondante de
    _named_tileset_cache -- sans ca, tout load_tileset_by_name(relative_path)
    ulterieur (une autre carte qui partage cette feuille, ou l'editeur de
    sprite lui-meme en rouvrant le fichier) reservirait la Surface pre-
    edition mise en cache, silencieusement. Seul point d'ecriture PNG du
    projet (core.editor.ui.sprite_editor's mode "pixel", voir son propre
    _px_save) -- centralise ici plutot que d'appeler pygame.image.save
    directement depuis l'UI pour que ce correctif de cache ne puisse pas
    etre oublie a un futur appelant."""
    path = PROJECT_ROOT / "assets" / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surface, str(path))
    _named_tileset_cache.pop(relative_path, None)