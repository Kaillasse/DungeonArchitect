import json
from pathlib import Path

import pygame

from core.editor.autotile import EMPTY, FLOOR, WALL
from core.data.ressources import DEFAULT_ANIM_SPEED, load_tileset_region
from core.data.sound_manager import play_card_sound

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Python-sourced seed data only. The live registry (OBJECT_TYPES, below the
# custom-type merge machinery) layers custom types + per-builtin mechanics
# overrides on top of this dict without ever mutating it.
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
        # "interact" is the trigger sound (see ObjectManager.check_button_trigger).
        "sounds": {"interact": "buttonpressed.wav"},
    },
    "gate": {
        "asset": "tiles/gateopenclose.png",
        # Custom placement ("doorway", not floor/wall): must sit on a WALL cell
        # that's a clean break in a straight wall segment -- one FLOOR neighbor
        # opposite one EMPTY neighbor, WALL flanking the other two sides (see
        # ObjectManager.is_valid_doorway). Makes a doorway unambiguous for both
        # the player and the procedural assembler (core.world.assembly).
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
        # "wall" is the fallback/default variant's placement. L/R variants use
        # custom placement (_resolve_placement/_torch_variant): on a FLOOR cell
        # with a WALL immediately beside it -- side-wall mounted, walkable and
        # drawn in front of the player (is_foreground_object), unlike the flat one.
        "placement": "wall",
        "size": (1, 1),
        "frames": 8,
        "variants": {
            "L": "tiles/Torch Yellow L.png",
            "R": "tiles/Torch Yellow R.png",
        },
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
    # chicken/cow/pig/sheep: no aggro/attack_range, never fight back, but
    # damageable/killable via "stats". No "loot_cards" needed -- the implicit
    # "1 copy of its own card" default (effective_loot_cards) covers it.
    "chicken": {
        "asset": "characters/Animals/Chicken.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 2,
        "frame_size": 32,
        "mob": True,
        "card_type": "mob",
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
        "stats": {"health": 2},
    },
    "skeleton1": {
        # "asset" is just the idle sheet, for the static editor palette icon --
        # live combat reads the full idle/movement/attack/damaged/death set via
        # load_enemy_frames (ENEMY_ANIMATION_FILES below).
        "asset": "characters/Ennemies/skeleton1/idle.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 6,
        "frame_size": 32,
        "mob": True,
        "card_type": "mob",
        # active_attack_frames (0-based) is the window a swing actually deals
        # damage. "loot" (currency->count) is read once on death. Real-item
        # drops go through "loot_cards" below instead of a sibling "item_loot" key.
        "stats": {
            "health": 3, "move_speed": 45, "aggro_range": 6.0, "attack_range": 1.2,
            # List, not tuple: MechanicsPanelUI round-trips this through JSON
            # (no tuple type there), so builtin vs. persisted-override compare equal.
            "active_attack_frames": [6, 7],
            "loot": {"gold": 2, "blue": 1},
        },
        # Explicit rather than effective_loot_cards' implicit default, to
        # preserve skeleton1's old dynamite drop.
        "loot_cards": {"skeleton1": 1, "dynamite": 1},
        # attack/damaged sounds; "death" is wired via Explorator._resolve_player_attacks
        # but has no default asset. idle/movement have no trigger (looping ambience).
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
        # skeleton2 has a different attack frame count (15); window derived from
        # skeleton1's relative position (~75%-87% through the swing).
        "stats": {
            "health": 3, "move_speed": 45, "aggro_range": 6.0, "attack_range": 1.2,
            "active_attack_frames": [11, 12],  # list, not tuple -- see skeleton1
            "loot": {"gold": 2, "blue": 1},
        },
        "sounds": {"attack": "skel2attack.wav", "damaged": "skeldamaged.wav"},
    },
    "stairs": {
        # Cropped once from basictileset.png frame 26 into its own file, to keep
        # load_object_frames' one-sheet-per-type convention. Custom placement
        # (_stairs_orientation): valid on FLOOR, or on EMPTY with a FLOOR
        # neighbor (room's void edge) -- variant "flip" mirrors the sprite when
        # that neighbor is specifically west.
        "asset": "tiles/stairs.png",
        "placement": "stairs",
        "size": (1, 1),
        "frames": 1,
        "card_type": "tile_special",
    },
    "cave_entrance": {
        # basictileset.png frame 27. Same doorway shape as gate/wall
        # (is_valid_doorway) but always open: no linkable/blocks_until_open,
        # just "walkable" -- a level-exit marker, not a lockable door.
        "asset": "tiles/cave_entrance.png",
        "placement": "doorway",
        "size": (1, 1),
        "frames": 1,
        "walkable": True,
        "card_type": "tile_special",
    },
    "big_entrance": {
        # basictileset.png frames 17+23 composed side-by-side into one 32x16
        # static asset. "frames": 1 with a non-square asset -- see
        # load_object_frames' whole-image branch. A real functional E/S (role
        # system): same doorway validity as gate/wall (checked off its origin
        # cell only), always open like cave_entrance.
        "asset": "tiles/big_entrance.png",
        "placement": "doorway",
        "size": (2, 1),
        "frames": 1,
        "walkable": True,
        "card_type": "tile_special",
    },
    "pillar": {
        # basictileset.png frame 18 (base), placed on FLOOR like "vase". Its
        # "top" half (frame 12, via "variants") is NOT a second object --
        # WorldRenderer._draw_pillar_tops draws it purely decoratively one cell
        # north, every frame, skipped over a doorway, drawn front-of-player.
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
        # 4 columns x 2 rows: row 0 idle/closed, row 1 opening anim. "frames"
        # is the flat total (8) load_object_frames slices across both rows.
        # Explorator._interact_with_chest sets "open"=True, "frame"=4 (row 1
        # start) and ObjectManager.update's activated/open advance takes it
        # from there, holding on frame 7.
        "asset": "tiles/lilchest.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 8,
        "rows": 2,
        "frame_size": 16,
        "blocks_movement": True,
        "chest": True,
        # Reuses "linkable" dot rendering/hit-testing, but a chest's dot opens
        # ChestPanelUI instead of a link-drag -- see Creator's is_chest() check.
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
# ecrit, fusionne dans OBJECT_TYPES/OBJECT_LIST au chargement du module puis
# a chaque enregistrement (register_custom_type) -- meme esprit additif que
# CardManager, sans risque de collision (l'id n'est jamais deja pris).
# ---------------------------------------------------------------------

CUSTOM_OBJECT_TYPES_PATH = PROJECT_ROOT / "assets" / "tiles" / "custom_object_types.json"


def _load_custom_object_types():
    """Absent/vide/corrompu -> dict vide, meme tolerance que les autres loaders JSON optionnels."""
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
    """One-time migration: un ancien PNJ custom stockait "npc": True et parfois
    "card_type": "pnj" -- le registre unifie ne lit plus que "mob". Mutates
    `custom` in place, returns whether anything changed. Idempotent."""
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

# Mechanics keys (opt-in gameplay behavior) vs identity/visual keys
# (asset/placement/size/frames/name + archetype-implied flags). A builtin's
# mechanics can be overridden (a custom_object_types.json entry marked
# OVERRIDE_MARKER, holding ONLY these keys) without touching its Python-sourced
# visual identity.
MECHANICS_KEYS = (
    "blocks_movement", "cell_modes", "interactable", "capabilities", "stats", "effects", "sounds", "sound_pitch",
    "loot_cards",
)
DOORWAY_MECHANICS_KEYS = ("linkable", "blocks_until_open")
OVERRIDE_MARKER = "__override_of_builtin__"


def _derive_card_type(config):
    """Best-effort card_type for a custom_object_types.json entry saved before
    this field existed. "pnj" no longer exists as a card_type -- every
    wandering entity is a "mob"; dialogue-capability is the orthogonal
    "interactable" flag instead."""
    if config.get("mob"):
        return "mob"
    if config.get("is_es") or config.get("chest"):
        return "tile_special"
    return "tile_decor"


def _merge_builtin(type_id, override):
    """A builtin's own entry with its mechanics keys replaced by `override`'s
    (always a full MECHANICS_KEYS/DOORWAY_MECHANICS_KEYS snapshot, never a
    sparse diff, so a flag can be explicitly turned back off). None if type_id
    no longer names a real builtin."""
    base = _BUILTIN_OBJECT_TYPES.get(type_id)
    if base is None:
        return None
    merged = dict(base)
    for key in MECHANICS_KEYS:
        merged.pop(key, None)
    if base.get("placement") == "doorway":
        for key in DOORWAY_MECHANICS_KEYS:
            merged.pop(key, None)
    for key in MECHANICS_KEYS + DOORWAY_MECHANICS_KEYS:
        if key in override:
            merged[key] = override[key]
    return merged


def _merged_object_types():
    """The live registry: every builtin with any persisted mechanics override
    merged on top, plus every custom/NPC type as-is (card_type backfilled once if missing)."""
    merged = dict(_BUILTIN_OBJECT_TYPES)
    for type_id, entry in _custom_types.items():
        if entry.get(OVERRIDE_MARKER):
            result = _merge_builtin(type_id, entry)
            if result is not None:
                merged[type_id] = result
        else:
            entry = dict(entry)
            entry.setdefault("card_type", _derive_card_type(entry))
            merged[type_id] = entry
    return merged


OBJECT_TYPES = _merged_object_types()
OBJECT_LIST.extend(
    type_id for type_id, entry in _custom_types.items()
    if not entry.get(OVERRIDE_MARKER) and type_id not in OBJECT_LIST
)

# Archetypes proposes par l'editeur de sprite -- limites aux types a une seule
# region (pas de paire torche L/R, pas de pilier base+haut). "mur" n'a besoin
# d'aucun flag supplementaire (la case WALL bloque deja). "porte"
# (placement="doorway", is_es=True) obtient la vraie validation
# is_valid_doorway/eligibilite assembleur via is_es_type (plus bas).
ARCHETYPES = {
    "sol": {"label": "Sol", "placement": "floor", "flags": {}},
    "mur": {"label": "Mur", "placement": "wall", "flags": {}},
    "porte": {"label": "Porte", "placement": "doorway", "flags": {"walkable": True, "is_es": True}},
}

# Les 3 etats possibles d'une case dans un "cell_modes" : "block" est solide
# (non walkable) ; "behind" et "front" sont tous deux walkable, seul leur
# ordre de dessin differe (arriere = normal ; devant = par-dessus le joueur).
# Voir ObjectManager.is_cell_walkable/cell_mode et WorldRenderer._draw_objects.
CELL_MODES = ("block", "behind", "front")

# Toute cle qu'un preset ARCHETYPES peut poser (aujourd'hui juste "porte"'s
# walkable/is_es) -- cles d'identite/visuel, effacees puis reappliquees a
# chaque update_type_visual pour qu'un changement d'archetype ne laisse pas de
# flag trainer. Distinct de MECHANICS_KEYS/DOORWAY_MECHANICS_KEYS (toggles
# optionnels par instance) : ici, consequences permanentes de l'archetype.
_ARCHETYPE_FLAG_KEYS = tuple(sorted({key for preset in ARCHETYPES.values() for key in preset["flags"]}))


def _build_visual_fields(name, tileset, rect, size, archetype, frame_rects=None):
    """Construction pure des champs d'identite/visuel d'une entree OBJECT_TYPES
    custom -- asset/placement/size/frames/name + les flags d'archetype.
    Partagee par register_custom_type et update_type_visual.

    `frame_rects` (archetype "porte" seulement), si fourni, remplace le `rect`
    unique par une liste de rects -- une frame d'ouverture par entree, choisies
    individuellement dans l'editeur de sprite. Sans lui : un seul "rect", frames=1."""
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
    entry.update(preset["flags"])
    return entry


def _build_mechanics_fields(existing, blocks_movement=False, cell_modes=None,
                             interactable=False, lockable=False, capabilities=None, stats=None, effects=None,
                             sounds=None, sound_pitch=None, loot_cards=None):
    """Construction pure des champs mecaniques/gameplay d'une entree
    OBJECT_TYPES -- partagee par register_custom_type et update_type_mechanics
    (custom ET builtin). `cell_modes`, si fourni, prevaut sur `blocks_movement`
    (jamais les deux a la fois).

    `lockable` (seulement si placement=="doorway") ajoute linkable/
    blocks_until_open, comme gate/wall. `capabilities`/`effects`/`sounds`/
    `sound_pitch` sont le meme vocabulaire generique que ITEM_DEFINITIONS
    (voir update_item_overrides) -- l'appelant (MechanicsPanelUI) decide seul
    ce qu'il affiche pour quel type de carte. `stats` n'a de sens que pour un
    mob enemy aujourd'hui mais n'est deliberement pas restreint ici.

    `loot_cards` ({card_id: count}) est la table de butin-en-cartes
    (core.world.entities._spawn_loot_pickups). None = ne pas toucher a
    l'existant ; {} explicite = "ne drop rien" (distinct de "pas edite du tout")."""
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
    return fields


def _persist_custom_object_types(custom):
    CUSTOM_OBJECT_TYPES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CUSTOM_OBJECT_TYPES_PATH.open("w", encoding="utf-8") as handle:
        json.dump(custom, handle, indent=2, ensure_ascii=False)


def _write_custom_type(type_id, entry):
    """Ecrit `entry` dans custom_object_types.json (fusionne, pas remplace) et
    met a jour OBJECT_TYPES/OBJECT_LIST en memoire immediatement. Backfille
    card_type si absent, sauf pour un override de builtin (OVERRIDE_MARKER)."""
    if not entry.get(OVERRIDE_MARKER):
        entry = dict(entry)
        entry.setdefault("card_type", _derive_card_type(entry))

    custom = _load_custom_object_types()
    custom[type_id] = entry
    _persist_custom_object_types(custom)

    OBJECT_TYPES[type_id] = entry
    if type_id not in OBJECT_LIST:
        OBJECT_LIST.append(type_id)


def _write_builtin_mechanics_override(type_id, mechanics_fields):
    """Persiste `mechanics_fields` comme override d'un builtin -- jamais le
    fragment brut en memoire, toujours la version fusionnee via _merge_builtin.

    L'override n'est retire que si `mechanics_fields` correspond EXACTEMENT
    aux valeurs codees en dur sur le builtin -- jamais juste "est vide" : un
    builtin comme "gate" (blocks_until_open=True en dur) produit un
    `mechanics_fields` vide quand l'utilisateur DESACTIVE ce flag ; confondre
    "vide" avec "aucun changement" ignorerait silencieusement la desactivation."""
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
    defaut du builtin -- distinct de delete_custom_type, impossible sur un builtin."""
    if type_id not in _BUILTIN_OBJECT_TYPES:
        raise ValueError(f"'{type_id}' n'est pas un type integre au jeu")
    custom = _load_custom_object_types()
    if custom.pop(type_id, None) is None:
        return
    _persist_custom_object_types(custom)
    OBJECT_TYPES[type_id] = dict(_BUILTIN_OBJECT_TYPES[type_id])


def register_custom_type(
    type_id, name, tileset, rect, size, archetype, blocks_movement=False, cell_modes=None,
    interactable=False, lockable=False, frame_rects=None,
):
    """Valide et persiste une NOUVELLE entree OBJECT_TYPES sourcee depuis une
    region de tileset (SpriteEditorPanelUI, mode creation -- voir
    update_custom_type pour l'edition). Leve ValueError sur id/archetype invalide ou deja pris."""
    if not type_id or not all(c.isalnum() or c == "_" for c in type_id):
        raise ValueError("Identifiant invalide (lettres/chiffres/_ uniquement)")
    if type_id in OBJECT_TYPES:
        raise ValueError(f"'{type_id}' existe deja")
    entry = _build_visual_fields(name, tileset, rect, size, archetype, frame_rects)
    entry.update(_build_mechanics_fields(entry, blocks_movement, cell_modes, interactable, lockable))
    _write_custom_type(type_id, entry)
    return entry


def update_type_visual(type_id, name, tileset, rect, size, archetype, frame_rects=None):
    """Edite UNIQUEMENT l'identite/visuel d'une carte custom DEJA enregistree
    (jamais un type integre, identifie par la forme dict de son "asset").
    Les cles mecaniques deja presentes survivent intactes -- seules les cles
    de _ARCHETYPE_FLAG_KEYS sont effacees puis reappliquees."""
    existing = OBJECT_TYPES.get(type_id)
    if existing is None:
        raise ValueError(f"'{type_id}' n'existe pas")
    if not isinstance(existing.get("asset"), dict):
        raise ValueError(f"'{type_id}' est un type integre au jeu, non modifiable")
    entry = dict(existing)
    for key in _ARCHETYPE_FLAG_KEYS:
        entry.pop(key, None)
    entry.update(_build_visual_fields(name, tileset, rect, size, archetype, frame_rects))
    _write_custom_type(type_id, entry)
    return entry


def update_type_mechanics(type_id, blocks_movement=False, cell_modes=None,
                           interactable=False, lockable=False, capabilities=None, stats=None, effects=None,
                           sounds=None, sound_pitch=None, loot_cards=None):
    """Edite UNIQUEMENT les mecaniques/gameplay d'un type DEJA enregistre --
    contrairement a update_type_visual, marche sur N'IMPORTE QUEL type,
    builtin OU custom (le point d'entree qui rend un builtin editable sans
    toucher son identite visuelle -- voir _write_builtin_mechanics_override).
    Efface d'abord les cles mecaniques existantes (jamais un merge naif)."""
    existing = OBJECT_TYPES.get(type_id)
    if existing is None:
        raise ValueError(f"'{type_id}' n'existe pas")
    fields = _build_mechanics_fields(
        existing, blocks_movement, cell_modes, interactable, lockable, capabilities, stats, effects, sounds,
        sound_pitch, loot_cards,
    )
    if not isinstance(existing.get("asset"), dict):
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
    interactable=False, lockable=False, frame_rects=None,
):
    """Alias de compatibilite -- combine update_type_visual + update_type_mechanics
    en un seul appel. SpriteEditorPanelUI continue de l'appeler tel quel."""
    update_type_visual(type_id, name, tileset, rect, size, archetype, frame_rects)
    return update_type_mechanics(type_id, blocks_movement, cell_modes, interactable, lockable)


def delete_custom_type(type_id):
    """Supprime definitivement une carte custom OU un type de PNJ (meme
    stockage -- register_npc_type/update_npc_type passent aussi par
    _write_custom_type) : retire du JSON et de OBJECT_TYPES/OBJECT_LIST.
    Jamais un type integre. N'a AUCUNE idee de si ce type est encore place
    quelque part -- a l'appelant (core.data.ressources.type_references) de verifier."""
    existing = OBJECT_TYPES.get(type_id)
    if existing is None:
        raise ValueError(f"'{type_id}' n'existe pas")
    if not isinstance(existing.get("asset"), dict):
        raise ValueError(f"'{type_id}' est un type integre au jeu, non supprimable")

    custom = _load_custom_object_types()
    custom.pop(type_id, None)
    _persist_custom_object_types(custom)

    del OBJECT_TYPES[type_id]
    if type_id in OBJECT_LIST:
        OBJECT_LIST.remove(type_id)


def find_custom_type_by_source(tileset, rect):
    """L'id de la carte custom dont le rect source correspond exactement a
    (tileset, rect), ou None -- permet a l'editeur de sprite de proposer une
    edition plutot qu'un doublon. Matche soit le "rect" singulier d'une carte
    a 1 frame, soit tout element du "rects" pluriel d'une porte multi-frame."""
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
    """(type_id, config) pour chaque carte custom sourcee depuis `tileset` --
    alimente la liste "cartes existantes" de SpriteEditorPanelUI."""
    return [
        (candidate_id, config) for candidate_id, config in OBJECT_TYPES.items()
        if isinstance(config.get("asset"), dict) and config["asset"].get("tileset") == tileset
    ]


# Object types backed by a live, wandering entity (core.world.entities.Mob)
# during exploration rather than just a static placed sprite -- derived from
# the "mob" flag, not a separately-maintained list.
#
# A FUNCTION, not a frozen tuple: a mob type registered via register_npc_type
# is created entirely in-session via the sprite editor, so freezing at import
# would silently miss anything registered after. Call fresh each use.
def mob_types():
    return tuple(name for name, config in OBJECT_TYPES.items() if config.get("mob"))

# The 8 compass directions an entity pack's regions get tagged with -- same
# vocabulary as core.world.entities.Player.DIRECTION_VECTORS, so there's only
# ever one direction naming scheme in this codebase.
NPC_DIRECTIONS = ("front", "front_right", "right", "back_right", "back", "back_left", "left", "front_left")

# Object types that function as an entry/exit (doorway between rooms, or a
# room's void edge) -- what get_role/set_role accept a role for, and what
# core.world.assembly's generator treats as a possible room-to-room connector.
ES_TYPES = ("gate", "wall", "cave_entrance", "big_entrance")

# Allowed "role" values per object kind -- an E/S (ES_TYPES) or a chest
# (is_chest()). Each kind's first entry is its default when a placed object
# carries no "role" key (old saves) -- exactly today's pre-role behavior.
ES_ROLES = ("connector", "dungeon_entrance", "dungeon_exit")
CHEST_ROLES = ("loot", "dungeon_exit")

# Each enemy type has its own assets/characters/Ennemies/<folder>/ directory
# with one fixed-name sheet per animation (idle/movement/attack/damaged/death.png).
ENEMY_FOLDERS = {
    "skeleton1": "skeleton1",
    "skeleton2": "skeleton2",
}
ENEMY_ANIMATIONS = ("idle", "movement", "attack", "damaged", "death")

# Currency pickup sheets: two rows of 16x16 frames -- row 0 idle "spin" loop,
# row 1 plays once on pickup (core.world.entities.Pickup). Shared by
# InventoryPanel's counter icon ("spin" only) and Pickup.
CURRENCY_FILES = {"gold": "item/Coin Sheet.png", "blue": "item/BlueCoin Sheet.png"}
CURRENCY_FRAME_SIZE = 16


_currency_frames_cache = {}


def load_currency_frames(currency_type):
    """Returns {"spin": [...], "collect": [...]}, each a list of 16x16 frames.
    Cached by currency_type. Frames are read-only, so sharing Surfaces across
    every Pickup of this currency_type is safe."""
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


# Real inventory items (vs. currency, see CURRENCY_FILES). Each entry serves
# both a ground ItemPickup's icon and an InventoryPanel slot's icon (same
# "icon_rect" crop, see Item.get_icon), plus its main_slots key. "capabilities"
# ({"throwable": {...}, "explosive": {...}, ...}) is the same vocabulary as a
# world-object's own optional "capabilities" (_build_mechanics_fields), read
# generically by Explorator._use_interact_item/ProjectileManager. "effects"
# (a LIST of {"kind": ..., ...params}, e.g. heal) is read generically too.
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
        # Fires the moment the throw is confirmed (Explorator._use_interact_item).
        "sounds": {"throw": "lightning_dyn.wav"},
    },
}

# Two-part item registry, same spirit as OBJECT_TYPES' builtin+custom split:
# `custom_items.json` holds full new item entries (register_item/update_item);
# `custom_items_overrides.json` holds a mechanics-only override (capabilities/
# effects) of an EXISTING builtin item id (dynamite today). Kept separate
# because they answer different questions ("does this id exist" vs "should
# its mechanics differ from Python defaults") -- a custom item is always
# complete, never a partial diff.
CUSTOM_ITEMS_PATH = PROJECT_ROOT / "assets" / "tiles" / "custom_items.json"
CUSTOM_ITEMS_OVERRIDES_PATH = PROJECT_ROOT / "assets" / "tiles" / "custom_items_overrides.json"


def _load_custom_items():
    """Absent/vide/corrompu -> dict vide, meme tolerance que _load_custom_object_types."""
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
    """Construction pure d'une entree ITEM_DEFINITIONS custom -- partagee par
    register_item/update_item. `card_type` toujours "item". `loot_cards`:
    meme convention "None = inchange, {} = explicitement vide" que _build_mechanics_fields."""
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
    """The loot table actually spawned as ground pickups when `card_id` dies
    or is destroyed: its own "loot_cards" override if ever saved (even an
    explicit {} meaning "drops nothing"), else the implicit default of one
    copy of its own card. Works for an OBJECT_TYPES- or ITEM_DEFINITIONS-backed
    id; a base-tile id (out of scope for this registry) always falls through
    to the default."""
    config = OBJECT_TYPES.get(card_id)
    if config is None:
        config = ITEM_DEFINITIONS.get(card_id)
    if config is not None and "loot_cards" in config:
        return dict(config["loot_cards"])
    return {card_id: 1}


def is_builtin_item(item_id):
    return item_id in _BUILTIN_ITEM_DEFINITIONS


def register_item(item_id, name, slot, icon_path, icon_rect, capabilities=None, effects=None, sounds=None,
                   sound_pitch=None, loot_cards=None):
    """Valide et persiste un NOUVEL item -- l'equivalent register_custom_type
    pour ITEM_DEFINITIONS. Leve ValueError sur un id invalide/deja pris ou un slot inconnu."""
    if not item_id or not all(c.isalnum() or c == "_" for c in item_id):
        raise ValueError("Identifiant invalide (lettres/chiffres/_ uniquement)")
    if item_id in ITEM_DEFINITIONS:
        raise ValueError(f"'{item_id}' existe deja")
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
    """Edite un item custom DEJA enregistre -- jamais un item integre
    (dynamite), voir update_item_overrides pour ca."""
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
    """Persiste un override mecanique (toujours l'etat complet, jamais un
    diff) pour un item EXISTANT INTEGRE AU JEU (dynamite -- les items custom
    passent par update_item). Compare toujours contre les valeurs mecaniques
    REELLES du builtin avant de decider si l'override est un no-op a retirer
    -- dynamite a "capabilities" actif par defaut, donc un override "tout
    desactive" DIFFERE du builtin et doit etre persiste."""
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
        merged = dict(base)
        for key in ("capabilities", "effects", "sounds", "sound_pitch", "loot_cards"):
            if key in entry:
                merged[key] = entry[key]
            else:
                merged.pop(key, None)
    _persist_custom_item_overrides(overrides)
    ITEM_DEFINITIONS[item_id] = merged
    return merged

DYNAMITE_FRAME_SIZE = 16
DYNAMITE_FRAME_COUNT = 4


_dynamite_frames_cache = None


def load_dynamite_frames():
    """The 4 throw-animation frames (16x16), sliced from the single-row 64x16
    dynamite.png sheet -- used by core.world.entities.ThrownDynamite, not the
    static icon (frame 0 via icon_rect). Cached at module level."""
    global _dynamite_frames_cache
    if _dynamite_frames_cache is None:
        sheet = pygame.image.load(PROJECT_ROOT / "assets" / ITEM_DEFINITIONS["dynamite"]["icon_path"]).convert_alpha()
        size = DYNAMITE_FRAME_SIZE
        _dynamite_frames_cache = [sheet.subsurface((i * size, 0, size, size)).copy() for i in range(DYNAMITE_FRAME_COUNT)]
    return _dynamite_frames_cache


# Explosion VFX: one 48x48 PNG per frame (not a sliced sheet, that's how it
# was authored). Played once by core.world.entities.Explosion.
EXPLOSION_FOLDER = "effect/smallexplosion"
EXPLOSION_FRAME_COUNT = 9


_explosion_frames_cache = None


def load_explosion_frames():
    """Cached at module level."""
    global _explosion_frames_cache
    if _explosion_frames_cache is None:
        _explosion_frames_cache = [
            pygame.image.load(PROJECT_ROOT / "assets" / EXPLOSION_FOLDER / f"frame{i:04d}.png").convert_alpha()
            for i in range(EXPLOSION_FRAME_COUNT)
        ]
    return _explosion_frames_cache


# Destruction VFX: a single 128x32 sheet, 4 frames of 32x32 sliced
# left-to-right. Played once by core.world.entities.DestructionSpark while
# homing toward whichever player destroyed the tile (see
# Dungeon.destroy_area/destroy_wall_cell's callers).
STAR_FOLDER = "effect/star"
STAR_FILENAME = "star.png"
STAR_FRAME_SIZE = 32
STAR_FRAME_COUNT = 4


_star_frames_cache = None


def load_star_frames():
    """Cached at module level, same reasoning as load_dynamite_frames/load_explosion_frames."""
    global _star_frames_cache
    if _star_frames_cache is None:
        sheet = pygame.image.load(PROJECT_ROOT / "assets" / STAR_FOLDER / STAR_FILENAME).convert_alpha()
        size = STAR_FRAME_SIZE
        _star_frames_cache = [sheet.subsurface((i * size, 0, size, size)).copy() for i in range(STAR_FRAME_COUNT)]
    return _star_frames_cache


def make_item(item_id):
    """Builds a core.world.inventory.Item from ITEM_DEFINITIONS -- kept here
    since ITEM_DEFINITIONS lives alongside every other asset registry in this module."""
    from core.world.inventory import Item
    definition = ITEM_DEFINITIONS[item_id]
    return Item(item_id, definition["name"], definition["icon_path"], definition.get("icon_rect"))


def load_object_frames(object_type, variant=None):
    """Slice an object's sprite sheet into its animation frames -- a flat
    list, left-to-right then row by row. Most types are a single row
    ("rows" defaults to 1: "frames" columns from row 0). A chest-like type
    with "rows": 2 has "frames" as the TOTAL count across both rows (e.g. 8
    for lilchest's 4-idle + 4-open), so row 1 continues the flat list where
    row 0 left off -- obj["frame"] just keeps counting upward."""
    config = OBJECT_TYPES[object_type]
    asset_path = config.get("variants", {}).get(variant, config["asset"])

    if isinstance(asset_path, dict):
        # {"tileset": ..., "rect": [x, y, w, h]} -- a region reference into a
        # shared tileset (custom types, see register_custom_type) instead of a
        # dedicated per-type file. Always a single static frame.
        #
        # {"tileset": ..., "rects": [[x, y, w, h], ...]} -- a custom "porte"
        # with its opening animation's frames picked individually, each its
        # own independent tileset region. One frame per rect, in order.
        if "rects" in asset_path:
            return [load_tileset_region(asset_path["tileset"], r) for r in asset_path["rects"]]
        return [load_tileset_region(asset_path["tileset"], asset_path["rect"])]

    asset = PROJECT_ROOT / "assets" / asset_path
    sheet = pygame.image.load(asset).convert_alpha()

    if config["frames"] == 1:
        # A single static frame pre-sized exactly to its final footprint (e.g.
        # "big_entrance", a 2-wide object with a 32x16 asset) -- no
        # frame_size/rows slicing, since every other type assumes square frames.
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
    """Full idle+move animation set for an animal NPC sheet (2x2 grid: row 0
    idle, row 1 move, 2 frames each of frame_size px). Used by
    core.world.entities.Animal for live wandering -- the static editor
    palette preview keeps using load_object_frames (idle row only). Cached by object_type."""
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
    each is its own single-row sheet, frame count derived from pixel width
    (sheet.get_width() // ENEMY_FRAME_SIZE) since skeleton1/skeleton2 don't
    share frame counts despite sharing a folder layout. Cached by enemy_type."""
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
    """{action: {direction: [tile_index, ...]}}, ordered by each tile's saved
    "order" field -- built from an entity-kind pack's tagged tiles (see
    SpriteEditorPanelUI's batch tagging). Sibling of
    core.editor.autotile.build_pack_lookup, deliberately separate (different
    domain: action/direction/order, not bitmask). Cached per (pack_name, file
    mtime) -- reloaded automatically when the sprite editor re-tags a tile."""
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
    """{action: {direction: [Surface, ...]}} -- the live-entity equivalent of
    load_animal_frames/load_enemy_frames, sourced from a sprite-editor-tagged
    entity pack instead of a fixed grid/folder convention. Cached by pack
    name -- a pack is never re-tagged while the game runs, only from the editor."""
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
    """(tagged: set, missing: set) of NPC_DIRECTIONS for `action_name` within
    `entity_pack` -- shared by npc_completeness (already-registered PNJ) and
    SpriteEditorPanelUI's live coverage preview while filling the
    "Enregistrer comme PNJ" form. `action_name` of None/"" returns everything
    as missing -- callers that only care about configured roles filter those
    out themselves."""
    if not action_name:
        return set(), set(NPC_DIRECTIONS)
    lookup = build_entity_pack_lookup(entity_pack)
    tagged = set(lookup.get(action_name, {}).keys())
    return tagged, set(NPC_DIRECTIONS) - tagged


def npc_completeness(type_id):
    """{"complete": bool, "missing": {role: [direction,...], ...}} for an
    ALREADY-REGISTERED entity-pack-backed mob type -- only checks roles
    present in its own wander_actions (an unset optional role is a
    deliberate choice, not a gap). {"complete": True, "missing": {}} for
    anything not entity-pack-backed, so callers don't need to check
    entity_pack presence first."""
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
    """Construction pure d'un dict au format OBJECT_TYPES pour un PNJ --
    parallele a _build_visual_fields mais separee : un PNJ n'a pas de rect
    propre, seulement une reference a un pack d'entite. `icon_rect` fournit
    l'icone statique (palette/objet pose, meme forme {"tileset","rect"} que
    load_object_frames attend). `wander_actions` ({"idle": ..., "move": ...})
    nomme les actions du pack a jouer pendant chaque etat de vagabondage (core.world.entities.Mob)."""
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
    """Valide et persiste une NOUVELLE entree OBJECT_TYPES de PNJ -- pendant de
    register_custom_type (voir update_npc_type pour l'edition).

    `entry["interactable"] = True` est ajoute ICI seulement (pas dans
    _build_npc_type_entry, reutilise par update_npc_type/
    rename_entity_pack_references, qui ne doivent pas ecraser un
    interactable desactive depuis la Forge) : un type cree via cet ecran est
    dialogable par defaut, mais reste editable/desactivable ensuite."""
    if not type_id or not all(c.isalnum() or c == "_" for c in type_id):
        raise ValueError("Identifiant invalide (lettres/chiffres/_ uniquement)")
    if type_id in OBJECT_TYPES:
        raise ValueError(f"'{type_id}' existe deja")
    entry = _build_npc_type_entry(name, entity_pack, tileset, icon_rect, size, wander_actions)
    entry["interactable"] = True
    _write_custom_type(type_id, entry)
    return entry


def update_npc_type(type_id, name, entity_pack, tileset, icon_rect, size, wander_actions):
    """Edite un PNJ deja enregistre -- pendant de update_custom_type. Meme
    garde-fou : type_id doit deja exister ET etre custom, jamais un type integre."""
    existing = OBJECT_TYPES.get(type_id)
    if existing is None:
        raise ValueError(f"'{type_id}' n'existe pas")
    if not isinstance(existing.get("asset"), dict):
        raise ValueError(f"'{type_id}' est un type integre au jeu, non modifiable")
    entry = _build_npc_type_entry(name, entity_pack, tileset, icon_rect, size, wander_actions)
    _write_custom_type(type_id, entry)
    return entry


def npc_types_for_pack(entity_pack):
    """(type_id, config) pour chaque PNJ deja enregistre depuis `entity_pack`
    -- pendant de custom_types_for_tileset pour la liste "PNJ existants"."""
    return [
        (candidate_id, config) for candidate_id, config in OBJECT_TYPES.items()
        if config.get("entity_pack") == entity_pack
    ]


def rename_entity_pack_references(old_pack_name, new_pack_name):
    """Garde le "entity_pack" de chaque PNJ enregistre en phase apres que
    ressources.rename_autotile_pack a deja renomme le fichier sur disque --
    appeler juste apres. Reecrit chaque entree via _build_npc_type_entry
    (seul entity_pack change) plutot que de modifier le dict en place, pour
    que le format persiste toujours celui de register_npc_type/update_npc_type."""
    for type_id, config in npc_types_for_pack(old_pack_name):
        entry = _build_npc_type_entry(
            config.get("name", type_id), new_pack_name, config["asset"]["tileset"],
            config["asset"]["rect"], config.get("size", [1, 1]), config.get("wander_actions", {}),
        )
        _write_custom_type(type_id, entry)


class ObjectManager:
    """Owns the placed-object list and the rules for placing them. The grid/size data it needs belongs to the Dungeon it's attached to."""

    ANIM_SPEED = DEFAULT_ANIM_SPEED  # seconds per frame

    def __init__(self, dungeon):
        self.dungeon = dungeon
        # _cell_index/objects_version back get_object_at -- see the `objects`
        # property setter and _index_object/_deindex_object. Kept in sync
        # incrementally by add_object/move_object; any wholesale replacement of
        # self.objects goes through the setter, which rebuilds from scratch.
        self._cell_index = {}
        self.objects_version = 0
        # id(obj) -> obj, every object currently animating (see
        # begin_animation/update()). Rebuilt on wholesale replacement of
        # self.objects, since a fresh load can arrive with objects already mid-animation.
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
        """Registers `obj` as currently animating -- call right after setting
        "activated"/"open" True for the first time (this class's own
        check_button_trigger, core.world.assembly's cross-room button/door
        sync, or Explorator._interact_with_chest). update() below only
        iterates this set; a finished object self-removes. Re-registering an
        already-animating/finished object is harmless."""
        self._animating[id(obj)] = obj

    def _footprint_cells_of(self, obj):
        size_x, size_y = OBJECT_TYPES[obj["type"]]["size"]
        for dx in range(size_x):
            for dy in range(size_y):
                yield obj["x"] + dx, obj["y"] + dy

    def _index_object(self, obj):
        # setdefault, not a plain assignment: preserves "first in self.objects
        # order wins" if two footprints ever overlapped (shouldn't happen
        # through ordinary placement, but a hand-edited save isn't re-validated).
        for cell in self._footprint_cells_of(obj):
            self._cell_index.setdefault(cell, obj)

    def _deindex_object(self, obj):
        for cell in self._footprint_cells_of(obj):
            if self._cell_index.get(cell) is obj:
                del self._cell_index[cell]

    def _rebuild_cell_index(self):
        self._cell_index = {}
        for obj in self._objects:
            self._index_object(obj)

    def _in_bounds(self, grid_x, grid_y):
        return 0 <= grid_x < self.dungeon.width and 0 <= grid_y < self.dungeon.height

    def add_object(self, object_type, grid_x, grid_y):
        if not self._in_bounds(grid_x, grid_y):
            return False

        valid, variant = self._resolve_placement(object_type, grid_x, grid_y)
        if not valid:
            return False

        placed = {
            "type": object_type,
            "x": grid_x,
            "y": grid_y,
        }

        if variant is not None:
            placed["variant"] = variant

        config = OBJECT_TYPES[object_type]
        if config.get("chest"):
            # Own dict copies, not the OBJECT_TYPES default objects -- ChestPanelUI
            # mutates these per-placed-chest and must never leak back into the registry.
            placed["loot"] = dict(config.get("default_loot", {}))
            placed["item_loot"] = dict(config.get("default_item_loot", {}))

        self._objects.append(placed)
        self._index_object(placed)
        self.objects_version += 1

        return True

    def get_object_at(self, grid_x, grid_y):
        """The object whose footprint covers this cell -- not just its
        origin, so a 2-wide "wall" is found from either cell. O(1) via
        _cell_index -- the hottest call in the collision path
        (is_cell_walkable, up to 4 corners x every entity x every frame)."""
        return self._cell_index.get((grid_x, grid_y))

    def is_chest(self, object_type):
        """True for a chest-like type (currently just lilchest) -- its dot
        opens ChestPanelUI in Creator instead of starting a link-drag."""
        return OBJECT_TYPES[object_type].get("chest", False)

    def is_linkable(self, object_type):
        return OBJECT_TYPES[object_type].get("linkable", False)

    def is_es_type(self, object_type):
        """True for gate/wall/cave_entrance/big_entrance, OR a custom "porte"
        archetype type (config["is_es"]) -- object kinds that carry a role
        (get_role/set_role) and that core.world.assembly's generator can
        treat as a room-to-room connector."""
        if object_type in ES_TYPES:
            return True
        return bool(OBJECT_TYPES.get(object_type, {}).get("is_es"))

    def get_role(self, obj):
        """The object's role -- connector/dungeon_entrance/dungeon_exit for
        an E/S, loot/dungeon_exit for a chest. Missing "role" key (old saves)
        reads as that kind's default. Object kinds with no role concept get None."""
        role = obj.get("role")
        if role is not None:
            return role
        if self.is_es_type(obj["type"]):
            return "connector"
        if self.is_chest(obj["type"]):
            return "loot"
        return None

    def set_role(self, obj, role):
        """Assigns a role, validated against ES_ROLES/CHEST_ROLES -- an
        invalid value is silently ignored rather than corrupting the object dict."""
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
        """Drawn after (in front of) the player, and walkable despite sitting on a WALL cell -- currently just L/R wall-mounted torches; a straight torch stays a plain blocking wall decoration. (A pillar's decorative top half gets the same front-of-player treatment, but it isn't a real object -- see WorldRenderer._draw_pillar_tops -- so it never reaches this method. A custom type with per-cell "cell_modes" decides front/back PER CELL instead of through this whole-object check.)"""
        return obj["type"] == "torch" and obj.get("variant") in ("L", "R")

    def cell_mode(self, obj, config, grid_x, grid_y):
        """The CELL_MODES value for (grid_x, grid_y) within `obj`'s
        footprint, or None if this type has no per-cell data -- callers fall
        back to whole-object blocks_movement/is_foreground_object checks.
        Cells outside the declared grid read as "behind" (fail-open)."""
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

            # Per-cell override (custom types only): a multi-cell footprint can
            # mix blocking/walkable cells instead of the whole-object flags
            # below applying uniformly. Absent on every built-in type.
            cell_mode = self.cell_mode(obj, config, grid_x, grid_y)
            if cell_mode is not None:
                if cell_mode == "block" and config.get("blocks_until_open"):
                    # A "block" cell on a lockable custom "porte" follows the
                    # same open/closed state as any other blocks_until_open
                    # object, independent of which cell is the anchor.
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
        """Marks `obj` (a "button") pressed -- starts its animation and plays
        the trigger sound. Shared by check_button_trigger and
        DungeonAssembly.check_button_trigger (local vs room-aware lookup)."""
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
        """Opens `target` (a blocks_until_open object, e.g. a linked
        gate/wall) if not already open -- `object_manager` is whichever
        ObjectManager actually owns `target` (a cross-room assembly_link's
        target may live in a different room's Dungeon)."""
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
        """Advance animation for any currently-animating object, holding on
        its last frame and dropping out of _animating right then -- iterates
        only that set, not every placed object."""
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
        """Reposition an already-placed object. Returns True if the new cell was valid."""
        if not self._in_bounds(grid_x, grid_y):
            return False

        valid, variant = self._resolve_placement(obj["type"], grid_x, grid_y)
        if not valid:
            return False

        self._deindex_object(obj)

        old_x, old_y = obj["x"], obj["y"]
        obj["x"], obj["y"] = grid_x, grid_y

        if variant is not None:
            obj["variant"] = variant
        else:
            obj.pop("variant", None)

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
        """The single footprint cell a placement validates its terrain
        against -- bottom-center of the object's "size", not its stored
        origin (top-left). Confirmed with the user: every OTHER cell of a
        multi-cell footprint is free to overlap anything without blocking
        placement -- purely visual overlap, drawn front/behind per its own
        cell_modes entry. Lets a tall object stand with its base against a
        wall while upper cells visually overlap the wall above. For a 1x1
        object this is just (grid_x, grid_y) -- unchanged from before."""
        size_x, size_y = OBJECT_TYPES[object_type]["size"]
        return grid_x + (size_x - 1) // 2, grid_y + size_y - 1

    def origin_for_anchor(self, object_type, anchor_x, anchor_y):
        """Inverts _anchor_cell: given the grid cell the player is actually
        pointing at, returns the (grid_x, grid_y) origin add_object/move_object
        expect. Lets Creator's placement/move-drag work in "where the cursor
        is" terms instead of the footprint's top-left corner -- before this,
        the cursor's cell was used directly as origin, so anything wider/taller
        than 1x1 terrain-validated size_x/size_y cells away from the cursor."""
        size_x, size_y = OBJECT_TYPES[object_type]["size"]
        return anchor_x - (size_x - 1) // 2, anchor_y - (size_y - 1)

    def _resolve_placement(self, object_type, grid_x, grid_y):
        """Returns (is_valid, variant) for placing/moving object_type at this cell."""
        if object_type == "torch":
            variant = self._torch_variant(grid_x, grid_y)
            if variant is not None:
                return True, variant
            if self.dungeon.logical_grid[grid_y][grid_x] == WALL:
                return True, None
            return False, None

        if self.is_es_type(object_type):
            return self._valid_doorway_anchor(object_type, grid_x, grid_y), None

        if object_type == "stairs":
            return self._stairs_orientation(grid_x, grid_y)

        anchor_x, anchor_y = self._anchor_cell(object_type, grid_x, grid_y)
        if not self._in_bounds(anchor_x, anchor_y):
            return False, None
        is_valid = self.dungeon.logical_grid[anchor_y][anchor_x] == self._required_cell(object_type)
        return is_valid, None

    def _stairs_orientation(self, grid_x, grid_y):
        """(is_valid, variant) for stairs: valid directly on FLOOR (no flip),
        or on EMPTY with at least one FLOOR neighbor (room's void edge) --
        "flip" mirrors the asset when that neighbor is specifically west, so
        it visually faces back toward the room regardless of which side the floor is on."""
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

    def _cell_or_empty(self, grid_x, grid_y):
        if self._in_bounds(grid_x, grid_y):
            return self.dungeon.logical_grid[grid_y][grid_x]
        return EMPTY

    def is_valid_doorway(self, grid_x, grid_y):
        """True if (grid_x, grid_y) is a WALL cell that's a clean break in a
        straight wall segment: exactly one FLOOR neighbor directly opposite
        exactly one EMPTY neighbor, WALL flanking the other two sides
        (off-grid neighbors count as EMPTY).

        This is the only shape a gate/wall entry-exit can occupy (enforced at
        placement/move time) -- it can never sit mid-room, so a floor tile is
        never ambiguously "just floor" vs a doorway. The procedural assembler
        re-checks this same pattern before treating a gate/wall as a
        connectable exit, so one lacking a void neighbor (e.g. a locked door
        gating a side room) is simply never picked as a connection -- it
        still works as an ordinary in-room obstacle.
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

    def _valid_doorway_anchor(self, object_type, grid_x, grid_y):
        """True if `object_type`'s anchor cell (_anchor_cell) is a valid
        is_valid_doorway break -- the ONLY cell of a multi-cell E/S's
        footprint that's validated; every other cell is free to overlap
        anything. Autotiled walls are only ever one cell thick, so a door
        taller/wider than 1 cell perpendicular to the wall could never find a
        second independent WALL cell there (that cell is the room's own
        FLOOR interior) -- checking only the anchor is what makes a
        multi-cell custom "porte" placeable at all. A 1x1 E/S has anchor ==
        its own cell, identical to a bare is_valid_doorway call."""
        anchor_x, anchor_y = self._anchor_cell(object_type, grid_x, grid_y)
        return self.is_valid_doorway(anchor_x, anchor_y)

    def prune_invalid(self):
        """Drop objects whose underlying cell no longer matches their
        placement rule (e.g. the floor/wall they sat on got erased), and any
        links left dangling by that.

        Called unconditionally after every Dungeon.paint_cell edit (up to
        dozens/sec during a drag-paint stroke), so the common case -- nothing
        near the painted cell needed pruning -- must stay cheap: `filtered`
        is always a subset of self._objects, so equal lengths means nothing
        was removed, and only then is the `objects` setter worth going
        through (it unconditionally rebuilds the cell index/animating set and
        bumps objects_version, invalidating WorldRenderer's cache)."""
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
