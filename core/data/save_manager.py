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

        dungeon.width = int(payload.get("width", dungeon.width))
        dungeon.height = int(payload.get("height", dungeon.height))
        dungeon.object_manager.objects = payload.get("objects", [])
        dungeon.logical_grid = [
            list(row) for row in payload.get("cells", dungeon.logical_grid)
        ]
        dungeon.rebuild()
