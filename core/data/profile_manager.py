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

# Display/pin value used everywhere a Profile.admingod=True bypass shows a
# stock number instead of a real one (main.py's --admingod, Creator's card-
# consumption gates, CardPanelUI's collection display) -- one shared
# constant so "what does admingod's stock read as" only has one answer.
ADMINGOD_STOCK = 999999


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
                 panel_layout=None, card_collection=None, admingod: bool = False, home_player_position=None,
                 card_stash=None):
        self.name = name
        self.xp = xp
        # Set only via `python main.py --admingod` (see main.py) -- never
        # from in-game UI. Creator._consume_card/_refund_card/_try_place_object
        # short-circuit on this instead of touching card_collection at all,
        # so the seeded count (see main.py's _apply_admingod) never actually
        # moves -- easier to test new cards/behaviors without stock running
        # out mid-session.
        self.admingod = bool(admingod)
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
        # {"x": float, "y": float} in home-room world/pixel coordinates, or
        # None before the player has ever crossed the home zoom threshold
        # (see Explorator._check_home_zoom_switch) -- the single source of
        # "where is the player" Creator reads for its entity-gated tools
        # (Generateur/Forge, see Creator._entity_in_range), since Creator
        # itself owns no player entity. Updated only on that Explo->Creator
        # crossing, not every movement frame -- cheap to persist and exactly
        # matches what Creator actually needs (the position at the moment
        # editing started), same lazy-persistence spirit as panel_layout.
        self.home_player_position = dict(home_player_position) if home_player_position else None
        # {card_id -> count} -- cards physically picked up during a run
        # (see core.world.entities.CardPickup/PickupManager) and banked at
        # victory (Explorator._trigger_victory), but not yet manually
        # dragged into card_collection from core.editor.ui.stash_panel.
        # StashPanelUI in the Home/Creator. Additive, same convention as
        # card_collection -- distinct bucket, never merged automatically:
        # a card sits here until the player deliberately deposits it.
        self.card_stash = dict(card_stash) if card_stash else {}

    @property
    def level(self) -> int:
        return progression.level_for_xp(self.xp)

    def add_xp(self, amount: int) -> bool:
        """Adds XP, returns True if this crossed into a new level (for a
        future level-up notification -- not consumed yet)."""
        before = self.level
        self.xp += amount
        return self.level > before

    def set_home_player_position(self, x: float, y: float) -> None:
        self.home_player_position = {"x": x, "y": y}


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
            admingod=payload.get("admingod", False),
            home_player_position=payload.get("home_player_position"),
            card_stash=payload.get("card_stash"),
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
                    "admingod": profile.admingod,
                    "home_player_position": profile.home_player_position,
                    "card_stash": profile.card_stash,
                },
                handle, indent=2, ensure_ascii=False,
            )
        return path


def apply_to_fresh_profile(session, mutate) -> Profile | None:
    """Reloads `session.profile` fresh from disk, applies `mutate(profile)`
    to it in place, saves, and updates `session.profile` to the fresh+
    mutated instance -- returns None (no-op) if the session has no profile
    at all. Centralizes a pattern two independent call sites used to
    duplicate verbatim (core.exploration.explorator.Explorator._grant_xp,
    core.network.server.GameServer._cmd_level): session.profile is loaded
    exactly once, at session creation, and never refreshed afterwards, so
    saving it as-is would silently clobber any field another long-lived
    writer touched since (chiefly Creator's card_collection consumption/
    refunds, see Creator._active_profile -- the original bug this reload-
    first pattern exists to avoid: erasing/placing a card in Creator, then
    earning any XP in Exploration during the same run, used to revert the
    card_collection change on disk the moment the naive save landed)."""
    if session.profile is None:
        return None
    fresh = ProfileManager().load(session.profile.name)
    mutate(fresh)
    ProfileManager().save(fresh)
    session.profile = fresh
    return fresh
