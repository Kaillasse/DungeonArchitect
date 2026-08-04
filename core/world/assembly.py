"""Procedural room-to-room assembler.

Aligns rooms at their gate/wall entry-exit objects, resolving tile overlap by
shifting the newly-attached room to an adjacent floor (+/-1 relative to the
room it's connecting from) instead of moving tiles within a floor.
"""

from __future__ import annotations

import random

from core.world.dungeon import Dungeon
from core.editor.autotile import EMPTY, WALL

ENTRY_EXIT_TYPES = ("gate", "wall")


class PlacedRoom:
    """A Dungeon placed at a given floor and global grid offset within a DungeonAssembly."""

    def __init__(self, dungeon, room_name, floor, offset_x, offset_y):
        self.dungeon = dungeon
        self.room_name = room_name
        self.floor = floor
        self.offset_x = offset_x
        self.offset_y = offset_y

    def to_global(self, local_x, local_y):
        return self.offset_x + local_x, self.offset_y + local_y

    def occupied_cells(self):
        """Global (x, y) -> logical cell type, for every non-empty cell in this room."""
        cells = {}
        for y, row in enumerate(self.dungeon.logical_grid):
            for x, cell in enumerate(row):
                if cell != EMPTY:
                    cells[self.to_global(x, y)] = cell
        return cells

    def entry_exits(self):
        return [
            obj for obj in self.dungeon.object_manager.objects
            if obj["type"] in ENTRY_EXIT_TYPES
        ]

    def has_spawn(self):
        return any(obj["type"] == "spawn" for obj in self.dungeon.object_manager.objects)


class DungeonAssembly:
    """Several rooms placed in a shared global grid, some possibly sharing (x, y) but on different floors."""

    def __init__(self):
        self.rooms = []

    def add_room(self, placed_room):
        self.rooms.append(placed_room)

    def rooms_on_floor(self, floor):
        return [room for room in self.rooms if room.floor == floor]

    def floors(self):
        return sorted({room.floor for room in self.rooms})

    def occupied_cells_on_floor(self, floor):
        cells = {}
        for room in self.rooms_on_floor(floor):
            cells.update(room.occupied_cells())
        return cells

    def room_at(self, floor, global_x, global_y):
        """The PlacedRoom on `floor` whose bounds contain (global_x, global_y), or None."""
        for room in self.rooms_on_floor(floor):
            local_x = global_x - room.offset_x
            local_y = global_y - room.offset_y
            if 0 <= local_x < room.dungeon.width and 0 <= local_y < room.dungeon.height:
                return room
        return None

    def render(self, screen, camera, active_floor, player_global_pos=None, hide_object_types=None):
        """Draw every floor relative to active_floor: floors below draw first (so
        active_floor's own tiles cover them wherever it has content, per gaps
        showing through elsewhere), active_floor draws normally, and floors
        above draw last (masking active_floor) except at player_global_pos,
        left unmasked so the player can always see the floor they're
        standing on rather than the ceiling above them.
        """
        for floor in self.floors():
            if floor < active_floor:
                self._render_floor(screen, camera, floor, hide_object_types=hide_object_types)

        self._render_floor(screen, camera, active_floor, hide_object_types=hide_object_types)

        for floor in self.floors():
            if floor > active_floor:
                self._render_floor(
                    screen, camera, floor,
                    hide_object_types=hide_object_types,
                    player_global_pos=player_global_pos,
                )

    def _render_floor(self, screen, camera, floor, hide_object_types=None, player_global_pos=None):
        tile_size = Dungeon.TILE_SIZE

        for room in self.rooms_on_floor(floor):
            hide_cells = None

            if player_global_pos is not None:
                local_x = player_global_pos[0] - room.offset_x
                local_y = player_global_pos[1] - room.offset_y
                if 0 <= local_x < room.dungeon.width and 0 <= local_y < room.dungeon.height:
                    hide_cells = {(local_x, local_y)}

            offset_camera = _OffsetCamera(camera, room.offset_x * tile_size, room.offset_y * tile_size)
            room.dungeon.render(screen, offset_camera, hide_object_types=hide_object_types, hide_cells=hide_cells)


class _OffsetCamera:
    """Wraps a Camera, shifting every world position by a fixed (room-placement) offset before the real camera transform."""

    def __init__(self, base_camera, offset_x, offset_y):
        self._base = base_camera
        self._offset_x = offset_x
        self._offset_y = offset_y

    @property
    def zoom(self):
        return self._base.zoom

    def world_to_screen(self, world_x, world_y):
        return self._base.world_to_screen(world_x + self._offset_x, world_y + self._offset_y)


def _load_room(room_name):
    dungeon = Dungeon()
    dungeon.load_from_json(room_name)
    return dungeon


def _collides(existing_cells, new_cells, ignore=None):
    """True if any new cell conflicts with an existing one at the same global position.

    Two rooms meeting at a shared WALL is expected (their auto-generated wall
    halos naturally coincide at a doorway) and not a collision -- only a
    mismatch (floor vs. floor, or floor vs. wall) counts. `ignore` excludes the
    shared entry-exit cell itself, which is *always* floor-on-floor by
    construction (that's the point of aligning the two rooms there) and isn't
    a real conflict -- without excluding it, two rooms could never end up on
    the same floor at all.
    """
    for pos, cell_type in new_cells.items():
        if pos == ignore:
            continue
        existing_type = existing_cells.get(pos)
        if existing_type is not None and not (existing_type == WALL and cell_type == WALL):
            return True
    return False


def _find_start_room(room_names):
    """First room (in the given order) with both a spawn and an entry-exit."""
    for room_name in room_names:
        dungeon = _load_room(room_name)
        has_spawn = any(obj["type"] == "spawn" for obj in dungeon.object_manager.objects)
        has_exit = any(obj["type"] in ENTRY_EXIT_TYPES for obj in dungeon.object_manager.objects)
        if has_spawn and has_exit:
            return room_name, dungeon
    return None, None


def generate_assembly(room_names, room_count, rng=None):
    """Build a DungeonAssembly from up to room_count rooms drawn from room_names.

    Starts from the first room (in room_names order) that has both a spawn and
    a gate/wall entry-exit, then repeatedly attaches another room (drawn at
    random from room_names, repeats allowed) at one of the growing assembly's
    still-unconnected entry-exits, aligned so the two entry-exit objects share
    the same global cell. If that placement's tiles would overlap an
    already-placed room on the same floor, the new room goes on floor +1
    instead (or -1 if that's also occupied) -- always relative to the floor
    of the room it's connecting from, not the assembly's max/min floor.

    Returns None if no room in room_names has both a spawn and an entry-exit.
    """
    if rng is None:
        rng = random

    start_name, start_dungeon = _find_start_room(room_names)
    if start_name is None:
        return None

    assembly = DungeonAssembly()
    start_room = PlacedRoom(start_dungeon, start_name, floor=0, offset_x=0, offset_y=0)
    assembly.add_room(start_room)

    pending = [(start_room, exit_obj) for exit_obj in start_room.entry_exits()]

    while len(assembly.rooms) < room_count and pending:
        anchor_room, anchor_exit = pending.pop(0)

        candidate_name = rng.choice(room_names)
        candidate_dungeon = _load_room(candidate_name)
        candidate_exits = [
            obj for obj in candidate_dungeon.object_manager.objects
            if obj["type"] in ENTRY_EXIT_TYPES
        ]
        if not candidate_exits:
            continue

        candidate_exit = rng.choice(candidate_exits)

        anchor_gx, anchor_gy = anchor_room.to_global(anchor_exit["x"], anchor_exit["y"])
        offset_x = anchor_gx - candidate_exit["x"]
        offset_y = anchor_gy - candidate_exit["y"]

        candidate_room = PlacedRoom(candidate_dungeon, candidate_name, anchor_room.floor, offset_x, offset_y)
        candidate_cells = candidate_room.occupied_cells()
        shared_cell = (anchor_gx, anchor_gy)

        floor = anchor_room.floor
        if _collides(assembly.occupied_cells_on_floor(floor), candidate_cells, ignore=shared_cell):
            floor = anchor_room.floor + 1
            candidate_room.floor = floor
            if _collides(assembly.occupied_cells_on_floor(floor), candidate_cells, ignore=shared_cell):
                floor = anchor_room.floor - 1
                candidate_room.floor = floor

        # The new entry-exit inherits the anchor's link data -- note this is a
        # data-level copy only: "links" addresses are still local (x, y)
        # coordinates, meaningful within a single room's own object list.
        # Making a button in one room actually trigger a linked gate/wall in a
        # *different* room of the assembly requires check_button_trigger (and
        # friends) to become assembly-aware, which isn't wired up yet -- that's
        # follow-up work for when Explorator can traverse the assembly.
        candidate_exit["links"] = [dict(link) for link in anchor_exit.get("links", [])]

        assembly.add_room(candidate_room)

        for exit_obj in candidate_exits:
            if exit_obj is not candidate_exit:
                pending.append((candidate_room, exit_obj))

    return assembly
