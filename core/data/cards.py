"""The Card system (Vision produit v0.05, see CLAUDE.md): every placeable
tile/mob/item -- PNJ included, now that the entity-unification pass folded
it into "mob" (see CARD_TYPES' own comment) -- is meant to become a Card:
a name, one or more images, a type, and a list of effects that the player
collects and can use to populate/customize their dungeon.

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

import hashlib
import json
from pathlib import Path

import pygame

from core.world.object_manager import (
    OBJECT_TYPES, ITEM_DEFINITIONS, load_object_frames, make_item, npc_completeness,
)
from core.data.ressources import load_tileset, get_tile_surface, list_rooms, rooms_directory
from core.editor.autotile import DEFAULT_FLOOR_SPRITE, DEFAULT_WALL_SPRITE, FLOOR, WALL

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CARDS_DIRECTORY = PROJECT_ROOT / "assets" / "cards"
CARDS_DIRECTORY.mkdir(parents=True, exist_ok=True)

# "pnj" no longer exists as a card_type of its own (the entity-unification
# pass) -- every wandering entity (former animal/enemy/npc) is a "mob",
# full stop; whether one is dialogue/interaction-capable (what used to make
# it specifically a "pnj") is the orthogonal "interactable" mechanics flag
# instead (see object_manager.effective_loot_cards' sibling
# _derive_card_type). "room" is the newest. "tile_decor"/"tile_special"
# split the old flat "tile" bucket used for every OBJECT_TYPES-bridged
# non-mob card (torch/vase/pillar vs. spawn/button/gate/wall/E-S/chest/...)
# -- "tile" itself now only names the 2 BASE_TILE_CARDS placeholders
# (tile_floor/tile_wall), see object_manager._derive_card_type for the rule
# that assigns the other two to an OBJECT_TYPES entry that doesn't declare
# card_type explicitly.
CARD_TYPES = ("tile", "tile_decor", "tile_special", "item", "mob", "room", "propriete")

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
    # "capabilities" here is the raw-terrain equivalent of an OBJECT_TYPES
    # card's own placable_on_floor/placable_on_wall (see object_manager.
    # is_placable/_with_derived_placable_capability) -- floor_placable/
    # wall_placable name the SAME two surfaces for the base autotile tile
    # itself rather than a placed object. Always present, never toggled
    # (there's no "non-placable" variant of raw terrain today) -- exists
    # so the capability is real, visible card data (see default_card_for's
    # own BASE_TILE_CARDS branch), ready for a future consumer (a
    # dynamite-recovered floor/wall fragment placeable mid-run, see
    # CLAUDE.md's roadmap) without inventing a second vocabulary for it.
    "tile_floor": {"name": "Sol", "images": ["tiles/basictileset.png"], "capabilities": {"floor_placable": {}}},
    "tile_wall": {"name": "Mur", "images": ["tiles/basictileset.png"], "capabilities": {"wall_placable": {}}},
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


PROPERTY_CARD_PREFIX = "prop__"

# "kind" only means anything for "capability"/"effect"/"state" (a card can
# carry more than one of any of the three, e.g. dynamite's throwable AND
# explosive) -- "stats"/"aggressivity"/"loot" are singleton blocks (see
# object_manager.extract_property_payload).
_PROPERTY_LABELS = {
    "capability": {
        "throwable": "Lancable", "explosive": "Explosif",
        "placable_on_floor": "Placable (sol)", "placable_on_wall": "Placable (mur)",
        "linkable": "Liable (bouton)", "doorway": "Entree/sortie", "lootable": "Contient du butin",
    },
    "effect": {"heal": "Soin"},
    "stats": {None: "Statistiques"},
    "aggressivity": {None: "Agressivite"},
    "state": {
        "idle": "Etat (immobile)", "move": "Etat (deplacement)", "sitting": "Etat (assis)",
        "laying": "Etat (allonge)", "run": "Etat (course)",
    },
    "loot": {None: "Butin"},
    "behavior": {None: "Comportement"},
}


def property_label(category, kind):
    return _PROPERTY_LABELS.get(category, {}).get(kind) or (kind or category).replace("_", " ").title()


# Where every torn property's own frozen snapshot lives -- {property_card_id:
# {"category":..., "kind":..., "payload":...}}. Confirmed with the user:
# provenance (which base card a property was torn FROM) stopped mattering
# entirely -- tearing "placable_on_floor" off a vase or a pillar is the
# exact same property card either way, no reason to track or care which.
# That meant dropping source_id from the id scheme below, which in turn
# meant a torn property card can no longer be resolved "live" by re-reading
# its (now nonexistent) source -- see property_card_id's own docstring.
# This file is what it's resolved from instead: a payload snapshot taken
# once, at the moment of tearing (see register_torn_property), which two
# DIFFERENT-valued extractions of the same (category, kind) -- e.g.
# "Explosif" torn off two items with different blast radii -- correctly
# keep as two separate entries/cards, confirmed with the user (never
# silently overwritten). Same "stateless converter, small JSON store"
# shape as every other custom_*.json registry in this project.
TORN_PROPERTIES_PATH = CARDS_DIRECTORY / "torn_properties.json"


def _load_torn_properties():
    if not TORN_PROPERTIES_PATH.exists():
        return {}
    try:
        with TORN_PROPERTIES_PATH.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _persist_torn_properties(data):
    TORN_PROPERTIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TORN_PROPERTIES_PATH.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def _payload_digest(payload):
    """A short, deterministic, order-independent fingerprint of `payload`
    (a dict for every category except "state", where it's a plain tagged-
    action-name string) -- two extractions with the EXACT same value
    always produce the same digest, so they resolve to the same property
    card id and stack instead of duplicating; two extractions with
    DIFFERENT values always produce different digests, so they never
    collide or silently overwrite each other (confirmed with the user)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:10]


def property_card_id(category, kind, payload):
    """The deterministic id for the property card representing (category,
    kind, payload) -- purely a function of WHAT was torn and its actual
    value, never of WHERE it came from (see TORN_PROPERTIES_PATH's own
    docstring for why source tracking was dropped entirely). Tearing the
    exact same fragment with the exact same value, from any source at
    all, always resolves to this same id, so repeated extractions stack a
    collection count instead of minting visually-identical duplicate
    cards."""
    digest = _payload_digest(payload)
    if kind:
        return f"{PROPERTY_CARD_PREFIX}{category}__{kind}__{digest}"
    return f"{PROPERTY_CARD_PREFIX}{category}__{digest}"


def register_torn_property(category, kind, payload):
    """Computes this fragment's own property_card_id and makes sure its
    snapshot is actually persisted to TORN_PROPERTIES_PATH -- called once,
    at the exact moment a fragment is torn (see MechanicsPanelUI._try_tear),
    while `payload` is still being read live off the card actually being
    torn. Idempotent: if this exact (category, kind, payload) combination
    was already torn before (by anyone, from any source), the existing
    snapshot is left untouched and just its id is returned -- no redundant
    write, no risk of clobbering it with a merely-equal-but-reordered
    payload. Returns the id."""
    card_id = property_card_id(category, kind, payload)
    data = _load_torn_properties()
    if card_id not in data:
        data[card_id] = {"category": category, "kind": kind, "payload": payload}
        _persist_torn_properties(data)
    return card_id


def parse_property_card_id(card_id):
    """(category, kind, payload) resolved from this property card's own
    frozen snapshot (see TORN_PROPERTIES_PATH), or None if `card_id` isn't
    a property-card id at all OR names one that was never actually
    registered (shouldn't normally happen -- a property card id only ever
    exists in the first place because register_torn_property minted it --
    but never worth crashing a caller over)."""
    if not card_id.startswith(PROPERTY_CARD_PREFIX):
        return None
    snapshot = _load_torn_properties().get(card_id)
    if snapshot is None:
        return None
    return snapshot.get("category"), snapshot.get("kind"), snapshot.get("payload")


def _room_file_exists(room_name):
    """A single stat() check, not list_rooms()'s full directory glob --
    default_card_for is called once per card id every time CardPanelUI/
    GeneratorPanelUI's grids resolve a room card (see core.editor.ui), so
    using list_rooms() here would re-glob assets/rooms/ once per visible
    room-card on top of the one glob list_known_card_ids() already does to
    enumerate them in the first place (N+1 scans instead of 1)."""
    return (rooms_directory() / f"{room_name}.json").exists()


class Card:
    def __init__(self, card_id, name, images, card_type, effects=None, capabilities=None, sounds=None,
                 sound_pitch=None, loot_cards=None, stats=None):
        self.card_id = card_id
        self.name = name
        self.images = list(images) if images else []
        self.card_type = card_type
        # A list of {"kind": ..., ...params} dicts (e.g. [{"kind": "heal",
        # "amount": 1}], see ITEM_DEFINITIONS' own "effects") -- a list
        # rather than a dict keyed by kind, since a card could plausibly
        # carry more than one effect of the same kind. Interpreted by
        # Explorator._use_interact_item for an item card; nothing consumes
        # it yet for an OBJECT_TYPES-bridged card (see default_card_for).
        self.effects = list(effects) if effects else []
        # {"throwable": {...}, "explosive": {...}, ...} -- same vocabulary
        # as OBJECT_TYPES/ITEM_DEFINITIONS' own "capabilities" (see
        # object_manager._build_mechanics_fields). Display-only from here
        # (see CardPanelUI's "Capacites : ..." detail line) -- the actual
        # gameplay consumers (Explorator._use_interact_item/
        # ProjectileManager) read the registry directly, not through Card.
        self.capabilities = dict(capabilities) if capabilities else {}
        # {"use"/"place"/"destroy": "filename.wav"}, relative to
        # core.data.sound_manager.SOUND_DIRECTORY -- same generic-vocabulary
        # spirit as capabilities/effects above. Not consumed from here
        # directly (the hot paths that actually play a sound -- item use in
        # Explorator._use_interact_item, object place/destroy in
        # Creator/Explorator -- read OBJECT_TYPES/ITEM_DEFINITIONS' own
        # "sounds" dict straight, same as effects/capabilities do, to avoid
        # a full Card resolution per frame); stored on Card too so the
        # Forge's display/edit UI has one consistent place to read it from.
        self.sounds = dict(sounds) if sounds else {}
        # {"use"/"place"/"destroy": [min, max]} -- optional random-pitch
        # range per sound slot, see object_manager's "sound_pitch"
        # mechanics field / core.data.sound_manager.play_card_sound. A key
        # only means anything here if self.sounds also has that key.
        self.sound_pitch = (
            {key: list(value) for key, value in sound_pitch.items()} if sound_pitch else {}
        )
        # {card_id: count} -- what this card drops (as OTHER cards, as
        # ground pickups) when it dies/is destroyed, see object_manager.
        # effective_loot_cards/core.world.entities._spawn_loot_pickups.
        # Unlike sounds/
        # capabilities/effects above, None here is NOT the same as {}: None
        # means "this card never had loot_cards explicitly saved, so the
        # implicit default (one copy of its own card) applies" -- resolved
        # by effective_loot_cards, never baked into this attribute itself,
        # so self.loot_cards stays an honest reflection of what's actually
        # persisted (an empty dict here really does mean "drops nothing",
        # not "unedited").
        self.loot_cards = dict(loot_cards) if loot_cards is not None else None
        # A mob-enemy's health/move_speed/aggro_range/attack_range/loot
        # block (see object_manager.MECHANICS_KEYS' own "stats" entry) --
        # unlike every other field above, no OBJECT_TYPES/ITEM_DEFINITIONS-
        # bridged Card ever populates this (stats aren't part of a placed/
        # collected card's own identity today, only a mob TYPE's combat
        # tuning) -- it exists purely so a "stats" property card (see
        # PROPERTY_CARD_PREFIX below) has something to display. None means
        # "not a stats property card", never "empty stats".
        self.stats = dict(stats) if stats is not None else None


def default_card_for(card_id):
    """The automatic bridge: synthesizes a Card straight from an existing
    OBJECT_TYPES/ITEM_DEFINITIONS entry, keyed by the exact same id, so the
    current tile/mob/item roster is immediately usable as cards without a
    single hand-authored assets/cards/*.json file. Returns None if card_id
    matches neither registry (not yet a resolvable card)."""
    base_tile = BASE_TILE_CARDS.get(card_id)
    if base_tile is not None:
        return Card(
            card_id, base_tile["name"], base_tile["images"], "tile",
            capabilities=base_tile.get("capabilities"),
        )

    room_name = room_name_from_card_id(card_id)
    if room_name is not None and _room_file_exists(room_name):
        # No images/effects -- a room-card's properties (dimensions, E/S
        # count, entities by type) are computed on demand from the room's
        # current saved content (see room_card_properties below) rather than
        # baked into the Card, so they never go stale after an edit in
        # Creator.
        return Card(card_id, room_name, [], "room")

    parsed_property = parse_property_card_id(card_id)
    if parsed_property is not None:
        # A property card is resolved from its own frozen snapshot now
        # (see TORN_PROPERTIES_PATH's own docstring) -- provenance was
        # dropped entirely (confirmed with the user: which base card a
        # property happened to be torn FROM never mattered), so unlike the
        # OBJECT_TYPES/ITEM_DEFINITIONS branch below, this is no longer a
        # live bridge back to anything -- the payload IS the card, fixed
        # at the moment register_torn_property first minted this id.
        category, kind, payload = parsed_property
        name = property_label(category, kind)
        return Card(
            card_id, name, [], "propriete",
            capabilities={kind: payload} if category == "capability" else None,
            effects=[payload] if category == "effect" else None,
            # "aggressivity" is stats-shaped (aggro_range/attack_range),
            # rendered the same way a full "stats" property already is.
            # "state" isn't stats at all (a single tagged-action-name
            # string, see object_manager.extract_property_payload's own
            # docstring) but reuses the same {key: value} rendering path
            # purely for display -- Card has no dedicated field for a
            # lone string payload, and inventing one for this single case
            # isn't worth it.
            stats=(
                payload if category in ("stats", "aggressivity")
                else {kind: payload} if category == "state"
                else None
            ),
            loot_cards=payload if category == "loot" else None,
        )

    config = OBJECT_TYPES.get(card_id)
    if config is not None:
        # card_type is now stored directly on every OBJECT_TYPES entry
        # (built-in literals set it explicitly; custom/mob entries get it
        # backfilled at write/load time, see object_manager._derive_card_type)
        # rather than re-derived here from the "mob" flag each call.
        images = [config["asset"]] + list(config.get("variants", {}).values())
        # A custom type registered via the sprite editor carries its own
        # chosen display name (see object_manager.register_custom_type) --
        # preferred over the auto-titlecased id every hand-authored
        # OBJECT_TYPES entry still falls back to (none of those set "name").
        name = config.get("name") or card_id.replace("_", " ").title()
        return Card(
            card_id, name, images, config.get("card_type", "tile_decor"),
            effects=config.get("effects"), capabilities=config.get("capabilities"),
            sounds=config.get("sounds"), sound_pitch=config.get("sound_pitch"),
            loot_cards=config.get("loot_cards"),
        )

    definition = ITEM_DEFINITIONS.get(card_id)
    if definition is not None:
        return Card(
            card_id, definition["name"], [definition["icon_path"]],
            definition.get("card_type", "item"),
            effects=definition.get("effects"), capabilities=definition.get("capabilities"),
            sounds=definition.get("sounds"), sound_pitch=definition.get("sound_pitch"),
            loot_cards=definition.get("loot_cards"),
        )

    return None


def card_completeness(card):
    """(is_complete, missing_summary: list[str]) for `card` -- dispatches
    by card_type. Only an entity-pack-backed "mob" (former "pnj") has a
    real completeness notion today: it can be registered from a single
    tagged tile (object_manager.register_npc_type), so idle/move/sitting/
    laying/running direction coverage is routinely still a work in
    progress right after registration -- object_manager.npc_completeness
    itself already returns "complete" unconditionally for a card_id that
    isn't entity-pack-backed, so calling it here for any "mob" (not just
    ones known to have a pack) is always safe. Every other card_type is
    unconditionally complete -- none of them support partial/staged
    content yet (register_custom_type always takes a fully-formed rect in
    one call, a room either exists or doesn't). A future card_type that
    gains its own staged-authoring flow should add its own branch here
    rather than touching Card itself, which stays the plain data holder it
    already is."""
    if card.card_type != "mob":
        return True, []
    result = npc_completeness(card.card_id)
    missing = [
        f"{role} ({len(directions)} direction{'s' if len(directions) > 1 else ''})"
        for role, directions in result["missing"].items()
    ]
    return result["complete"], missing


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
                    sounds=payload.get("sounds"),
                    sound_pitch=payload.get("sound_pitch"),
                    loot_cards=payload.get("loot_cards"),
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
                    "sounds": card.sounds,
                    "sound_pitch": card.sound_pitch,
                    "loot_cards": card.loot_cards,
                },
                handle, indent=2, ensure_ascii=False,
            )
        return path

    def list_known_card_ids(self, owned_ids=()):
        """Every card id currently resolvable via load(): custom
        assets/cards/*.json files, every OBJECT_TYPES/ITEM_DEFINITIONS key
        (the automatic bridge), plus whichever of `owned_ids` are property-
        card ids (see PROPERTY_CARD_PREFIX) -- sorted, same "one entry per
        named thing" spirit as core.data.ressources.list_rooms(), just
        unioned across sources instead of one directory scan.

        Unlike every other source here, a property card has no registry/
        directory of its own to enumerate from -- it only "exists" once a
        player has actually torn it out at least once, which is exactly
        what owning a copy in card_collection already records. The caller
        (CardPanelUI.refresh, the only one with a Profile in hand) passes
        `profile.card_collection` for this; every other caller (none
        today, but see resolve_card_sprite/room_card_manifest, which never
        need the full known-id list at all) can omit it -- a card that was
        torn but never owned yet simply doesn't show up, same as any other
        card_type."""
        custom_ids = {path.stem for path in CARDS_DIRECTORY.glob("*.json")}
        room_ids = {room_card_id(name) for name in list_rooms()}
        property_ids = {card_id for card_id in owned_ids if parse_property_card_id(card_id) is not None}
        return sorted(
            custom_ids | set(OBJECT_TYPES) | set(ITEM_DEFINITIONS) | set(BASE_TILE_CARDS) | room_ids | property_ids
        )


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


def room_card_properties(room_name):
    """Computed display properties for a room card -- dimensions, E/S count
    (the same "genuinely usable connector" definition
    core.world.assembly._valid_entry_exits applies), a tally of placed
    entities by type, and "manifest": {card_id: count} of every tile/object
    card actually invested in this room's current saved content (FLOOR/WALL
    cell counts as tile_floor/tile_wall, plus one entry per placed object's
    own type) -- the single source of truth for both a room card's
    refund-on-delete (see core.editor.creator.Creator._delete_room, via
    room_card_manifest below -- rooms ARE literally packs of the cards used
    to build them) and its "Contenu du pack" display (see CardPanelUI).
    Computed fresh from the saved file every call rather than cached, since
    Creator can edit the room live in between -- one Dungeon load covers
    both the manifest and the rest of these properties (previously two
    separate loads, one per function)."""
    from core.world.dungeon import Dungeon  # deferred: cards.py otherwise only imports "leaf" modules

    dungeon = Dungeon()
    dungeon.load_from_json(room_name)
    om = dungeon.object_manager

    manifest = {}
    for row in dungeon.logical_grid:
        for cell in row:
            if cell == FLOOR:
                manifest["tile_floor"] = manifest.get("tile_floor", 0) + 1
            elif cell == WALL:
                manifest["tile_wall"] = manifest.get("tile_wall", 0) + 1

    es_count = sum(
        1 for obj in om.objects
        if om.is_es_type(obj["type"]) and om.get_role(obj) == "connector" and om.is_valid_doorway(obj["x"], obj["y"])
    )
    entities = {}
    for obj in om.objects:
        manifest[obj["type"]] = manifest.get(obj["type"], 0) + 1
        entities[obj["type"]] = entities.get(obj["type"], 0) + 1

    return {
        "width": dungeon.width, "height": dungeon.height, "es_count": es_count,
        "entities": entities, "manifest": manifest,
    }


def room_card_manifest(room_name):
    """{card_id: count} of every tile/object card actually invested in
    room_name's current saved content -- see room_card_properties, which
    this now delegates to (one Dungeon load instead of two)."""
    return room_card_properties(room_name)["manifest"]
