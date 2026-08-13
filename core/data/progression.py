"""Player progression: XP curve, level derivation, and the level -> unlocked
object types table. Pure data/formulas, no I/O -- see core.data.profile_manager
for persistence. Every constant here (curve factor, XP grants, unlock
thresholds) is a placeholder tuned for a first pass, deliberately grouped in
one file so it's a one-line change to retune."""

from __future__ import annotations

import math

MAX_LEVEL = 100

# Cumulative XP required to REACH level n (n=1 costs 0). Quadratic so later
# levels take progressively longer -- XP_CURVE_FACTOR is the one knob to
# retune the whole curve's steepness.
XP_CURVE_FACTOR = 20


def xp_for_level(level: int) -> int:
    """Total XP needed to have reached `level` (level 1 -> 0)."""
    level = max(1, min(level, MAX_LEVEL))
    return XP_CURVE_FACTOR * (level - 1) * level


def level_for_xp(xp: int) -> int:
    """Current level for a total XP amount, capped at MAX_LEVEL. Inverts
    xp_for_level's own quadratic curve (F*(L-1)*L <= xp) directly via
    math.isqrt -- an exact integer square root, so no floating-point
    rounding risk -- instead of counting up level by level from 1. isqrt
    lands within one level of the right answer by construction; the two
    nudges below settle that last step against xp_for_level itself, the
    actual source of truth for the boundary."""
    if xp <= 0:
        return 1
    factor = XP_CURVE_FACTOR
    level = (factor + math.isqrt(factor * factor + 4 * factor * xp)) // (2 * factor)
    level = max(1, min(level, MAX_LEVEL))
    while level < MAX_LEVEL and xp >= xp_for_level(level + 1):
        level += 1
    while level > 1 and xp < xp_for_level(level):
        level -= 1
    return level


# XP granted by each already-authoritative gameplay event (see
# Explorator._grant_xp and its call sites) -- never trusted from a network
# client, only ever computed server-side (or locally in solo play, which
# runs the identical simulation code).
XP_ENEMY_KILL = 25
XP_ANIMAL_KILL = 5
XP_DUNGEON_CLEAR = 100

# Level threshold -> newly-unlocked object type names (keys of
# core.world.object_manager.OBJECT_TYPES/OBJECT_LIST) at that threshold.
# unlocked_objects() unions every threshold <= the queried level, so a type
# doesn't need to be repeated at higher levels once unlocked. Seed values
# only -- not yet consumed by ObjectPalette/ToolPaletteUI (that's the next
# step), free to retune.
UNLOCKS: dict[int, set[str]] = {
    1: {"spawn", "cave_entrance"},
    3: {"vase", "torch"},
    5: {"button", "gate", "wall"},
    8: {"lilchest"},
    10: {"chicken", "cow", "pig", "sheep"},
    15: {"stairs", "big_entrance", "pillar"},
    20: {"skeleton1"},
    30: {"skeleton2"},
}


def unlocked_objects(level: int) -> frozenset[str]:
    """Every object type unlocked at or before `level`."""
    result: set[str] = set()
    for threshold, names in UNLOCKS.items():
        if level >= threshold:
            result |= names
    return frozenset(result)
