"""Persisted player profile (name + XP): converts a Profile to/from its JSON
file under assets/profiles/. Mirrors core.data.save_manager.SaveManager's
"stateless converter, tolerant load" shape."""

from __future__ import annotations

import json
import re
from pathlib import Path

from core.data import progression

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
    def __init__(self, name: str, xp: int = 0):
        self.name = name
        self.xp = xp

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
        safe_name = _sanitize_name(name)
        path = self.get_profile_path(safe_name)
        if not path.exists() or path.stat().st_size == 0:
            return Profile(safe_name)

        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, json.JSONDecodeError):
            return Profile(safe_name)

        return Profile(safe_name, xp=int(payload.get("xp", 0)))

    def save(self, profile: Profile) -> Path:
        path = self.get_profile_path(profile.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(
                {"version": 1, "name": profile.name, "xp": profile.xp},
                handle, indent=2, ensure_ascii=False,
            )
        return path
