import json
from pathlib import Path

import pygame

from core.editor.autotile import EMPTY, FLOOR, WALL
from core.data.ressources import DEFAULT_ANIM_SPEED, load_tileset_region
from core.data.sound_manager import SoundManager

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
    },
    "gate": {
        "asset": "tiles/gateopenclose.png",
        # Custom placement, not a plain "floor"/"wall" lookup -- see
        # ObjectManager._resolve_placement/is_valid_doorway: a gate/wall must
        # sit on a WALL cell that reads as a clean break in a straight wall
        # segment (one FLOOR neighbor, the room interior, directly opposite
        # one EMPTY neighbor, the void beyond, with WALL flanking the other
        # two sides). This is what makes a placed entry-exit unambiguous for
        # both the player (no ordinary floor tile doubles as a doorway) and
        # the procedural assembler (core.world.assembly), which additionally
        # only treats a gate/wall with this pattern as a connectable exit.
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
        "animal": True,
        "card_type": "mob",
    },
    "cow": {
        "asset": "characters/Animals/Cow.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 2,
        "frame_size": 32,
        "animal": True,
        "card_type": "mob",
    },
    "pig": {
        "asset": "characters/Animals/Pig.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 2,
        "frame_size": 32,
        "animal": True,
        "card_type": "mob",
    },
    "sheep": {
        "asset": "characters/Animals/Sheep.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 2,
        "frame_size": 32,
        "animal": True,
        "card_type": "mob",
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
        "enemy": True,
        "card_type": "mob",
        # Merged in from the old standalone ENEMY_STATS dict -- health/
        # move_speed/aggro_range/attack_range are tuning defaults, not values
        # given by any design doc. active_attack_frames (0-based) is the
        # window during which a swing actually deals damage: frames 7-8 of 9
        # (1-based), as specified. "loot" (currency type -> count) is read
        # once, on death, by Explorator._spawn_loot -- an enemy with no
        # "loot" key (or an empty one) simply drops nothing. "item_loot"
        # (item id -> count, see ITEM_DEFINITIONS) is the same idea for real
        # inventory items rather than currency.
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
            "item_loot": {"dynamite": 1},
        },
    },
    "skeleton2": {
        "asset": "characters/Ennemies/skeleton2/idle.png",
        "placement": "floor",
        "size": (1, 1),
        "frames": 6,
        "frame_size": 32,
        "enemy": True,
        "card_type": "mob",
        # skeleton2 has a different attack frame count (15) with no given
        # mapping, so its window is derived from skeleton1's *relative*
        # position (~75%-87% through the swing) rather than guessed outright.
        "stats": {
            "health": 3, "move_speed": 45, "aggro_range": 6.0, "attack_range": 1.2,
            "active_attack_frames": [11, 12],  # see skeleton1's own comment -- list, not tuple
            "loot": {"gold": 2, "blue": 1},
        },
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
        # basictileset.png frame 27. Same doorway shape/validity as
        # gate/wall (ObjectManager.is_valid_doorway) -- see
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
        # below): same doorway shape/validity as gate/wall/cave_entrance
        # (ObjectManager.is_valid_doorway, checked off its origin cell only
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

# Object-type mechanics keys (opt-in gameplay behavior) vs identity/visual
# keys (asset/placement/size/frames/name + whatever the archetype preset
# always implies, e.g. "porte"'s walkable/is_es) -- see update_type_visual/
# update_type_mechanics below. A builtin's mechanics can be overridden (a
# custom_object_types.json entry marked OVERRIDE_MARKER, holding ONLY these
# keys) without ever touching its Python-sourced visual identity.
MECHANICS_KEYS = ("blocks_movement", "cell_modes", "interactable", "capabilities", "stats", "effects")
DOORWAY_MECHANICS_KEYS = ("linkable", "blocks_until_open")
OVERRIDE_MARKER = "__override_of_builtin__"


def _derive_card_type(config):
    """Best-effort card_type for a custom_object_types.json entry saved
    before this field existed -- same rule core.data.cards.default_card_for
    used to apply ad hoc per-Card, now the single place that does it, once,
    for the registry entry itself."""
    if config.get("npc"):
        return "pnj"
    if config.get("animal") or config.get("enemy"):
        return "mob"
    if config.get("is_es") or config.get("chest"):
        return "tile_special"
    return "tile_decor"


def _merge_builtin(type_id, override):
    """A builtin's own Python-sourced entry, with its mechanics keys
    replaced by `override`'s (an OVERRIDE_MARKER-tagged entry holding a
    full snapshot of MECHANICS_KEYS/DOORWAY_MECHANICS_KEYS -- never a
    sparse diff, so a flag can be explicitly turned back off). None if
    type_id no longer names a real builtin (a stale override left over
    from a since-removed one)."""
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
    """The live registry: every builtin, with any persisted mechanics
    override merged on top, plus every genuine custom/NPC type as-is
    (card_type backfilled once if the entry predates that field)."""
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


def _build_visual_fields(name, tileset, rect, size, archetype, frame_rects=None):
    """Construction pure (aucune I/O) des champs d'identite/visuel d'une
    entree OBJECT_TYPES custom -- asset/placement/size/frames/name plus les
    flags que l'archetype impose toujours (voir ARCHETYPES). Partagee par
    register_custom_type (creer) et update_type_visual (editer).

    `frame_rects` (archetype "porte" seulement), s'il est fourni, remplace
    le `rect` unique par une liste de rects -- une frame d'animation
    d'ouverture par entree, choisies individuellement dans l'editeur de
    sprite plutot qu'une bande continue decoupee automatiquement (voir
    SpriteEditorPanelUI). Sans lui (tout le reste, y compris une "porte" a
    1 frame), comportement actuel inchange : un seul "rect", frames=1."""
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
                             interactable=False, lockable=False, capabilities=None, stats=None, effects=None):
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
    disponible pour n'importe quel type."""
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
    card_type reste celui, deja correct, du builtin lui-meme."""
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


def register_custom_type(
    type_id, name, tileset, rect, size, archetype, blocks_movement=False, cell_modes=None,
    interactable=False, lockable=False, frame_rects=None,
):
    """Valide et persiste une NOUVELLE entree OBJECT_TYPES sourcee depuis une
    region de tileset -- le point d'ecriture que SpriteEditorPanelUI appelle
    une fois la selection confirmee, en mode creation (voir update_custom_type
    pour le mode edition). Leve ValueError sur un id/archetype invalide ou
    deja pris, pour que l'appelant affiche un message plutot que de
    corrompre le registre silencieusement."""
    if not type_id or not all(c.isalnum() or c == "_" for c in type_id):
        raise ValueError("Identifiant invalide (lettres/chiffres/_ uniquement)")
    if type_id in OBJECT_TYPES:
        raise ValueError(f"'{type_id}' existe deja")
    entry = _build_visual_fields(name, tileset, rect, size, archetype, frame_rects)
    entry.update(_build_mechanics_fields(entry, blocks_movement, cell_modes, interactable, lockable))
    _write_custom_type(type_id, entry)
    return entry


def update_type_visual(type_id, name, tileset, rect, size, archetype, frame_rects=None):
    """Edite UNIQUEMENT l'identite/visuel d'une carte custom DEJA
    enregistree (type_id doit deja exister ET etre une carte custom --
    jamais un type integre au jeu comme "vase", identifie par la forme
    dict de son "asset" -- meme un id qui collisionnerait par coincidence
    avec un type integre ne peut jamais l'ecraser). Contrairement a
    l'ancien _build_custom_type_entry (qui reconstruisait tout depuis
    zero), les cles mecaniques deja presentes survivent intactes -- seules
    les cles de _ARCHETYPE_FLAG_KEYS (walkable/is_es) sont effacees puis
    reappliquees, pour qu'un changement d'archetype ne laisse pas un flag
    de l'ancien archetype trainer."""
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
                           interactable=False, lockable=False, capabilities=None, stats=None, effects=None):
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
    fields = _build_mechanics_fields(existing, blocks_movement, cell_modes, interactable, lockable, capabilities, stats, effects)
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
    en un seul appel, meme signature/comportement qu'avant leur separation
    (voir ces deux fonctions). SpriteEditorPanelUI continue d'appeler
    celui-ci sans aucun changement : il passe deja les champs visuels ET
    mecaniques dans le meme appel, en repassant inchange tout ce qu'il ne
    laisse pas l'utilisateur editer lui-meme (voir MechanicsPanelUI, qui
    fait le symetrique avec update_type_mechanics seul)."""
    update_type_visual(type_id, name, tileset, rect, size, archetype, frame_rects)
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


# Object types backed by a live, wandering entity (core.world.entities.Animal)
# during exploration rather than just a static placed sprite -- see
# entities.AnimalManager. Derived from the "animal" flag above instead of a
# separately-maintained list, so OBJECT_TYPES stays the single registry.
ANIMAL_TYPES = tuple(name for name, config in OBJECT_TYPES.items() if config.get("animal"))

# Same idea as ANIMAL_TYPES, for core.world.entities.Enemy/EnemyManager.
ENEMY_TYPES = tuple(name for name, config in OBJECT_TYPES.items() if config.get("enemy"))

# Same idea again, for core.world.entities.Npc/NpcManager (PNJ -- see
# register_npc_type/load_npc_frames below) -- EXCEPT, unlike ANIMAL_TYPES/
# ENEMY_TYPES above, this is a FUNCTION, not a tuple frozen at import
# time. Animal/enemy types are all hand-authored in this file (never
# created at runtime), so freezing them once at import has never actually
# mattered; an NPC type is created entirely in-session via the sprite
# editor's register_npc_type, so a frozen tuple would silently never see
# a type registered after this module was first imported -- the exact
# "custom type registered mid-session" gap ObjectManager.is_es_type was
# already fixed to avoid (it reads config.get("is_es") dynamically
# instead of a frozen ES_TYPES-style tuple). Call npc_types() fresh at
# each use instead of caching its result across a session.
def npc_types():
    return tuple(name for name, config in OBJECT_TYPES.items() if config.get("npc"))

# The 8 compass directions an entity pack's regions get tagged with (see
# SpriteEditorPanelUI's entity-pack bitmap-tagging mode) -- deliberately
# the exact same 8 names core.world.entities.Player.DIRECTION_VECTORS
# already uses for its own 8-way facing, so there's only ever one
# direction vocabulary in this codebase, not two equivalent ones that
# could drift apart.
NPC_DIRECTIONS = ("front", "front_right", "right", "back_right", "back", "back_left", "left", "front_left")

# Object types that function as an entry/exit (a doorway between rooms, or
# the boundary of a room's void edge) -- the only types get_role/set_role
# below accept a "connector"/"dungeon_entrance"/"dungeon_exit" role for, and
# what core.world.assembly's procedural generator treats as a possible
# room-to-room connector (imported there instead of a second, separately
# maintained tuple).
ES_TYPES = ("gate", "wall", "cave_entrance", "big_entrance")

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


def _build_item_entry(name, slot, icon_path, icon_rect, capabilities=None, effects=None):
    """Construction pure (aucune I/O) d'une entree ITEM_DEFINITIONS custom --
    partagee par register_item/update_item. `card_type` toujours "item" --
    aucun autre type de carte n'utilise ce registre."""
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


def is_builtin_item(item_id):
    return item_id in _BUILTIN_ITEM_DEFINITIONS


def register_item(item_id, name, slot, icon_path, icon_rect, capabilities=None, effects=None):
    """Valide et persiste un NOUVEL item -- l'equivalent register_custom_type
    pour ITEM_DEFINITIONS. Leve ValueError sur un id invalide/deja pris ou
    un slot inconnu."""
    if not item_id or not all(c.isalnum() or c == "_" for c in item_id):
        raise ValueError("Identifiant invalide (lettres/chiffres/_ uniquement)")
    if item_id in ITEM_DEFINITIONS:
        raise ValueError(f"'{item_id}' existe deja")
    if slot not in ("attack", "interact", "passive"):
        raise ValueError(f"Slot inconnu : {slot}")
    entry = _build_item_entry(name, slot, icon_path, icon_rect, capabilities, effects)
    custom = _load_custom_items()
    custom[item_id] = entry
    _persist_custom_items(custom)
    ITEM_DEFINITIONS[item_id] = entry
    return entry


def update_item(item_id, name, slot, icon_path, icon_rect, capabilities=None, effects=None):
    """Edite un item custom DEJA enregistre -- jamais un item integre au jeu
    (dynamite) comme register_item/update_item ne peuvent jamais l'ecraser :
    voir update_item_overrides pour editer les mecaniques d'un builtin."""
    if item_id not in ITEM_DEFINITIONS:
        raise ValueError(f"'{item_id}' n'existe pas")
    if is_builtin_item(item_id):
        raise ValueError(f"'{item_id}' est un item integre au jeu, non modifiable (voir update_item_overrides)")
    if slot not in ("attack", "interact", "passive"):
        raise ValueError(f"Slot inconnu : {slot}")
    entry = _build_item_entry(name, slot, icon_path, icon_rect, capabilities, effects)
    custom = _load_custom_items()
    custom[item_id] = entry
    _persist_custom_items(custom)
    ITEM_DEFINITIONS[item_id] = entry
    return entry


def update_item_overrides(item_id, capabilities, effects):
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
    base_state = {key: base[key] for key in ("capabilities", "effects") if key in base}

    overrides = _load_custom_item_overrides()
    if entry == base_state:
        overrides.pop(item_id, None)
        merged = dict(base)
    else:
        overrides[item_id] = entry
        merged = dict(base)
        for key in ("capabilities", "effects"):
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


def make_item(item_id):
    """Builds a core.world.inventory.Item from ITEM_DEFINITIONS -- kept here
    (not in inventory.py) since ITEM_DEFINITIONS lives alongside every other
    asset registry in this module (OBJECT_TYPES, CURRENCY_FILES)."""
    from core.world.inventory import Item
    definition = ITEM_DEFINITIONS[item_id]
    return Item(item_id, definition["name"], definition["icon_path"], definition.get("icon_rect"))


def load_object_frames(object_type, variant=None):
    """Slice an object's sprite sheet into its animation frames -- a flat
    list, "frames" cells read left-to-right then row by row. Almost every
    object type is a single row ("rows" defaults to 1, in which case this is
    exactly the old behavior: "frames" columns from row 0). A chest-like
    type with "rows": 2 instead has "frames" as the TOTAL count across both
    rows (e.g. 8 for lilchest's 4-idle + 4-open sheet), so row 1 continues
    the flat list right where row 0 left off -- obj["frame"] can then just
    keep counting upward across the "seam" between rows without needing to
    know rows exist at all (see OBJECT_TYPES["lilchest"])."""
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
        # {"tileset": ..., "rects": [[x, y, w, h], ...]} -- a custom "porte"
        # with its opening animation's frames picked individually (see
        # SpriteEditorPanelUI), each its own independent tileset region
        # rather than consecutive cells of one sheet. One frame per rect, in
        # order -- "frames" (see _build_visual_fields) already equals
        # len(rects), so obj["frame"] indexes straight into this list.
        if "rects" in asset_path:
            return [load_tileset_region(asset_path["tileset"], r) for r in asset_path["rects"]]
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
    ALREADY-REGISTERED PNJ type -- only checks roles actually present in
    its own wander_actions (an optional role like "sitting"/"laying"/"run"
    left unset is a deliberate choice, not a gap -- see core.world.
    entities.Npc's own class docstring on why each is independently
    optional). {"complete": True, "missing": {}} for anything that isn't a
    registered PNJ type at all, so a caller can call this unconditionally
    without checking config.get("npc") first."""
    config = OBJECT_TYPES.get(type_id)
    if config is None or not config.get("npc"):
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
    jouer pendant chacun des deux etats de vagabondage de NpcManager (voir
    core.world.entities.Npc)."""
    return {
        "asset": {"tileset": tileset, "rect": list(icon_rect)},
        "placement": "floor",
        "size": list(size),
        "frames": 1,
        "name": name,
        "npc": True,
        "entity_pack": entity_pack,
        "wander_actions": dict(wander_actions),
    }


def register_npc_type(type_id, name, entity_pack, tileset, icon_rect, size, wander_actions):
    """Valide et persiste une NOUVELLE entree OBJECT_TYPES de PNJ -- le
    pendant de register_custom_type pour ce cas (voir update_npc_type pour
    l'edition). Meme garde-fou d'id que register_custom_type."""
    if not type_id or not all(c.isalnum() or c == "_" for c in type_id):
        raise ValueError("Identifiant invalide (lettres/chiffres/_ uniquement)")
    if type_id in OBJECT_TYPES:
        raise ValueError(f"'{type_id}' existe deja")
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
        if config.get("npc") and config.get("entity_pack") == entity_pack
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
        # setdefault, not a plain assignment: if two objects' footprints ever
        # overlapped (shouldn't happen through ordinary placement, but
        # nothing here re-validates a hand-edited save), this preserves the
        # exact same "first in self.objects order wins" result the old
        # linear scan in get_object_at used to produce.
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
        multiplied badly with entity count."""
        return self._cell_index.get((grid_x, grid_y))

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
        """Drawn after (in front of) the player, and walkable despite sitting on a WALL cell -- currently just L/R wall-mounted torches; a straight torch stays a plain blocking wall decoration. (A pillar's decorative top half gets the same front-of-player treatment, but it isn't a real object -- see WorldRenderer._draw_pillar_tops -- so it never reaches this method. A custom type with per-cell "cell_modes" -- see cell_mode/WorldRenderer._draw_objects -- decides front/back PER CELL instead of through this whole-object check.)"""
        return obj["type"] == "torch" and obj.get("variant") in ("L", "R")

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
        SoundManager().play("button_pressed")

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

    def _cell_or_empty(self, grid_x, grid_y):
        if self._in_bounds(grid_x, grid_y):
            return self.dungeon.logical_grid[grid_y][grid_x]
        return EMPTY

    def is_valid_doorway(self, grid_x, grid_y):
        """True if (grid_x, grid_y) is a WALL cell that reads as a clean break in a
        straight wall segment: exactly one FLOOR neighbor (the room interior)
        directly opposite exactly one EMPTY neighbor (the void beyond), with
        WALL flanking the other two sides. Off-grid neighbors count as EMPTY.

        This is the only shape a gate/wall entry-exit is ever allowed to
        occupy (enforced here, at placement/move time) -- it can't end up in
        the middle of a room, which is what made it ambiguous whether a given
        floor tile was "just floor" or a doorway to another room. The
        procedural assembler (core.world.assembly) also re-checks this same
        pattern before treating a gate/wall as a connectable exit, so a
        gate/wall lacking a void neighbor (interior-only, e.g. a locked door
        gating a side room) is simply never picked as a room-to-room
        connection -- it still works as an ordinary in-room obstacle.
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
        """True if `object_type`'s own anchor cell (see _anchor_cell) is a
        valid is_valid_doorway break -- the ONLY cell of a multi-cell E/S's
        footprint that placement validates; every other cell is free to
        overlap anything (a wall, void, ...) without blocking placement,
        see _anchor_cell's own docstring for why. The autotiled walls this
        game generates are only ever ONE cell thick, so a door taller/wider
        than 1 cell in the direction perpendicular to the wall could never
        find a second WALL cell to independently validate against there
        (that second cell is the room's own interior FLOOR) -- checking
        only the anchor is what makes a multi-cell custom "porte" placeable
        at all. A 1x1 E/S (gate/wall/cave_entrance/big_entrance's own
        origin, or a 1-cell custom "porte") has anchor == its own single
        cell, so this is identical to a bare is_valid_doorway call for
        every type that existed before this."""
        anchor_x, anchor_y = self._anchor_cell(object_type, grid_x, grid_y)
        return self.is_valid_doorway(anchor_x, anchor_y)

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
