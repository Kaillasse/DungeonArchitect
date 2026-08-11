import json
from pathlib import Path

from core.data.ressources import ROOMS_DIRECTORY


class SaveManager:
    """Converts a Dungeon to/from its JSON room file. Owns no world data itself."""

    def get_room_path(self, room_name: str) -> Path:
        return ROOMS_DIRECTORY / f"{room_name}.json"

    def to_json(self, dungeon) -> dict:
        return {
            "version": 4,
            "width": dungeon.width,
            "height": dungeon.height,
            "objects": dungeon.object_manager.objects,
            "cells": dungeon.logical_grid,
            "floor_theme": dungeon.floor_theme,
            "wall_theme": dungeon.wall_theme,
        }

    def save(self, dungeon, room_name: str = "room_001") -> Path:
        output = self.get_room_path(room_name)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as handle:
            json.dump(self.to_json(dungeon), handle, indent=2, ensure_ascii=False)
        return output

    def load(self, dungeon, room_name: str = "room_001") -> None:
        input_file = self.get_room_path(room_name)
        if not input_file.exists() or input_file.stat().st_size == 0:
            return

        try:
            with input_file.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, json.JSONDecodeError):
            return

        self.apply_json(dungeon, payload)

    def apply_json(self, dungeon, payload: dict) -> None:
        """Apply an already-parsed room payload to a Dungeon -- shared by load() and the assembly loader, which reads each room's payload out of one combined donjon file instead of its own."""
        dungeon.width = int(payload.get("width", dungeon.width))
        dungeon.height = int(payload.get("height", dungeon.height))
        dungeon.object_manager.objects = payload.get("objects", [])
        dungeon.logical_grid = [
            list(row) for row in payload.get("cells", dungeon.logical_grid)
        ]
        # Additive (absent on any save from before this existed) -- None
        # means exactly today's interior-only behavior, see Dungeon's own
        # floor_theme/wall_theme docstring.
        dungeon.floor_theme = payload.get("floor_theme")
        dungeon.wall_theme = payload.get("wall_theme")
        # Not rebuild() -- a load trusts the saved `cells` as-is (walls
        # included) rather than re-deriving them from floor cells, so a
        # runtime-destroyed wall (or a room hand-edited with autotile off)
        # never gets silently "repaired" just by reopening the room. Only
        # sprite_grid (pure logical-cell -> tile-art translation) needs
        # recomputing, since that's never persisted.
        dungeon.resync_sprite_grid()
