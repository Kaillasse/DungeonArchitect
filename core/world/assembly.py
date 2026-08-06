"""Procedural room-to-room assembler.

Aligns rooms at their gate/wall entry-exit objects, resolving tile overlap by
shifting the newly-attached room to an adjacent floor (+/-1 relative to the
room it's connecting from) instead of moving tiles within a floor.
"""

from __future__ import annotations

import json
import random

import pygame

from core.world.dungeon import Dungeon
from core.world.entities import PlayerRef
from core.world.object_manager import OBJECT_TYPES
from core.editor.autotile import EMPTY, FLOOR, WALL
from core.data.ressources import DONJONS_DIRECTORY
from core.data.sound_manager import SoundManager

ENTRY_EXIT_TYPES = ("gate", "wall")

OPPOSITE_SIDE = {"north": "south", "south": "north", "east": "west", "west": "east"}


def _valid_entry_exits(dungeon):
    """gate/wall objects that actually qualify as a room-to-room connection:
    ObjectManager.is_valid_doorway (a WALL cell with one FLOOR neighbor
    opposite one EMPTY neighbor, WALL flanking the rest) means this exit
    genuinely borders the void, not just another spot inside the room. A
    gate/wall placed with no void neighbor (e.g. a locked door gating a side
    room) still works as an ordinary in-room obstacle -- it's just never
    picked as a connector here."""
    return [
        obj for obj in dungeon.object_manager.objects
        if obj["type"] in ENTRY_EXIT_TYPES and dungeon.object_manager.is_valid_doorway(obj["x"], obj["y"])
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
        return _valid_entry_exits(self.dungeon)

    def border_edges(self):
        return _border_edges(self.dungeon)

    def has_spawn(self):
        return any(obj["type"] == "spawn" for obj in self.dungeon.object_manager.objects)


class DungeonAssembly:
    """Several rooms placed in a shared global grid, some possibly sharing (x, y) but on different floors."""

    def __init__(self):
        self.rooms = []
        self._shadow_cache = {}
        self._gradient_hole_cache = {}
        self._below_cache = {}
        self._border_cache = {}  # floor -> (terrain_version tuple, {room: hide_border_cells}) -- see _border_cells_by_room

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
        obj = room.dungeon.object_manager.get_object_at(local_x, local_y)

        if obj is None or obj["type"] != "button" or obj.get("activated"):
            return

        obj["activated"] = True
        obj["frame"] = 0
        obj["anim_timer"] = 0.0
        SoundManager().play("button_pressed")

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

    def update(self, dt, player_refs=(), player_floor=None):
        """player_refs only ever gets passed down to rooms on player_floor --
        an animal/enemy on another floor has no business colliding (or, for
        enemies, aggroing) with a player who isn't physically there (mirrors
        locate_room's per-floor scoping). Each ref's hitbox arrives in global
        coordinates (that's what Explorator/the player use everywhere), but
        each room's own Dungeon only ever thinks in that room's local
        coordinates -- same as is_global_cell_walkable converting before
        delegating to a room's ObjectManager -- so it's shifted back by that
        room's offset here before being handed down. Each ref's `player` (the
        actual object, for take_damage) is forwarded as-is -- no coordinate
        transform needed since only its identity matters here, never its
        .position (see EnemyManager/Enemy, which only ever read distances
        from the already-shifted hitbox).
        """
        tile_size = Dungeon.TILE_SIZE
        for room in self.rooms:
            local_refs = ()
            if room.floor == player_floor:
                local_refs = [
                    PlayerRef(ref.player, ref.hitbox.move(-room.offset_x * tile_size, -room.offset_y * tile_size))
                    for ref in player_refs
                ]
            room.dungeon.update(dt, player_refs=local_refs)

    # ------------------------------------------------------------------
    # Rendering -- the active floor is drawn normally (full tiles/objects/
    # animals); every other floor is drawn as a cheap cached "shadow" of its
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
               skip_active_floor_foreground=False, skip_active_floor_animals=False,
               skip_active_floor_enemies=False, show_grid=True):
        """Draw every floor relative to active_floor: floors below first
        (flat-tinted shadow, no hole), the active floor with full detail,
        floors above last (shadow with a soft hole around player_world_pos --
        a continuous world pixel position, omit it, e.g. Creator's static
        preview with no player, to render them with no hole at all).

        skip_active_floor_foreground lets a caller that draws its own player
        sprite (Explorator) leave out active_floor's foreground objects (an
        L/R torch) here and draw them afterwards via
        render_active_floor_foreground(), so the player ends up behind them.
        skip_active_floor_animals/skip_active_floor_enemies work the same way
        for active_floor's live Animals/Enemies, letting Explorator draw them
        together with the player via render_active_floor_entities() instead,
        sorted by feet position so whichever is lower on screen draws in
        front. Creator, which draws no player sprite, leaves all three off
        and gets everything in one pass.
        """
        for floor in self.floors():
            if floor < active_floor:
                self._render_floor_below(screen, camera, floor, active_floor, hide_object_types=hide_object_types)

        self._render_floor(
            screen, camera, active_floor,
            hide_object_types=hide_object_types,
            skip_foreground=skip_active_floor_foreground,
            skip_animals=skip_active_floor_animals,
            skip_enemies=skip_active_floor_enemies,
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
        """Y-sorted draw of every live Animal/Enemy on active_floor plus every
        player in `players`: whichever entity's feet (.position.y, in the
        same world-pixel sense Animal/Enemy/Player.get_hitbox() anchor their
        hitbox to) sit lower on screen draws in front, matching how a
        top-down scene actually reads. Call after render(...,
        skip_active_floor_animals=True, skip_active_floor_enemies=True) and
        before render_active_floor_foreground() -- same slot a single player
        used to occupy alone via a plain player.draw().

        An animal's/enemy's .position is local to its own room's Dungeon (no
        offset baked in, unlike a player's, which is already global -- see
        DungeonAssembly.update's docstring), so it's converted to a global y
        here purely for comparison; drawing itself still goes through that
        room's own offset camera, same as every other per-room draw call.
        """
        tile_size = Dungeon.TILE_SIZE
        entries = []

        for room in self.rooms_on_floor(active_floor):
            offset_camera = _OffsetCamera(camera, room.offset_x * tile_size, room.offset_y * tile_size)
            for animal in room.dungeon.animal_manager.animals:
                global_y = animal.position.y + room.offset_y * tile_size
                entries.append((global_y, animal, offset_camera))
            for enemy in room.dungeon.enemy_manager.enemies:
                global_y = enemy.position.y + room.offset_y * tile_size
                entries.append((global_y, enemy, offset_camera))

        for player in players:
            entries.append((player.position.y, player, camera))

        entries.sort(key=lambda entry: entry[0])
        for _, entity, entity_camera in entries:
            entity.draw(screen, entity_camera)

    def _render_floor(self, screen, camera, floor, hide_object_types=None, skip_foreground=False,
                       skip_animals=False, skip_enemies=False, show_grid=True):
        tile_size = Dungeon.TILE_SIZE
        rooms = self.rooms_on_floor(floor)
        hide_border_cells_by_room = self._border_cells_by_room(floor, rooms)

        for room in rooms:
            offset_camera = _OffsetCamera(camera, room.offset_x * tile_size, room.offset_y * tile_size)
            room.dungeon.render(
                screen, offset_camera,
                hide_object_types=hide_object_types,
                skip_foreground_objects=skip_foreground,
                skip_animals=skip_animals,
                skip_enemies=skip_enemies,
                show_grid=show_grid,
                hide_border_cells=hide_border_cells_by_room.get(room, ()),
            )

    def _border_cells_by_room(self, floor, rooms):
        """{room: hide_border_cells} for every room on `floor` (see
        _south_seam_cells) -- cached per floor and only recomputed when some
        room's Dungeon.terrain_version has actually changed (destroy_area is
        the only thing that bumps it), since _render_floor runs every frame
        at 60fps but the underlying seam data is static except after a rare,
        event-driven terrain edit. `occupied_cells_on_floor` already does the
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
        just its logical footprint, unlike _get_shadow) -- animals/enemies are
        excluded since this cache isn't refreshed every frame, so a live
        position baked into it would go stale immediately. Rendered onto its
        own zero-offset surface via _ZoomOnlyCamera, independent of the real
        camera's current pan position, then tinted once with
        BLEND_RGBA_MULT. Cached per (room, zoom) -- distance-based fade is
        applied afterwards via set_alpha, not baked in, so one cached surface
        covers every distance."""
        key = (room, zoom)
        cached = self._below_cache.get(key)
        if cached is not None:
            return cached

        tile_size = Dungeon.TILE_SIZE
        size = (
            max(1, round(room.dungeon.width * tile_size * zoom)),
            max(1, round(room.dungeon.height * tile_size * zoom)),
        )
        surface = pygame.Surface(size, pygame.SRCALPHA)
        room.dungeon.render(
            surface, _ZoomOnlyCamera(zoom),
            hide_object_types=hide_object_types,
            skip_animals=True,
            skip_enemies=True,
            show_grid=False,
        )
        surface.fill(self.BELOW_TINT_COLOR, special_flags=pygame.BLEND_RGBA_MULT)

        self._below_cache[key] = surface
        return surface

    def _get_shadow(self, room, color, zoom):
        """A cached, pre-tinted silhouette of `room`'s logical footprint --
        every non-EMPTY cell filled with `color` (an (r, g, b, alpha) tuple),
        no tiles/objects/animals at all -- scaled to `zoom`. Built once per
        (room, color, zoom): color is fully determined by floor distance and
        direction (see _render_floor_shadow), so at most 2*SHADOW_MAX_DISTANCE
        variants of a given room's shadow are ever cached, each a single blit
        per frame afterwards instead of a full tile-by-tile re-render."""
        key = (room, color, zoom)
        cached = self._shadow_cache.get(key)
        if cached is not None:
            return cached

        tile_size = Dungeon.TILE_SIZE
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


def _find_start_room(room_names):
    """First room (in the given order) with both a spawn and a valid way out
    -- a gate/wall entry-exit or a border-floor edge (see _border_edges),
    either is enough to start growing the assembly from."""
    for room_name in room_names:
        dungeon = _load_room(room_name)
        has_spawn = any(obj["type"] == "spawn" for obj in dungeon.object_manager.objects)
        if has_spawn and (_valid_entry_exits(dungeon) or _border_edges(dungeon)):
            return room_name, dungeon
    return None, None


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


def generate_assembly(room_names, room_count, rng=None):
    """Build a DungeonAssembly from up to room_count rooms drawn from room_names.

    Starts from the first room (in room_names order) that has both a spawn and
    a way out (a gate/wall entry-exit or a border-floor edge), then repeatedly
    attaches another room (drawn at random from room_names, repeats allowed)
    at one of the growing assembly's still-unconnected connection points.
    Two connection kinds are tried, tagged in the `pending` queue as
    ("exit", obj) or ("border", edge):

    - An entry-exit merge aligns two gate/wall objects onto the *same* global
      cell (see the "exit" branch below). If that placement's tiles would
      overlap an already-placed room on the same floor, the new room goes on
      floor +1 instead (or -1 if that's also occupied) -- always relative to
      the floor of the room it's connecting from, not the assembly's max/min
      floor.
    - A border merge (_attach_via_border) glues two rooms directly edge-to-
      edge along a matching-length border-floor run, with no door object and
      no floor-stepping fallback -- see its docstring for why.

    Returns None if no room in room_names has both a spawn and a way out.
    """
    if rng is None:
        rng = random

    start_name, start_dungeon = _find_start_room(room_names)
    if start_name is None:
        return None

    assembly = DungeonAssembly()
    start_room = PlacedRoom(start_dungeon, start_name, floor=0, offset_x=0, offset_y=0, index=0)
    assembly.add_room(start_room)

    pending = [(start_room, ("exit", exit_obj)) for exit_obj in start_room.entry_exits()]
    pending += [(start_room, ("border", edge)) for edge in start_room.border_edges()]

    while len(assembly.rooms) < room_count and pending:
        anchor_room, (kind, item) = pending.pop(0)

        if kind == "border":
            result = _attach_via_border(rng, room_names, assembly, anchor_room, item)
            if result is None:
                continue
            candidate_room, consumed_edge = result
            for exit_obj in candidate_room.entry_exits():
                pending.append((candidate_room, ("exit", exit_obj)))
            for edge in candidate_room.border_edges():
                if edge != consumed_edge:
                    pending.append((candidate_room, ("border", edge)))
            continue

        anchor_exit = item

        candidate_name = rng.choice(room_names)
        candidate_dungeon = _load_room(candidate_name)
        candidate_exits = _valid_entry_exits(candidate_dungeon)
        # Only align onto an exit of the SAME type as the anchor's (a gate
        # merges with a gate, a wall with a wall) -- otherwise the two halves
        # of one physical doorway would be different objects with unrelated
        # sprites/animations. Orientation doesn't need filtering here: two
        # exits facing opposite directions land the candidate's interior
        # exactly in the anchor's void (a same-floor connection), while two
        # exits facing the same direction land the candidate's interior
        # exactly on top of the anchor's own interior -- always a genuine
        # FLOOR/FLOOR collision (is_valid_doorway guarantees a FLOOR neighbor
        # right next to any doorway), so _fits() below always pushes that
        # case to a different floor instead (a staircase-style connection).
        # Either way the merge is coherent; _fits() is what actually decides.
        matching_exits = [obj for obj in candidate_exits if obj["type"] == anchor_exit["type"]]
        if not matching_exits:
            continue

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

        # Try the anchor's own floor first, then alternate +1/-1, +2/-2, ...
        # outward until a floor with no real conflict is found. This must
        # never give up and place the room anyway -- two rooms actually
        # overlapping on the same floor is exactly the "several rooms
        # superimposed" bug that lets the player walk through a wall covering
        # another room's floor, since collision is resolved per-floor
        # (DungeonAssembly.locate_room) assuming at most one room ever claims
        # a given floor cell.
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

        # Tag both halves of the merged doorway with the other side's room
        # index, whether this connection ended up same-floor or not -- a
        # single edge-triggered mechanism (DungeonAssembly.resolve_room_transition)
        # handles both an ordinary same-floor E/S and a cross-floor "portal"
        # crossing identically: stepping onto the door cell switches straight
        # to the room on the other end (see locate_room's docstring for why
        # this can't just fall out of FLOOR-ownership checks the way ordinary
        # movement within one room does).
        anchor_exit["door_target_room"] = candidate_index
        candidate_exit["door_target_room"] = anchor_room.index

        # A button in EITHER room that links (locally) to ITS OWN half of the
        # merged doorway should also open the OTHER half -- the two halves
        # are separate objects (one per room's own object list) that just
        # happen to share one global cell, each with its own independent
        # "open" flag, so opening one side alone leaves the other room's
        # collision still reading closed. A plain local {"x", "y"} link only
        # resolves within one room's own object list, so each direction needs
        # a global, floor-qualified reference instead (an "assembly_link"),
        # which DungeonAssembly.check_button_trigger knows how to follow
        # across rooms. Only the anchor-side half of this used to be handled
        # here, which is exactly why one physical doorway could open cleanly
        # from one room's button but stay closed as seen from the other
        # room's side -- whichever side happened to hold the button "won",
        # the other never got told to open. The candidate/anchor exits' own
        # pre-existing local links (if any) are untouched either way -- they're
        # still valid as-is, since neither room's internal layout changes.
        for source_obj in anchor_room.dungeon.object_manager.objects:
            if source_obj["type"] != "button":
                continue
            for link_ref in source_obj.get("links", []):
                if (link_ref["x"], link_ref["y"]) == (anchor_exit["x"], anchor_exit["y"]):
                    source_obj.setdefault("assembly_links", []).append(
                        {"floor": floor, "x": anchor_gx, "y": anchor_gy}
                    )
                    break

        for source_obj in candidate_room.dungeon.object_manager.objects:
            if source_obj["type"] != "button":
                continue
            for link_ref in source_obj.get("links", []):
                if (link_ref["x"], link_ref["y"]) == (candidate_exit["x"], candidate_exit["y"]):
                    source_obj.setdefault("assembly_links", []).append(
                        {"floor": anchor_room.floor, "x": anchor_gx, "y": anchor_gy}
                    )
                    break

        assembly.add_room(candidate_room)

        for exit_obj in candidate_exits:
            if exit_obj is not candidate_exit:
                pending.append((candidate_room, ("exit", exit_obj)))
        for edge in candidate_room.border_edges():
            pending.append((candidate_room, ("border", edge)))

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
            index=len(assembly.rooms),
        )
        assembly.add_room(placed)

    return assembly
