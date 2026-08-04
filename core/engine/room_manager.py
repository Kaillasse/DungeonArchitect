from core.world.dungeon import Dungeon
from core.data.ressources import ROOMS_DIRECTORY, list_rooms, next_new_room_name


class RoomManager:
    """Save/load/delete operations on rooms. Which room is "current" is the caller's concern, not this class's."""

    def __init__(self, grid: Dungeon):
        self.grid = grid

    def scan(self):
        return list_rooms()

    def next_new_room_name(self):
        return next_new_room_name()

    def save(self, name):
        self.grid.save_to_json(name)

    def load(self, name):
        self.grid.load_from_json(name)

    def delete(self, name):
        path = ROOMS_DIRECTORY / f"{name}.json"
        if path.exists():
            path.unlink()
