"""Procedural room-to-room assembler.

Aligns rooms at their gate/wall entry-exit objects, resolving tile overlap by
shifting the newly-attached room to an adjacent floor (+/-1 relative to the
room it's connecting from) instead of moving tiles within a floor.
"""

from __future__ import annotations

import json
import math
import random
from collections import deque

import pygame

from core.world.dungeon import Dungeon
from core.world.entities import PlayerRef
from core.editor.autotile import EMPTY, FLOOR, WALL
from core.data.ressources import DONJONS_DIRECTORY

OPPOSITE_SIDE = {"north": "south", "south": "north", "east": "west", "west": "east"}

# How many full generate_assembly attempts to try before settling for the
# best one seen -- see generate_assembly's own docstring for why whole
# attempts are regenerated rather than steering a single one.
GENERATION_ATTEMPTS = 25


def _valid_entry_exits(dungeon):
    """gate/wall/cave_entrance/big_entrance objects (plus any custom type
    registered with the "porte" archetype -- ObjectManager.is_es_type is
    the single source of truth for E/S membership, so a custom E/S is a
    genuine assembler-eligible connector here, not just placeable in the
    editor) that actually qualify as a room-to-room connection:
    ObjectManager.is_valid_doorway (a WALL cell with one FLOOR neighbor
    opposite one EMPTY neighbor, WALL flanking the rest) means this exit
    genuinely borders the void, not just another spot inside the room. A
    gate/wall placed with no void neighbor (e.g. a locked door gating a
    side room) still works as an ordinary in-room obstacle -- it's just
    never picked as a connector here. Also excludes anything flagged
    "dungeon_entrance"/"dungeon_exit" (ObjectManager.get_role) -- neither
    is ever an ordinary inter-room connector: a dungeon_entrance only ever
    lives in home (never generation material in practice) and a
    dungeon_exit is meant to stay a genuine dead end in whichever room it
    lands in, not get merged with another room."""
    return [
        obj for obj in dungeon.object_manager.objects
        if dungeon.object_manager.is_es_type(obj["type"])
        and dungeon.object_manager.get_role(obj) == "connector"
        # The object's own anchor cell (bottom-center of its footprint), not
        # just its stored origin -- same check placement itself already
        # went through (see ObjectManager._valid_doorway_anchor's own
        # docstring), so a multi-cell E/S (a 2-wide "wall"/"big_entrance",
        # or a custom "porte" of any size) is validated identically here
        # and at placement time.
        and dungeon.object_manager._valid_doorway_anchor(obj["type"], obj["x"], obj["y"])
    ]


def _border_edges(dungeon):
    """Contiguous runs of FLOOR cells sitting exactly on one of the room's
    own 4 grid edges -- e.g. every cell in row 0 that's FLOOR. A FLOOR cell
    on a grid edge naturally has no WALL on the side facing off-grid
    (build_walls_around never walls an out-of-bounds neighbor -- see
    autotile.py), so these are already open, wall-free connection points
    with no gate/wall object needed at all: two rooms glued here just
    continue as one uninterrupted floor, no door in between (see
    _attach_via_border). Returns a list of (side, start, length) tuples,
    "start" being the local row (north/south) or column (east/west) index
    where the run begins."""
    w, h = dungeon.width, dungeon.height
    grid = dungeon.logical_grid
    edges = []

    def _collect(side, is_floor_along_line):
        run_start = None
        for i, is_floor in enumerate(is_floor_along_line):
            if is_floor and run_start is None:
                run_start = i
            elif not is_floor and run_start is not None:
                edges.append((side, run_start, i - run_start))
                run_start = None
        if run_start is not None:
            edges.append((side, run_start, len(is_floor_along_line) - run_start))

    _collect("north", [grid[0][x] == FLOOR for x in range(w)])
    _collect("south", [grid[h - 1][x] == FLOOR for x in range(w)])
    _collect("west", [grid[y][0] == FLOOR for y in range(h)])
    _collect("east", [grid[y][w - 1] == FLOOR for y in range(h)])

    return edges


class PlacedRoom:
    """A Dungeon placed at a given floor and global grid offset within a DungeonAssembly.

    `index` is this room's position in the owning DungeonAssembly.rooms list,
    known to the caller at construction time (generate_assembly/load_assembly
    both add rooms in a stable, deterministic order) -- it's how a door object's
    "door_target_room" reference resolves back to a specific PlacedRoom.
    """

    def __init__(self, dungeon, room_name, floor, offset_x, offset_y, index):
        self.dungeon = dungeon
        self.room_name = room_name
        self.floor = floor
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.index = index
        self._occupied_cells_cache = None

    def to_global(self, local_x, local_y):
        return self.offset_x + local_x, self.offset_y + local_y

    def occupied_cells(self):
        """Global (x, y) -> logical cell type, for every non-empty cell in
        this room. Cached: a placed room's own logical_grid never changes
        for the lifetime of this PlacedRoom (destructibility isn't
        implemented yet -- see CLAUDE.md -- and Creator's painting tools
        are suspended while a generated dungeon is being previewed), so the
        first scan is reused for every later call instead of rescanning the
        full grid every time -- this is called repeatedly inside
        generate_assembly's own placement search (_fits, _collides), where
        it used to dominate generation cost on a large room pool."""
        if self._occupied_cells_cache is None:
            cells = {}
            for y, row in enumerate(self.dungeon.logical_grid):
                for x, cell in enumerate(row):
                    if cell != EMPTY:
                        cells[self.to_global(x, y)] = cell
            self._occupied_cells_cache = cells
        return self._occupied_cells_cache

    def entry_exits(self):
        return _valid_entry_exits(self.dungeon)

    def border_edges(self):
        return _border_edges(self.dungeon)

    def has_spawn(self):
        return any(obj["type"] == "spawn" for obj in self.dungeon.object_manager.objects)


class DungeonAssembly:
    """Several rooms placed in a shared global grid, some possibly sharing (x, y) but on different floors."""

    def __init__(self):
        self.rooms = []
        # floor -> [PlacedRoom, ...], kept in sync by add_room (the only
        # place self.rooms is ever mutated after __init__ -- generate_assembly
        # always finalizes a room's .floor before calling add_room, never
        # after). rooms_on_floor is called from nearly every per-frame
        # collision/render/button query in this class and from Explorator's
        # own _rooms_with_offset, so an O(total rooms) scan per call adds up
        # fast on an assembly with many rooms/floors -- this makes it O(1)
        # plus the size of just that floor's own room list.
        self._rooms_by_floor = {}
        self._shadow_cache = {}
        self._gradient_hole_cache = {}
        self._below_cache = {}
        self._border_cache = {}  # floor -> (terrain_version tuple, {room: hide_border_cells}) -- see _border_cells_by_room
        # floor -> merged occupied_cells() dict, see occupied_cells_on_floor
        # -- invalidated per-floor by add_room, the only mutator.
        self._occupied_cache = {}

    def add_room(self, placed_room):
        self.rooms.append(placed_room)
        self._rooms_by_floor.setdefault(placed_room.floor, []).append(placed_room)
        # A new room on this floor changes what occupied_cells_on_floor(floor)
        # must return -- drop just that floor's cached merge (individual
        # rooms' own occupied_cells() stay valid and cached, see PlacedRoom).
        self._occupied_cache.pop(placed_room.floor, None)

    def rooms_on_floor(self, floor):
        return self._rooms_by_floor.get(floor, [])

    def floors(self):
        return sorted(self._rooms_by_floor.keys())

    def occupied_cells_on_floor(self, floor):
        """Merged occupied_cells() of every room on `floor`. Cached per
        floor (unlike PlacedRoom.occupied_cells(), which is cheap to keep
        forever, a floor's merge must invalidate whenever add_room places a
        new room there -- see add_room) -- called repeatedly inside
        generate_assembly's own placement search (_fits/_collides), where
        re-merging every room on a floor from scratch on every candidate
        placement used to dominate generation cost as the room pool grew."""
        cached = self._occupied_cache.get(floor)
        if cached is not None:
            return cached
        cells = {}
        for room in self.rooms_on_floor(floor):
            cells.update(room.occupied_cells())
        self._occupied_cache[floor] = cells
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

    def locate_room(self, global_x, global_y, floor, prefer_room=None):
        """The room *on `floor`* that actually occupies (global_x, global_y).

        Scoped to a single floor on purpose: collision must never consider
        another floor's rooms, or two rooms that happen to share a bounding
        box (they're built from the same source rooms, so this is common)
        could let the player "phase" through a wall that's solid on their
        own floor just because an unrelated room on another floor happens to
        have FLOOR at that same global cell. Crossing floors (or rooms) is
        handled separately, via `resolve_room_transition` -- see
        generate_assembly's door_target_room.

        Prefers staying in `prefer_room` if it still claims the cell (checked
        first), then falls back to any other room on `floor`. Checks FLOOR
        ownership first, only falling back to "any non-empty cell" (a WALL,
        e.g. an unrelated auto-generated halo) if nothing claims FLOOR there.
        """
        rooms = self.rooms_on_floor(floor)
        candidates = ([prefer_room] if prefer_room in rooms else []) + rooms

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

    def resolve_room_transition(self, current_room, last_door_obj, global_x, global_y):
        """Edge-triggered room switch across a gate/wall entry-exit: stepping
        onto a door cell that carries a "door_target_room" (stamped by
        generate_assembly on both halves of a merged doorway, whether it's a
        same-floor E/S or a cross-floor portal -- both use the identical
        mechanism now) switches to that room exactly once, on entry.

        This deliberately does NOT re-derive the current room from FLOOR
        ownership every frame (that's what `locate_room` is for, and it's
        still used for collision/button resolution) -- a door crossing is a
        discrete event, not a continuous "which room owns this pixel" query.
        Standing still on the shared door cell must not flip back and forth,
        and going back the way you came requires fully leaving the door cell
        and re-entering it from the other room's side.

        `last_door_obj` is the door object (a plain dict from some room's
        object list) the player was resolved to be on last frame, or None.
        Returns (room, last_door_obj) for the caller to store back.
        """
        local_x, local_y = global_x - current_room.offset_x, global_y - current_room.offset_y
        door_obj = current_room.dungeon.object_manager.get_object_at(local_x, local_y)

        if door_obj is None:
            return current_room, None

        if door_obj is last_door_obj or "door_target_room" not in door_obj:
            return current_room, last_door_obj

        target_room = self.rooms[door_obj["door_target_room"]]
        target_local_x = global_x - target_room.offset_x
        target_local_y = global_y - target_room.offset_y
        # Re-derive the door as seen from the *target* room, not the one we
        # just left -- next frame's lookup happens via target_room, so
        # comparing against door_obj (the source room's copy) would never
        # match and would re-trigger a bounce straight back.
        target_door_obj = target_room.dungeon.object_manager.get_object_at(target_local_x, target_local_y)

        # The player could only physically reach this cell because door_obj
        # (this room's own copy) read as open -- but the two halves of a
        # merged doorway are separate object dicts with independent state
        # (see generate_assembly), and could disagree (an assembly_links
        # propagation gap, or a stale save carrying a baked-in "open" key).
        # Force them back into agreement at the moment of crossing so a
        # crossing that was valid on this side can never stand the player
        # against a closed copy on the other side -- this is what was
        # actually producing "stuck inside a wall after taking an open
        # door" (resolve_room_transition never used to check the
        # destination at all).
        if target_door_obj is not None and door_obj.get("open"):
            target_door_obj["open"] = True
            target_door_obj["activated"] = door_obj.get("activated", True)
            target_door_obj["frame"] = door_obj.get("frame", target_door_obj.get("frame", 0))
            target_room.dungeon.object_manager.begin_animation(target_door_obj)

        return target_room, target_door_obj

    def is_global_cell_walkable(self, global_x, global_y, floor, prefer_room=None):
        room = self.locate_room(global_x, global_y, floor, prefer_room=prefer_room)
        if room is None:
            return False
        return room.dungeon.object_manager.is_cell_walkable(global_x - room.offset_x, global_y - room.offset_y)

    def check_button_trigger(self, global_x, global_y, floor, prefer_room=None):
        """Assembly-aware equivalent of ObjectManager.check_button_trigger -- resolves
        both same-room links (local {"x","y"}) and cross-room ones
        (assembly_links: {"floor","x","y"} in global coordinates, added at
        generation time -- see generate_assembly). Scoped to `floor` for the
        same reason locate_room is: the player can only ever press a button
        that's actually on their current floor.
        """
        room = self.locate_room(global_x, global_y, floor, prefer_room=prefer_room)
        if room is None:
            return

        local_x, local_y = global_x - room.offset_x, global_y - room.offset_y
        object_manager = room.dungeon.object_manager
        obj = object_manager.get_object_at(local_x, local_y)

        if obj is None or obj["type"] != "button" or obj.get("activated"):
            return

        object_manager._activate_button(obj)

        for link_target in obj.get("links", []):
            target = object_manager.get_object_at(link_target["x"], link_target["y"])
            object_manager._open_if_blocking(target, object_manager)

        for link_target in obj.get("assembly_links", []):
            # "room" (a room index, added at generation time -- see
            # generate_assembly) is the authoritative target when present.
            # room_at's bounding-box search is ambiguous for a same-floor
            # doorway merge, where the anchor and candidate rooms' bounds
            # both legitimately contain the shared door cell -- it always
            # resolved to whichever room was inserted first (the anchor),
            # so a button in the anchor room could never actually reach the
            # candidate's copy through this path. Older saved donjons don't
            # have "room" on their assembly_links entries yet (additive
            # field, same as variant/links/open), so room_at is kept as a
            # best-effort fallback for those rather than breaking them.
            room_index = link_target.get("room")
            if room_index is not None:
                target_room = self.rooms[room_index] if 0 <= room_index < len(self.rooms) else None
            else:
                target_room = self.room_at(link_target["floor"], link_target["x"], link_target["y"])
            if target_room is None:
                continue
            target = target_room.dungeon.object_manager.get_object_at(
                link_target["x"] - target_room.offset_x,
                link_target["y"] - target_room.offset_y,
            )
            target_room.dungeon.object_manager._open_if_blocking(target, target_room.dungeon.object_manager)

    def update(self, dt, player_refs_by_floor=None, magnet_radius=0):
        """player_refs_by_floor ({floor: [PlayerRef, ...]}) only ever gets
        passed down to rooms on a matching floor -- a mob on
        another floor has no business colliding (or, for enemies, aggroing)
        with a player who isn't physically there (mirrors locate_room's
        per-floor scoping). Grouped by floor rather than one scalar
        "player_floor" because two sessions can now genuinely be on two
        different floors at once (see PlayerSession.current_placed_room) --
        each floor's rooms must only ever see the refs of players actually
        on that floor. Each ref's hitbox arrives in global coordinates
        (that's what Explorator/the player use everywhere), but each room's
        own Dungeon only ever thinks in that room's local coordinates --
        same as is_global_cell_walkable converting before delegating to a
        room's ObjectManager -- so it's shifted back by that room's offset
        here before being handed down. Each ref's `player`/`session` (the
        actual objects, for take_damage / whichever session a future
        combat-adjacent feature needs) are forwarded as-is -- no coordinate
        transform needed since only their identity matters here, never .position (see
        MobManager/Mob, which only ever read distances
        from the already-shifted hitbox).

        Only rooms on a floor within SHADOW_MAX_DISTANCE of some occupied
        floor are actually simulated -- a room nobody is near (no player on
        its floor, and not even visible as a tinted shadow/below floor,
        since that's exactly what SHADOW_MAX_DISTANCE bounds -- see render())
        has its object animations/mob wandering/aggro AI frozen instead of
        ticking every frame for no one to see. This used to simulate every
        room in the whole assembly unconditionally, which scales as O(total
        rooms x entities) regardless of how much of the dungeon is actually
        in play. Freezing is harmless and self-healing: an object's animation
        just holds where it was and resumes the next tick a player is close
        enough again, same as this class's own shadow/below render caches
        already tolerate staleness on floors that aren't the active one.
        """
        player_refs_by_floor = player_refs_by_floor or {}
        if not player_refs_by_floor:
            return

        active_floors = set()
        for floor in player_refs_by_floor:
            for offset in range(-self.SHADOW_MAX_DISTANCE, self.SHADOW_MAX_DISTANCE + 1):
                active_floors.add(floor + offset)

        tile_size = Dungeon.TILE_SIZE
        for room in self.rooms:
            if room.floor not in active_floors:
                continue
            refs_on_floor = player_refs_by_floor.get(room.floor, ())
            local_refs = [
                PlayerRef(
                    ref.player, ref.hitbox.move(-room.offset_x * tile_size, -room.offset_y * tile_size), ref.session,
                )
                for ref in refs_on_floor
            ]
            room.dungeon.update(
                dt, player_refs=local_refs, magnet_radius=magnet_radius,
                room_offset=(room.offset_x * tile_size, room.offset_y * tile_size),
            )

    # ------------------------------------------------------------------
    # Rendering -- the active floor is drawn normally (full tiles/objects/
    # mobs); every other floor is drawn as a cheap cached "shadow" of its
    # rooms' logical footprints only (see _render_floor_shadow), never a full
    # re-render, since it's never interacted with directly. Floor distance
    # from active_floor picks both the tint (black above, grey below) and the
    # opacity; anything more than SHADOW_MAX_DISTANCE floors away isn't drawn
    # at all.
    #
    # Floors BELOW draw before the active floor (underneath it, a floor you
    # glimpse through gaps) -- a flat, constant tint, no hole. Floors ABOVE
    # draw AFTER the active floor (a ceiling on top of it, blocking the view)
    # with a soft-edged hole cut out around the player so their own floor
    # stays visible close to them, exactly like the pre-shadow-cache version.
    # ------------------------------------------------------------------

    SHADOW_OPACITY_STEP = 0.34  # opacity lost per floor of distance from active_floor
    SHADOW_MAX_DISTANCE = 2  # floors beyond this aren't drawn at all
    SHADOW_COLOR_ABOVE = (0, 0, 0)
    SHADOW_COLOR_BELOW = (150, 150, 150)
    # ~50% white/blue BLEND_RGBA_MULT tint for floors below active_floor (see
    # _get_below_render) -- multiplying (not a plain alpha-over blend) leaves
    # fully-transparent void pixels at alpha 0 while still tinting the real
    # tile/object art, so the player can actually see which tile they'd land
    # on, not just a flat silhouette.
    BELOW_TINT_COLOR = (167, 197, 255, 255)
    VISION_RADIUS_TILES = 4.5
    VISION_FALLOFF_TILES = 1.5  # width of the soft edge just inside VISION_RADIUS_TILES

    def render(self, screen, camera, active_floor, player_world_pos=None, hide_object_types=None,
               skip_active_floor_foreground=False, skip_active_floor_mobs=False, show_grid=True):
        """Draw every floor relative to active_floor: floors below first
        (flat-tinted shadow, no hole), the active floor with full detail,
        floors above last (shadow with a soft hole around player_world_pos --
        a continuous world pixel position, omit it, e.g. Creator's static
        preview with no player, to render them with no hole at all).

        skip_active_floor_foreground lets a caller that draws its own player
        sprite (Explorator) leave out active_floor's foreground objects (an
        L/R torch) here and draw them afterwards via
        render_active_floor_foreground(), so the player ends up behind them.
        skip_active_floor_mobs works the same way for active_floor's live
        Mobs, letting Explorator draw them together with the player via
        render_active_floor_entities() instead, sorted by feet position so
        whichever is lower on screen draws in front. Creator, which draws
        no player sprite, leaves both off and gets everything in one pass.
        """
        for floor in self.floors():
            if floor < active_floor:
                self._render_floor_below(screen, camera, floor, active_floor, hide_object_types=hide_object_types)

        self._render_floor(
            screen, camera, active_floor,
            hide_object_types=hide_object_types,
            skip_foreground=skip_active_floor_foreground,
            skip_mobs=skip_active_floor_mobs,
            show_grid=show_grid,
        )

        for floor in self.floors():
            if floor > active_floor:
                self._render_floor_shadow(screen, camera, floor, active_floor, player_world_pos=player_world_pos)

    def render_active_floor_foreground(self, screen, camera, active_floor, hide_object_types=None):
        """Objects ObjectManager.is_foreground_object() flags (e.g. an L/R torch) on active_floor -- call after drawing the player sprite."""
        tile_size = Dungeon.TILE_SIZE
        for room in self.rooms_on_floor(active_floor):
            offset_camera = _OffsetCamera(camera, room.offset_x * tile_size, room.offset_y * tile_size)
            room.dungeon.render_foreground(screen, offset_camera, hide_object_types=hide_object_types)

    def render_active_floor_entities(self, screen, camera, active_floor, players):
        """Y-sorted draw of every live Mob on active_floor plus every player
        in `players`: whichever entity's feet (.position.y, in the same
        world-pixel sense Mob/Player.get_hitbox() anchor their hitbox to)
        sit lower on screen draws in front, matching how a top-down scene
        actually reads. Call after render(..., skip_active_floor_mobs=True)
        and before render_active_floor_foreground() -- same slot a single
        player used to occupy alone via a plain player.draw().

        A mob's .position is local to its own room's Dungeon (no offset
        baked in, unlike a player's, which is already global -- see
        DungeonAssembly.update's docstring), so it's converted to a global y
        here purely for comparison; drawing itself still goes through that
        room's own offset camera, same as every other per-room draw call.
        """
        tile_size = Dungeon.TILE_SIZE
        entries = []

        for room in self.rooms_on_floor(active_floor):
            offset_camera = _OffsetCamera(camera, room.offset_x * tile_size, room.offset_y * tile_size)
            for mob in room.dungeon.mob_manager.mobs:
                global_y = mob.position.y + room.offset_y * tile_size
                entries.append((global_y, mob, offset_camera))

        for player in players:
            entries.append((player.position.y, player, camera))

        entries.sort(key=lambda entry: entry[0])
        for _, entity, entity_camera in entries:
            entity.draw(screen, entity_camera)

    def _render_floor(self, screen, camera, floor, hide_object_types=None, skip_foreground=False,
                       skip_mobs=False, show_grid=True):
        tile_size = Dungeon.TILE_SIZE
        rooms = self.rooms_on_floor(floor)
        hide_border_cells_by_room = self._border_cells_by_room(floor, rooms)

        # Two passes, not one -- every room's own floor/objects first
        # (show_border=False), THEN every room's border ledge in a second,
        # guaranteed-last loop (see WorldRenderer.render_border's own
        # docstring). hide_border_cells_by_room already suppresses a ledge
        # at a genuine border-merge seam, but this ordering is a real
        # safety net on top of that filter: even a seam it somehow missed
        # still gets painted OVER by the neighboring room's real floor
        # (drawn in THIS SAME pass-1 loop, at a different iteration) rather
        # than risk a stray ledge landing on top of it depending on
        # whichever order `rooms` happens to iterate in.
        offset_cameras = {}
        for room in rooms:
            offset_camera = _OffsetCamera(camera, room.offset_x * tile_size, room.offset_y * tile_size)
            offset_cameras[room] = offset_camera
            room.dungeon.render(
                screen, offset_camera,
                hide_object_types=hide_object_types,
                skip_foreground_objects=skip_foreground,
                skip_mobs=skip_mobs,
                show_grid=show_grid,
                show_border=False,
            )

        for room in rooms:
            room.dungeon.render_border(
                screen, offset_cameras[room], hide_border_cells=hide_border_cells_by_room.get(room, ()),
            )

    def _border_cells_by_room(self, floor, rooms):
        """{room: hide_border_cells} for every room on `floor` (see
        _south_seam_cells) -- cached per floor and only recomputed when some
        room's Dungeon.terrain_version has actually changed (destroy_area is
        the only thing that bumps it for a room inside an assembly -- Creator
        painting also bumps terrain_version, but only ever on a standalone
        single-room Dungeon, never one that's part of a DungeonAssembly),
        since _render_floor runs every frame at 60fps but the underlying seam
        data is static except after a rare, event-driven terrain edit.
        `occupied_cells_on_floor` already does the
        "merge every room's occupied_cells" work this used to re-derive by
        hand.

        This class's other render caches (_shadow_cache/_below_cache) never
        invalidate at all -- terrain edits are rare enough that staleness
        there hasn't mattered in practice. This one is versioned instead,
        since a stale seam would visibly paint a false ledge over (or leave
        a gap in front of) a room's own floor after a destroy_area."""
        cache_key = tuple(room.dungeon.terrain_version for room in rooms)
        cached = self._border_cache.get(floor)
        if cached is not None and cached[0] == cache_key:
            return cached[1]

        floor_floor_cells = {
            cell for cell, cell_type in self.occupied_cells_on_floor(floor).items() if cell_type == FLOOR
        }
        result = {room: self._south_seam_cells(room, floor_floor_cells) for room in rooms}
        self._border_cache[floor] = (cache_key, result)
        return result

    @staticmethod
    def _south_seam_cells(room, floor_floor_cells):
        """Local (x, height-1) south-edge FLOOR cells of `room` whose global
        south neighbor is FLOOR belonging to some room on the same floor --
        a genuine _border_edges seam, not real void (see _render_floor)."""
        height, width = room.dungeon.height, room.dungeon.width
        grid = room.dungeon.logical_grid
        seam_cells = set()
        for x in range(width):
            if grid[height - 1][x] != FLOOR:
                continue
            if room.to_global(x, height) in floor_floor_cells:
                seam_cells.add((x, height - 1))
        return seam_cells

    def _render_floor_shadow(self, screen, camera, floor, active_floor, player_world_pos=None):
        """player_world_pos only ever matters for a floor ABOVE active_floor
        (see render()'s docstring) -- a floor below never gets a hole."""
        distance = abs(floor - active_floor)
        if distance == 0 or distance > self.SHADOW_MAX_DISTANCE:
            return

        opacity = max(0.0, 1.0 - self.SHADOW_OPACITY_STEP * distance)
        tone = self.SHADOW_COLOR_ABOVE if floor > active_floor else self.SHADOW_COLOR_BELOW
        color = (*tone, int(255 * opacity))

        hole_patch = hole_center = None
        if player_world_pos is not None:
            radius_px = int(self.VISION_RADIUS_TILES * Dungeon.TILE_SIZE * camera.zoom)
            falloff_px = int(self.VISION_FALLOFF_TILES * Dungeon.TILE_SIZE * camera.zoom)
            hole_patch = self._gradient_hole(radius_px, falloff_px)
            hole_center = camera.world_to_screen(*player_world_pos)

        tile_size = Dungeon.TILE_SIZE
        for room in self.rooms_on_floor(floor):
            shadow = self._get_shadow(room, color, camera.zoom)
            screen_pos = camera.world_to_screen(room.offset_x * tile_size, room.offset_y * tile_size)
            room_rect = pygame.Rect(screen_pos, shadow.get_size())

            if hole_patch is not None:
                hole_rect = hole_patch.get_rect(center=(int(hole_center[0]), int(hole_center[1])))
                if room_rect.colliderect(hole_rect):
                    # Only rooms the vision circle actually overlaps pay for a
                    # copy + patch blit -- every other room (the common case)
                    # stays on the plain cached-blit-only path above. MULT
                    # (not MIN) because the shadow's own alpha is already
                    # below 255 (its distance-based opacity) -- multiplying
                    # scales it proportionally by the hole's 0..255 gradient,
                    # so the falloff still spans the whole band instead of
                    # clamping flat as soon as the hole's alpha passes the
                    # shadow's own (which MIN would do).
                    shadow = shadow.copy()
                    local_pos = (hole_rect.x - room_rect.x, hole_rect.y - room_rect.y)
                    shadow.blit(hole_patch, local_pos, special_flags=pygame.BLEND_RGBA_MULT)

            screen.blit(shadow, screen_pos)

    def _render_floor_below(self, screen, camera, floor, active_floor, hide_object_types=None):
        """Real tiles/objects of `floor` (see _get_below_render), blue-tinted
        and faded by distance from active_floor -- replaces the old flat grey
        silhouette so the player can see concretely which tile they'd land on
        falling through void, not just that "something" is down there."""
        distance = active_floor - floor
        if distance <= 0 or distance > self.SHADOW_MAX_DISTANCE:
            return

        opacity = max(0.0, 1.0 - self.SHADOW_OPACITY_STEP * distance)

        tile_size = Dungeon.TILE_SIZE
        for room in self.rooms_on_floor(floor):
            rendered = self._get_below_render(room, camera.zoom, hide_object_types)
            rendered.set_alpha(int(255 * opacity))
            screen_pos = camera.world_to_screen(room.offset_x * tile_size, room.offset_y * tile_size)
            screen.blit(rendered, screen_pos)

    def _get_below_render(self, room, zoom, hide_object_types):
        """A cached, blue-tinted render of `room`'s actual tiles/objects (not
        just its logical footprint, unlike _get_shadow) -- mobs are
        excluded since this cache isn't refreshed every frame, so a live
        position baked into it would go stale immediately. Rendered onto its
        own zero-offset surface via _ZoomOnlyCamera, independent of the real
        camera's current pan position, then tinted once with
        BLEND_RGBA_MULT. Cached per (room, zoom) -- distance-based fade is
        applied afterwards via set_alpha, not baked in, so one cached surface
        covers every distance.

        Keyed on tile_px (the rounded per-tile pixel size zoom actually
        resolves to), not the raw zoom float -- same reasoning as
        WorldRenderer._get_scaled_tile's own cache: Camera.zoom_at's
        *1.2/0.8 steps rarely land on the exact same float twice, so keying
        on zoom made this cache grow by one full room-sized Surface per
        room x every distinct zoom float ever visited, for the entire
        lifetime of the assembly, instead of collapsing every zoom that
        rounds to the same pixel size onto one entry."""
        tile_size = Dungeon.TILE_SIZE
        tile_px = round(tile_size * zoom)
        key = (room, tile_px)
        cached = self._below_cache.get(key)
        if cached is not None:
            return cached

        size = (
            max(1, round(room.dungeon.width * tile_size * zoom)),
            max(1, round(room.dungeon.height * tile_size * zoom)),
        )
        surface = pygame.Surface(size, pygame.SRCALPHA)
        room.dungeon.render(
            surface, _ZoomOnlyCamera(zoom),
            hide_object_types=hide_object_types,
            skip_mobs=True,
            show_grid=False,
            show_border=False,
        )
        surface.fill(self.BELOW_TINT_COLOR, special_flags=pygame.BLEND_RGBA_MULT)

        self._below_cache[key] = surface
        return surface

    def _get_shadow(self, room, color, zoom):
        """A cached, pre-tinted silhouette of `room`'s logical footprint --
        every non-EMPTY cell filled with `color` (an (r, g, b, alpha) tuple),
        no tiles/objects/mobs at all -- scaled to `zoom`. Built once per
        (room, color, zoom): color is fully determined by floor distance and
        direction (see _render_floor_shadow), so at most 2*SHADOW_MAX_DISTANCE
        variants of a given room's shadow are ever cached, each a single blit
        per frame afterwards instead of a full tile-by-tile re-render.

        Keyed on tile_px, not the raw zoom float -- same reasoning as
        _get_below_render's own cache (see its docstring): keying on zoom
        made this grow by one room-sized Surface per room x color x every
        distinct zoom float ever visited, instead of collapsing every zoom
        that rounds to the same pixel size onto one entry."""
        tile_size = Dungeon.TILE_SIZE
        tile_px = round(tile_size * zoom)
        key = (room, color, tile_px)
        cached = self._shadow_cache.get(key)
        if cached is not None:
            return cached

        base = pygame.Surface((room.dungeon.width * tile_size, room.dungeon.height * tile_size), pygame.SRCALPHA)
        for y, row in enumerate(room.dungeon.logical_grid):
            for x, cell in enumerate(row):
                if cell != EMPTY:
                    base.fill(color, (x * tile_size, y * tile_size, tile_size, tile_size))

        size = (max(1, round(base.get_width() * zoom)), max(1, round(base.get_height() * zoom)))
        scaled = pygame.transform.scale(base, size)
        self._shadow_cache[key] = scaled
        return scaled

    def _gradient_hole(self, radius_px, falloff_px):
        """A small cached SRCALPHA patch: alpha 0 (fully punched) out to
        (radius_px - falloff_px), then a linear ramp up to alpha 255 (no
        effect once multiplied into a shadow) at radius_px and beyond -- a
        soft-edged hole instead of a hard-edged circle. Built once per
        (radius_px, falloff_px) pair (both vary only with zoom, not every
        frame) by stamping successively smaller filled circles from the
        outside in, each one's alpha computed for its own radius -- O(radius_px)
        draw calls on a cache miss instead of a per-pixel loop.
        """
        key = (radius_px, falloff_px)
        patch = self._gradient_hole_cache.get(key)
        if patch is not None:
            return patch

        size = radius_px * 2 + 2
        patch = pygame.Surface((size, size), pygame.SRCALPHA)
        patch.fill((255, 255, 255, 255))
        center = (radius_px + 1, radius_px + 1)
        inner_radius = max(radius_px - falloff_px, 0)
        falloff_span = max(radius_px - inner_radius, 1)

        for r in range(radius_px, -1, -1):
            if r <= inner_radius:
                alpha = 0
            else:
                alpha = int(255 * (r - inner_radius) / falloff_span)
            pygame.draw.circle(patch, (255, 255, 255, alpha), center, r)

        self._gradient_hole_cache[key] = patch
        return patch


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


class _ZoomOnlyCamera:
    """A stationary camera at a fixed zoom, no panning -- used by
    _get_below_render to render a room's own tiles/objects into an
    independent cache surface, decoupled from wherever the live scrolling
    camera currently points (only its zoom matters for that cache)."""

    def __init__(self, zoom):
        self.zoom = zoom

    def world_to_screen(self, world_x, world_y):
        return world_x * self.zoom, world_y * self.zoom


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


def _find_start_room(room_names, rng=None):
    """A random room among room_names with both a spawn and a valid way out
    -- a gate/wall entry-exit or a border-floor edge (see _border_edges),
    either is enough to start growing the assembly from. Previously always
    the FIRST such room in room_names order, which meant every generation
    from a given pool started from the same room every time (whichever the
    multi-select pool happened to list first) -- rng.choice over every
    qualifying candidate instead, same rng generate_assembly already
    threads through every other random pick here."""
    if rng is None:
        rng = random
    candidates = []
    for room_name in room_names:
        dungeon = _load_room(room_name)
        has_spawn = any(obj["type"] == "spawn" for obj in dungeon.object_manager.objects)
        if has_spawn and (_valid_entry_exits(dungeon) or _border_edges(dungeon)):
            candidates.append((room_name, dungeon))
    if not candidates:
        return None, None
    return rng.choice(candidates)


def _border_offset(anchor_room, anchor_edge, candidate_dungeon, candidate_edge):
    """Global (offset_x, offset_y) placing candidate_dungeon directly,
    seamlessly adjacent to anchor_room along anchor_edge's side -- the two
    border-floor runs (see _border_edges) end up continuing as one
    uninterrupted strip of floor, no shared/overlapping cell at all (unlike
    an entry-exit merge, which aligns onto the *same* global cell)."""
    side, anchor_start, _length = anchor_edge
    _cand_side, candidate_start, _cand_length = candidate_edge
    anchor_w, anchor_h = anchor_room.dungeon.width, anchor_room.dungeon.height

    if side == "east":
        offset_x = anchor_room.offset_x + anchor_w
        offset_y = anchor_room.offset_y + anchor_start - candidate_start
    elif side == "west":
        offset_x = anchor_room.offset_x - candidate_dungeon.width
        offset_y = anchor_room.offset_y + anchor_start - candidate_start
    elif side == "south":
        offset_y = anchor_room.offset_y + anchor_h
        offset_x = anchor_room.offset_x + anchor_start - candidate_start
    else:  # "north"
        offset_y = anchor_room.offset_y - candidate_dungeon.height
        offset_x = anchor_room.offset_x + anchor_start - candidate_start

    return offset_x, offset_y


def _attach_via_border(rng, room_names, assembly, anchor_room, anchor_edge):
    """Try to glue another room directly onto anchor_room's border-floor run
    (anchor_edge) -- no gate/wall object at all, the floor just continues
    seamlessly across the seam, reading as one continuous room rather than
    two rooms joined by a door. Requires an exact length match on the
    opposite side (kept simple on purpose: partial-overlap alignment would
    need its own conflict-resolution story). Unlike an entry-exit merge,
    this never steps to a different floor on collision -- a seam that
    doesn't fit as a flat, same-floor continuation just isn't placed at all,
    since a floor-shifted "seamless" room would no longer actually read as
    one continuous room. Returns (new PlacedRoom, the edge it consumed) or
    None if nothing fit."""
    opposite = OPPOSITE_SIDE[anchor_edge[0]]

    candidate_name = rng.choice(room_names)
    candidate_dungeon = _load_room(candidate_name)
    candidate_edges = [
        edge for edge in _border_edges(candidate_dungeon)
        if edge[0] == opposite and edge[2] == anchor_edge[2]
    ]
    if not candidate_edges:
        return None

    candidate_edge = rng.choice(candidate_edges)
    offset_x, offset_y = _border_offset(anchor_room, anchor_edge, candidate_dungeon, candidate_edge)

    candidate_room = PlacedRoom(
        candidate_dungeon, candidate_name, anchor_room.floor, offset_x, offset_y, index=len(assembly.rooms)
    )

    if _collides(assembly.occupied_cells_on_floor(anchor_room.floor), candidate_room.occupied_cells()):
        return None

    assembly.add_room(candidate_room)
    return candidate_room, candidate_edge


def _room_has_dungeon_exit(dungeon):
    """True if `dungeon` carries at least one object explicitly tagged
    role="dungeon_exit" (an E/S or a chest, see ObjectManager.get_role) --
    the pool-level test used to find which rooms in a player's selection
    are even CAPABLE of ending a generated dungeon, before generate_assembly
    tries to guarantee one gets placed (see its own docstring)."""
    manager = dungeon.object_manager
    return any(manager.get_role(obj) == "dungeon_exit" for obj in manager.objects)


def _attach_via_exit(rng, room_names, assembly, anchor_room, anchor_exit):
    """Try to attach a new room onto anchor_room via an entry-exit merge
    through anchor_exit -- the "exit"-kind pending item's own placement
    logic (aligning two same-typed gate/wall objects onto one shared global
    cell, stepping to an adjacent floor on collision, propagating a button
    link across the merged doorway). Returns (new PlacedRoom, the exit it
    consumed) or None if no room in room_names has a same-typed connector.

    Extracted out of generate_assembly's own main loop (which still calls
    this for its ordinary random draws) so the guaranteed-exit pass below
    can reuse the EXACT same attachment mechanics against a narrower pool
    (only rooms carrying a dungeon_exit-tagged object, see
    _room_has_dungeon_exit) -- same "one mechanism, two callers" shape as
    _attach_via_border already has."""
    candidate_name = rng.choice(room_names)
    candidate_dungeon = _load_room(candidate_name)
    candidate_exits = _valid_entry_exits(candidate_dungeon)
    matching_exits = [obj for obj in candidate_exits if obj["type"] == anchor_exit["type"]]
    if not matching_exits:
        return None

    candidate_exit = rng.choice(matching_exits)

    anchor_gx, anchor_gy = anchor_room.to_global(anchor_exit["x"], anchor_exit["y"])
    offset_x = anchor_gx - candidate_exit["x"]
    offset_y = anchor_gy - candidate_exit["y"]

    candidate_index = len(assembly.rooms)
    candidate_room = PlacedRoom(
        candidate_dungeon, candidate_name, anchor_room.floor, offset_x, offset_y, index=candidate_index
    )
    candidate_cells = candidate_room.occupied_cells()
    shared_cell = (anchor_gx, anchor_gy)

    def _fits(floor):
        return not _collides(assembly.occupied_cells_on_floor(floor), candidate_cells, ignore=shared_cell)

    floor = anchor_room.floor
    if not _fits(floor):
        step = 1
        while True:
            floor = anchor_room.floor + step
            if _fits(floor):
                break
            floor = anchor_room.floor - step
            if _fits(floor):
                break
            step += 1
        candidate_room.floor = floor

    anchor_exit["door_target_room"] = candidate_index
    candidate_exit["door_target_room"] = anchor_room.index

    for source_obj in anchor_room.dungeon.object_manager.objects:
        if source_obj["type"] != "button":
            continue
        for link_ref in source_obj.get("links", []):
            if (link_ref["x"], link_ref["y"]) == (anchor_exit["x"], anchor_exit["y"]):
                source_obj.setdefault("assembly_links", []).append(
                    {"floor": floor, "x": anchor_gx, "y": anchor_gy, "room": candidate_index}
                )
                break

    for source_obj in candidate_room.dungeon.object_manager.objects:
        if source_obj["type"] != "button":
            continue
        for link_ref in source_obj.get("links", []):
            if (link_ref["x"], link_ref["y"]) == (candidate_exit["x"], candidate_exit["y"]):
                source_obj.setdefault("assembly_links", []).append(
                    {"floor": anchor_room.floor, "x": anchor_gx, "y": anchor_gy, "room": anchor_room.index}
                )
                break

    assembly.add_room(candidate_room)
    return candidate_room, candidate_exit


def _room_hop_distances(edge_pairs, room_count, start_index=0):
    """BFS hop-count (edges, not rooms) from `start_index` to every other
    room index reachable via `edge_pairs` (a list of (a, b) room-index
    pairs recorded as generate_assembly attaches each room, both merge
    kinds alike -- a border glue is just as much a real room-to-room
    adjacency as a door merge, even though it stamps no door_target_room).
    A room never reached (shouldn't happen -- every placed room attaches
    to the growing assembly by construction) reads as float('inf'), so it
    always sorts last/never satisfies a >= distance check."""
    adjacency = {i: [] for i in range(room_count)}
    for a, b in edge_pairs:
        adjacency[a].append(b)
        adjacency[b].append(a)

    distances = {start_index: 0}
    queue = deque([start_index])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency[current]:
            if neighbor not in distances:
                distances[neighbor] = distances[current] + 1
                queue.append(neighbor)

    return {i: distances.get(i, float("inf")) for i in range(room_count)}


def _run_expansion(rng, room_names, assembly, pending, edges, target_count):
    """The shared random-expansion loop -- pops a pending connection point,
    tries to attach a new room from `room_names` there (an entry-exit merge
    or a border glue, see generate_assembly's own docstring), and keeps
    going until either `target_count` rooms are placed or `pending` runs
    dry. Records every successful attachment's (anchor_index, new_index)
    pair into `edges` (mutated in place) -- the room-to-room adjacency
    graph _dungeon_exit_score/_finalize_dungeon_exit rank a finished
    attempt's dungeon_exit placement by (see _room_hop_distances)."""
    while len(assembly.rooms) < target_count and pending:
        anchor_room, (kind, item) = pending.popleft()

        if kind == "border":
            result = _attach_via_border(rng, room_names, assembly, anchor_room, item)
            if result is None:
                continue
            candidate_room, consumed_edge = result
            edges.append((anchor_room.index, candidate_room.index))
            for exit_obj in candidate_room.entry_exits():
                pending.append((candidate_room, ("exit", exit_obj)))
            for edge in candidate_room.border_edges():
                if edge != consumed_edge:
                    pending.append((candidate_room, ("border", edge)))
            continue

        result = _attach_via_exit(rng, room_names, assembly, anchor_room, item)
        if result is None:
            continue
        candidate_room, candidate_exit = result
        edges.append((anchor_room.index, candidate_room.index))

        for exit_obj in candidate_room.entry_exits():
            if exit_obj is not candidate_exit:
                pending.append((candidate_room, ("exit", exit_obj)))
        for edge in candidate_room.border_edges():
            pending.append((candidate_room, ("border", edge)))


def _generate_assembly_once(room_names, room_count, rng):
    """One full, ordinary generation pass -- the original algorithm,
    unchanged: start from a random room with both a spawn and a way out,
    then expand via _run_expansion until room_count rooms are placed or
    pending runs dry. No exit-guarantee logic at all; that's
    generate_assembly's job, layered on top by calling this repeatedly (see
    its own docstring for why repeating whole attempts, rather than trying
    to steer a single attempt, turned out to be the robust way to do that).
    Returns (assembly, edges) -- edges is generate_assembly's own
    room-to-room adjacency list (see _room_hop_distances) -- or (None,
    None) if no room in room_names has both a spawn and a way out."""
    start_name, start_dungeon = _find_start_room(room_names, rng)
    if start_name is None:
        return None, None

    assembly = DungeonAssembly()
    start_room = PlacedRoom(start_dungeon, start_name, floor=0, offset_x=0, offset_y=0, index=0)
    assembly.add_room(start_room)

    # deque, not a plain list -- pending.pop(0) on a list is O(len(pending)),
    # trending the whole generation loop toward O(n^2) in room_count/pool
    # size as pending keeps growing (every accepted room appends its own new
    # exits/border-edges below). popleft() is O(1).
    pending = deque((start_room, ("exit", exit_obj)) for exit_obj in start_room.entry_exits())
    pending.extend((start_room, ("border", edge)) for edge in start_room.border_edges())

    edges = []
    _run_expansion(rng, room_names, assembly, pending, edges, room_count)
    return assembly, edges


def _dungeon_exit_score(assembly, edges):
    """-1 if no "dungeon_exit"-tagged object exists anywhere in `assembly`
    (the "no exit at all" bug this whole mechanism exists to catch), else
    the LARGEST room-hop-distance (see _room_hop_distances) among however
    many dungeon_exit objects it does have -- generate_assembly's own
    ranking of "how good is this attempt", used to pick the best of several
    full regeneration attempts (see its own docstring)."""
    distances = _room_hop_distances(edges, len(assembly.rooms)) if assembly.rooms else {}
    best = -1
    for room in assembly.rooms:
        manager = room.dungeon.object_manager
        for obj in room.dungeon.object_manager.objects:
            if manager.get_role(obj) == "dungeon_exit":
                best = max(best, distances.get(room.index, -1))
    return best


def generate_assembly(room_names, room_count, rng=None):
    """Build a DungeonAssembly from up to room_count rooms drawn from room_names.

    Starts from the first room (in room_names order) that has both a spawn and
    a way out (a gate/wall entry-exit or a border-floor edge), then repeatedly
    attaches another room (drawn at random from room_names, repeats allowed)
    at one of the growing assembly's still-unconnected connection points.
    Two connection kinds are tried, tagged in the `pending` queue as
    ("exit", obj) or ("border", edge):

    - An entry-exit merge aligns two gate/wall objects onto the *same* global
      cell (see _attach_via_exit). If that placement's tiles would overlap an
      already-placed room on the same floor, the new room goes on floor +1
      instead (or -1 if that's also occupied) -- always relative to the floor
      of the room it's connecting from, not the assembly's max/min floor.
    - A border merge (_attach_via_border) glues two rooms directly edge-to-
      edge along a matching-length border-floor run, with no door object and
      no floor-stepping fallback -- see its docstring for why.

    Guaranteed dungeon exit: if the room pool has at least one room carrying
    a "dungeon_exit"-tagged object (see _room_has_dungeon_exit) AND
    room_count > 1, a single ordinary generation attempt (_generate_assembly_once)
    is run up to GENERATION_ATTEMPTS times, scored by _dungeon_exit_score
    (-1 = no exit at all, otherwise how many room-hops away it landed), and
    the BEST-scoring attempt is kept -- stopping early the moment one meets
    math.ceil(room_count / 2) rooms of distance from spawn (the user's own
    hardened rule). Earlier tries at steering a single attempt toward this
    (reserving a room slot, then forcing an exit-capable room into it) kept
    running into the same trap: whatever budget was reserved for "explore
    more connectors if the first one doesn't fit" was also the ONLY budget
    left to actually place the exit once a fit was found, so it could
    never both explore AND still have room to land. Regenerating the WHOLE
    attempt from scratch sidesteps that entirely -- every attempt is the
    ordinary, already-correct algorithm, unmodified, so there's nothing new
    to get subtly wrong; only the "which finished attempt do we keep" logic
    is new. This is what makes "no exit at all" (a real bug the user hit)
    vanishingly unlikely whenever the pool can support one at all -- it
    already happens on its own within a handful of ordinary attempts most
    of the time, and the loop still returns the best attempt seen even if
    none ever meets the full distance target, rather than an unlucky worst
    case forcing a hard failure. Still not a mathematical guarantee for a
    very small/awkward room pool (a pool where the exit-capable room's own
    connectors never once fit anywhere across every attempt stays exit-less,
    same residual limitation _finalize_dungeon_exit documents) -- but this
    is a world away from "essentially left to chance" the single-attempt
    version had.

    Returns None if no room in room_names has both a spawn and a way out.
    """
    if rng is None:
        rng = random

    exit_capable_names = (
        [name for name in dict.fromkeys(room_names) if _room_has_dungeon_exit(_load_room(name))]
        if room_count > 1 else []
    )

    if not exit_capable_names:
        assembly, edges = _generate_assembly_once(room_names, room_count, rng)
        if assembly is None:
            return None
        _finalize_dungeon_exit(assembly, edges)
        return assembly

    required_hops = max(0, math.ceil(room_count / 2) - 1)
    best_assembly, best_edges, best_score = None, None, -2
    for _ in range(GENERATION_ATTEMPTS):
        assembly, edges = _generate_assembly_once(room_names, room_count, rng)
        if assembly is None:
            return None  # no valid start room at all -- no attempt count fixes that
        score = _dungeon_exit_score(assembly, edges)
        if score > best_score:
            best_assembly, best_edges, best_score = assembly, edges, score
        if score >= required_hops:
            break

    _finalize_dungeon_exit(best_assembly, best_edges)
    return best_assembly


def _finalize_dungeon_exit(assembly, edges):
    """At most one "dungeon_exit"-role object (an E/S or a chest --
    ObjectManager.get_role) survives across the whole assembled dungeon --
    every candidate is ranked by its own room's hop-distance from spawn
    (see _room_hop_distances) and the FARTHEST one wins; every other one is
    demoted back to its type's own default role. Runs once, after every
    room is already placed, rather than tracking a "claimed" flag per
    add_room call site -- simpler and provably correct regardless of which
    of the two attach paths (entry-exit merge or border glue) placed a
    given room. Only mutates each room's already-generation-local copy of
    its objects (PlacedRoom.dungeon is a fresh load, never the same
    in-memory objects as the source room file on disk), so a room reused
    unflagged in a later, separate generation is unaffected.

    Ranking by distance (not just "first found") matters even though
    generate_assembly already tries to force a suitably-far exit room in:
    an EARLIER room from the main expansion can independently carry its own
    dungeon_exit tag too (nothing stops a player from using more than one
    exit-capable room in the same pool), and the farther of the two should
    always win regardless of placement order.

    Documented limitation: still an upper bound only for a pool with no
    exit-capable room at all -- a generation can end up with zero
    dungeon_exit objects if none of the placed rooms happened to carry one.
    No amount of ranking here can force one into existence; that's
    generate_assembly's own job (see its docstring), and even that is a
    best-effort push toward ceil(room_count / 2), not a hard guarantee, once
    a large room_count makes for a very bushy (shallow, wide) graph."""
    distances = _room_hop_distances(edges, len(assembly.rooms)) if assembly.rooms else {}
    best_obj, best_distance = None, -1
    for room in assembly.rooms:
        for obj in room.dungeon.object_manager.objects:
            if room.dungeon.object_manager.get_role(obj) != "dungeon_exit":
                continue
            distance = distances.get(room.index, -1)
            if distance > best_distance:
                best_obj, best_distance = obj, distance

    for room in assembly.rooms:
        manager = room.dungeon.object_manager
        for obj in room.dungeon.object_manager.objects:
            if manager.get_role(obj) != "dungeon_exit" or obj is best_obj:
                continue
            manager.set_role(obj, "connector" if manager.is_es_type(obj["type"]) else "loot")


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
            index=len(assembly.rooms),
        )
        assembly.add_room(placed)

    return assembly
