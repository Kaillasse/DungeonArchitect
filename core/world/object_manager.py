import json
from pathlib import Path

import pygame

from core.editor.autotile import EMPTY, FLOOR, WALL
from core.data.ressources import DEFAULT_ANIM_SPEED, load_tileset_region
from core.data.sound_manager import play_card_sound

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Renamed from the old "OBJECT_TYPES" -- this is now only the Python-sourced
# seed data. The real, live registry (still called OBJECT_TYPES, see below
# past the custom-type merge machinery) layers custom types AND per-builtin
# mechanics overrides (see update_type_mechanics/_write_builtin_mechanics_override)
# on top of this dict without ever mutating it.
_BUILTIN_OBJECT_TYPES = {
    "spawn": {
        "asset": "characters/Player/rotate.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 8,
        "card_type": "tile_special",
    },
    "button": {
        "asset": "tiles/Button.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 3,
        "linkable": True,
        "walkable": True,
        "card_type": "tile_special",
        # "interact" is the trigger sound (see ObjectManager.
        # check_button_trigger) -- was a hardcoded SOUND_FILES event before
        # the card sound system, now the card's own default, editable from
        # the Forge like any other type's "sounds".
        "sounds": {"interact": "buttonpressed.wav"},
    },
    "gate": {
        "asset": "tiles/gateopenclose.png",
        # Custom placement, not a plain "floor"/"wall" lookup -- see
        # ObjectManager._resolve_placement/is_valid_wall_break: a gate/wall
        # must sit on a WALL cell that reads as a clean break in a straight,
        # 1-cell-thick wall segment (WALL flanking the two perpendicular
        # sides, FLOOR on at least one of the two opposite sides). Doesn't
        # require a void neighbor -- an interior door works too. The
        # procedural assembler (core.world.assembly) separately re-checks
        # the STRICTER is_valid_doorway pattern (FLOOR opposite EMPTY)
        # before treating a gate/wall as a connectable exit, so only a
        # void-facing one is ever picked as a room-to-room connection.
        "placement": "doorway",
        "size": (1, 1),
        "frames": 8,
        "linkable": True,
        "blocks_until_open": True,
        "card_type": "tile_special",
    },
    "wall": {
        "asset": "tiles/wallopenclose.png",
        "placement": "doorway",
        "size": (2, 1),
        "frames": 7,
        "linkable": True,
        "blocks_until_open": True,
        "card_type": "tile_special",
    },
    "torch": {
        "asset": "tiles/Torch Yellow.png",
        # "wall" here is just the fallback/default variant's placement (a
        # torch mounted flat on a plain wall cell, e.g. a back wall). The
        # L/R variants use custom placement logic instead (see
        # ObjectManager._resolve_placement/_torch_variant): they go on a
        # FLOOR cell that has a WALL immediately beside it (right -> R,
        # left -> L), since they're meant to sit at a side wall the player
        # walks past, not block a whole cell -- that's also why only L/R
        # are walkable/drawn in front of the player
        # (ObjectManager.is_foreground_object), not the plain variant.
        "placement": "wall",
        "size": (1, 1),
        "frames": 8,
        "variants": {
            "L": "tiles/Torch Yellow L.png",
            "R": "tiles/Torch Yellow R.png",
        },
        # Which of this type's own "variants" get foreground treatment (see
        # is_foreground_object) -- data on the type itself rather than a
        # literal `obj["type"] == "torch"` string check, so the rule stays
        # correct even if this card is ever renamed or recreated under a
        # different id (2026-08-20).
        "foreground_variants": ("L", "R"),
        "card_type": "tile_decor",
    },
    "vase": {
        "asset": "tiles/Vase.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 16,
        "blocks_movement": True,
        "card_type": "tile_decor",
    },
    "chicken": {
        "asset": "characters/Animals/Chicken.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 2,
        "frame_size": 32,
        "mob": True,
        "card_type": "mob",
        # Migrated from Animal's old hardcoded HEALTH=2 class constant (the
        # entity-unification pass, see core/world/entities.py's Mob) -- no
        # aggro/attack_range, so it never fights back, but it's still
        # damageable/killable exactly like before, now via data instead of
        # a class default. No explicit "loot_cards" needed: the implicit
        # "1 copy of its own card" default (object_manager.effective_loot_cards)
        # already reproduces its old behavior.
        "stats": {"health": 2},
    },
    "cow": {
        "asset": "characters/Animals/Cow.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 2,
        "frame_size": 32,
        "mob": True,
        "card_type": "mob",
        # Migrated from Animal's old hardcoded HEALTH=2 class constant (the
        # entity-unification pass, see core/world/entities.py's Mob) -- no
        # aggro/attack_range, so it never fights back, but it's still
        # damageable/killable exactly like before, now via data instead of
        # a class default. No explicit "loot_cards" needed: the implicit
        # "1 copy of its own card" default (object_manager.effective_loot_cards)
        # already reproduces its old behavior.
        "stats": {"health": 2},
    },
    "pig": {
        "asset": "characters/Animals/Pig.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 2,
        "frame_size": 32,
        "mob": True,
        "card_type": "mob",
        # Migrated from Animal's old hardcoded HEALTH=2 class constant (the
        # entity-unification pass, see core/world/entities.py's Mob) -- no
        # aggro/attack_range, so it never fights back, but it's still
        # damageable/killable exactly like before, now via data instead of
        # a class default. No explicit "loot_cards" needed: the implicit
        # "1 copy of its own card" default (object_manager.effective_loot_cards)
        # already reproduces its old behavior.
        "stats": {"health": 2},
    },
    "sheep": {
        "asset": "characters/Animals/Sheep.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 2,
        "frame_size": 32,
        "mob": True,
        "card_type": "mob",
        # Migrated from Animal's old hardcoded HEALTH=2 class constant (the
        # entity-unification pass, see core/world/entities.py's Mob) -- no
        # aggro/attack_range, so it never fights back, but it's still
        # damageable/killable exactly like before, now via data instead of
        # a class default. No explicit "loot_cards" needed: the implicit
        # "1 copy of its own card" default (object_manager.effective_loot_cards)
        # already reproduces its old behavior.
        "stats": {"health": 2},
    },
    "skeleton1": {
        # "asset" here is just skeleton1's idle sheet -- the static editor
        # palette/placed-object icon only ever needs the idle row, same as
        # animals (load_object_frames). Live combat behavior reads the full
        # idle/movement/attack/damaged/death set via load_enemy_frames
        # instead, using ENEMY_ANIMATION_FILES below.
        "asset": "characters/Ennemies/skeleton1/idle.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 6,
        "frame_size": 32,
        "mob": True,
        "card_type": "mob",
        # Merged in from the old standalone ENEMY_STATS dict -- health/
        # move_speed/aggro_range/attack_range are tuning defaults, not values
        # given by any design doc. active_attack_frames (0-based) is the
        # window during which a swing actually deals damage: frames 7-8 of 9
        # (1-based), as specified. "loot" (currency type -> count) is read
        # once, on death, by Explorator._spawn_loot -- an enemy with no
        # "loot" key (or an empty one) simply drops nothing. Real-item drops
        # used to be a sibling "item_loot" key here -- retired in favor of
        # "loot_cards" below (an item entry there spawns both a card pickup
        # AND a physical ItemPickup, see _spawn_loot_pickups).
        "stats": {
            "health": 3, "move_speed": 45, "aggro_range": 6.0, "attack_range": 1.2,
            # A list, not a tuple -- MechanicsPanelUI's stats editing
            # round-trips this through update_type_mechanics/JSON (which
            # has no tuple type, always deserializes an array as a list),
            # so keeping the Python source a list too means the builtin's
            # own value and a persisted-then-reloaded override compare
            # equal (see _write_builtin_mechanics_override's no-op check)
            # instead of permanently miscomparing tuple != list.
            "active_attack_frames": [6, 7],
            "loot": {"gold": 2, "blue": 1},
        },
        # Explicit rather than left to effective_loot_cards' own implicit
        # "1 copy of its own card" default, to preserve skeleton1's old
        # dynamite drop (previously stats["item_loot"], see above) under
        # the new unified mechanism.
        "loot_cards": {"skeleton1": 1, "dynamite": 1},
        # Per-state sounds (see ENEMY_ANIMATIONS -- idle/movement/attack/
        # damaged/death) -- attack/damaged were already wired via SOUND_FILES
        # before the card sound system (see entities.py's Enemy.attack/
        # take_damage), now the card's own defaults, editable from the
        # Forge. "death" is wired too (Explorator._resolve_player_attacks),
        # but has no default asset yet. idle/movement have no trigger at all
        # (looping ambience, not a one-shot event) -- still shown as
        # assignable slots in the Forge (see module docstring), just inert
        # until a future pass wires a looping-sound mechanism.
        "sounds": {"attack": "skel1attack.wav", "damaged": "skeldamaged.wav"},
    },
    "skeleton2": {
        "asset": "characters/Ennemies/skeleton2/idle.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 6,
        "frame_size": 32,
        "mob": True,
        "card_type": "mob",
        # skeleton2 has a different attack frame count (15) with no given
        # mapping, so its window is derived from skeleton1's *relative*
        # position (~75%-87% through the swing) rather than guessed outright.
        "stats": {
            "health": 3, "move_speed": 45, "aggro_range": 6.0, "attack_range": 1.2,
            "active_attack_frames": [11, 12],  # see skeleton1's own comment -- list, not tuple
            "loot": {"gold": 2, "blue": 1},
        },
        "sounds": {"attack": "skel2attack.wav", "damaged": "skeldamaged.wav"},
    },
    "stairs": {
        # Sourced from basictileset.png frame 26, not a dedicated
        # per-object sheet like every other entry here -- cropped once into
        # its own small file (Phase 6a) to keep load_object_frames'
        # one-sheet-per-type convention rather than teaching it to read a
        # sub-region of a shared tileset. Custom placement (see
        # ObjectManager._resolve_placement/_stairs_orientation): valid on an
        # ordinary FLOOR cell, or on an EMPTY cell that has a FLOOR neighbor
        # (a room's void-facing edge) -- "variant"="flip" mirrors the sprite
        # horizontally when that floor neighbor is specifically to the west,
        # so a single asset covers both orientations without a second file.
        "asset": "tiles/stairs.png",
        "placement": "stairs",
        "size": (1, 1),
        "frames": 1,
        "card_type": "tile_special",
    },
    "cave_entrance": {
        # basictileset.png frame 27. Same wall-break placement shape as
        # gate/wall (ObjectManager.is_valid_wall_break) -- see
        # _resolve_placement -- but always open: no "linkable"/
        # "blocks_until_open", just "walkable" like a button, since this is
        # meant as a level-exit marker, not a lockable door.
        "asset": "tiles/cave_entrance.png",
        "placement": "doorway",
        "size": (1, 1),
        "frames": 1,
        "walkable": True,
        "card_type": "tile_special",
    },
    "big_entrance": {
        # basictileset.png frames 17 (left half) + 23 (right half), composed
        # side-by-side once into one 32x16 static asset (Phase 6a). "frames":
        # 1 with a non-square asset is why load_object_frames gained its
        # whole-image branch. Promoted from purely-decorative wall dressing
        # to a real functional E/S (role system, see get_role/set_role
        # below): same wall-break placement shape as gate/wall/cave_entrance
        # (ObjectManager.is_valid_wall_break, checked off its origin cell only
        # -- already proven to work for a 2-wide footprint by "wall"), and
        # always open like cave_entrance (no "linkable"/"blocks_until_open"
        # -- there's no button-linking use case for a 2-wide entrance).
        "asset": "tiles/big_entrance.png",
        "placement": "doorway",
        "size": (2, 1),
        "frames": 1,
        "walkable": True,
        "card_type": "tile_special",
    },
    "pillar": {
        # basictileset.png frame 18 (base). A single ordinary object, placed
        # on FLOOR exactly like "vase" -- move/erase/click-drag all reuse the
        # generic single-cell machinery unchanged, so a pillar is always
        # destroyed/moved as one block, never split. Its "top" half (frame
        # 12, via the "variants" override below) is *not* a second object at
        # all: WorldRenderer._draw_pillar_tops draws it purely decoratively,
        # one cell north of wherever this object currently is, every frame
        # -- no placement rule, no independent existence, so it can never be
        # individually selected, moved, or orphaned. It's skipped only where
        # an entry-exit object (gate/wall/cave_entrance/stairs) sits, so it
        # never visually covers a doorway; it renders in front of anything
        # else (including the player), same z-order slot an L/R torch uses.
        "asset": "tiles/pillar.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 1,
        "blocks_movement": True,
        "variants": {
            "top": "tiles/pillar_top.png",
        },
        "card_type": "tile_decor",
    },
    "lilchest": {
        # 4 columns x 2 rows: row 0 idle/closed, row 1 the opening animation
        # -- "frames" is the TOTAL flat count load_object_frames slices into
        # (4 * 2 = 8), "rows" tells it to read both rows instead of just row
        # 0 (see load_object_frames). A freshly-placed chest just sits at
        # frame 0 (idle) forever until opened -- see
        # ObjectManager.add_object seeding "loot"/"item_loot" from
        # default_loot/default_item_loot below, and
        # Explorator._interact_with_chest, which sets "open": True and
        # "frame": 4 (the start of row 1) so ObjectManager.update's existing
        # activated/open animation-advance takes it from there and holds on
        # frame 7 (row 1's last frame) once open, exactly like any other
        # blocks_until_open object.
        "asset": "tiles/lilchest.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 8,
        "rows": 2,
        "frame_size": 16,
        "blocks_movement": True,
        "chest": True,
        # Reuses the indicator-dot rendering/hit-testing "linkable" already
        # drives (Creator draws/hit-tests it identically), but a chest's dot
        # opens ChestPanelUI instead of starting a link-drag -- see
        # Creator's indicator-click handler, which checks is_chest() first.
        "linkable": True,
        "default_loot": {"gold": 5, "blue": 5},
        "default_item_loot": {"dynamite": 2},
        "card_type": "tile_special",
    },
}
OBJECT_LIST = [
    "spawn",
    "button",
    "gate",
    "wall",
    "torch",
    "vase",
    "chicken",
    "cow",
    "pig",
    "sheep",
    "skeleton1",
    "skeleton2",
    "lilchest",
    "stairs",
    "cave_entrance",
    "big_entrance",
    "pillar",
]

# ---------------------------------------------------------------------
# Registre additif de types custom -- le fichier que l'editeur de sprite
# (core.editor.ui.SpriteEditorPanelUI) ecrit, fusionne dans OBJECT_TYPES/
# OBJECT_LIST au chargement du module puis a chaque nouvel enregistrement
# via register_custom_type (voir plus bas) -- meme esprit additif que
# CardManager (fichier custom qui complete le defaut), sans risque de
# collision puisque le tool ne genere jamais un id deja pris (voir
# register_custom_type).
# ---------------------------------------------------------------------

CUSTOM_OBJECT_TYPES_PATH = PROJECT_ROOT / "assets" / "tiles" / "custom_object_types.json"


def _load_custom_object_types():
    """Absent/vide/corrompu -> dict vide, meme tolerance que les autres
    loaders JSON optionnels du projet (ProfileManager, CardManager)."""
    if not CUSTOM_OBJECT_TYPES_PATH.exists():
        return {}
    try:
        with CUSTOM_OBJECT_TYPES_PATH.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


_custom_types = _load_custom_object_types()


def _migrate_legacy_npc_flag(custom):
    """One-time migration (entity-unification pass): a custom PNJ type
    registered before this pass persisted "npc": True on disk -- the new
    unified registry only ever checks "mob" (see mob_types() below), so an
    un-migrated entry would silently stop spawning as a live entity at all.
    Also clears a stale stored "card_type": "pnj" (some entries had this
    explicitly persisted, e.g. by an in-progress sprite-editor session
    predating this pass) -- _merged_object_types' own card_type backfill
    only ever fills in a MISSING key (setdefault), so an already-stored
    "pnj" would otherwise never re-derive to "mob" on its own. Mutates
    `custom` in place and returns whether anything changed. Runs directly
    against the raw JSON dict (not through _persist_custom_object_types/
    _write_custom_type, both defined further down this file, to avoid a
    forward-reference at the module-load call site below) -- idempotent, a
    no-op on every later import once every entry has been rewritten once."""
    changed = False
    for entry in custom.values():
        if entry.get("npc") and not entry.get("mob"):
            entry["mob"] = True
            entry.setdefault("interactable", True)
            entry.pop("npc", None)
            changed = True
        if entry.get("card_type") == "pnj":
            entry.pop("card_type", None)
            changed = True
    return changed


if _migrate_legacy_npc_flag(_custom_types):
    CUSTOM_OBJECT_TYPES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CUSTOM_OBJECT_TYPES_PATH.open("w", encoding="utf-8") as _handle:
        json.dump(_custom_types, _handle, indent=2, ensure_ascii=False)

# Object-type mechanics keys (opt-in gameplay behavior) vs identity/visual
# keys (asset/placement/size/frames/name + whatever the archetype preset
# always implies, e.g. "porte"'s walkable/is_es) -- see update_type_visual/
# update_type_mechanics below. A builtin's mechanics can be overridden (a
# custom_object_types.json entry marked OVERRIDE_MARKER, holding ONLY these
# keys) without ever touching its Python-sourced visual identity.
MECHANICS_KEYS = (
    "blocks_movement", "cell_modes", "interactable", "capabilities", "stats", "effects", "sounds", "sound_pitch",
    "loot_cards", "direction_mode",
)
DOORWAY_MECHANICS_KEYS = ("linkable", "blocks_until_open")
OVERRIDE_MARKER = "__override_of_builtin__"


def _is_builtin_type(type_id):
    """The real discriminator behind "is `type_id` a builtin, non-editable-
    identity type" -- id membership in `_BUILTIN_OBJECT_TYPES`, not the
    `isinstance(asset, dict)` shape check update_type_visual/
    update_type_mechanics/delete_custom_type used to test directly (asset
    being a dict only ever coincided with "custom" because every custom
    type used to be created exclusively via the sprite editor's tileset-
    region crop flow -- fuse_card below is the first path that registers a
    custom type by cloning a builtin's own asset field verbatim, a plain
    string, which the old shape check would have misread as "builtin" and
    crashed on)."""
    return type_id in _BUILTIN_OBJECT_TYPES


def _derive_card_type(config):
    """Best-effort card_type for a custom_object_types.json entry saved
    before this field existed -- same rule core.data.cards.default_card_for
    used to apply ad hoc per-Card, now the single place that does it, once,
    for the registry entry itself.

    "pnj" is no longer a card_type of its own -- every wandering entity
    (former animal/enemy/npc) is a "mob", full stop; whether one is
    dialogue/interaction-capable (what used to make it specifically a
    "pnj") is the orthogonal "interactable" flag instead, not a different
    card_type."""
    if config.get("mob"):
        return "mob"
    if config.get("is_es") or config.get("chest"):
        return "tile_special"
    return "tile_decor"


def derive_card_type_from_capabilities(entry):
    """The NEW, capability-driven card_type rule -- confirmed with the
    user, replacing _derive_card_type's own explicit-flag approach
    (mob/is_es/chest) as the long-term source of truth for what KIND of
    card something is. Properties determine the type, not the other way
    around:

      1. real stats (a "stats" dict with at least something in it, e.g.
         health) -> "mob" -- a creature stays a creature even though it's
         ALSO technically placable in Creator like any other object;
         health wins outright.
      2. placable_on_floor/placable_on_wall present, PLUS at least one
         OTHER capability -> "tile_special".
      3. placable_on_floor/placable_on_wall present, alone -> "tile_decor".
      4. neither -> "item".

    Deliberately NOT yet the single source of truth anywhere (see the
    staged rollout plan confirmed with the user) -- introduced to run
    ALONGSIDE the existing stored "card_type" field first, so every
    disagreement between the two can be found and resolved (either by
    fixing this rule or by fixing the entry's own data, e.g. giving an
    entity-pack-backed mob with no combat stats at least a health value
    so it still reads as a creature) before anything actually switches
    over to reading this instead of the stored field. Only meaningful for
    OBJECT_TYPES/ITEM_DEFINITIONS entries (tile/object/mob/item) -- room
    and propriete cards are not capability-bearing registry entries at
    all and stay explicitly typed (core.data.cards), confirmed out of
    scope for this rule."""
    if entry.get("stats"):
        return "mob"
    capabilities = entry.get("capabilities") or {}
    placable_keys = {"placable_on_floor", "placable_on_wall"}
    if not (set(capabilities) & placable_keys):
        return "item"
    return "tile_special" if (set(capabilities) - placable_keys) else "tile_decor"


# What actually makes a type placeable in Creator (see
# Creator._try_place_object's own gate on this) -- confirmed with the
# user: this used to be a purely implicit consequence of just existing in
# OBJECT_TYPES with a "placement" field, invisible anywhere in the card
# system itself (a tile-object card showed no tearable properties at all
# in the Forge even though it plainly "uses" a placement capability to be
# placeable to begin with). "floor"/"stairs" placement -> placable_on_floor,
# "wall"/"doorway" -> placable_on_wall (a doorway object like gate/
# cave_entrance still occupies a WALL cell, see is_valid_doorway) -- same
# two surfaces card_tear.py's own base-tile equivalent
# (core.data.cards.BASE_TILE_CARDS' floor_placable/wall_placable) names,
# just for a placed OBJECT instead of raw terrain.
_PLACABLE_CAPABILITY_BY_PLACEMENT = {
    "floor": "placable_on_floor",
    "stairs": "placable_on_floor",
    "wall": "placable_on_wall",
    "doorway": "placable_on_wall",
}

# Object types that function as an entry/exit (a doorway between rooms, or
# the boundary of a room's void edge) -- the only types get_role/set_role
# accept a "connector"/"dungeon_entrance"/"dungeon_exit" role for, and what
# core.world.assembly's procedural generator treats as a possible room-to-
# room connector (imported there instead of a second, separately
# maintained tuple). Moved up here (used to live right before
# ES_ROLES/ENEMY_FOLDERS, much further down) so
# _with_derived_special_capabilities below -- called from _merged_object_types
# at IMPORT time, before the rest of this module has executed -- can see it.
ES_TYPES = ("gate", "wall", "cave_entrance", "big_entrance")


def _with_derived_placable_capability(entry):
    """Backfills `entry`'s own "capabilities" dict with a
    placable_on_floor/placable_on_wall entry derived from its "placement"
    field, UNLESS it already explicitly carries one of the two (an
    override actually saved via the Forge, see MechanicsPanelUI.
    _passthrough_capabilities -- once real, never silently replaced).
    Mirrors _derive_card_type's own "backfill once, at the registry
    level" shape -- called from every path that produces a live OBJECT_TYPES
    entry (_merged_object_types, register_custom_type) so this is true
    the instant a type exists, builtin or custom, not just after the next
    restart re-runs _merged_object_types. A type with no recognized
    "placement" (there is none today, but a future one is possible) is
    returned completely unchanged -- never made "placable" by fiat."""
    key = _PLACABLE_CAPABILITY_BY_PLACEMENT.get(entry.get("placement"))
    if key is None:
        return entry
    capabilities = entry.get("capabilities") or {}
    if "placable_on_floor" in capabilities or "placable_on_wall" in capabilities:
        return entry
    entry = dict(entry)
    entry["capabilities"] = {**capabilities, key: {}}
    return entry


def _with_derived_special_capabilities(type_id, entry):
    """Backfills linkable/doorway/lootable into `entry`'s own
    "capabilities" dict, mirrored from the SAME flat flags/membership
    that already drive real behavior elsewhere (is_linkable/is_es_type/
    is_chest below) -- confirmed with the user: what made a type
    "tile_special" instead of plain "tile_decor" used to live entirely
    outside the capabilities vocabulary (linkable, is_es, chest were
    plain flat flags), so derive_card_type_from_capabilities' own
    "placable + another capability = tile_special" rule could never see
    it. This does NOT reimplement or replace any of that behavior --
    is_valid_doorway, check_button_trigger, and core.world.assembly's
    procedural generator all keep reading the original flags/ES_TYPES
    exactly as before. It only ADDS a parallel, visible, tearable
    capability entry that reflects the same fact. "doorway" covers
    is_es_type's own two sources (ES_TYPES membership for a builtin, or
    config["is_es"] for a custom "porte"-archetype type) so it can never
    silently drift out of sync with the real rule.

    Left deliberately incomplete: "spawn" and "stairs" are hardcoded
    tile_special in their own Python source entries for reasons that
    aren't linkable/is_es/chest at all (a spawn marker, a level-transition
    marker) -- neither gets backfilled anything here, so both still
    compute as tile_decor under the new rule. Flagged, not silently
    "fixed" by inventing a capability for them -- see the conversation
    this was introduced in."""
    additions = {}
    if entry.get("linkable"):
        additions["linkable"] = {}
    if type_id in ES_TYPES or entry.get("is_es"):
        additions["doorway"] = {}
    if entry.get("chest"):
        additions["lootable"] = {}
    if not additions:
        return entry
    capabilities = entry.get("capabilities") or {}
    merged = dict(capabilities)
    changed = False
    for key, value in additions.items():
        if key not in merged:
            merged[key] = value
            changed = True
    if not changed:
        return entry
    entry = dict(entry)
    entry["capabilities"] = merged
    return entry


def is_placable(object_type, on="any"):
    """Whether `object_type` currently carries a placable_on_floor/
    placable_on_wall capability (see _with_derived_placable_capability) --
    the real, explicit gate for "can this be placed at all", replacing
    the old implicit "it exists in OBJECT_TYPES, therefore it's
    placeable" assumption nothing else could see or check. `on` narrows
    to one specific surface ("floor"/"wall"); the default "any" accepts
    either. Shared by Creator._try_place_object today -- meant to be
    reused unchanged by a future Exploration-side placement gesture
    (picking up/re-placing a broken tile mid-run, see CLAUDE.md's
    roadmap): same capability, same check, wherever it happens to run."""
    capabilities = OBJECT_TYPES.get(object_type, {}).get("capabilities", {})
    if on == "floor":
        return "placable_on_floor" in capabilities
    if on == "wall":
        return "placable_on_wall" in capabilities
    return "placable_on_floor" in capabilities or "placable_on_wall" in capabilities


def _merge_mechanics_override(base, entry, keys):
    """`base` with every key in `keys` replaced by whichever of them
    `entry` (a full snapshot, never a sparse diff, so a flag can be
    explicitly turned back off) actually carries -- the shared merge step
    behind _merge_builtin (OBJECT_TYPES, MECHANICS_KEYS +
    DOORWAY_MECHANICS_KEYS) and update_item_overrides (ITEM_DEFINITIONS,
    its own smaller key set). Clearing every key first rather than only
    the ones `base` happens to already carry is deliberate -- `.pop(key,
    None)` is a no-op for an absent key, so this stays correct even for a
    non-doorway builtin that never had DOORWAY_MECHANICS_KEYS to begin
    with."""
    merged = dict(base)
    for key in keys:
        merged.pop(key, None)
    for key in keys:
        if key in entry:
            merged[key] = entry[key]
    return merged


def _merge_builtin(type_id, override):
    """A builtin's own Python-sourced entry, with its mechanics keys
    replaced by `override`'s (an OVERRIDE_MARKER-tagged entry holding a
    full snapshot of MECHANICS_KEYS/DOORWAY_MECHANICS_KEYS). None if
    type_id no longer names a real builtin (a stale override left over
    from a since-removed one)."""
    base = _BUILTIN_OBJECT_TYPES.get(type_id)
    if base is None:
        return None
    return _merge_mechanics_override(base, override, MECHANICS_KEYS + DOORWAY_MECHANICS_KEYS)


def _with_all_derived_capabilities(type_id, entry):
    """Both backfills combined -- the one call every producer of a live
    OBJECT_TYPES entry should make (see _merged_object_types/
    _write_custom_type)."""
    entry = _with_derived_placable_capability(entry)
    return _with_derived_special_capabilities(type_id, entry)


def _merged_object_types():
    """The live registry: every builtin, with any persisted mechanics
    override merged on top, plus every genuine custom/NPC type as-is
    (card_type backfilled once if the entry predates that field). Every
    entry also gets its placable_on_floor/placable_on_wall/linkable/
    doorway/lootable capabilities backfilled here (see
    _with_all_derived_capabilities) -- the single place every OBJECT_TYPES
    entry, builtin or custom, overridden or not, ultimately flows
    through."""
    merged = {
        type_id: _with_all_derived_capabilities(type_id, entry)
        for type_id, entry in _BUILTIN_OBJECT_TYPES.items()
    }
    for type_id, entry in _custom_types.items():
        if entry.get(OVERRIDE_MARKER):
            result = _merge_builtin(type_id, entry)
            if result is not None:
                merged[type_id] = _with_all_derived_capabilities(type_id, result)
        else:
            entry = dict(entry)
            entry.setdefault("card_type", _derive_card_type(entry))
            merged[type_id] = _with_all_derived_capabilities(type_id, entry)
    return merged


OBJECT_TYPES = _merged_object_types()
OBJECT_LIST.extend(
    type_id for type_id, entry in _custom_types.items()
    if not entry.get(OVERRIDE_MARKER) and type_id not in OBJECT_LIST
)

# Archetypes proposes par l'editeur de sprite -- volontairement limites aux
# types a une seule region (pas de paire torche L/R, pas de pilier
# base+haut, qui ont chacun besoin de deux selections liees -- extension
# future, non construite ici). "mur" n'a besoin d'aucun flag supplementaire :
# la case WALL elle-meme bloque deja, comme la variante plate de "torch".
# "porte" (placement="doorway", is_es=True) obtient la vraie validation
# is_valid_doorway/eligibilite assembleur procedural via is_es_type
# (voir plus bas) -- initialement ecarte le jour ou "Tuile speciale" a ete
# construit, parce que ES_TYPES etait un tuple code en dur ; is_es_type
# lit desormais aussi ce flag, donc un type custom en beneficie pour de bon.
ARCHETYPES = {
    "sol": {"label": "Sol", "placement": "floor", "flags": {}},
    "mur": {"label": "Mur", "placement": "wall", "flags": {}},
    "porte": {"label": "Porte", "placement": "doorway", "flags": {"walkable": True, "is_es": True}},
}


#  Les 3 etats possibles d'une case dans un "cell_modes" (voir
# _build_mechanics_fields) -- "block" est solide (non walkable, dessine
# dans la passe normale/arriere) ; "behind" et "front" sont tous deux
# walkable, seul leur ordre de dessin differe (arriere = normal, comme une
# fleur/un tapis ; devant = comme une torche, la case se dessine par-dessus
# le joueur). Voir ObjectManager.is_cell_walkable/cell_draw_mode et
# WorldRenderer._draw_objects pour la consommation.
CELL_MODES = ("block", "behind", "front")


# Every key any ARCHETYPES preset can unconditionally set (today just
# "porte"'s walkable/is_es) -- identity/visual keys, cleared and reapplied
# fresh on every update_type_visual call so switching a custom type's
# archetype can't leave a stale flag from its previous archetype behind.
# Distinct from MECHANICS_KEYS/DOORWAY_MECHANICS_KEYS: those are optional
# per-instance toggles (blocks_movement, lockable...), these are permanent
# consequences of "this IS a porte/sol/mur-shaped thing".
_ARCHETYPE_FLAG_KEYS = tuple(sorted({key for preset in ARCHETYPES.values() for key in preset["flags"]}))


def _build_visual_fields(
    name, tileset, rect, size, archetype, frame_rects=None, directions=None, entity_pack=None, wander_actions=None,
):
    """Construction pure (aucune I/O) des champs d'identite/visuel d'une
    entree OBJECT_TYPES custom -- asset/placement/size/frames/name plus les
    flags que l'archetype impose toujours (voir ARCHETYPES). Partagee par
    register_custom_type (creer) et update_type_visual (editer).

    `frame_rects`, s'il est fourni, remplace le `rect` unique par une liste
    de rects choisis individuellement dans l'editeur de sprite plutot
    qu'une bande continue decoupee automatiquement -- a l'origine
    reserve a l'archetype "porte" (une frame d'animation d'ouverture par
    entree), desormais disponible pour n'importe quel archetype (2026-08-18,
    voir `directions` ci-dessous) : rien dans ce champ lui-meme n'a jamais
    ete specifique a "porte", seule l'UI de l'editeur de sprite limitait qui
    pouvait le fournir. Sans lui, comportement actuel inchange : un seul
    "rect", frames=1.

    `directions` ({direction: frame_index}, direction etant une valeur de
    NPC_DIRECTIONS), s'il est fourni, tague CHAQUE frame de `frame_rects`
    avec la direction qu'elle represente -- ex. une frame "front", une
    "left", une "right" d'un meme banc/torche multiframe. Rien a voir avec
    le pack d'entite action/direction/ordre des PNJ (build_entity_pack_
    lookup) : pas de fichier separe, pas de concept d'action, juste un
    dict directement sur la carte elle-meme -- deliberement plus simple,
    voir load_object_frames/ObjectManager._auto_wall_direction qui le
    consomment. `direction_mode` ("auto"/"manuel", voir
    _build_mechanics_fields) decide qui choisit la direction d'une
    instance posee ; `directions` ici decide seulement quelle FRAME
    represente quelle direction.

    `entity_pack`, s'il est fourni, attache une reference vers un pack
    d'entite (le meme pack/action/direction/ordre que register_npc_type
    consomme deja via load_npc_frames) -- PUREMENT structurel/visuel,
    comme `directions`/`frame_rects` : `rect` reste l'icone statique
    affichee tant que la carte n'est rien d'autre qu'une carte posee.
    Deliberement AUCUN champ "mob" pose ici -- rattacher un pack ne
    decide jamais que cette carte est vivante (2026-08-19, confirme avec
    l'utilisateur : "Comportement" est une propriete a dechirer/coller
    depuis un mob existant, jamais une decision prise a la creation, voir
    extract_property_payload/_apply_property_payload's "behavior"). Cette
    carte porte donc ses propres etats (autant qu'on veut, tagues
    librement sur le pack, voir entities.Mob._stationary_state_options)
    sans jamais etre vivante tant qu'aucun "Comportement" n'a ete colle
    dessus.

    `wander_actions` ({role: action_name}), s'il est fourni, ne fait que
    NOMMER quel tag joue pour un role reconnu (idle/move/sitting/laying/
    run) quand ce tag ne s'appelle pas litteralement comme le role --
    purement une table de correspondance, meme nature que `directions` ci-
    dessus, jamais une decision de gameplay : chaque role retombe deja sur
    son propre nom litteral en son absence (voir entities.Mob.
    _current_action_name, 2026-08-19), donc ce champ reste facultatif,
    utile seulement pour reutiliser un tag qui porte un autre nom."""
    preset = ARCHETYPES.get(archetype)
    if preset is None:
        raise ValueError(f"Archetype inconnu : {archetype}")

    if frame_rects:
        asset = {"tileset": tileset, "rects": [list(r) for r in frame_rects]}
        frames = len(frame_rects)
    else:
        asset = {"tileset": tileset, "rect": list(rect)}
        frames = 1

    entry = {
        "asset": asset,
        "placement": preset["placement"],
        "size": list(size),
        "frames": frames,
        "name": name,
    }
    if directions:
        entry["directions"] = dict(directions)
    if entity_pack:
        entry["entity_pack"] = entity_pack
    if wander_actions:
        entry["wander_actions"] = dict(wander_actions)
    entry.update(preset["flags"])
    return entry


def _build_mechanics_fields(existing, blocks_movement=False, cell_modes=None,
                             interactable=False, lockable=False, capabilities=None, stats=None, effects=None,
                             sounds=None, sound_pitch=None, loot_cards=None,
                             direction_mode=None):
    """Construction pure (aucune I/O) des champs mecaniques/gameplay d'une
    entree OBJECT_TYPES -- partagee par register_custom_type et
    update_type_mechanics (custom ET builtin, voir plus bas). `cell_modes`,
    s'il est fourni, prevaut sur `blocks_movement` (voisinage ET ordre de
    dessin par case pour un objet multi-cases) -- les deux representent la
    meme idee a des granularites differentes, jamais les deux a la fois.

    `lockable` (seulement si `existing["placement"] == "doorway"` --
    ignore silencieusement ailleurs) ajoute "linkable"/"blocks_until_open",
    exactement comme gate/wall : la porte devient liable a un bouton et
    bloque tant qu'elle n'est pas ouverte, au lieu de rester "walkable" en
    permanence (le flag par defaut de l'archetype "porte", voir
    ARCHETYPES -- un flag d'identite, jamais touche ici). Par defaut False.

    `capabilities` ({"throwable": {...}, "explosive": {...}, ...}) est le
    meme vocabulaire que ITEM_DEFINITIONS' propre champ "capabilities" --
    voir update_item_overrides -- rendu disponible ici aussi pour qu'un
    objet du monde (pas seulement un item d'inventaire) puisse un jour
    porter la meme capacite (ex: un vase explosif).

    `stats` (health/move_speed/aggro_range/attack_range/active_attack_frames/
    loot/item_loot -- voir _BUILTIN_OBJECT_TYPES["skeleton1"]) n'a de sens
    que pour un mob enemy aujourd'hui (aucun animal n'en a) -- deliberement
    PAS valide/restreint ici, meme philosophie que `capabilities` : un
    vocabulaire generique que n'importe quel type peut porter, l'appelant
    (MechanicsPanelUI) decide seul ce qu'il affiche/calcule pour quel type
    de carte.

    `effects` (meme forme que ITEM_DEFINITIONS' propre champ "effects" --
    une LISTE de {"kind": ..., ...params}, voir core.data.cards.Card) est
    le pendant "effets" de `capabilities` -- meme raisonnement, rendu
    disponible pour n'importe quel type.

    `sounds` ({"use"/"place"/"destroy": "filename.wav"}, relatif a
    core.data.sound_manager.SOUND_DIRECTORY) est le pendant sonore de
    `capabilities`/`effects` -- meme vocabulaire generique, meme
    "l'appelant (MechanicsPanelUI) decide seul ce qu'il affiche/joue pour
    quel type de carte".

    `sound_pitch` ({"use"/"place"/"destroy": [min, max]}) est optionnel et
    purement additif par rapport a `sounds` -- une cle absente ou manquante
    dans `sounds` veut dire "pitch normal, pas de plage" pour ce son ; une
    entree ici n'a de sens que pour une cle qui a aussi une entree dans
    `sounds` (voir core.data.sound_manager.play_card_sound, qui tire un
    multiplicateur aleatoire dans cette plage a CHAQUE lecture -- jamais
    calcule/fige une seule fois ici).

    `loot_cards` ({card_id: count}) est la table de butin-en-cartes dont
    des CardPickup sont fait tomber au sol (voir core.world.entities.
    _spawn_loot_pickups) quand cette carte meurt/est detruite -- SANS
    cette cle du tout, effective_loot_cards ci-dessous
    retombe sur le defaut implicite "1 exemplaire de sa propre carte", donc
    None ici veut dire "ne pas toucher a l'existant", jamais "table vide" :
    contrairement a capabilities/effects/sounds (verifies par vacuite, un
    dict {} explicitement voulu par le joueur -- "cette carte ne drop
    litteralement rien" -- serait sinon indiscernable de "pas edite du
    tout" et retomberait silencieusement sur le defaut au lieu de le
    remplacer).

    `direction_mode` ("auto"/"manuel") decide QUI choisit la direction
    d'une instance posee pour un type dont `directions` (voir
    _build_visual_fields -- {direction: frame_index} sur la carte
    elle-meme, pas un pack separe) tague au moins une frame : "auto" la
    recalcule a chaque pose/deplacement via ObjectManager._auto_wall_
    direction (generalisation de l'ancienne regle L/R de la torche a
    N'IMPORTE QUELLE direction taguee), "manuel" la laisse entierement au
    joueur (ex: pivoter avec R pendant le glisser-deposer) et ObjectManager
    ne la touche plus jamais une fois posee (voir add_object/move_object).
    Sans valeur, ou sans `directions` du tout, n'a aucun effet -- meme
    philosophie que capabilities/stats/effects/sounds : un vocabulaire
    generique, l'appelant (MechanicsPanelUI) decide seul ce qu'il propose
    pour quel type de carte. Volontairement separe de `directions` :
    celui-ci se decide au decoupage (quelle frame EST quelle direction),
    celui-la a n'importe quel moment apres coup depuis la Forge (qui
    CHOISIT la direction une fois posee)."""
    fields = {}
    if cell_modes is not None:
        fields["cell_modes"] = [list(row) for row in cell_modes]
    elif blocks_movement:
        fields["blocks_movement"] = True
    if interactable:
        fields["interactable"] = True
    if existing.get("placement") == "doorway" and lockable:
        fields["linkable"] = True
        fields["blocks_until_open"] = True
    if capabilities:
        fields["capabilities"] = dict(capabilities)
    if effects:
        fields["effects"] = list(effects)
    if stats:
        fields["stats"] = dict(stats)
    if sounds:
        fields["sounds"] = dict(sounds)
    if sound_pitch:
        fields["sound_pitch"] = {key: list(value) for key, value in sound_pitch.items()}
    if loot_cards is not None:
        fields["loot_cards"] = dict(loot_cards)
    if direction_mode:
        fields["direction_mode"] = direction_mode
    return fields


def _persist_custom_object_types(custom):
    CUSTOM_OBJECT_TYPES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CUSTOM_OBJECT_TYPES_PATH.open("w", encoding="utf-8") as handle:
        json.dump(custom, handle, indent=2, ensure_ascii=False)


def _write_custom_type(type_id, entry):
    """Ecrit `entry` dans custom_object_types.json (fusionne, pas remplace
    -- toute autre carte custom deja enregistree reste intacte) et met a
    jour OBJECT_TYPES/OBJECT_LIST en memoire immediatement, que ce soit une
    creation ou une mise a jour. Backfille card_type une fois si absent
    (meme regle que _merged_object_types, ici pour qu'une entree ecrite
    CETTE session l'ait deja en memoire sans attendre un redemarrage) --
    jamais pour un override de builtin (OVERRIDE_MARKER), dont le
    card_type reste celui, deja correct, du builtin lui-meme. Meme
    raisonnement pour placable_on_floor/placable_on_wall/linkable/doorway/
    lootable (voir _with_all_derived_capabilities) -- un override n'a de
    toute facon pas de champ "placement"/"linkable"/"is_es"/"chest" du
    tout (identite/visuel, jamais touche par une mecanique), donc
    s'applique en pratique seulement aux vraies creations/edits de type
    custom, exactement comme card_type ci-dessus."""
    if not entry.get(OVERRIDE_MARKER):
        entry = dict(entry)
        entry.setdefault("card_type", _derive_card_type(entry))
        entry = _with_all_derived_capabilities(type_id, entry)

    custom = _load_custom_object_types()
    custom[type_id] = entry
    _persist_custom_object_types(custom)

    OBJECT_TYPES[type_id] = entry
    if type_id not in OBJECT_LIST:
        OBJECT_LIST.append(type_id)


def _write_builtin_mechanics_override(type_id, mechanics_fields):
    """Persiste `mechanics_fields` (deja construit par _build_mechanics_fields)
    comme override d'un builtin -- jamais le fragment brut dans OBJECT_TYPES
    en memoire (ca casserait le tout prochain load_object_frames/
    is_cell_walkable sur ce type avant le prochain redemarrage), toujours la
    version fusionnee via _merge_builtin.

    L'override n'est retire (plutot que persiste) que si `mechanics_fields`
    correspond EXACTEMENT aux valeurs mecaniques deja codees en dur sur le
    builtin lui-meme -- jamais juste "est vide". Un builtin comme "gate"
    (blocks_until_open=True en dur) ou "vase" (blocks_movement=True en dur)
    produit un `mechanics_fields` vide quand l'utilisateur DESACTIVE ce
    flag depuis la Forge (aucune cle a ajouter pour representer "off") --
    confondre "vide" avec "aucun changement souhaite" aurait silencieusement
    ignore cette desactivation et restaure les valeurs par defaut a chaque
    sauvegarde, empechant justement la nouvelle capacite que ce retrait de
    garde est cense debloquer (voir le plan -- "un gate/wall togglable non
    verrouillable")."""
    base = _BUILTIN_OBJECT_TYPES[type_id]
    base_mechanics = {key: base[key] for key in MECHANICS_KEYS + DOORWAY_MECHANICS_KEYS if key in base}

    custom = _load_custom_object_types()
    if mechanics_fields == base_mechanics:
        custom.pop(type_id, None)
        merged = dict(base)
    else:
        override = dict(mechanics_fields)
        override[OVERRIDE_MARKER] = True
        custom[type_id] = override
        merged = _merge_builtin(type_id, override)
    _persist_custom_object_types(custom)
    OBJECT_TYPES[type_id] = merged


def reset_builtin_mechanics(type_id):
    """Efface un override de mecaniques et restaure les valeurs Python par
    defaut du builtin -- verbe distinct de delete_custom_type, qui doit
    rester impossible a invoquer sur un builtin (voir sa propre garde)."""
    if type_id not in _BUILTIN_OBJECT_TYPES:
        raise ValueError(f"'{type_id}' n'est pas un type integre au jeu")
    custom = _load_custom_object_types()
    if custom.pop(type_id, None) is None:
        return
    _persist_custom_object_types(custom)
    OBJECT_TYPES[type_id] = dict(_BUILTIN_OBJECT_TYPES[type_id])


def _validate_new_id(id_, registry):
    """Raises ValueError if `id_` isn't a well-formed, still-free key for
    `registry` -- shared by register_custom_type/register_npc_type
    (OBJECT_TYPES) and register_item (ITEM_DEFINITIONS), each registering
    a brand-new entry and needing the same "letters/digits/_ only, not
    already taken" guard before writing anything."""
    if not id_ or not all(c.isalnum() or c == "_" for c in id_):
        raise ValueError("Identifiant invalide (lettres/chiffres/_ uniquement)")
    if id_ in registry:
        raise ValueError(f"'{id_}' existe deja")


def register_custom_type(
    type_id, name, tileset, rect, size, archetype, blocks_movement=False, cell_modes=None,
    interactable=False, lockable=False, frame_rects=None, directions=None, entity_pack=None, wander_actions=None,
):
    """Valide et persiste une NOUVELLE entree OBJECT_TYPES sourcee depuis une
    region de tileset -- le point d'ecriture que SpriteEditorPanelUI appelle
    une fois la selection confirmee, en mode creation (voir update_custom_type
    pour le mode edition). Leve ValueError sur un id/archetype invalide ou
    deja pris, pour que l'appelant affiche un message plutot que de
    corrompre le registre silencieusement. `entity_pack`/`wander_actions`
    (voir _build_visual_fields) ne posent jamais "mob" -- restent purement
    visuels/structurels meme ici."""
    _validate_new_id(type_id, OBJECT_TYPES)
    entry = _build_visual_fields(
        name, tileset, rect, size, archetype, frame_rects, directions, entity_pack, wander_actions,
    )
    entry.update(_build_mechanics_fields(entry, blocks_movement, cell_modes, interactable, lockable))
    _write_custom_type(type_id, entry)
    return entry


def update_type_visual(
    type_id, name, tileset, rect, size, archetype, frame_rects=None, directions=None,
    entity_pack=None, wander_actions=None,
):
    """Edite UNIQUEMENT l'identite/visuel d'une carte custom DEJA
    enregistree (type_id doit deja exister ET etre une carte custom --
    jamais un type integre au jeu comme "vase", identifie par la forme
    dict de son "asset" -- meme un id qui collisionnerait par coincidence
    avec un type integre ne peut jamais l'ecraser). Contrairement a
    l'ancien _build_custom_type_entry (qui reconstruisait tout depuis
    zero), les cles mecaniques deja presentes survivent intactes -- seules
    les cles de _ARCHETYPE_FLAG_KEYS (walkable/is_es), "directions" et
    "entity_pack" sont effacees puis reappliquees : la premiere pour qu'un
    changement d'archetype ne laisse pas un flag de l'ancien archetype
    trainer, la seconde parce qu'un re-decoupage change frame_rects (donc
    les index que "directions" reference), la troisieme pour qu'un
    entity_pack non re-fourni ici ne survive pas silencieusement (un
    re-decoupage qui abandonne le pack pour un frame_rects/rect classique
    doit vraiment l'abandonner) -- sans ce nettoyage, une valeur non
    re-fournie survivrait pointant potentiellement sur de mauvaises
    donnees apres l'edition."""
    existing = OBJECT_TYPES.get(type_id)
    if existing is None:
        raise ValueError(f"'{type_id}' n'existe pas")
    if _is_builtin_type(type_id):
        raise ValueError(f"'{type_id}' est un type integre au jeu, non modifiable")
    entry = dict(existing)
    for key in _ARCHETYPE_FLAG_KEYS:
        entry.pop(key, None)
    entry.pop("directions", None)
    entry.pop("entity_pack", None)
    entry.pop("wander_actions", None)
    entry.update(_build_visual_fields(
        name, tileset, rect, size, archetype, frame_rects, directions, entity_pack, wander_actions,
    ))
    _write_custom_type(type_id, entry)
    return entry


def update_type_mechanics(type_id, blocks_movement=False, cell_modes=None,
                           interactable=False, lockable=False, capabilities=None, stats=None, effects=None,
                           sounds=None, sound_pitch=None, loot_cards=None,
                           direction_mode=None):
    """Edite UNIQUEMENT les mecaniques/gameplay d'un type DEJA enregistre --
    contrairement a update_type_visual, fonctionne sur N'IMPORTE QUEL type
    existant, builtin OU custom (c'est le point d'entree qui rend un
    builtin editable sans jamais toucher a son identite visuelle -- voir
    _write_builtin_mechanics_override). Efface d'abord les cles mecaniques
    existantes (jamais un merge naif : sinon desactiver un flag deja actif
    ne ferait jamais rien) puis reapplique celles calculees pour cet appel.

    `stats`/`effects` n'ont de sens aujourd'hui que pour certains types
    (stats : mob enemy seulement ; effects : n'importe lequel, mais rien
    ne le consomme encore cote OBJECT_TYPES hors interpretation manuelle,
    voir cards.py) -- deliberement PAS valides/restreints ici, meme
    philosophie que `capabilities` : un vocabulaire generique que
    N'IMPORTE QUEL type peut porter, l'UI appelante (MechanicsPanelUI)
    decide seule ce qu'elle affiche/calcule pour quel type de carte."""
    existing = OBJECT_TYPES.get(type_id)
    if existing is None:
        raise ValueError(f"'{type_id}' n'existe pas")
    fields = _build_mechanics_fields(
        existing, blocks_movement, cell_modes, interactable, lockable, capabilities, stats, effects, sounds,
        sound_pitch, loot_cards, direction_mode,
    )
    if _is_builtin_type(type_id):
        _write_builtin_mechanics_override(type_id, fields)
        return OBJECT_TYPES[type_id]
    entry = dict(existing)
    for key in MECHANICS_KEYS:
        entry.pop(key, None)
    if existing.get("placement") == "doorway":
        for key in DOORWAY_MECHANICS_KEYS:
            entry.pop(key, None)
    entry.update(fields)
    _write_custom_type(type_id, entry)
    return entry


def update_custom_type(
    type_id, name, tileset, rect, size, archetype, blocks_movement=False, cell_modes=None,
    interactable=False, lockable=False, frame_rects=None, directions=None, entity_pack=None, wander_actions=None,
):
    """Alias de compatibilite -- combine update_type_visual + update_type_mechanics
    en un seul appel, meme signature/comportement qu'avant leur separation
    (voir ces deux fonctions). SpriteEditorPanelUI continue d'appeler
    celui-ci sans aucun changement : il passe deja les champs visuels ET
    mecaniques dans le meme appel, en repassant inchange tout ce qu'il ne
    laisse pas l'utilisateur editer lui-meme (voir MechanicsPanelUI, qui
    fait le symetrique avec update_type_mechanics seul)."""
    update_type_visual(type_id, name, tileset, rect, size, archetype, frame_rects, directions, entity_pack, wander_actions)
    return update_type_mechanics(type_id, blocks_movement, cell_modes, interactable, lockable)


def delete_custom_type(type_id):
    """Supprime definitivement une carte custom OU un type de PNJ (meme
    stockage, voir _write_custom_type -- register_npc_type/update_npc_type
    passent aussi par lui) : retire du JSON persiste et de OBJECT_TYPES/
    OBJECT_LIST en memoire. Meme garde qu'update_custom_type -- jamais un
    type integre au jeu (identifie par la forme dict de son "asset").
    Leve ValueError sans rien modifier si absent/non-custom, meme
    convention d'erreur que register_custom_type. N'a AUCUNE idee de si ce
    type est encore place quelque part -- c'est a l'appelant (voir
    core.data.ressources.type_references) de verifier et refuser avant
    d'appeler ceci, sans quoi une room qui le referencait encore
    planterait (KeyError) au prochain chargement plutot que de se degrader
    proprement (voir ObjectManager.is_cell_walkable)."""
    existing = OBJECT_TYPES.get(type_id)
    if existing is None:
        raise ValueError(f"'{type_id}' n'existe pas")
    if _is_builtin_type(type_id):
        raise ValueError(f"'{type_id}' est un type integre au jeu, non supprimable")

    custom = _load_custom_object_types()
    custom.pop(type_id, None)
    _persist_custom_object_types(custom)

    del OBJECT_TYPES[type_id]
    if type_id in OBJECT_LIST:
        OBJECT_LIST.remove(type_id)


def find_custom_type_by_source(tileset, rect):
    """L'id de la carte custom dont le rect source correspond exactement a
    (tileset, rect), ou None -- permet a l'editeur de sprite d'avertir/
    proposer une edition plutot que d'enregistrer un doublon visuellement
    redondant. Une entree custom se reconnait a la forme dict de son
    "asset" (voir _build_visual_fields) -- jamais un type integre, qui
    utilise toujours un chemin de fichier (chaine). Matche soit le "rect"
    singulier d'une carte a 1 frame, soit n'importe quel element du
    "rects" pluriel d'une porte multi-frame (voir _build_visual_fields)
    -- une region deja prise comme UNE frame d'une porte doit etre
    signalee tout autant qu'une carte a 1 frame ordinaire."""
    rect = list(rect)
    for candidate_id, config in OBJECT_TYPES.items():
        asset = config.get("asset")
        if not isinstance(asset, dict) or asset.get("tileset") != tileset:
            continue
        if list(asset.get("rect", [])) == rect:
            return candidate_id
        if any(list(r) == rect for r in asset.get("rects", [])):
            return candidate_id
    return None


def custom_types_for_tileset(tileset):
    """(type_id, config) pour chaque carte custom sourcee depuis `tileset`
    -- alimente la liste/les marqueurs "cartes existantes" de
    SpriteEditorPanelUI pour qu'un joueur voie ce qui est deja pris avant
    de recadrer par-dessus, ou clique une entree pour la rouvrir en
    edition (voir update_custom_type)."""
    return [
        (candidate_id, config) for candidate_id, config in OBJECT_TYPES.items()
        if isinstance(config.get("asset"), dict) and config["asset"].get("tileset") == tileset
    ]


# Object types backed by a live, wandering entity (core.world.entities.Mob)
# during exploration rather than just a static placed sprite -- see
# entities.MobManager. Derived from the "mob" flag above instead of a
# separately-maintained list, so OBJECT_TYPES stays the single registry.
#
# A FUNCTION, not a tuple frozen at import time -- unlike the old, now-
# retired ANIMAL_TYPES/ENEMY_TYPES (hand-authored in this file, never
# created at runtime, so freezing once at import never actually mattered),
# a mob type registered via register_npc_type is created entirely
# in-session via the sprite editor -- a frozen tuple would silently never
# see one registered after this module was first imported, the exact
# "custom type registered mid-session" gap ObjectManager.is_es_type was
# already fixed to avoid (it reads config.get("is_es") dynamically instead
# of a frozen ES_TYPES-style tuple). Call mob_types() fresh at each use
# instead of caching its result across a session.
def mob_types():
    return tuple(name for name, config in OBJECT_TYPES.items() if config.get("mob"))

# The 8 compass directions an entity pack's regions get tagged with (see
# SpriteEditorPanelUI's entity-pack bitmap-tagging mode) -- deliberately
# the exact same 8 names core.world.entities.Player.DIRECTION_VECTORS
# already uses for its own 8-way facing, so there's only ever one
# direction vocabulary in this codebase, not two equivalent ones that
# could drift apart.
NPC_DIRECTIONS = ("front", "front_right", "right", "back_right", "back", "back_left", "left", "front_left")

# Allowed "role" values (ObjectManager.get_role/set_role) per object kind --
# an E/S (ES_TYPES) or a chest (is_chest()). Each kind's first entry is its
# default when a placed object carries no "role" key at all (old saves,
# every object placed before this system existed) -- "connector"/"loot" are
# both exactly today's pre-role behavior, so nothing needs migrating.
ES_ROLES = ("connector", "dungeon_entrance", "dungeon_exit")
CHEST_ROLES = ("loot", "dungeon_exit")

# Each enemy type has its own assets/characters/Ennemies/<folder>/ directory
# with one fixed-name sheet per animation (idle/movement/attack/damaged/death.png).
ENEMY_FOLDERS = {
    "skeleton1": "skeleton1",
    "skeleton2": "skeleton2",
}
ENEMY_ANIMATIONS = ("idle", "movement", "attack", "damaged", "death")


def mob_kind(type_id):
    """"enemy"/"animal"/"pnj" for a mob type, or None if `type_id` isn't a
    mob at all. Mirrors core.world.entities.Mob.__init__'s own frame-source
    dispatch (entity_pack presence first, then ENEMY_FOLDERS membership) --
    the single source of truth for what 4 separate call sites (Mob itself,
    the Forge, CardPanelUI, CardRenderer) used to each re-derive
    independently via `type_id in ENEMY_FOLDERS`."""
    config = OBJECT_TYPES.get(type_id)
    if config is None or not config.get("mob"):
        return None
    if config.get("entity_pack"):
        return "pnj"
    return "enemy" if type_id in ENEMY_FOLDERS else "animal"

# ENEMY_STATS (health/move_speed/aggro_range/attack_range/loot/item_loot) is
# now merged directly into each enemy's own _BUILTIN_OBJECT_TYPES[...]["stats"]
# entry above -- read via OBJECT_TYPES[enemy_type]["stats"], no standalone
# dict here anymore.

# Currency pickup sheets (assets/item/, alongside dynamite.png): two rows
# of 16x16 frames -- row 0 is the idle "spinning coin" loop, row 1 plays once
# when the player actually picks it up (core.world.entities.Pickup). Shared
# by InventoryPanel's counter icon (which only ever uses "spin") and Pickup,
# so both stay visually identical to a single source of truth.
CURRENCY_FILES = {"gold": "item/Coin Sheet.png", "blue": "item/BlueCoin Sheet.png"}
CURRENCY_FRAME_SIZE = 16


_currency_frames_cache = {}


def load_currency_frames(currency_type):
    """Returns {"spin": [...], "collect": [...]}, each a list of 16x16
    frames. Cached by currency_type -- every dropped/picked-up coin of the
    same type re-read and re-sliced this sheet from disk with no caching
    at all before this, unlike WorldRenderer's own _get_object_frames for
    placed static objects. Frames are only ever read (indexed), never
    mutated in place -- see _draw_cached_sprite's own separate zoom-scaled
    cache -- so sharing the same Surface objects across every Pickup of
    this currency_type is safe."""
    if currency_type in _currency_frames_cache:
        return _currency_frames_cache[currency_type]

    sheet = pygame.image.load(PROJECT_ROOT / "assets" / CURRENCY_FILES[currency_type]).convert_alpha()
    size = CURRENCY_FRAME_SIZE
    columns = sheet.get_width() // size

    def _row(row_index):
        return [sheet.subsurface((i * size, row_index * size, size, size)).copy() for i in range(columns)]

    frames = {"spin": _row(0), "collect": _row(1)}
    _currency_frames_cache[currency_type] = frames
    return frames


# Real inventory items (as opposed to currency, see CURRENCY_FILES above) --
# each entry is enough for both a ground ItemPickup's static icon and an
# InventoryPanel slot's icon (same "icon_rect" crop, see Item.get_icon), plus
# which main_slots key it belongs in. "capabilities" ({"throwable": {...},
# "explosive": {...}, ...}) replaces the old bare "throwable": True boolean --
# same vocabulary/shape as a world-object's own optional "capabilities" (see
# _build_mechanics_fields), read generically by Explorator._use_interact_item/
# ProjectileManager instead of a hardcoded dynamite-only path, so a future
# second throwable+explosive item works numerically for free (only its own
# sprite/visual would need wiring up). "effects" (a LIST of {"kind": ...,
# ...params} dicts, e.g. [{"kind": "heal", "amount": 1}] -- note this is a
# list, not a dict like "capabilities": core.editor.ui.card_renderer already
# anticipated this exact shape (`effect.get("kind") for effect in
# card.effects`) before any real effect existed, and a list allows more than
# one effect of the same kind on a card, which a dict keyed by kind name
# couldn't) is read generically by Explorator._use_interact_item too.
_BUILTIN_ITEM_DEFINITIONS = {
    "dynamite": {
        "name": "Dynamite",
        "icon_path": "item/dynamite.png",
        "icon_rect": (0, 0, 16, 16),  # frame 0 -- "avant pickup" / inventory display
        "slot": "interact",
        "card_type": "item",
        "capabilities": {
            "throwable": {"speed": 220},
            "explosive": {"radius_tiles": 2, "damage": 1},
        },
        # "throw" fires the moment the throw is confirmed (see
        # Explorator._use_interact_item's "throwable" branch) -- was a
        # hardcoded "dynamite_interact" SOUND_FILES event before the card
        # sound system, now the card's own default.
        "sounds": {"throw": "lightning_dyn.wav"},
    },
}

# Two-part item registry, same spirit as OBJECT_TYPES' builtin+custom split:
# `custom_items.json` holds full, brand-new item entries (register_item/
# update_item, the ITEM_DEFINITIONS equivalent of register_custom_type),
# while `custom_items_overrides.json` holds a mechanics-only override
# (capabilities and/or effects) of an EXISTING builtin item id (dynamite
# today) -- update_item_overrides, the equivalent of
# update_type_mechanics/_write_builtin_mechanics_override. The two files
# stay separate because they answer different questions ("does this id
# exist at all" vs "should this id's mechanics differ from its Python
# defaults") and a custom item is always complete, never a partial diff.
CUSTOM_ITEMS_PATH = PROJECT_ROOT / "assets" / "tiles" / "custom_items.json"
CUSTOM_ITEMS_OVERRIDES_PATH = PROJECT_ROOT / "assets" / "tiles" / "custom_items_overrides.json"


def _load_custom_items():
    """Absent/vide/corrompu -> dict vide, meme tolerance que
    _load_custom_object_types."""
    if not CUSTOM_ITEMS_PATH.exists():
        return {}
    try:
        with CUSTOM_ITEMS_PATH.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _persist_custom_items(custom):
    CUSTOM_ITEMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CUSTOM_ITEMS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(custom, handle, indent=2, ensure_ascii=False)


def _load_custom_item_overrides():
    if not CUSTOM_ITEMS_OVERRIDES_PATH.exists():
        return {}
    try:
        with CUSTOM_ITEMS_OVERRIDES_PATH.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _persist_custom_item_overrides(overrides):
    CUSTOM_ITEMS_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CUSTOM_ITEMS_OVERRIDES_PATH.open("w", encoding="utf-8") as handle:
        json.dump(overrides, handle, indent=2, ensure_ascii=False)


def _build_item_entry(name, slot, icon_path, icon_rect, capabilities=None, effects=None, sounds=None,
                       sound_pitch=None, loot_cards=None):
    """Construction pure (aucune I/O) d'une entree ITEM_DEFINITIONS custom --
    partagee par register_item/update_item. `card_type` toujours "item" --
    aucun autre type de carte n'utilise ce registre. `loot_cards`: voir
    _build_mechanics_fields's own docstring -- meme convention "None =
    inchange, {} = explicitement vide" (jamais confondu avec "absent")."""
    entry = {
        "name": name,
        "icon_path": icon_path,
        "icon_rect": list(icon_rect),
        "slot": slot,
        "card_type": "item",
    }
    if capabilities:
        entry["capabilities"] = dict(capabilities)
    if effects:
        entry["effects"] = list(effects)
    if sounds:
        entry["sounds"] = dict(sounds)
    if sound_pitch:
        entry["sound_pitch"] = {key: list(value) for key, value in sound_pitch.items()}
    if loot_cards is not None:
        entry["loot_cards"] = dict(loot_cards)
    return entry


def _merged_item_definitions():
    overrides = _load_custom_item_overrides()
    merged = {}
    for item_id, base in _BUILTIN_ITEM_DEFINITIONS.items():
        entry = dict(base)
        entry.update(overrides.get(item_id, {}))
        merged[item_id] = entry
    for item_id, entry in _load_custom_items().items():
        merged[item_id] = dict(entry)
    return merged


ITEM_DEFINITIONS = _merged_item_definitions()


def effective_loot_cards(card_id):
    """The loot table actually spawned as ground pickups (see
    core.world.entities._spawn_loot_pickups) when `card_id` dies (a mob) or
    is destroyed (a tile_decor/tile_special object, or an item -- an item
    entry ALSO spawns a physical ItemPickup on top of the CardPickup, see
    _spawn_loot_pickups): its own "loot_cards" override if one was ever
    saved for it (even an explicitly emptied {}, meaning "drops nothing at
    all" -- see _build_mechanics_fields/_build_item_entry's own docstrings
    on why presence, not truthiness, is what's checked at save time), else
    the implicit default of one copy of its own card -- exactly the
    hardcoded behavior every destructible/killable card had before this
    table existed, now just the fallback rather than the only option.
    Works for both an OBJECT_TYPES- and an ITEM_DEFINITIONS-backed id (a
    tile_floor/tile_wall BASE_TILE_CARDS id matches neither registry, so it
    always falls through to its own default -- consistent, since those two
    are deliberately kept out of the unified mechanics registry, see
    CLAUDE.md)."""
    config = OBJECT_TYPES.get(card_id)
    if config is None:
        config = ITEM_DEFINITIONS.get(card_id)
    if config is not None and "loot_cards" in config:
        return dict(config["loot_cards"])
    return {card_id: 1}


def extract_property_payload(entry, category, kind=None):
    """The single mechanical fragment named by (category, kind) currently
    carried by a live OBJECT_TYPES/ITEM_DEFINITIONS `entry` -- the read
    half of the Forge's "Dechirer" feature (core.editor.ui.mechanics_panel)
    and core.data.cards.default_card_for's property-card bridge, which both
    need the exact same extraction logic (a torn-out property card is
    always resolved live from its source, never snapshotted -- see that
    module's own docstring). None if `entry` doesn't currently carry this
    fragment at all (a capability/effect kind it never had, or a mob/item
    with no stats/loot_cards saved) -- the caller's signal that there's
    nothing to tear or fuse.

    `category` in {"capability", "effect", "stats", "aggressivity", "state",
    "loot", "behavior"} -- "capability"/"effect"/"state" need `kind` (which
    capability/effect/wander_actions role, e.g. "explosive"/"heal"/"idle"
    -- a card can carry more than one of any of the three); "stats"/
    "aggressivity"/"loot"/"behavior" are singleton blocks, `kind` is
    ignored for them.

    "aggressivity" is a finer-grained VIEW into the same "stats" block
    "stats" already exposes whole -- just aggro_range/attack_range, never
    active_attack_frames (deliberately excluded, same reasoning as every
    other place that field is kept out of Dechirer/Coller: those frame
    indices are specific to the SOURCE mob's own sprite sheet, so
    transplanting them onto a target with a differently-shaped attack
    animation would silently point at the wrong frames) -- so "l'agressivite"
    (confirmed with the user) can be torn/fused on its own, without
    dragging health/move_speed/loot along with it.

    "state" reads a PNJ's own wander_actions (which tagged action of its
    entity pack plays for role `kind`, e.g. "idle"/"sitting") -- None if
    that role isn't actually configured, same "nothing to tear" signal as
    every other category.

    "behavior" (2026-08-19, confirmed with the user -- "Comportement")
    exposes the single fact that makes a card come alive at all: `mob`.
    Deliberately just that ONE flag, never the source's own entity_pack/
    wander_actions -- Assembler already attaches a card's OWN pack
    reference structurally (see register_custom_type's entity_pack param),
    with no type/property decided there at all (mob absent); tearing
    "Comportement" off ANY existing mob (flat-frame or entity-pack alike,
    the source's own art is irrelevant, only the flag matters) and gluing
    it onto that typeless card is what turns it into a living one, using
    ITS OWN states -- never the donor's. True if `entry` is a mob, else
    None (nothing to tear), same "nothing to tear" signal as every other
    category -- there is no meaningful "torn mob:False"."""
    if category == "capability":
        return entry.get("capabilities", {}).get(kind)
    if category == "effect":
        for effect in entry.get("effects", []):
            if effect.get("kind") == kind:
                return effect
        return None
    if category == "stats":
        return entry.get("stats")
    if category == "aggressivity":
        stats = entry.get("stats") or {}
        payload = {key: stats[key] for key in ("aggro_range", "attack_range") if key in stats}
        return payload or None
    if category == "state":
        return entry.get("wander_actions", {}).get(kind)
    if category == "loot":
        return entry.get("loot_cards")
    if category == "behavior":
        return True if entry.get("mob") else None
    return None


def _apply_property_payload(entry, category, kind, payload):
    """Writes `payload` (see extract_property_payload) into `entry` in
    place -- always a REPLACE of that one fragment, never a merge/sum (a
    fused card's stats/capability/effect are exactly the source's, not the
    base's-plus-the-source's -- confirmed with the user: "remplacer les
    stats d'une carte par celle d'une autre" is the fun version, a simple
    sum "semble un peu fort"). Only the named fragment's own key is
    touched -- an "explosive" capability payload never disturbs an existing
    "throwable" one on the same entry, an "heal" effect never disturbs a
    differently-kinded effect already present. Same for "aggressivity"
    (only aggro_range/attack_range within "stats" -- health/move_speed/
    loot, if the target already had them, survive untouched) and "state"
    (only that one wander_actions role -- every other role the target's
    pack already had configured survives untouched)."""
    if category == "capability":
        capabilities = dict(entry.get("capabilities", {}))
        capabilities[kind] = dict(payload)
        entry["capabilities"] = capabilities
    elif category == "effect":
        entry["effects"] = [e for e in entry.get("effects", []) if e.get("kind") != kind] + [dict(payload)]
    elif category == "stats":
        entry["stats"] = dict(payload)
    elif category == "aggressivity":
        stats = dict(entry.get("stats") or {})
        stats.update(payload)
        entry["stats"] = stats
    elif category == "state":
        wander_actions = dict(entry.get("wander_actions", {}))
        wander_actions[kind] = payload
        entry["wander_actions"] = wander_actions
    elif category == "loot":
        entry["loot_cards"] = dict(payload)
    elif category == "behavior":
        # Just the flag -- never touches entity_pack/wander_actions, see
        # extract_property_payload's own docstring on why (the target's
        # OWN pack/states, already attached structurally by Assembler,
        # must survive this untouched). card_type also needs an explicit
        # fix here: _write_custom_type's own card_type backfill is a
        # setdefault (only fires when the key is ABSENT), and fuse_card's
        # new_entry starts as a copy of the base entry, which already HAD
        # a card_type (e.g. "tile_decor") from before it became alive --
        # without this, a freshly-animated card would keep displaying
        # under its old, now-stale card_type.
        entry["mob"] = True
        entry["card_type"] = "mob"


def _write_custom_item(item_id, entry):
    """The ITEM_DEFINITIONS twin of _write_custom_type -- writes `entry`
    into custom_items.json (merged, not replaced) and updates
    ITEM_DEFINITIONS in memory immediately. Unlike _write_custom_type, never
    needs a card_type backfill -- every ITEM_DEFINITIONS entry (builtin or
    custom) already always carries "card_type": "item" explicitly (see
    _build_item_entry/_BUILTIN_ITEM_DEFINITIONS), so a clone of one already
    has it."""
    custom = _load_custom_items()
    custom[item_id] = entry
    _persist_custom_items(custom)
    ITEM_DEFINITIONS[item_id] = entry


def fuse_card(base_id, category, kind, payload):
    """The write half of the Forge's "Coller" feature: greffe le fragment
    (category, kind, payload) -- deja resolu par l'appelant depuis la
    propriete torn dechiree, voir core.data.cards.parse_property_card_id/
    TORN_PROPERTIES_PATH, cette fonction ne connait plus aucune source --
    sur une copie de `base_id`, enregistree sous un TOUT NOUVEL id --
    jamais une mutation de `base_id` lui-meme (c'est le point entier de
    cette fonction : une carte fusionnee doit rester independante de tout
    ce qui reste range sous `base_id`, contrairement a
    update_type_mechanics/update_item, qui mettent a jour un type
    partage). Retourne le nouvel id, ou None si `base_id` porte deja ce
    fragment exact (no-op deliberement silencieux, jamais une erreur --
    greffer deux fois la meme propriete doit rester 1 seule carte, jamais
    consommer deux fois pour rien, voir le module docstring).

    L'id du nouveau type est deterministe : `root_id` (la racine non
    fusionnee -- remonte a travers `fused_from` si `base_id` est deja lui-
    meme une fusion, pour qu'une deuxieme greffe ne s'imbrique jamais en
    "id__x__y" mais reste "root__x_y") plus l'ensemble TRIE des fragments
    deja appliques -- deux chemins de creation differents aboutissant a la
    meme combinaison (base, {fragments}) retombent donc toujours sur le
    meme id, et leurs comptes en collection s'empilent au lieu de dupliquer
    des cartes visuellement identiques (confirme avec l'utilisateur)."""
    write = _write_custom_type
    base_entry = OBJECT_TYPES.get(base_id)
    if base_entry is None:
        write = _write_custom_item
        base_entry = ITEM_DEFINITIONS.get(base_id)
    if base_entry is None:
        raise ValueError(f"'{base_id}' n'existe pas")

    if category == "behavior" and not base_entry.get("entity_pack"):
        # A flat-frame mob (is_mob, no entity_pack -- a builtin animal/
        # enemy) needs a real file-path "asset" + (for "enemy" specifically)
        # ENEMY_FOLDERS membership -- load_animal_frames/load_enemy_frames
        # both assume that shape unconditionally and crash on anything
        # else. A custom card's "asset" is always a tileset-region dict,
        # never a file path, so gluing "Comportement" onto one with no
        # entity_pack would silently produce a mob:True card the game
        # can't actually render at all (found 2026-08-19, a real crash --
        # TypeError in load_animal_frames). Refused here instead: only a
        # card that already has its OWN entity_pack (see register_custom_
        # type's own `entity_pack` param, attached structurally by
        # Assembler) can ever become alive.
        raise ValueError(
            "Cette carte n'a pas de pack d'entite attache -- construis-la d'abord dans l'assembleur "
            "(pack 'Personnage / Entite') avant de lui coller un Comportement."
        )

    fused_from = base_entry.get("fused_from")
    root_id = fused_from["base"] if fused_from else base_id
    existing_fragments = set(fused_from["fragments"]) if fused_from else set()
    # alnum/underscore only, same charset _validate_new_id enforces for
    # every other freshly-minted type_id -- this one flows straight into
    # new_id below without going through that guard (a derived id can
    # legitimately already exist, see the no-op check right after), so it
    # has to be safe on its own.
    fragment_key = f"{category}_{kind}" if kind else category
    new_fragments = existing_fragments | {fragment_key}
    if new_fragments == existing_fragments:
        return None

    new_id = f"{root_id}__{'_'.join(sorted(new_fragments))}"
    new_entry = dict(base_entry)
    _apply_property_payload(new_entry, category, kind, payload)
    new_entry["fused_from"] = {"base": root_id, "fragments": sorted(new_fragments)}
    root_entry = OBJECT_TYPES.get(root_id, ITEM_DEFINITIONS.get(root_id, {}))
    root_name = root_entry.get("name") or root_id.replace("_", " ").title()
    # No more source card to name -- the property's own generic label
    # (see core.data.cards.property_label) is all there is to attach now
    # (confirmed with the user: provenance never mattered here either).
    from core.data.cards import property_label
    new_entry["name"] = f"{root_name} + {property_label(category, kind)}"
    write(new_id, new_entry)
    return new_id


def is_builtin_item(item_id):
    return item_id in _BUILTIN_ITEM_DEFINITIONS


def delete_custom_item(item_id):
    """Supprime definitivement un item custom -- pendant de delete_custom_type
    pour ITEM_DEFINITIONS (2026-08-19, meme garde/erreurs). N'existait pas
    avant : aucun chemin ne permettait de supprimer un item custom, seulement
    de le modifier (update_item). Meme absence de verification de reference
    que delete_custom_type -- c'est a l'appelant de refuser une suppression
    encore utilisee quelque part avant d'appeler ceci."""
    existing = ITEM_DEFINITIONS.get(item_id)
    if existing is None:
        raise ValueError(f"'{item_id}' n'existe pas")
    if is_builtin_item(item_id):
        raise ValueError(f"'{item_id}' est un item integre au jeu, non supprimable")

    custom = _load_custom_items()
    custom.pop(item_id, None)
    _persist_custom_items(custom)

    del ITEM_DEFINITIONS[item_id]


def register_item(item_id, name, slot, icon_path, icon_rect, capabilities=None, effects=None, sounds=None,
                   sound_pitch=None, loot_cards=None):
    """Valide et persiste un NOUVEL item -- l'equivalent register_custom_type
    pour ITEM_DEFINITIONS. Leve ValueError sur un id invalide/deja pris ou
    un slot inconnu."""
    _validate_new_id(item_id, ITEM_DEFINITIONS)
    if slot not in ("attack", "interact", "passive"):
        raise ValueError(f"Slot inconnu : {slot}")
    entry = _build_item_entry(name, slot, icon_path, icon_rect, capabilities, effects, sounds, sound_pitch, loot_cards)
    custom = _load_custom_items()
    custom[item_id] = entry
    _persist_custom_items(custom)
    ITEM_DEFINITIONS[item_id] = entry
    return entry


def update_item(item_id, name, slot, icon_path, icon_rect, capabilities=None, effects=None, sounds=None,
                 sound_pitch=None, loot_cards=None):
    """Edite un item custom DEJA enregistre -- jamais un item integre au jeu
    (dynamite) comme register_item/update_item ne peuvent jamais l'ecraser :
    voir update_item_overrides pour editer les mecaniques d'un builtin."""
    if item_id not in ITEM_DEFINITIONS:
        raise ValueError(f"'{item_id}' n'existe pas")
    if is_builtin_item(item_id):
        raise ValueError(f"'{item_id}' est un item integre au jeu, non modifiable (voir update_item_overrides)")
    if slot not in ("attack", "interact", "passive"):
        raise ValueError(f"Slot inconnu : {slot}")
    entry = _build_item_entry(name, slot, icon_path, icon_rect, capabilities, effects, sounds, sound_pitch, loot_cards)
    custom = _load_custom_items()
    custom[item_id] = entry
    _persist_custom_items(custom)
    ITEM_DEFINITIONS[item_id] = entry
    return entry


def update_item_overrides(item_id, capabilities, effects, sounds=None, sound_pitch=None, loot_cards=None):
    """Persiste un override mecanique (capacites ET/OU effets, toujours
    l'etat complet, jamais un diff partiel -- desactiver l'un ne necessite
    pas un appel separe) pour un item EXISTANT INTEGRE AU JEU (dynamite
    aujourd'hui -- les items custom passent par update_item ci-dessus).

    Compare toujours contre les valeurs mecaniques REELLES du builtin (pas
    juste "est-ce vide ?") avant de decider si l'override est un no-op a
    retirer -- meme piege que _write_builtin_mechanics_override a evite
    pour OBJECT_TYPES : dynamite a "capabilities" actif par defaut, donc un
    override vide (tout desactive) DIFFERE bel et bien du builtin et doit
    etre persiste, pas silencieusement ignore."""
    base = _BUILTIN_ITEM_DEFINITIONS.get(item_id)
    if base is None:
        raise ValueError(f"'{item_id}' n'existe pas ou n'est pas un item integre au jeu")

    entry = {}
    if capabilities:
        entry["capabilities"] = dict(capabilities)
    if effects:
        entry["effects"] = list(effects)
    if sounds:
        entry["sounds"] = dict(sounds)
    if sound_pitch:
        entry["sound_pitch"] = {key: list(value) for key, value in sound_pitch.items()}
    if loot_cards is not None:
        entry["loot_cards"] = dict(loot_cards)
    base_state = {
        key: base[key] for key in ("capabilities", "effects", "sounds", "sound_pitch", "loot_cards") if key in base
    }

    overrides = _load_custom_item_overrides()
    if entry == base_state:
        overrides.pop(item_id, None)
        merged = dict(base)
    else:
        overrides[item_id] = entry
        merged = _merge_mechanics_override(
            base, entry, ("capabilities", "effects", "sounds", "sound_pitch", "loot_cards")
        )
    _persist_custom_item_overrides(overrides)
    ITEM_DEFINITIONS[item_id] = merged
    return merged

DYNAMITE_FRAME_SIZE = 16
DYNAMITE_FRAME_COUNT = 4


_dynamite_frames_cache = None


def load_dynamite_frames():
    """The 4 throw-animation frames (16x16 each), sliced from the single-row
    64x16 dynamite.png sheet -- used by core.world.entities.ThrownDynamite,
    not by the static ground/inventory icon (that's just frame 0, read
    directly via ITEM_DEFINITIONS["dynamite"]["icon_rect"]). Cached at
    module level -- every thrown stick re-read this sheet from disk with
    no caching before this."""
    global _dynamite_frames_cache
    if _dynamite_frames_cache is None:
        sheet = pygame.image.load(PROJECT_ROOT / "assets" / ITEM_DEFINITIONS["dynamite"]["icon_path"]).convert_alpha()
        size = DYNAMITE_FRAME_SIZE
        _dynamite_frames_cache = [sheet.subsurface((i * size, 0, size, size)).copy() for i in range(DYNAMITE_FRAME_COUNT)]
    return _dynamite_frames_cache


# Explosion VFX (assets/effect/smallexplosion/) -- one 48x48 PNG per frame,
# not a sliced sheet like everything else in this module, since that's how
# it was authored. Played once by core.world.entities.Explosion wherever a
# ThrownDynamite detonates.
EXPLOSION_FOLDER = "effect/smallexplosion"
EXPLOSION_FRAME_COUNT = 9


_explosion_frames_cache = None


def load_explosion_frames():
    """Cached at module level -- every dynamite blast previously re-read
    all 9 individual PNG files from disk with no caching at all."""
    global _explosion_frames_cache
    if _explosion_frames_cache is None:
        _explosion_frames_cache = [
            pygame.image.load(PROJECT_ROOT / "assets" / EXPLOSION_FOLDER / f"frame{i:04d}.png").convert_alpha()
            for i in range(EXPLOSION_FRAME_COUNT)
        ]
    return _explosion_frames_cache


# Destruction VFX (assets/effect/star/star.png) -- a single 128x32 sheet,
# 4 frames of 32x32 sliced left-to-right, same convention as
# load_dynamite_frames. Played once by core.world.entities.DestructionSpark
# while homing toward whichever player destroyed the tile (melee) or the
# nearest player in the room (explosion) -- see Dungeon.destroy_area/
# destroy_wall_cell's own callers.
STAR_FOLDER = "effect/star"
STAR_FILENAME = "star.png"
STAR_FRAME_SIZE = 32
STAR_FRAME_COUNT = 4


_star_frames_cache = None


def load_star_frames():
    """Cached at module level, same reasoning as load_dynamite_frames/
    load_explosion_frames -- every destroyed tile would otherwise re-read
    this sheet from disk."""
    global _star_frames_cache
    if _star_frames_cache is None:
        sheet = pygame.image.load(PROJECT_ROOT / "assets" / STAR_FOLDER / STAR_FILENAME).convert_alpha()
        size = STAR_FRAME_SIZE
        _star_frames_cache = [sheet.subsurface((i * size, 0, size, size)).copy() for i in range(STAR_FRAME_COUNT)]
    return _star_frames_cache


# Flame VFX (assets/effect/fire/flamme.png) -- a single 96x16 sheet, 6
# frames of 16x16 sliced left-to-right, same convention as
# load_star_frames. Played on a loop (not once, unlike explosion/star) by
# core.editor.ui.card_burn.BurnAnimation while a torn-off card piece burns
# away in core.editor.ui.mechanics_panel.MechanicsPanelUI's Dechirer
# gesture -- the one sprite-sheet loader in this module used from UI code
# rather than the live world, kept here anyway since this is already the
# single place every other sprite sheet in the project is loaded/cached
# from.
FLAME_FOLDER = "effect/fire"
FLAME_FILENAME = "flamme.png"
FLAME_FRAME_SIZE = 16
FLAME_FRAME_COUNT = 6


_flame_frames_cache = None


def load_flame_frames():
    """Cached at module level, same reasoning as load_star_frames."""
    global _flame_frames_cache
    if _flame_frames_cache is None:
        sheet = pygame.image.load(PROJECT_ROOT / "assets" / FLAME_FOLDER / FLAME_FILENAME).convert_alpha()
        size = FLAME_FRAME_SIZE
        _flame_frames_cache = [sheet.subsurface((i * size, 0, size, size)).copy() for i in range(FLAME_FRAME_COUNT)]
    return _flame_frames_cache


def make_item(item_id):
    """Builds a core.world.inventory.Item from ITEM_DEFINITIONS -- kept here
    (not in inventory.py) since ITEM_DEFINITIONS lives alongside every other
    asset registry in this module (OBJECT_TYPES, CURRENCY_FILES)."""
    from core.world.inventory import Item
    definition = ITEM_DEFINITIONS[item_id]
    return Item(item_id, definition["name"], definition["icon_path"], definition.get("icon_rect"))


def load_object_frames(object_type, variant=None, direction=None):
    """Slice an object's sprite sheet into its animation frames -- a flat
    list, "frames" cells read left-to-right then row by row. Almost every
    object type is a single row ("rows" defaults to 1, in which case this is
    exactly the old behavior: "frames" columns from row 0). A chest-like
    type with "rows": 2 instead has "frames" as the TOTAL count across both
    rows (e.g. 8 for lilchest's 4-idle + 4-open sheet), so row 1 continues
    the flat list right where row 0 left off -- obj["frame"] can then just
    keep counting upward across the "seam" between rows without needing to
    know rows exist at all (see OBJECT_TYPES["lilchest"]).

    `direction` (one of NPC_DIRECTIONS) only matters for a type whose
    "directions" ({direction: frame_index}, see _build_visual_fields) has
    that key -- resolves to that ONE frame_rects entry, on the card itself,
    no separate pack/action concept at all (deliberately simpler than the
    PNJ action/direction/order entity-pack scheme -- see _build_mechanics_
    fields' own docstring for why decor doesn't need it). Falls through to
    the type's ordinary `variant`/base-asset resolution below when
    `directions` doesn't have that key (a stale obj["direction"] from
    before a re-crop, or simply no `directions` at all) -- same fail-open
    spirit as cell_mode's own out-of-range fallback."""
    config = OBJECT_TYPES[object_type]
    asset_path = config.get("variants", {}).get(variant, config["asset"])

    if isinstance(asset_path, dict):
        # {"tileset": ..., "rect": [x, y, w, h]} -- a region reference into a
        # shared tileset (custom types registered via the in-app sprite
        # editor, see register_custom_type below) instead of a dedicated
        # per-type file. Always a single static frame, same as the
        # "frames": 1 branch below -- a region reference is never sliced
        # into an animation.
        #
        # {"tileset": ..., "rects": [[x, y, w, h], ...]} -- multiple frames
        # picked individually (see SpriteEditorPanelUI), each its own
        # independent tileset region rather than consecutive cells of one
        # sheet -- originally just a "porte" opening animation, now also
        # used by any type with per-frame `directions`. `direction`, when
        # given and tagged, selects exactly one of these rects instead of
        # returning the whole list; otherwise every rect comes back in
        # order ("frames" -- see _build_visual_fields -- already equals
        # len(rects), so obj["frame"] indexes straight into this list for
        # a plain, direction-less multi-frame animation).
        if "rects" in asset_path:
            rects = asset_path["rects"]
            directions = config.get("directions")
            if directions and direction in directions:
                index = directions[direction]
                if 0 <= index < len(rects):
                    return [load_tileset_region(asset_path["tileset"], rects[index])]
            return [load_tileset_region(asset_path["tileset"], r) for r in rects]
        return [load_tileset_region(asset_path["tileset"], asset_path["rect"])]

    asset = PROJECT_ROOT / "assets" / asset_path
    sheet = pygame.image.load(asset).convert_alpha()

    if config["frames"] == 1:
        # A single static frame whose asset is pre-sized exactly to its
        # final footprint (e.g. "big_entrance", a 2-wide object with a 32x16
        # asset) -- no frame_size/rows slicing makes sense here, since every
        # other type assumes SQUARE frame_size x frame_size cells. Every
        # existing type sets "frames" to its actual per-row column count
        # (always >= 1 for an animated/static-but-square sprite), so this
        # only ever affects a type that deliberately opts into it.
        return [sheet]

    frame_size = config.get("frame_size", 24 if object_type == "spawn" else 16)
    rows = config.get("rows", 1)
    columns = config["frames"] // rows

    frames = []
    for row in range(rows):
        for col in range(columns):
            rect = pygame.Rect(col * frame_size, row * frame_size, frame_size, frame_size)
            frames.append(sheet.subsurface(rect).copy())
    return frames


_animal_frames_cache = {}


def load_animal_frames(object_type):
    """Full idle+move animation set for an animal NPC sheet (a 2x2 grid: row 0
    idle, row 1 move, each row 2 frames of frame_size px). Used by
    core.world.entities.Animal for live wandering during exploration -- the
    static editor palette/placed-object preview keeps using
    load_object_frames, which only reads the idle row (config["frames"]).

    Cached by object_type -- every wandering animal of the same type
    re-read and re-sliced this sheet from disk with no caching at all
    before this."""
    if object_type in _animal_frames_cache:
        return _animal_frames_cache[object_type]

    config = OBJECT_TYPES[object_type]
    asset = PROJECT_ROOT / "assets" / config["asset"]
    sheet = pygame.image.load(asset).convert_alpha()
    frame_size = config["frame_size"]

    def _row(row_index):
        return [
            sheet.subsurface(
                pygame.Rect(i * frame_size, row_index * frame_size, frame_size, frame_size)
            ).copy()
            for i in range(2)
        ]

    frames = {"idle": _row(0), "move": _row(1)}
    _animal_frames_cache[object_type] = frames
    return frames


ENEMY_FRAME_SIZE = 32

_enemy_frames_cache = {}


def load_enemy_frames(enemy_type):
    """Full idle/movement/attack/damaged/death animation set for an enemy --
    unlike animals, each is its own single-row sheet, so the frame count per
    sheet is derived from its own pixel width (sheet.get_width() //
    ENEMY_FRAME_SIZE, same approach as Player.cut_sheet) rather than
    assumed -- skeleton1 and skeleton2 don't share frame counts for any of
    their animations despite sharing a folder layout.

    Cached by enemy_type -- every spawned skeleton of the same type
    re-read every one of its animation sheets from disk with no caching
    at all before this."""
    if enemy_type in _enemy_frames_cache:
        return _enemy_frames_cache[enemy_type]

    folder = ENEMY_FOLDERS[enemy_type]
    frames = {}
    for animation in ENEMY_ANIMATIONS:
        path = PROJECT_ROOT / "assets" / "characters" / "Ennemies" / folder / f"{animation}.png"
        sheet = pygame.image.load(path).convert_alpha()
        columns = sheet.get_width() // ENEMY_FRAME_SIZE
        frames[animation] = [
            sheet.subsurface(
                pygame.Rect(i * ENEMY_FRAME_SIZE, 0, ENEMY_FRAME_SIZE, ENEMY_FRAME_SIZE)
            ).copy()
            for i in range(columns)
        ]
    _enemy_frames_cache[enemy_type] = frames
    return frames


_entity_pack_lookup_cache = {}


def build_entity_pack_lookup(pack_name):
    """{action: {direction: [tile_index, ...]}}, ordered by each tile's own
    saved "order" field -- built from an entity-kind pack's tagged tiles
    (see core.editor.ui.SpriteEditorPanelUI's batch action/direction
    tagging, and core.data.ressources.update_autotile_pack_tiles). Sibling
    of core.editor.autotile.build_pack_lookup, deliberately NOT the same
    function -- that one's return shape (bitmask -> single tile, plus
    weighted variants) has no equivalent here; action/direction/order is a
    different domain entirely. Cached per (pack_name, file mtime), same
    stat()-not-reparse pattern as build_pack_lookup -- reloaded
    automatically the moment the sprite editor tags/re-tags a tile."""
    from core.data.ressources import load_autotile_pack, get_autotile_pack_path

    try:
        mtime = get_autotile_pack_path(pack_name).stat().st_mtime
    except OSError:
        mtime = None

    cached = _entity_pack_lookup_cache.get(pack_name)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    payload = load_autotile_pack(pack_name) or {"tiles": []}
    lookup = {}
    for tile in payload.get("tiles", []):
        index = tile.get("index")
        action = tile.get("action")
        direction = tile.get("direction")
        if index is None or action is None or direction is None:
            continue
        lookup.setdefault(action, {}).setdefault(direction, []).append(
            (tile.get("order", 0), index)
        )

    for directions in lookup.values():
        for direction, ordered in directions.items():
            ordered.sort(key=lambda pair: pair[0])
            directions[direction] = [index for _order, index in ordered]

    result = lookup
    _entity_pack_lookup_cache[pack_name] = (mtime, result)
    return result


_npc_frames_cache = {}


def load_npc_frames(entity_pack_name):
    """{action: {direction: [Surface, ...]}} -- the live-entity equivalent
    of load_animal_frames/load_enemy_frames, but sourced from a
    sprite-editor-tagged entity pack instead of a fixed grid/folder
    convention (see build_entity_pack_lookup). Cached by pack name, same
    convention as its siblings -- an NPC type's pack is never re-tagged
    while the game itself is running, only from the editor, so this cache
    never needs to react to a pack changing mid-session the way the
    editor's own build_entity_pack_lookup does."""
    if entity_pack_name in _npc_frames_cache:
        return _npc_frames_cache[entity_pack_name]

    from core.data.ressources import load_autotile_pack

    payload = load_autotile_pack(entity_pack_name)
    if payload is None:
        raise ValueError(f"Pack d'entite inconnu : {entity_pack_name}")
    tileset = payload["tileset"]
    rects_by_index = {tile["index"]: tile["rect"] for tile in payload.get("tiles", [])}

    lookup = build_entity_pack_lookup(entity_pack_name)
    frames = {
        action: {
            direction: [load_tileset_region(tileset, rects_by_index[index]) for index in indices]
            for direction, indices in directions.items()
        }
        for action, directions in lookup.items()
    }
    _npc_frames_cache[entity_pack_name] = frames
    return frames


def action_direction_coverage(entity_pack, action_name):
    """(tagged: set, missing: set) of NPC_DIRECTIONS for `action_name`
    within `entity_pack` -- the shared primitive behind npc_completeness
    (a PNJ type already registered) AND core.editor.ui.SpriteEditorPanelUI's
    own live coverage preview while still filling the "Enregistrer comme
    PNJ" form, before anything is registered at all. One source of truth
    for "how much of this action is tagged" rather than two counting
    routines that could drift. `action_name` of None/"" (an unset optional
    role) returns everything as missing -- callers that only care about
    CONFIGURED roles (see npc_completeness) filter those out themselves
    rather than this function silently skipping them."""
    if not action_name:
        return set(), set(NPC_DIRECTIONS)
    lookup = build_entity_pack_lookup(entity_pack)
    tagged = set(lookup.get(action_name, {}).keys())
    return tagged, set(NPC_DIRECTIONS) - tagged


def npc_completeness(type_id):
    """{"complete": bool, "missing": {role: [direction,...], ...}} for an
    ALREADY-REGISTERED entity-pack-backed mob type -- only checks roles
    actually present in its own wander_actions (an optional role like
    "sitting"/"laying"/"run" left unset is a deliberate choice, not a gap
    -- see core.world.entities.Mob's own class docstring on why each is
    independently optional). {"complete": True, "missing": {}} for
    anything that isn't entity-pack-backed at all (a hand-authored
    animal/enemy-style mob, or a plain object/item), so a caller can call
    this unconditionally without checking config.get("entity_pack") first
    -- gated on entity_pack presence, not "is this a PNJ": completeness is
    about which frame-authoring path a mob uses, orthogonal to whether
    it's also interactable."""
    config = OBJECT_TYPES.get(type_id)
    if config is None or not config.get("entity_pack"):
        return {"complete": True, "missing": {}}

    entity_pack = config["entity_pack"]
    missing = {}
    for role, action_name in config.get("wander_actions", {}).items():
        _tagged, gaps = action_direction_coverage(entity_pack, action_name)
        if gaps:
            missing[role] = sorted(gaps)
    return {"complete": not missing, "missing": missing}


def _build_npc_type_entry(name, entity_pack, tileset, icon_rect, size, wander_actions):
    """Construction pure (aucune I/O) d'un dict au format OBJECT_TYPES pour
    un PNJ -- parallele a _build_visual_fields, mais volontairement
    PAS partagee avec lui : sa signature est pensee pour "un archetype +
    un rect (ou frame_rects) unique", alors qu'un PNJ n'a aucun rect
    propre, seulement une reference a tout un pack d'entite. `icon_rect`
    fournit uniquement l'icone statique (palette/objet pose, voir
    load_object_frames -- chemin totalement inchange, la forme
    {"tileset","rect"} est deja ce que ce loader attend). `wander_actions`
    ({"idle": ..., "move": ...}) nomme lesquelles des actions du pack
    jouer pendant chacun des deux etats de vagabondage de MobManager (voir
    core.world.entities.Mob)."""
    return {
        "asset": {"tileset": tileset, "rect": list(icon_rect)},
        "placement": "floor",
        "size": list(size),
        "frames": 1,
        "name": name,
        "mob": True,
        "entity_pack": entity_pack,
        "wander_actions": dict(wander_actions),
    }


def register_npc_type(type_id, name, entity_pack, tileset, icon_rect, size, wander_actions):
    """Valide et persiste une NOUVELLE entree OBJECT_TYPES referencant un
    entity_pack -- le pendant de register_custom_type pour ce cas (voir
    update_npc_type pour l'edition). Meme garde-fou d'id que
    register_custom_type.

    N'impose plus interactable=True a la creation (2026-08-18) -- ce chemin
    d'enregistrement construit n'importe quelle carte animee referencant un
    pack d'entite (PNJ dialogable, mais aussi un mob combat-only fait de
    tags attack/damaged/death, voir entities.Mob), pas seulement un PNJ
    dialogable ; interactable reste un simple flag optionnel, editable comme
    n'importe quel autre MECHANICS_KEYS via update_type_mechanics, jamais
    force par defaut."""
    _validate_new_id(type_id, OBJECT_TYPES)
    entry = _build_npc_type_entry(name, entity_pack, tileset, icon_rect, size, wander_actions)
    _write_custom_type(type_id, entry)
    return entry


def update_npc_type(type_id, name, entity_pack, tileset, icon_rect, size, wander_actions):
    """Edite un PNJ deja enregistre -- pendant de update_custom_type. Meme
    garde-fou : type_id doit deja exister ET etre un type custom (asset en
    dict), jamais un type integre au jeu."""
    existing = OBJECT_TYPES.get(type_id)
    if existing is None:
        raise ValueError(f"'{type_id}' n'existe pas")
    if not isinstance(existing.get("asset"), dict):
        raise ValueError(f"'{type_id}' est un type integre au jeu, non modifiable")
    entry = _build_npc_type_entry(name, entity_pack, tileset, icon_rect, size, wander_actions)
    _write_custom_type(type_id, entry)
    return entry


def npc_types_for_pack(entity_pack):
    """(type_id, config) pour chaque PNJ deja enregistre depuis
    `entity_pack` -- pendant de custom_types_for_tileset, pour la liste
    "PNJ existants" de SpriteEditorPanelUI en mode pack d'entite."""
    return [
        (candidate_id, config) for candidate_id, config in OBJECT_TYPES.items()
        if config.get("entity_pack") == entity_pack
    ]


def rename_entity_pack_references(old_pack_name, new_pack_name):
    """Keeps every registered PNJ's own "entity_pack" field in sync after
    ressources.rename_autotile_pack has already renamed the pack's file on
    disk -- a pack rename is only complete once this has run too (call it
    right after, see SpriteEditorPanelUI's pack-rename callback). Rewrites
    each affected entry through _build_npc_type_entry (same name/tileset/
    icon_rect/size/wander_actions, only entity_pack changes) rather than
    poking the dict in place, so the persisted shape never drifts from
    what register_npc_type/update_npc_type themselves would have written."""
    for type_id, config in npc_types_for_pack(old_pack_name):
        entry = _build_npc_type_entry(
            config.get("name", type_id), new_pack_name, config["asset"]["tileset"],
            config["asset"]["rect"], config.get("size", [1, 1]), config.get("wander_actions", {}),
        )
        _write_custom_type(type_id, entry)


class ObjectManager:
    """Owns the placed-object list and the rules for placing them. The grid/size data it needs belongs to the Dungeon it's attached to."""

    ANIM_SPEED = DEFAULT_ANIM_SPEED  # seconds per frame -- see ressources.DEFAULT_ANIM_SPEED's own docstring

    def __init__(self, dungeon):
        self.dungeon = dungeon
        # _cell_index/objects_version back get_object_at -- see the `objects`
        # property setter below and _index_object/_deindex_object. Kept in
        # sync incrementally by add_object/move_object (the only two methods
        # that ever add a cell or move one without replacing the whole list);
        # any wholesale replacement of `self.objects` (prune_invalid,
        # SaveManager.apply_json's direct `object_manager.objects = ...`)
        # goes through the property setter instead, which just rebuilds the
        # index from scratch -- simpler and safe for an infrequent, already
        # O(n)-anyway operation, and it means an external assignment can
        # never silently leave the index stale.
        #
        # Each cell maps to a STACK (list, oldest first) of every object
        # whose footprint covers it, not a single object -- two objects can
        # legitimately overlap now that door/gate placement no longer
        # requires an empty cell (is_valid_wall_break, 2026-08-18: a door is
        # meant to be placeable directly on/under a purely decorative
        # multi-cell wall object like "bordureporte"). get_object_at returns
        # the LAST (most recently placed/moved) entry, so the functional
        # object placed on top of a decoration is what collision/interact
        # actually sees; removing it via _deindex_object naturally reveals
        # whatever was underneath instead of leaving the cell unindexed.
        self._cell_index = {}
        self.objects_version = 0
        # id(obj) -> obj, every object currently animating (activated/open
        # and not yet holding on its last frame) -- see begin_animation/
        # update() below. Rebuilt from scratch on any wholesale replacement
        # of `self.objects` (the property setter), same reasoning as
        # _cell_index: a fresh load can arrive with objects already
        # activated/open mid-animation (see SaveManager's "additive field"
        # docs), and prune_invalid dropping an animating object must drop it
        # from here too.
        self._animating = {}
        self._objects = []

    @property
    def objects(self):
        return self._objects

    @objects.setter
    def objects(self, value):
        self._objects = value
        self._rebuild_cell_index()
        self._rebuild_animating()
        self.objects_version += 1

    def _rebuild_animating(self):
        self._animating = {}
        for obj in self._objects:
            if obj.get("activated") or obj.get("open"):
                self.begin_animation(obj)

    def begin_animation(self, obj):
        """Registers `obj` as currently animating -- call right after
        setting "activated"/"open" True for the first time, from wherever
        that happens: this class's own check_button_trigger, or
        core.world.assembly's cross-room button/door-sync logic (each
        against the ObjectManager that actually owns the target object, not
        necessarily `self`), or Explorator._interact_with_chest opening a
        chest. update() below only ever iterates this set instead of every
        placed object, and self-removes an entry once it reaches its last
        frame -- calling this again for an already-registered or
        already-finished object is harmless (dict keyed by id(obj), and a
        finished one is simply re-pruned on the very next update() tick)."""
        self._animating[id(obj)] = obj

    def _footprint_cells_of(self, obj):
        size_x, size_y = OBJECT_TYPES[obj["type"]]["size"]
        for dx in range(size_x):
            for dy in range(size_y):
                yield obj["x"] + dx, obj["y"] + dy

    def _index_object(self, obj):
        # Appends to each cell's stack -- see __init__'s own docstring for
        # why a cell can hold more than one object now. get_object_at reads
        # the last entry, so whichever object was placed/moved here most
        # recently is the one collision/interact/erase actually see.
        for cell in self._footprint_cells_of(obj):
            self._cell_index.setdefault(cell, []).append(obj)

    def _deindex_object(self, obj):
        for cell in self._footprint_cells_of(obj):
            stack = self._cell_index.get(cell)
            if stack is None:
                continue
            try:
                stack.remove(obj)
            except ValueError:
                continue
            if not stack:
                del self._cell_index[cell]

    def _rebuild_cell_index(self):
        self._cell_index = {}
        for obj in self._objects:
            self._index_object(obj)

    def _in_bounds(self, grid_x, grid_y):
        return 0 <= grid_x < self.dungeon.width and 0 <= grid_y < self.dungeon.height

    def add_object(self, object_type, grid_x, grid_y, direction=None):
        """`direction` (one of NPC_DIRECTIONS) is the MANUAL-mode caller's
        own choice (e.g. Creator's R-rotate-during-drag) for a type whose
        "direction_mode" is "manual" -- ignored (overridden) for a type
        whose direction_mode is "auto", since _resolve_placement always
        recomputes that one from wall adjacency regardless of what's
        passed in here. See _build_mechanics_fields' own docstring for the
        auto/manual distinction."""
        if not self._in_bounds(grid_x, grid_y):
            return False

        valid, variant, auto_direction = self._resolve_placement(object_type, grid_x, grid_y)
        if not valid:
            return False

        placed = {
            "type": object_type,
            "x": grid_x,
            "y": grid_y,
        }

        if variant is not None:
            placed["variant"] = variant

        resolved_direction = auto_direction if auto_direction is not None else direction
        if resolved_direction is not None:
            placed["direction"] = resolved_direction

        config = OBJECT_TYPES[object_type]
        if config.get("chest"):
            # Own dict copies, not the OBJECT_TYPES default objects themselves
            # -- ChestPanelUI mutates these per-placed-chest (see Creator),
            # which must never leak back into the shared registry entry.
            placed["loot"] = dict(config.get("default_loot", {}))
            placed["item_loot"] = dict(config.get("default_item_loot", {}))

        self._objects.append(placed)
        self._index_object(placed)
        self.objects_version += 1

        return True

    def get_object_at(self, grid_x, grid_y):
        """The object whose footprint (OBJECT_TYPES[type]["size"]) covers this
        cell -- not just its origin, so a 2-wide "wall" is found from either
        cell it occupies. O(1) via _cell_index rather than a linear scan --
        this is the hottest call in the collision path (is_cell_walkable, up
        to 4 corners x every entity x every frame), so an O(n) scan here
        multiplied badly with entity count. If more than one object covers
        this cell (a door placed on/under a decorative wall object, see
        __init__), returns the most recently placed/moved one -- the stack's
        last entry."""
        stack = self._cell_index.get((grid_x, grid_y))
        return stack[-1] if stack else None

    def is_chest(self, object_type):
        """True for a chest-like type (currently just lilchest) -- its
        indicator dot (drawn/hit-tested via is_linkable, which chest types
        also set) opens ChestPanelUI in Creator instead of starting a
        link-drag; see Creator's indicator-click handler."""
        return OBJECT_TYPES[object_type].get("chest", False)

    def is_linkable(self, object_type):
        return OBJECT_TYPES[object_type].get("linkable", False)

    def is_es_type(self, object_type):
        """True for gate/wall/cave_entrance/big_entrance, OR a custom type
        registered with the "porte" archetype (config["is_es"], see
        _build_visual_fields) -- the object kinds that carry a role
        (get_role/set_role below, both already call this rather than
        ES_TYPES directly, so they pick up custom E/S types for free) and
        that core.world.assembly's generator can treat as a room-to-room
        connector (assembly._valid_entry_exits also calls this). Used by
        Creator's right-click role-picker dispatch, and by
        _resolve_placement's doorway-shape validation below."""
        if object_type in ES_TYPES:
            return True
        return bool(OBJECT_TYPES.get(object_type, {}).get("is_es"))

    def get_role(self, obj):
        """The object's role -- "connector"/"dungeon_entrance"/
        "dungeon_exit" for an E/S, "loot"/"dungeon_exit" for a chest.
        Missing "role" key (every object placed before this system
        existed, or a fresh default placement) reads as that kind's
        default -- "connector" for an E/S, "loot" for a chest -- so old
        saves need no migration. Object kinds with no role concept at all
        just get None."""
        role = obj.get("role")
        if role is not None:
            return role
        if self.is_es_type(obj["type"]):
            return "connector"
        if self.is_chest(obj["type"]):
            return "loot"
        return None

    def set_role(self, obj, role):
        """Assigns a role, validated against the allowed set for this
        object's kind (ES_ROLES/CHEST_ROLES) -- an invalid value (not
        offered by the editor UI, but this is also the one place a future
        network-facing admin command would come through) is silently
        ignored rather than corrupting the object dict. Returns True if
        the role was actually applied."""
        if self.is_es_type(obj["type"]):
            allowed = ES_ROLES
        elif self.is_chest(obj["type"]):
            allowed = CHEST_ROLES
        else:
            return False
        if role not in allowed:
            return False
        obj["role"] = role
        return True

    def is_foreground_object(self, obj):
        """Drawn after (in front of) the player, and walkable despite sitting on a WALL cell -- currently just L/R wall-mounted torches; a straight torch stays a plain blocking wall decoration. (A pillar's decorative top half gets the same front-of-player treatment, but it isn't a real object -- see WorldRenderer._draw_pillar_tops -- so it never reaches this method. A custom type with per-cell "cell_modes" -- see cell_mode/WorldRenderer._draw_objects -- decides front/back PER CELL instead of through this whole-object check.) Reads the placed object's own type's "foreground_variants" (see torch's own OBJECT_TYPES entry) rather than hardcoding `obj["type"] == "torch"` -- any card whose variant is listed there gets this treatment, not just one specific id (2026-08-20)."""
        config = OBJECT_TYPES.get(obj["type"], {})
        return obj.get("variant") in config.get("foreground_variants", ())

    def cell_mode(self, obj, config, grid_x, grid_y):
        """The CELL_MODES value ("block"/"behind"/"front") for (grid_x,
        grid_y) within `obj`'s footprint, or None if this type has no
        per-cell data at all (every built-in type, and any custom type
        registered with the plain blocks_movement flag instead) -- callers
        fall back to the whole-object blocks_movement/is_foreground_object
        checks in that case. Cells outside the declared grid (shouldn't
        happen) read as "behind" -- walkable, normal draw order, the least
        surprising fail-open."""
        cell_modes = config.get("cell_modes")
        if cell_modes is None:
            return None
        dx, dy = grid_x - obj["x"], grid_y - obj["y"]
        if 0 <= dy < len(cell_modes) and 0 <= dx < len(cell_modes[dy]):
            return cell_modes[dy][dx]
        return "behind"

    def is_cell_walkable(self, grid_x, grid_y):
        if not self._in_bounds(grid_x, grid_y):
            return False

        obj = self.get_object_at(grid_x, grid_y)

        if obj is not None:
            config = OBJECT_TYPES[obj["type"]]

            # Per-cell override (custom types only, see
            # _build_mechanics_fields) -- a multi-cell object's footprint
            # can mix blocking/walkable cells (e.g. a pillar-like object
            # with a walkable top row, blocking base row), instead of the
            # single whole-object blocks_movement/walkable flags below
            # applying uniformly. Absent on every built-in type, so this
            # branch is simply never reached for them -- fully additive.
            cell_mode = self.cell_mode(obj, config, grid_x, grid_y)
            if cell_mode is not None:
                if cell_mode == "block" and config.get("blocks_until_open"):
                    # A "block" cell on a lockable custom "porte" follows the
                    # same open/closed state as any other blocks_until_open
                    # object instead of being permanently solid -- note this
                    # is independent of which cell is the object's actual
                    # placement anchor (see _anchor_cell): the player can
                    # mark ANY cell(s) "block" here, whether or not that's
                    # also the anchor. A "block" cell_mode on a plain
                    # decorative object (no blocks_until_open) stays
                    # permanently solid as before.
                    return obj.get("open", False)
                return cell_mode != "block"

            if config.get("blocks_movement"):
                return False

            if config.get("blocks_until_open"):
                return obj.get("open", False)

            if config.get("walkable"):
                return True

        return self.dungeon.logical_grid[grid_y][grid_x] != WALL

    def _activate_button(self, obj):
        """Marks `obj` (a "button") pressed -- starts its own animation and
        plays the trigger sound. Shared by check_button_trigger and
        DungeonAssembly.check_button_trigger, which both trigger a button
        but scope "which object is at this cell" differently (a plain
        local lookup here vs. a room-aware global-coordinate lookup
        there) -- factored out after a past fix to this exact activation
        step only ever landed in one of the two copies."""
        obj["activated"] = True
        obj["frame"] = 0
        obj["anim_timer"] = 0.0
        self.begin_animation(obj)
        config = OBJECT_TYPES[obj["type"]]
        play_card_sound(
            config.get("sounds", {}), "interact", fallback_event="button_pressed",
            pitch_range=config.get("sound_pitch", {}).get("interact"),
        )

    @staticmethod
    def _open_if_blocking(target, object_manager):
        """Opens `target` (a blocks_until_open object, e.g. a linked gate/
        wall) if it isn't already -- `object_manager` is whichever
        ObjectManager actually owns `target` (not necessarily the one this
        was called on), since a cross-room assembly_link's target lives in
        a different room's own Dungeon/ObjectManager entirely."""
        if target is not None and OBJECT_TYPES[target["type"]].get("blocks_until_open") and not target.get("open"):
            target["open"] = True
            target["frame"] = 0
            target["anim_timer"] = 0.0
            object_manager.begin_animation(target)

    def check_button_trigger(self, grid_x, grid_y):
        """Call every frame the player occupies (grid_x, grid_y); no-ops unless a fresh button is there."""
        obj = self.get_object_at(grid_x, grid_y)

        if obj is None or obj["type"] != "button" or obj.get("activated"):
            return

        self._activate_button(obj)

        for link_target in obj.get("links", []):
            target = self.get_object_at(link_target["x"], link_target["y"])
            self._open_if_blocking(target, self)

    def update(self, dt):
        """Advance animation for any currently-animating object (see
        begin_animation), holding on its last frame once reached and
        dropping out of _animating right then -- iterates only that set
        instead of every placed object, since most of a room's objects are
        never activated/open at all and the ones that are eventually finish
        and stop needing per-frame work."""
        finished_ids = []

        for object_id, obj in self._animating.items():
            last_frame = OBJECT_TYPES[obj["type"]]["frames"] - 1
            frame = obj.get("frame", 0)

            if frame >= last_frame:
                finished_ids.append(object_id)
                continue

            timer = obj.get("anim_timer", 0.0) + dt

            while timer >= self.ANIM_SPEED and frame < last_frame:
                timer -= self.ANIM_SPEED
                frame += 1

            obj["frame"] = frame
            obj["anim_timer"] = timer

            if frame >= last_frame:
                finished_ids.append(object_id)

        for object_id in finished_ids:
            del self._animating[object_id]

    def link(self, obj_a, obj_b):
        """Symmetric link between two linkable objects (e.g. a button and the gate/wall it opens)."""
        if obj_a is obj_b:
            return

        a_target = {"x": obj_b["x"], "y": obj_b["y"]}
        b_target = {"x": obj_a["x"], "y": obj_a["y"]}

        a_links = obj_a.setdefault("links", [])
        if a_target not in a_links:
            a_links.append(a_target)

        b_links = obj_b.setdefault("links", [])
        if b_target not in b_links:
            b_links.append(b_target)

    def move_object(self, obj, grid_x, grid_y):
        """Reposition an already-placed object. Returns True if the new cell was valid.

        A "direction_mode"="auto" object's direction is recomputed here
        just like its variant already is (torch's own L/R already worked
        this way) -- but a "manual" one's obj["direction"] is left
        completely untouched (auto_direction comes back None for those,
        see _resolve_placement), so dragging an already-placed bench
        elsewhere never spins it back to some wall-adjacency guess."""
        if not self._in_bounds(grid_x, grid_y):
            return False

        valid, variant, auto_direction = self._resolve_placement(obj["type"], grid_x, grid_y)
        if not valid:
            return False

        self._deindex_object(obj)

        old_x, old_y = obj["x"], obj["y"]
        obj["x"], obj["y"] = grid_x, grid_y

        if variant is not None:
            obj["variant"] = variant
        else:
            obj.pop("variant", None)

        if auto_direction is not None:
            obj["direction"] = auto_direction

        self._index_object(obj)
        self.objects_version += 1

        self._retarget_links(old_x, old_y, grid_x, grid_y)

        return True

    def _retarget_links(self, old_x, old_y, new_x, new_y):
        for obj in self.objects:
            for link_target in obj.get("links", []):
                if link_target["x"] == old_x and link_target["y"] == old_y:
                    link_target["x"], link_target["y"] = new_x, new_y

    def _anchor_cell(self, object_type, grid_x, grid_y):
        """The single footprint cell a placement actually validates its
        terrain against -- bottom-center of the object's own "size", not
        its stored (grid_x, grid_y) origin (always the top-left corner, see
        _footprint_cells_of). Confirmed with the user: every OTHER cell of a
        multi-cell footprint is free to land on anything at all (a wall,
        void, another object's territory) without blocking placement -- purely
        a visual overlap onto whatever's already there, drawn front/behind
        the player exactly as its own cell_modes entry says (unaffected by
        this -- cell_modes still independently decides walkability/draw
        order per cell, see is_cell_walkable/cell_mode). This is what lets a
        tall object (a multi-cell custom "porte", a tree...) stand with its
        base against a wall while its upper cells visually overlap the wall
        above it, instead of that overlap rejecting the placement outright.
        For a 1x1 object this is just (grid_x, grid_y) -- identical to
        before for the overwhelming majority of existing types, built-in or
        custom."""
        size_x, size_y = OBJECT_TYPES[object_type]["size"]
        return grid_x + (size_x - 1) // 2, grid_y + size_y - 1

    def origin_for_anchor(self, object_type, anchor_x, anchor_y):
        """Inverts _anchor_cell: given the grid cell the player is actually
        pointing at (which placement/move validates against -- see
        _anchor_cell's own docstring), returns the (grid_x, grid_y) origin
        (top-left) add_object/move_object expect. Lets a caller (Creator's
        placement-drag/move-drag) work entirely in "where the cursor is"
        terms instead of separately reasoning about the footprint's
        top-left corner -- before this, the cursor's own grid cell was
        used directly AS the origin, so for anything wider/taller than
        1x1 the cell that actually got terrain-validated (_anchor_cell,
        bottom-center of THAT origin) landed size_x/size_y cells away from
        wherever the player was actually pointing, e.g. a multi-cell door
        failing to "see" the exact wall cell it was being visually aimed
        at."""
        size_x, size_y = OBJECT_TYPES[object_type]["size"]
        return anchor_x - (size_x - 1) // 2, anchor_y - (size_y - 1)

    def _resolve_placement(self, object_type, grid_x, grid_y):
        """Returns (is_valid, variant, direction) for placing/moving
        object_type at this cell. `direction` is only ever non-None for a
        "direction_mode"="auto" type (see _build_mechanics_fields) --
        a "manual" one's direction comes from the caller (add_object's own
        `direction` param), never computed here."""
        if object_type == "torch":
            variant = self._torch_variant(grid_x, grid_y)
            if variant is not None:
                return True, variant, None
            if self.dungeon.logical_grid[grid_y][grid_x] == WALL:
                return True, None, None
            return False, None, None

        if self.is_es_type(object_type):
            return self._valid_wall_break_anchor(object_type, grid_x, grid_y), None, None

        if object_type == "stairs":
            is_valid, variant = self._stairs_orientation(grid_x, grid_y)
            return is_valid, variant, None

        config = OBJECT_TYPES[object_type]
        direction = None
        if config.get("direction_mode") == "auto" and config.get("directions"):
            direction = self._auto_wall_direction(object_type, grid_x, grid_y)

        anchor_x, anchor_y = self._anchor_cell(object_type, grid_x, grid_y)
        if not self._in_bounds(anchor_x, anchor_y):
            return False, None, None
        is_valid = self.dungeon.logical_grid[anchor_y][anchor_x] == self._required_cell(object_type)
        return is_valid, None, direction

    def _stairs_orientation(self, grid_x, grid_y):
        """(is_valid, variant) for stairs: valid directly on a FLOOR cell (no
        flip -- an ordinary interior placement), or on an EMPTY cell that has
        at least one FLOOR neighbor (a room's void-facing edge) -- "flip"
        mirrors the single stairs.png asset horizontally when that floor
        neighbor is specifically to the west, so it visually faces back
        toward the room regardless of which side of it the floor is on."""
        cell = self.dungeon.logical_grid[grid_y][grid_x]
        if cell == FLOOR:
            return True, None
        if cell != EMPTY:
            return False, None

        if grid_x > 0 and self.dungeon.logical_grid[grid_y][grid_x - 1] == FLOOR:
            return True, "flip"

        for nx, ny in ((grid_x + 1, grid_y), (grid_x, grid_y - 1), (grid_x, grid_y + 1)):
            if self._in_bounds(nx, ny) and self.dungeon.logical_grid[ny][nx] == FLOOR:
                return True, None

        return False, None

    def _torch_variant(self, grid_x, grid_y):
        """L/R variant for a torch on a floor cell with an adjacent wall: wall to the right -> R, wall to the left -> L. None if this isn't a valid floor-beside-a-wall spot."""
        if self.dungeon.logical_grid[grid_y][grid_x] != FLOOR:
            return None
        if grid_x + 1 < self.dungeon.width and self.dungeon.logical_grid[grid_y][grid_x + 1] == WALL:
            return "R"
        if grid_x > 0 and self.dungeon.logical_grid[grid_y][grid_x - 1] == WALL:
            return "L"
        return None

    # (NPC_DIRECTIONS key, dx, dy) for each of the 4 cardinal sides a
    # "direction_mode"="auto" object's own `directions` (see
    # _build_visual_fields) might have tagged -- _auto_wall_direction
    # below. Only the 4 cardinal keys make sense for a flat wall-mounted
    # decor (the other 4 NPC_DIRECTIONS values are diagonals, meaningless
    # against a straight wall segment).
    _AUTO_DIRECTION_WALL_ADJACENCY = (
        ("right", 1, 0),
        ("left", -1, 0),
        ("back", 0, -1),
        ("front", 0, 1),
    )

    def _auto_wall_direction(self, object_type, grid_x, grid_y):
        """"direction_mode"="auto" placement (see _build_mechanics_fields):
        a generalization of _torch_variant's original L/R-only rule to
        every direction the type's own `directions` actually has tagged.
        Valid on a FLOOR cell with a WALL immediately on one of its 4
        cardinal sides -- returns whichever of "right"/"left"/"back"/
        "front" that side maps to, but only if THIS type has that specific
        direction tagged (skips a side it doesn't cover, checked in a
        fixed right/left/back/front order so a corner spot with two
        candidate walls picks deterministically). None if no adjacent-wall
        side matches a tagged direction at all -- _resolve_placement's own
        caller then falls back to this type's ordinary floor/wall
        placement check with no direction resolved."""
        if self.dungeon.logical_grid[grid_y][grid_x] != FLOOR:
            return None
        tagged = OBJECT_TYPES[object_type].get("directions") or {}
        for direction, dx, dy in self._AUTO_DIRECTION_WALL_ADJACENCY:
            if direction not in tagged:
                continue
            nx, ny = grid_x + dx, grid_y + dy
            if self._in_bounds(nx, ny) and self.dungeon.logical_grid[ny][nx] == WALL:
                return direction
        return None

    def _cell_or_empty(self, grid_x, grid_y):
        if self._in_bounds(grid_x, grid_y):
            return self.dungeon.logical_grid[grid_y][grid_x]
        return EMPTY

    def is_valid_doorway(self, grid_x, grid_y):
        """True if (grid_x, grid_y) is a WALL cell that reads as a clean break in a
        straight wall segment: exactly one FLOOR neighbor (the room interior)
        directly opposite exactly one EMPTY neighbor (the void beyond), with
        WALL flanking the other two sides. Off-grid neighbors count as EMPTY.

        This is the procedural assembler's (core.world.assembly) own
        question -- "is this gate/wall a genuine room-to-room connector" --
        NOT the placement-time question of "can a door go here" (that's
        is_valid_wall_break below, deliberately a looser check). A
        gate/wall satisfying is_valid_wall_break but not this -- an
        interior door with floor (or another decoration) on both sides,
        no void neighbor -- simply never gets picked as a connection by
        the assembler; it still works as an ordinary in-room/decorative
        door.
        """
        if not self._in_bounds(grid_x, grid_y):
            return False
        if self.dungeon.logical_grid[grid_y][grid_x] != WALL:
            return False

        up = self._cell_or_empty(grid_x, grid_y - 1)
        down = self._cell_or_empty(grid_x, grid_y + 1)
        left = self._cell_or_empty(grid_x - 1, grid_y)
        right = self._cell_or_empty(grid_x + 1, grid_y)

        if {up, down} == {FLOOR, EMPTY}:
            return left == WALL and right == WALL
        if {left, right} == {FLOOR, EMPTY}:
            return up == WALL and down == WALL
        return False

    def is_valid_wall_break(self, grid_x, grid_y):
        """True if (grid_x, grid_y) is a WALL cell sitting in a clean,
        1-cell-thick wall segment -- WALL flanking the two perpendicular
        sides, with FLOOR on at least one of the two opposite sides (so the
        door actually borders a walkable room instead of floating inside
        solid interior wall with no floor anywhere nearby). This is
        placement's own permissive rule for "can a door/gate go here" --
        unlike is_valid_doorway, it does NOT require a void on the other
        side, so a door can sit on any straight wall, including an interior
        one (e.g. framed by a purely decorative multi-cell wall object like
        "bordureporte" -- nothing here checks for an existing object on the
        cell, since placement never has, see add_object). Simplified from
        is_valid_doorway on 2026-08-18 after that stricter rule turned out
        to block exactly this case; see is_valid_doorway's own docstring
        for why that stricter shape still exists separately, for the
        assembler."""
        if not self._in_bounds(grid_x, grid_y):
            return False
        if self.dungeon.logical_grid[grid_y][grid_x] != WALL:
            return False

        up = self._cell_or_empty(grid_x, grid_y - 1)
        down = self._cell_or_empty(grid_x, grid_y + 1)
        left = self._cell_or_empty(grid_x - 1, grid_y)
        right = self._cell_or_empty(grid_x + 1, grid_y)

        if FLOOR in (up, down):
            return left == WALL and right == WALL
        if FLOOR in (left, right):
            return up == WALL and down == WALL
        return False

    def _valid_doorway_anchor(self, object_type, grid_x, grid_y):
        """True if `object_type`'s own anchor cell (see _anchor_cell) is a
        valid is_valid_doorway break -- used by the procedural assembler
        (core.world.assembly) to decide whether a placed E/S is usable as a
        room-to-room connector, NOT by placement itself anymore (see
        _valid_wall_break_anchor)."""
        anchor_x, anchor_y = self._anchor_cell(object_type, grid_x, grid_y)
        return self.is_valid_doorway(anchor_x, anchor_y)

    def _valid_wall_break_anchor(self, object_type, grid_x, grid_y):
        """Placement-time counterpart to _valid_doorway_anchor: True if
        `object_type`'s own anchor cell (see _anchor_cell) is a valid
        is_valid_wall_break -- the ONLY cell of a multi-cell E/S's
        footprint that placement validates; every other cell is free to
        overlap anything (a wall, void, another decoration...) without
        blocking placement, see _anchor_cell's own docstring for why. The
        autotiled walls this game generates are only ever ONE cell thick,
        so a door taller/wider than 1 cell in the direction perpendicular
        to the wall could never find a second WALL cell to independently
        validate against there (that second cell is the room's own
        interior FLOOR) -- checking only the anchor is what makes a
        multi-cell custom "porte" placeable at all."""
        anchor_x, anchor_y = self._anchor_cell(object_type, grid_x, grid_y)
        return self.is_valid_wall_break(anchor_x, anchor_y)

    def prune_invalid(self):
        """Drop objects whose underlying cell no longer matches their placement rule (e.g. the floor/wall they sat on got erased), and any links left dangling by that.

        Called unconditionally after every single Dungeon.paint_cell edit
        (potentially dozens of times a second during a drag-paint stroke),
        so the overwhelmingly common case -- nothing near the painted cell
        actually needed pruning -- must stay cheap. `filtered` is always a
        subset of self._objects (a plain filter, nothing added/reordered),
        so equal lengths means nothing was removed; only then is it worth
        going through the `objects` property setter, which unconditionally
        rebuilds the cell index/animating set and bumps objects_version
        (invalidating WorldRenderer's doorway/spawn/pillar cache) even when
        the list it's assigned is identical to what's already there."""
        filtered = [
            obj for obj in self.objects
            if self._resolve_placement(obj["type"], obj["x"], obj["y"])[0]
        ]
        if len(filtered) != len(self._objects):
            self.objects = filtered

        existing = {(obj["x"], obj["y"]) for obj in self.objects}
        for obj in self.objects:
            if "links" not in obj:
                continue
            obj["links"] = [
                link_target for link_target in obj["links"]
                if (link_target["x"], link_target["y"]) in existing
            ]
            if not obj["links"]:
                del obj["links"]

    def _required_cell(self, object_type):
        return FLOOR if OBJECT_TYPES[object_type]["placement"] == "floor" else WALL
