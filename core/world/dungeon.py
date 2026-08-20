from core.world.object_manager import ObjectManager, OBJECT_TYPES
from core.world.entities import MobManager, PickupManager, ProjectileManager, EffectManager
from core.rendering.world_renderer import WorldRenderer
from core.data.save_manager import SaveManager
from core.data.ressources import TILE_SIZE as SOURCE_TILE_SIZE, WORLD_SCALE
from core.data.sound_manager import play_card_sound
from core.editor.autotile import (
    EMPTY, FLOOR, WALL, build_walls_around, unbuild_walls_around, erase_at,
    resolve_sprite_grid, resolve_sprite_grid_region, LOCAL_EDIT_SPRITE_RADIUS,
)


DEFAULT_GRID_SAVE_PATH = "room_001"

__all__ = ["DEFAULT_GRID_SAVE_PATH", "Dungeon", "corner_cells"]


def corner_cells(rect, tile_size):
    """The 4 grid cells covering `rect`'s corners -- rect.right - 1/
    rect.bottom - 1 rather than the raw edges, so a rect exactly aligned to a
    tile boundary doesn't spill into the neighboring cell. Shared by every
    "is this whole rect walkable" check (Dungeon.is_rect_walkable,
    DungeonAssembly.is_rect_walkable, Explorator._is_walkable) -- this exact
    geometry has already needed bugfixing once (a void/wall corner mismatch
    that could deadlock movement right at a room boundary)."""
    for x, y in (
        (rect.left, rect.top),
        (rect.right - 1, rect.top),
        (rect.left, rect.bottom - 1),
        (rect.right - 1, rect.bottom - 1),
    ):
        yield x // tile_size, y // tile_size


class Dungeon:
    """Owns the world data (grid, size) and orchestrates its components. Draws nothing, saves nothing, and doesn't manage objects itself."""

    TILE_SIZE = SOURCE_TILE_SIZE * WORLD_SCALE

    # Safety cap for grow() -- 100x the default 20x20 room's area, generous
    # for a room/home that grows over a long time, but bounded against a
    # runaway allocation from a single stray out-of-bounds paint.
    MAX_ROOM_DIMENSION = 200

    def __init__(self, width: int = 20, height: int = 20) -> None:
        self.width = width
        self.height = height
        self.tile_size = self.TILE_SIZE

        self.logical_grid = [[EMPTY for _ in range(width)] for _ in range(height)]
        self.sprite_grid = [[-1 for _ in range(width)] for _ in range(height)]

        # Per-cell autotile pack name (or None -- the built-in interior
        # tileset), same shape as logical_grid. Unlike floor_theme/wall_theme
        # below (only ever the CURRENT brush from here on), this is what's
        # actually read at render/resolve time -- see paint_cell's stamping
        # and autotile._resolve_cell_sprite. Lets two cells of the same room
        # paint with two different tilesets, which a room-wide theme couldn't.
        self.theme_grid = [[None for _ in range(width)] for _ in range(height)]

        # Bumped by anything that mutates logical_grid's cell values --
        # paint_cell and destroy_area -- lets a cache keyed on it
        # (DungeonAssembly._border_cells_by_room, WorldRenderer's ledge
        # cache) know when terrain-derived data has gone stale.
        self.terrain_version = 0

        # Only ever toggled in Creator (ToolPaletteUI -- True only when both
        # Sol and Mur are active). When False, painting/erasing touch only
        # the clicked cell, no automatic wall halo -- a prerequisite for a
        # destructible world, where a wall broken at runtime must never get "healed" by a rebuild.
        self.autotile_enabled = True

        # Autotile pack names this room paints FLOOR/WALL cells with instead
        # of the built-in interior tileset -- None (default) means today's
        # behavior. Plain attributes, assigned after the fact (Creator's
        # right-click theme picker), not constructor params.
        self.floor_theme = None
        self.wall_theme = None

        self.object_manager = ObjectManager(self)
        self.mob_manager = MobManager(self)
        self.pickup_manager = PickupManager(self)
        self.projectile_manager = ProjectileManager(self)
        self.effect_manager = EffectManager(self)
        self.renderer = WorldRenderer()
        self.save = SaveManager()

    # ------------------------------------------------------------------
    # Grille logique
    # ------------------------------------------------------------------

    def resync_sprite_grid(self) -> None:
        """Recomputes sprite_grid from the current logical_grid without
        touching it (no wall regeneration) -- used after loading, so a
        save's already-correct `cells` is trusted as-is instead of being
        re-derived every time a room opens. Reads self.theme_grid, the
        per-cell pack each cell was actually painted with -- floor_theme/
        wall_theme are only ever the CURRENT brush, never re-applied to already-painted cells here.

        Also bumps terrain_version -- this is the one place a room LOAD
        (SaveManager.apply_json, the only caller) replaces logical_grid
        wholesale without going through paint_cell/destroy_area/
        destroy_wall_cell/grow, every one of which already bumps it
        itself. Without this, WorldRenderer._ledge_cache (keyed on
        terrain_version, see its own docstring) kept reading as "still
        valid" across a room switch and kept showing the PREVIOUS room's
        south-border ledge tiles until the next in-room edit happened to
        bump the version -- the "bordures de la room d'avant" bug."""
        self.sprite_grid = resolve_sprite_grid(self.logical_grid, self.theme_grid)
        self.terrain_version += 1

    def paint_cell(self, grid_x: int, grid_y: int, erase: bool = False, cell_type: int = FLOOR, wall_gate=None) -> None:
        """Autotile (when enabled) is purely incremental -- only the clicked
        cell's own neighborhood is touched (build_walls_around/
        unbuild_walls_around), never a full-grid rescan. A full rescan is
        exactly what made re-enabling autotile after painting a lot of floor
        with it off wall everything at once on the next click.

        cell_type only matters in the non-autotile branch -- autotile ON
        always paints FLOOR (WALL only appears there as build_walls_around's
        side effect). It's what lets ToolPaletteUI paint a raw WALL cell
        directly when only "Mur" is active.

        wall_gate is forwarded as-is to build_walls_around's own `gate`
        (autotile ON only) -- lets a caller meter/limit each halo cell
        (e.g. Creator gating on card stock) without this method knowing why."""
        if not (0 <= grid_x < self.width and 0 <= grid_y < self.height):
            return

        before = self._snapshot_local(grid_x, grid_y, LOCAL_EDIT_SPRITE_RADIUS)

        if erase:
            if self.autotile_enabled:
                was_wall = self.logical_grid[grid_y][grid_x] == WALL
                erase_at(self.logical_grid, grid_x, grid_y)
                unbuild_walls_around(self.logical_grid, grid_x, grid_y)
                if was_wall:
                    for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                        unbuild_walls_around(self.logical_grid, grid_x + dx, grid_y + dy)
            else:
                self.logical_grid[grid_y][grid_x] = EMPTY
        else:
            if self.autotile_enabled:
                self.logical_grid[grid_y][grid_x] = FLOOR
                build_walls_around(self.logical_grid, grid_x, grid_y, gate=wall_gate)
            else:
                self.logical_grid[grid_y][grid_x] = cell_type

        # Stamps the CURRENT brush onto every cell that actually changed
        # logical type in this call -- the clicked cell plus any halo cell
        # walled/unwalled as a side effect. A neighbor already FLOOR/WALL
        # before this click is untouched -- repainting one spot with a
        # different brush never retouches cells painted earlier with another one.
        self._stamp_theme_changes(before, grid_x, grid_y, LOCAL_EDIT_SPRITE_RADIUS)

        # Bounded to the clicked cell's own neighborhood instead of a
        # full-grid rescan -- runs on every cell of a click-drag paint
        # stroke, potentially dozens of times a second, while a sprite only
        # ever depends on its own 4 cardinal neighbors.
        resolve_sprite_grid_region(
            self.logical_grid, self.sprite_grid, grid_x, grid_y,
            theme_grid=self.theme_grid,
        )
        self.object_manager.prune_invalid()
        self.terrain_version += 1

    def _snapshot_local(self, center_x: int, center_y: int, radius: int):
        """Copy of logical_grid's values in the (clamped) Chebyshev-`radius`
        box around (center_x, center_y), taken right before a terrain edit --
        paired with _stamp_theme_changes to know exactly which cells a
        paint/erase call actually changed."""
        y0, y1 = max(0, center_y - radius), min(self.height, center_y + radius + 1)
        x0, x1 = max(0, center_x - radius), min(self.width, center_x + radius + 1)
        return (y0, x0, [row[x0:x1] for row in self.logical_grid[y0:y1]])

    def _stamp_theme_changes(self, before, center_x: int, center_y: int, radius: int) -> None:
        """Sets theme_grid[y][x] to the current brush for every cell in
        `before`'s box whose logical value changed to FLOOR/WALL since the
        snapshot -- a cell that changed to EMPTY (erased) is left as-is
        (orphaned, never read while EMPTY); a cell that didn't change keeps whatever pack it was already painted with."""
        y0, x0, before_rows = before
        for row_offset, y in enumerate(range(y0, y0 + len(before_rows))):
            before_row = before_rows[row_offset]
            for col_offset, x in enumerate(range(x0, x0 + len(before_row))):
                old = before_row[col_offset]
                new = self.logical_grid[y][x]
                if new == old:
                    continue
                if new == FLOOR:
                    self.theme_grid[y][x] = self.floor_theme
                elif new == WALL:
                    self.theme_grid[y][x] = self.wall_theme

    def update(self, dt: float, player_refs=(), magnet_radius: float = 0, room_offset=(0, 0)) -> None:
        self.object_manager.update(dt)
        self.mob_manager.update(dt, player_refs=player_refs, room_offset=room_offset)
        self.pickup_manager.update(dt, player_refs=player_refs, magnet_radius=magnet_radius)
        self.projectile_manager.update(dt, player_refs=player_refs, room_offset=room_offset)
        self.effect_manager.update(dt)

    def _play_destroy_sound_at(self, x: int, y: int) -> None:
        """Plays whichever OBJECT_TYPES card sits at (x, y)'s own
        "sounds.destroy" (MechanicsPanelUI's "Son : Casse" row), if any --
        must run BEFORE the cell is cleared/prune_invalid drops the object
        (get_object_at can't find it afterward). A silent no-op for a bare
        terrain cell (no card sound yet) or an object with none assigned."""
        obj = self.object_manager.get_object_at(x, y)
        if obj is None:
            return
        config = OBJECT_TYPES.get(obj["type"], {})
        play_card_sound(config.get("sounds", {}), "destroy", pitch_range=config.get("sound_pitch", {}).get("destroy"))

    def _cell_card_ids(self, x: int, y: int) -> list:
        """Card id(s) destroyed at (x, y) if cleared right now -- the
        terrain's own tile_floor/tile_wall card (core.data.cards.BASE_TILE_CARDS),
        plus whatever OBJECT_TYPES card (if any) sits on that cell too --
        both destroyed together by the same explosion/melee swing, so both
        are worth a card. Must run BEFORE the cell is actually cleared (same
        ordering _play_destroy_sound_at requires). Used to spawn a card
        pickup once the corresponding DestructionSpark finishes
        (_spawn_loot_pickups), not at destruction time itself."""
        card_ids = []
        cell = self.logical_grid[y][x]
        if cell == FLOOR:
            card_ids.append("tile_floor")
        elif cell == WALL:
            card_ids.append("tile_wall")
        obj = self.object_manager.get_object_at(x, y)
        if obj is not None:
            card_ids.append(obj["type"])
        return card_ids

    def destroy_area(self, center_x: int, center_y: int, radius_tiles: int):
        """Carves a circular hole into the terrain -- both FLOOR and WALL
        cells within `radius_tiles` of (center_x, center_y) become EMPTY.
        Unlike paint_cell, never re-walls the boundary afterwards
        (build_walls_around would instantly "heal" the hole shut) -- an
        explosion is meant to leave a permanent gap. prune_invalid() then
        drops any object that no longer sits on a cell its placement rule
        allows. Returns (destroyed, card_ids_by_cell): the (x, y) grid cells
        actually cleared (already-EMPTY cells skipped, not double-counted)
        -- ProjectileManager uses this to spawn one VFX per real cell -- and
        {(x, y): [card_id, ...]} for exactly those same cells, used to
        credit a card once each cell's own spark arrives."""
        destroyed = []
        card_ids_by_cell = {}
        for dy in range(-radius_tiles, radius_tiles + 1):
            for dx in range(-radius_tiles, radius_tiles + 1):
                if dx * dx + dy * dy > radius_tiles * radius_tiles:
                    continue
                x, y = center_x + dx, center_y + dy
                if 0 <= x < self.width and 0 <= y < self.height and self.logical_grid[y][x] != EMPTY:
                    card_ids_by_cell[(x, y)] = self._cell_card_ids(x, y)
                    self._play_destroy_sound_at(x, y)
                    self.logical_grid[y][x] = EMPTY
                    destroyed.append((x, y))

        # Same bounded-region update as paint_cell -- the carved circle
        # itself is exactly radius_tiles, +1 more for the cardinal-neighbor
        # sprite dependency (see resolve_sprite_grid_region).
        resolve_sprite_grid_region(
            self.logical_grid, self.sprite_grid, center_x, center_y, radius=radius_tiles + 1,
            theme_grid=self.theme_grid,
        )
        self.object_manager.prune_invalid()
        self.terrain_version += 1
        return destroyed, card_ids_by_cell

    def destroy_wall_cell(self, x: int, y: int):
        """Single-cell destruction for the player's melee attack -- unlike
        destroy_area, only ever clears a WALL cell, never FLOOR: a punch
        shouldn't carve a pit into open ground, only break an actual wall in
        front of the player. Returns (success, card_ids) -- whether a wall
        was actually there to break, and whichever card(s) that break is
        worth, for the caller to credit once its own spark arrives;
        card_ids is always [] when success is False."""
        if not (0 <= x < self.width and 0 <= y < self.height) or self.logical_grid[y][x] != WALL:
            return False, []
        card_ids = self._cell_card_ids(x, y)
        self._play_destroy_sound_at(x, y)
        self.logical_grid[y][x] = EMPTY
        resolve_sprite_grid_region(
            self.logical_grid, self.sprite_grid, x, y, radius=1,
            theme_grid=self.theme_grid,
        )
        self.object_manager.prune_invalid()
        self.terrain_version += 1
        return True, card_ids

    def grow(self, left: int = 0, right: int = 0, top: int = 0, bottom: int = 0) -> bool:
        """Extends the grid in any combination of the 4 directions --
        `right`/`bottom` just append new EMPTY/-1/None columns/rows, but
        `left`/`top` INSERT new ones at the start, shifting every existing
        cell to a higher index -- so every absolute coordinate stored
        elsewhere (every placed object's own "x"/"y", and every link's
        {"x","y"} pointing at the OTHER object) must shift by the same
        (left, top) to keep pointing at the same physical cell.
        object_manager's own _cell_index is rebuilt once afterward rather
        than incrementally, since every key changed at once.

        Deliberately does NOT re-run resolve_sprite_grid/build_walls_around
        for the new area -- the caller (Creator, painting the cell that
        triggered this) already does that right after this returns.

        Returns False (no-op) if the resulting size would exceed
        MAX_ROOM_DIMENSION in either dimension -- same silent-reject spirit
        every other out-of-bounds guard in this class uses, rather than raising."""
        if not (left or right or top or bottom):
            return True
        new_width = self.width + left + right
        new_height = self.height + top + bottom
        if new_width > self.MAX_ROOM_DIMENSION or new_height > self.MAX_ROOM_DIMENSION:
            return False

        def _grow_row(row, fill):
            return [fill] * left + row + [fill] * right

        self.logical_grid = [[EMPTY] * new_width for _ in range(top)] + \
            [_grow_row(row, EMPTY) for row in self.logical_grid] + \
            [[EMPTY] * new_width for _ in range(bottom)]
        self.sprite_grid = [[-1] * new_width for _ in range(top)] + \
            [_grow_row(row, -1) for row in self.sprite_grid] + \
            [[-1] * new_width for _ in range(bottom)]
        self.theme_grid = [[None] * new_width for _ in range(top)] + \
            [_grow_row(row, None) for row in self.theme_grid] + \
            [[None] * new_width for _ in range(bottom)]

        if left or top:
            for obj in self.object_manager.objects:
                obj["x"] += left
                obj["y"] += top
                for link in obj.get("links", []):
                    link["x"] += left
                    link["y"] += top
            self.object_manager._rebuild_cell_index()

        self.width = new_width
        self.height = new_height
        self.terrain_version += 1
        return True

    def spawn_mobs(self) -> None:
        """(Re)build the live wandering Mob entities for this room's placed
        mob objects -- call once after loading, not on every edit. See
        MobManager.spawn(); Creator never calls this, so its static preview
        only shows a placed mob's frame-0 icon, not a live one."""
        self.mob_manager.spawn()

    # ------------------------------------------------------------------
    # Sauvegarde
    # ------------------------------------------------------------------

    def load_from_json(self, room_name):
        self.save.load(self, room_name)

    def save_to_json(self, room_name):
        self.save.save(self, room_name)

    # ------------------------------------------------------------------
    # Coordonnées
    # ------------------------------------------------------------------

    def grid_to_world(self, grid_x: int, grid_y: int):
        return (
            grid_x * self.tile_size + self.tile_size / 2,
            grid_y * self.tile_size + self.tile_size,
        )

    def world_to_grid(self, world_x: float, world_y: float):
        return (
            int(world_x // self.tile_size),
            int(world_y // self.tile_size),
        )

    def object_indicator_position(self, obj):
        """World position of an object's link indicator (top-right corner of its cell)."""
        return (
            (obj["x"] + 1) * self.tile_size,
            obj["y"] * self.tile_size,
        )

    # ------------------------------------------------------------------
    # Requêtes monde
    # ------------------------------------------------------------------

    def get_spawn_world_position(self):
        for obj in self.object_manager.objects:
            if obj["type"] == "spawn":
                return self.grid_to_world(obj["x"], obj["y"])
        return None

    def is_rect_walkable(self, rect):
        for grid_x, grid_y in corner_cells(rect, self.tile_size):
            if not self.object_manager.is_cell_walkable(grid_x, grid_y):
                return False

        return True

    def is_void_at(self, grid_x, grid_y) -> bool:
        """True if (grid_x, grid_y) is out of this dungeon's bounds or an
        EMPTY logical cell -- e.g. a destroy_area hole, or past the room's
        edge. Shared by every live entity manager's own void-culling
        (MobManager/PickupManager.update) and Explorator._is_void_at's
        single-room branch, which used to duplicate this exact check."""
        if not (0 <= grid_x < self.width and 0 <= grid_y < self.height):
            return True
        return self.logical_grid[grid_y][grid_x] == EMPTY

    # ------------------------------------------------------------------
    # Rendu
    # ------------------------------------------------------------------

    def render(self, screen, camera, spawn_preview=None, hide_object_types=None, show_link_indicators=False,
               skip_foreground_objects=False, skip_mobs=False,
               show_grid=True, show_border=True, hide_border_cells=None):
        self.renderer.render(
            screen, self, camera,
            spawn_preview=spawn_preview,
            hide_object_types=hide_object_types,
            show_link_indicators=show_link_indicators,
            skip_foreground_objects=skip_foreground_objects,
            show_grid=show_grid,
            show_border=show_border,
            hide_border_cells=hide_border_cells,
        )
        if not skip_mobs:
            self.mob_manager.draw(screen, camera)
        self.pickup_manager.draw(screen, camera)
        self.projectile_manager.draw(screen, camera)
        self.effect_manager.draw(screen, camera)

    def render_foreground(self, screen, camera, hide_object_types=None):
        """Objects flagged draw_after_player (e.g. torch), meant to be drawn after the player sprite."""
        self.renderer.render_foreground_objects(screen, self, camera, hide_object_types=hide_object_types)

    def render_border(self, screen, camera, hide_border_cells=None):
        """The south-edge ledge tile only -- see WorldRenderer.render_border/
        DungeonAssembly._render_floor for why this is called as its own
        separate, guaranteed-last pass across every room in an assembly
        rather than folded into each room's own render() call."""
        self.renderer.render_border(screen, self, camera, hide_border_cells=hide_border_cells)
