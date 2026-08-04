"""Procedural room-to-room assembler.

Aligns rooms at their gate/wall entry-exit objects, resolving tile overlap by
shifting the newly-attached room to an adjacent floor (+/-1 relative to the
room it's connecting from) instead of moving tiles within a floor.
"""

from __future__ import annotations

import json
import random

from core.world.dungeon import Dungeon
from core.world.object_manager import OBJECT_TYPES
from core.editor.autotile import EMPTY, FLOOR, WALL
from core.data.ressources import DONJONS_DIRECTORY

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

    # ------------------------------------------------------------------
    # Live exploration -- crossing between rooms/floors as the player moves
    # ------------------------------------------------------------------

    def locate_room(self, global_x, global_y, prefer_room=None):
        """The room (any floor) that actually occupies (global_x, global_y).

        Prefers staying in `prefer_room` (the room the player was in last
        frame) if it still claims the cell -- otherwise searches every room
        in the assembly. This is what lets the player cross from one room
        into another, possibly on a different floor, just by walking there:
        there's no separate "enter this room" trigger, only ordinary movement.

        Checks FLOOR ownership first, before falling back to "any non-empty
        cell" (i.e. WALL). Two rooms on different floors can coincidentally
        share a global position where one has real FLOOR and the other only
        has an unrelated auto-generated WALL cell from its own layout -- the
        FLOOR is what actually matters for "which room is this", so it must
        win even when checking prefer_room second (or not at all).
        """
        candidates = ([prefer_room] if prefer_room is not None else []) + self.rooms

        for room in candidates:
            local_x, local_y = global_x - room.offset_x, global_y - room.offset_y
            if 0 <= local_x < room.dungeon.width and 0 <= local_y < room.dungeon.height:
                if room.dungeon.logical_grid[local_y][local_x] == FLOOR:
                    return room

        for room in candidates:
            local_x, local_y = global_x - room.offset_x, global_y - room.offset_y
            if 0 <= local_x < room.dungeon.width and 0 <= local_y < room.dungeon.height:
                if room.dungeon.logical_grid[local_y][local_x] != EMPTY:
                    return room

        return None

    def is_global_cell_walkable(self, global_x, global_y, prefer_room=None):
        room = self.locate_room(global_x, global_y, prefer_room=prefer_room)
        if room is None:
            return False
        return room.dungeon.object_manager.is_cell_walkable(global_x - room.offset_x, global_y - room.offset_y)

    def is_rect_walkable(self, rect, prefer_room=None):
        tile_size = Dungeon.TILE_SIZE
        corners = (
            (rect.left, rect.top),
            (rect.right - 1, rect.top),
            (rect.left, rect.bottom - 1),
            (rect.right - 1, rect.bottom - 1),
        )

        for x, y in corners:
            grid_x = x // tile_size
            grid_y = y // tile_size
            if not self.is_global_cell_walkable(grid_x, grid_y, prefer_room=prefer_room):
                return False

        return True

    def check_button_trigger(self, global_x, global_y, prefer_room=None):
        """Assembly-aware equivalent of ObjectManager.check_button_trigger -- resolves
        both same-room links (local {"x","y"}) and cross-room ones
        (assembly_links: {"floor","x","y"} in global coordinates, added at
        generation time -- see generate_assembly).
        """
        room = self.locate_room(global_x, global_y, prefer_room=prefer_room)
        if room is None:
            return

        local_x, local_y = global_x - room.offset_x, global_y - room.offset_y
        obj = room.dungeon.object_manager.get_object_at(local_x, local_y)

        if obj is None or obj["type"] != "button" or obj.get("activated"):
            return

        obj["activated"] = True
        obj["frame"] = 0
        obj["anim_timer"] = 0.0

        for link_target in obj.get("links", []):
            target = room.dungeon.object_manager.get_object_at(link_target["x"], link_target["y"])
            self._open_if_blocking(target)

        for link_target in obj.get("assembly_links", []):
            target_room = self.room_at(link_target["floor"], link_target["x"], link_target["y"])
            if target_room is None:
                continue
            target = target_room.dungeon.object_manager.get_object_at(
                link_target["x"] - target_room.offset_x,
                link_target["y"] - target_room.offset_y,
            )
            self._open_if_blocking(target)

    @staticmethod
    def _open_if_blocking(target):
        if target is not None and OBJECT_TYPES[target["type"]].get("blocks_until_open") and not target.get("open"):
            target["open"] = True
            target["frame"] = 0
            target["anim_timer"] = 0.0

    def update(self, dt):
        for room in self.rooms:
            room.dungeon.object_manager.update(dt)

    def render(self, screen, camera, active_floor, player_global_pos=None, hide_object_types=None, skip_active_floor_foreground=False):
        """Draw every floor relative to active_floor: floors below draw first (so
        active_floor's own tiles cover them wherever it has content, per gaps
        showing through elsewhere), active_floor draws normally, and floors
        above draw last (masking active_floor) except at player_global_pos,
        left unmasked so the player can always see the floor they're
        standing on rather than the ceiling above them.

        skip_active_floor_foreground lets a caller that draws its own player
        sprite (Explorator) leave out active_floor's foreground objects (an
        L/R torch) here and draw them afterwards via
        render_active_floor_foreground(), so the player ends up behind them.
        Creator, which draws no player sprite, leaves this off and gets
        everything in one pass.
        """
        for floor in self.floors():
            if floor < active_floor:
                self._render_floor(screen, camera, floor, hide_object_types=hide_object_types)

        self._render_floor(
            screen, camera, active_floor,
            hide_object_types=hide_object_types,
            skip_foreground=skip_active_floor_foreground,
        )

        for floor in self.floors():
            if floor > active_floor:
                self._render_floor(
                    screen, camera, floor,
                    hide_object_types=hide_object_types,
                    player_global_pos=player_global_pos,
                )

    def render_active_floor_foreground(self, screen, camera, active_floor, hide_object_types=None):
        """Objects ObjectManager.is_foreground_object() flags (e.g. an L/R torch) on active_floor -- call after drawing the player sprite."""
        tile_size = Dungeon.TILE_SIZE
        for room in self.rooms_on_floor(active_floor):
            offset_camera = _OffsetCamera(camera, room.offset_x * tile_size, room.offset_y * tile_size)
            room.dungeon.render_foreground(screen, offset_camera, hide_object_types=hide_object_types)

    def _render_floor(self, screen, camera, floor, hide_object_types=None, player_global_pos=None, skip_foreground=False):
        tile_size = Dungeon.TILE_SIZE

        for room in self.rooms_on_floor(floor):
            hide_cells = None

            if player_global_pos is not None:
                local_x = player_global_pos[0] - room.offset_x
                local_y = player_global_pos[1] - room.offset_y
                if 0 <= local_x < room.dungeon.width and 0 <= local_y < room.dungeon.height:
                    hide_cells = {(local_x, local_y)}

            offset_camera = _OffsetCamera(camera, room.offset_x * tile_size, room.offset_y * tile_size)
            room.dungeon.render(
                screen, offset_camera,
                hide_object_types=hide_object_types,
                hide_cells=hide_cells,
                skip_foreground_objects=skip_foreground,
            )


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

        # Any button in the anchor's room that links to the anchor's exit should
        # also open the candidate's now-merged copy of that same door -- but a
        # plain local {"x", "y"} link only resolves within one room's own object
        # list, so this needs a global, floor-qualified reference instead
        # (an "assembly_link"), which DungeonAssembly.check_button_trigger knows
        # how to follow across rooms. The candidate exit's own pre-existing
        # local links (if any) are untouched -- they're still valid as-is,
        # since candidate room's internal layout doesn't change.
        for source_obj in anchor_room.dungeon.object_manager.objects:
            if source_obj["type"] != "button":
                continue
            for link_ref in source_obj.get("links", []):
                if (link_ref["x"], link_ref["y"]) == (anchor_exit["x"], anchor_exit["y"]):
                    source_obj.setdefault("assembly_links", []).append(
                        {"floor": floor, "x": anchor_gx, "y": anchor_gy}
                    )
                    break

        assembly.add_room(candidate_room)

        for exit_obj in candidate_exits:
            if exit_obj is not candidate_exit:
                pending.append((candidate_room, exit_obj))

    return assembly


def _donjon_path(name):
    return DONJONS_DIRECTORY / f"{name}.json"


def save_assembly(assembly, name):
    """Save a DungeonAssembly as one combined assets/donjons/<name>.json.

    Each room is stored fully (not just a reference to its source room file)
    since generation can mutate a room's objects (an entry-exit inheriting a
    link) -- reloading from assets/rooms/ by name would lose that.
    """
    payload = {
        "version": 1,
        "rooms": [
            {
                "room_name": room.room_name,
                "floor": room.floor,
                "offset_x": room.offset_x,
                "offset_y": room.offset_y,
                **room.dungeon.save.to_json(room.dungeon),
            }
            for room in assembly.rooms
        ],
    }

    path = _donjon_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path


def load_assembly(name):
    """Load a DungeonAssembly previously saved with save_assembly(), or None if it doesn't exist."""
    path = _donjon_path(name)
    if not path.exists() or path.stat().st_size == 0:
        return None

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return None

    assembly = DungeonAssembly()
    for room_payload in payload.get("rooms", []):
        dungeon = Dungeon()
        dungeon.save.apply_json(dungeon, room_payload)
        placed = PlacedRoom(
            dungeon,
            room_payload.get("room_name", ""),
            room_payload["floor"],
            room_payload["offset_x"],
            room_payload["offset_y"],
        )
        assembly.add_room(placed)

    return assembly
