"""Persisted player profile (name + XP): converts a Profile to/from its JSON
file under assets/profiles/. Mirrors core.data.save_manager.SaveManager's
"stateless converter, tolerant load" shape."""

from __future__ import annotations

import json
import re
from pathlib import Path

from core.data import progression
from core.data.cards import STARTING_CARD_COLLECTION

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIRECTORY = PROJECT_ROOT / "assets" / "profiles"
PROFILES_DIRECTORY.mkdir(parents=True, exist_ok=True)

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_NAME_LENGTH = 32


def _sanitize_name(name) -> str:
    """Restricts a profile name to [A-Za-z0-9_-], capped in length, falling
    back to "player" if that leaves nothing. Every path this module builds
    goes through this -- `name` may originate from an untrusted network
    `join` message (see core.network.server), so this is what stops a
    crafted name (e.g. "../../whatever") from escaping PROFILES_DIRECTORY."""
    cleaned = _SAFE_NAME_RE.sub("_", str(name or "").strip())[:_MAX_NAME_LENGTH]
    return cleaned or "player"


class Profile:
    def __init__(self, name: str, xp: int = 0, generator_room_names=None, generator_room_count: int = 3,
                 panel_layout=None, card_collection=None):
        self.name = name
        self.xp = xp
        # Creator's GeneratorPanelUI room-pool selection + room-count
        # stepper, persisted here so a dungeon_entrance crossing (see
        # Explorator._check_dungeon_entrance) has generation parameters to
        # read even on a fresh app launch, and so the panel itself reopens
        # with the player's last choice instead of resetting to "every room,
        # count 3" -- defaults here match GeneratorPanelUI's own constructor
        # defaults exactly, so an absent/fresh profile behaves identically
        # to before this field existed.
        self.generator_room_names = list(generator_room_names) if generator_room_names else []
        self.generator_room_count = generator_room_count
        # {"tools"/"object_palette"/"room"/"generator": {"x", "y", "collapsed"}}
        # -- Creator's docked PanelFrame positions/collapsed state (see
        # Creator._on_panel_frame_change/_refresh_panel_layout). Additive,
        # same convention as the generator fields above -- an empty dict
        # (a profile that's never moved a panel) leaves every panel at its
        # default constructor position.
        self.panel_layout = dict(panel_layout) if panel_layout else {}
        # {card_id -> count owned} -- see core.data.cards. Additive, same
        # convention as panel_layout above: starts empty, since no card-
        # granting mechanic (drop, PNJ trade) exists yet -- CardPanelUI
        # shows every *known* card (core.data.cards.CardManager.
        # list_known_card_ids()) regardless of this being empty, so the
        # panel stays useful before any gain mechanic exists.
        self.card_collection = dict(card_collection) if card_collection else {}

    @property
    def level(self) -> int:
        return progression.level_for_xp(self.xp)

    def add_xp(self, amount: int) -> bool:
        """Adds XP, returns True if this crossed into a new level (for a
        future level-up notification -- not consumed yet)."""
        before = self.level
        self.xp += amount
        return self.level > before


class ProfileManager:
    """Stateless save(profile)/load(name), same spirit as SaveManager for a
    Dungeon -- owns no profile state itself."""

    def get_profile_path(self, name: str) -> Path:
        return PROFILES_DIRECTORY / f"{_sanitize_name(name)}.json"

    def load(self, name: str) -> Profile:
        """A genuinely fresh profile (no file yet, or one too corrupt to
        read at all -- both cases construct a brand-new Profile with no
        recoverable data) starts with STARTING_CARD_COLLECTION. An existing,
        readable file is never re-seeded here even if its own
        card_collection is empty (e.g. every starting card has since been
        spent) -- only payload.get("card_collection") below applies then,
        same additive-field convention as every other field."""
        safe_name = _sanitize_name(name)
        path = self.get_profile_path(safe_name)
        if not path.exists() or path.stat().st_size == 0:
            return Profile(safe_name, card_collection=dict(STARTING_CARD_COLLECTION))

        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, json.JSONDecodeError):
            return Profile(safe_name, card_collection=dict(STARTING_CARD_COLLECTION))

        return Profile(
            safe_name,
            xp=int(payload.get("xp", 0)),
            generator_room_names=payload.get("generator_room_names"),
            generator_room_count=int(payload.get("generator_room_count", 3)),
            panel_layout=payload.get("panel_layout"),
            card_collection=payload.get("card_collection"),
        )

    def save(self, profile: Profile) -> Path:
        path = self.get_profile_path(profile.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "version": 1,
                    "name": profile.name,
                    "xp": profile.xp,
                    "generator_room_names": profile.generator_room_names,
                    "generator_room_count": profile.generator_room_count,
                    "panel_layout": profile.panel_layout,
                    "card_collection": profile.card_collection,
                },
                handle, indent=2, ensure_ascii=False,
            )
        return path
