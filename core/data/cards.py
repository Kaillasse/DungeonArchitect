"""The Card system (Vision produit v0.05, see CLAUDE.md): every placeable
tile/mob/item, and eventually every PNJ, is meant to become a Card -- a name,
one or more images, a type, and a list of effects that the player collects
and can use to populate/customize their dungeon.

This module is the foundation slice only: the data model, its persistence,
and an automatic bridge from today's existing registries (OBJECT_TYPES,
ITEM_DEFINITIONS in core.world.object_manager) so the current tile/mob/item
roster becomes "cards" for free, with no hand-authored JSON needed. Effect
execution, card creation/editing, and card-driven placement are deliberately
not part of this slice -- see CLAUDE.md's Card system entry for the full
scope split.

Mirrors core.data.profile_manager's "stateless converter, tolerant load"
shape, and core.data.ressources' Path(...).mkdir(parents=True, exist_ok=True)
directory-constant convention.
"""

from __future__ import annotations

import json
from pathlib import Path

import pygame

from core.world.object_manager import OBJECT_TYPES, ITEM_DEFINITIONS, load_object_frames, make_item
from core.data.ressources import load_tileset, get_tile_surface, list_rooms, ROOMS_DIRECTORY
from core.editor.autotile import DEFAULT_FLOOR_SPRITE, DEFAULT_WALL_SPRITE, FLOOR, WALL

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CARDS_DIRECTORY = PROJECT_ROOT / "assets" / "cards"
CARDS_DIRECTORY.mkdir(parents=True, exist_ok=True)

# "pnj" is reserved -- zero cards of this type exist until the PNJ system
# itself is built (a separate, later vision item). "room" is the newest --
# see room_card_id/default_card_for's room branch below.
CARD_TYPES = ("tile", "item", "mob", "room", "pnj")

# Prefix namespacing a saved room (assets/rooms/<name>.json) as a Card id --
# a double underscore rather than e.g. ":" since a room name is already
# guaranteed filesystem-safe (see core.engine.room_manager.rename's own
# sanitization) and this must itself remain a valid Windows filename
# component (CardManager.get_card_path uses the card_id directly). No
# collision risk with any OBJECT_TYPES/ITEM_DEFINITIONS/BASE_TILE_CARDS id --
# none of those use this prefix.
ROOM_CARD_PREFIX = "room__"

# The two raw terrain-cell "tiles" a Creator can paint (see
# core.editor.creator.Creator._paint_at_mouse) -- deliberately NOT bridged
# from OBJECT_TYPES like every other tile/mob card, since OBJECT_TYPES
# already has an unrelated "wall" entry (the doorway wall *object*, not a
# raw WALL terrain cell) that a card id of "wall" would collide with.
# Plain data (not pre-built Card instances) so default_card_for() always
# constructs a fresh Card, same as every other branch -- a shared mutable
# instance here could get corrupted by a future caller that mutates the
# Card it was handed.
BASE_TILE_CARDS = {
    "tile_floor": {"name": "Sol", "images": ["tiles/basictileset.png"]},
    "tile_wall": {"name": "Mur", "images": ["tiles/basictileset.png"]},
}

# What a brand-new Profile's card_collection starts with (see
# core.data.profile_manager.ProfileManager.load's "file absent" branch) --
# every other card starts at 0 (nothing else placeable until acquired).
STARTING_CARD_COLLECTION = {"tile_floor": 20, "tile_wall": 20}


def room_card_id(room_name):
    return f"{ROOM_CARD_PREFIX}{room_name}"


def room_name_from_card_id(card_id):
    """The room name a room-card id refers to, or None if card_id isn't one
    (any other card type, or a plain unprefixed string) -- the single check
    every room-card-aware caller (CardPanelUI's drag-start, Creator's
    drop-on-Generator handling, CardRenderer's room layout) goes through."""
    if card_id.startswith(ROOM_CARD_PREFIX):
        return card_id[len(ROOM_CARD_PREFIX):]
    return None


def _room_file_exists(room_name):
    """A single stat() check, not list_rooms()'s full directory glob --
    default_card_for is called once per card id every time CardPanelUI/
    GeneratorPanelUI's grids resolve a room card (see core.editor.ui), so
    using list_rooms() here would re-glob assets/rooms/ once per visible
    room-card on top of the one glob list_known_card_ids() already does to
    enumerate them in the first place (N+1 scans instead of 1)."""
    return (ROOMS_DIRECTORY / f"{room_name}.json").exists()


class Card:
    def __init__(self, card_id, name, images, card_type, effects=None):
        self.card_id = card_id
        self.name = name
        self.images = list(images) if images else []
        self.card_type = card_type
        # Stored/round-tripped, never interpreted yet -- no effect engine
        # exists in this slice (see module docstring).
        self.effects = list(effects) if effects else []


def default_card_for(card_id):
    """The automatic bridge: synthesizes a Card straight from an existing
    OBJECT_TYPES/ITEM_DEFINITIONS entry, keyed by the exact same id, so the
    current tile/mob/item roster is immediately usable as cards without a
    single hand-authored assets/cards/*.json file. Returns None if card_id
    matches neither registry (not yet a resolvable card)."""
    base_tile = BASE_TILE_CARDS.get(card_id)
    if base_tile is not None:
        return Card(card_id, base_tile["name"], base_tile["images"], "tile")

    room_name = room_name_from_card_id(card_id)
    if room_name is not None and _room_file_exists(room_name):
        # No images/effects -- a room-card's properties (dimensions, E/S
        # count, entities by type) are computed on demand from the room's
        # current saved content (see room_card_properties below) rather than
        # baked into the Card, so they never go stale after an edit in
        # Creator.
        return Card(card_id, room_name, [], "room")

    config = OBJECT_TYPES.get(card_id)
    if config is not None:
        card_type = "mob" if (config.get("animal") or config.get("enemy")) else "tile"
        images = [config["asset"]] + list(config.get("variants", {}).values())
        # A custom type registered via the sprite editor carries its own
        # chosen display name (see object_manager.register_custom_type) --
        # preferred over the auto-titlecased id every hand-authored
        # OBJECT_TYPES entry still falls back to (none of those set "name").
        name = config.get("name") or card_id.replace("_", " ").title()
        return Card(card_id, name, images, card_type)

    definition = ITEM_DEFINITIONS.get(card_id)
    if definition is not None:
        return Card(card_id, definition["name"], [definition["icon_path"]], "item")

    return None


def resolve_card_sprite(card_id):
    """The raw, unscaled representative icon Surface for a card, or None if
    nothing can be resolved. Pure asset resolution -- no compositing, no
    scaling, no dependency on Profile/Creator (see core.editor.ui.
    CardRenderer for the actual card-image compositing that uses this).

    Reuses exactly the same icon-loading paths already used elsewhere in
    the project instead of inventing new crop logic:
    - An OBJECT_TYPES-bridged card (tile/mob) -> load_object_frames(card_id)
      [0] (frame 0 -- the same "icon" ObjectPalette and WorldRenderer's
      placed-object rendering already use).
    - An ITEM_DEFINITIONS-bridged card (item) -> make_item(card_id).
      get_icon() (the same icon Inventory/ItemPickup rendering already use).
    - A BASE_TILE_CARDS card (tile_floor/tile_wall) -> the matching frame
      cropped straight out of the shared tileset (DEFAULT_FLOOR_SPRITE=14 /
      DEFAULT_WALL_SPRITE=3 -- the exact same indices the autotiler itself
      falls back to for a plain interior floor/wall cell).
    - A room card (see room_card_id/room_name_from_card_id) -> a small
      top-down schematic of the room's own saved layout (see
      render_room_thumbnail), not a fixed icon -- "the room in miniature",
      always current since it's re-rendered from the saved file rather than
      cached onto the Card.
    - A hand-authored custom card (assets/cards/*.json, none exist yet) ->
      best-effort: load its first image path directly if the file exists.
      Dead in practice today (no card-creation UI exists), kept for when
      one does.
    """
    if card_id in BASE_TILE_CARDS:
        tile_index = DEFAULT_FLOOR_SPRITE if card_id == "tile_floor" else DEFAULT_WALL_SPRITE
        return get_tile_surface(load_tileset(), tile_index)

    if card_id in OBJECT_TYPES:
        frames = load_object_frames(card_id)
        return frames[0] if frames else None

    if card_id in ITEM_DEFINITIONS:
        return make_item(card_id).get_icon()

    room_name = room_name_from_card_id(card_id)
    if room_name is not None:
        return render_room_thumbnail(room_name)

    card = CardManager().load(card_id)
    if card is not None and card.images:
        path = PROJECT_ROOT / "assets" / card.images[0]
        if path.exists():
            return pygame.image.load(path).convert_alpha()

    return None


class CardManager:
    """Stateless save(card)/load(card_id), same spirit as ProfileManager --
    owns no card state itself."""

    def get_card_path(self, card_id):
        return CARDS_DIRECTORY / f"{card_id}.json"

    def load(self, card_id):
        """A hand-authored/customized assets/cards/<id>.json takes priority
        over the automatic bridge -- this is what lets a future card-editing
        UI "override" a bridged default (e.g. rename "vase" or give it
        effects) just by calling save() once. Falls back to
        default_card_for(card_id) if no custom file exists, tolerating a
        missing/corrupt file exactly like ProfileManager.load does. Returns
        None if card_id resolves to nothing at all."""
        path = self.get_card_path(card_id)
        if path.exists() and path.stat().st_size > 0:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError, json.JSONDecodeError):
                payload = None
            if payload is not None:
                return Card(
                    payload.get("id", card_id),
                    payload.get("name", card_id),
                    payload.get("images"),
                    payload.get("card_type", "tile"),
                    effects=payload.get("effects"),
                )

        return default_card_for(card_id)

    def save(self, card):
        path = self.get_card_path(card.card_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "version": 1,
                    "id": card.card_id,
                    "name": card.name,
                    "images": card.images,
                    "card_type": card.card_type,
                    "effects": card.effects,
                },
                handle, indent=2, ensure_ascii=False,
            )
        return path

    def list_known_card_ids(self):
        """Every card id currently resolvable via load(): custom
        assets/cards/*.json files, plus every OBJECT_TYPES/ITEM_DEFINITIONS
        key (the automatic bridge) -- sorted, same "one entry per named
        thing" spirit as core.data.ressources.list_rooms(), just unioned
        across three sources instead of one directory scan."""
        custom_ids = {path.stem for path in CARDS_DIRECTORY.glob("*.json")}
        room_ids = {room_card_id(name) for name in list_rooms()}
        return sorted(custom_ids | set(OBJECT_TYPES) | set(ITEM_DEFINITIONS) | set(BASE_TILE_CARDS) | room_ids)


def render_room_thumbnail(room_name):
    """A small top-down schematic of a room's saved layout -- FLOOR/WALL
    cells as flat colors, EMPTY left transparent, no object sprites (too
    small to read at card-icon scale). Returned as a raw, unscaled
    1px-per-cell Surface so it flows through exactly the same generic
    sprite box/scale code every other card's icon already goes through
    (CardRenderer._compose), rather than a special-cased render path --
    "the room in miniature", placed where a sprite normally goes. None for
    a degenerate (zero-size) room."""
    from core.world.dungeon import Dungeon  # deferred, see room_card_manifest below

    dungeon = Dungeon()
    dungeon.load_from_json(room_name)
    if dungeon.width <= 0 or dungeon.height <= 0:
        return None

    surface = pygame.Surface((dungeon.width, dungeon.height), pygame.SRCALPHA)
    for y, row in enumerate(dungeon.logical_grid):
        for x, cell in enumerate(row):
            if cell == FLOOR:
                surface.set_at((x, y), (214, 186, 138, 255))
            elif cell == WALL:
                surface.set_at((x, y), (92, 78, 66, 255))
    return surface


def room_card_manifest(room_name):
    """{card_id: count} of every tile/object card actually invested in this
    room's current saved content -- FLOOR/WALL cell counts (tile_floor/
    tile_wall) plus one entry per placed object's own type. The single
    source of truth for both a room card's refund-on-delete (see
    core.editor.creator.Creator._delete_room) and, indirectly, its
    displayed properties (see room_card_properties below, which shares the
    same "load into a scratch Dungeon" approach but reads different fields).
    Computed fresh from the saved file every call rather than cached, since
    Creator can edit the room live in between."""
    from core.world.dungeon import Dungeon  # deferred: cards.py otherwise only imports "leaf" modules

    dungeon = Dungeon()
    dungeon.load_from_json(room_name)

    manifest = {}
    for row in dungeon.logical_grid:
        for cell in row:
            if cell == FLOOR:
                manifest["tile_floor"] = manifest.get("tile_floor", 0) + 1
            elif cell == WALL:
                manifest["tile_wall"] = manifest.get("tile_wall", 0) + 1
    for obj in dungeon.object_manager.objects:
        manifest[obj["type"]] = manifest.get(obj["type"], 0) + 1
    return manifest


def room_card_properties(room_name):
    """Computed display properties for a room card: dimensions, E/S count
    (the same "genuinely usable connector" definition
    core.world.assembly._valid_entry_exits applies), and a tally of placed
    entities by type."""
    from core.world.dungeon import Dungeon  # deferred, see room_card_manifest

    dungeon = Dungeon()
    dungeon.load_from_json(room_name)
    om = dungeon.object_manager

    es_count = sum(
        1 for obj in om.objects
        if om.is_es_type(obj["type"]) and om.get_role(obj) == "connector" and om.is_valid_doorway(obj["x"], obj["y"])
    )
    entities = {}
    for obj in om.objects:
        entities[obj["type"]] = entities.get(obj["type"], 0) + 1

    return {"width": dungeon.width, "height": dungeon.height, "es_count": es_count, "entities": entities}
