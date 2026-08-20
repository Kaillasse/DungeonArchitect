import re

from core.world.dungeon import Dungeon
from core.data.ressources import rooms_directory, list_rooms, next_new_room_name

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_NAME_LENGTH = 64  # a room name doubles as a raw filename -- generous but real cap


def _sanitize_room_name(name) -> str:
    """Restricts a room name to [A-Za-z0-9_-], capped in length -- same
    convention as profile_manager._sanitize_name, since a room name is
    also used directly as a filename (assets/rooms/<name>.json). Returns
    "" (not a fallback name) if that leaves nothing, so rename() can tell
    an all-invalid input apart from a real name and refuse it outright."""
    return _SAFE_NAME_RE.sub("_", str(name or "").strip())[:_MAX_NAME_LENGTH]


class RoomManager:
    """Save/load/delete/rename operations on rooms. Which room is "current" is the caller's concern, not this class's."""

    def __init__(self, grid: Dungeon):
        self.grid = grid

    def scan(self):
        return list_rooms()

    def next_new_room_name(self):
        return next_new_room_name()

    def save(self, name):
        self.grid.save_to_json(name)

    def delete(self, name):
        path = rooms_directory() / f"{name}.json"
        if path.exists():
            path.unlink()

    def rename(self, old_name, new_name):
        """Renames assets/rooms/<old_name>.json to <new_name>.json -- a
        plain file move, since a room's name is never stored inside its own
        payload (SaveManager.to_json has no name field at all). Refuses
        (no-op, returns None) if the source doesn't exist, the sanitized
        target is empty/identical to the source, or a room already owns
        that name -- silent refusal rather than an exception, since the
        caller (Creator._rename_room) is driven by freeform player text
        input that can't be trusted to always be sane.

        Returns the actual sanitized name the room now has on success (not
        just True) -- new_name as typed may have been sanitized to
        something slightly different, and the caller needs the REAL
        resulting name to correctly update whatever else references the
        old one (current_room, a profile's saved generation pool)."""
        old_path = rooms_directory() / f"{old_name}.json"
        if not old_path.exists():
            return None

        safe_new_name = _sanitize_room_name(new_name)
        if not safe_new_name or safe_new_name == old_name:
            return None

        new_path = rooms_directory() / f"{safe_new_name}.json"
        if new_path.exists():
            return None

        old_path.rename(new_path)
        return safe_new_name
