from core.world.object_manager import ObjectManager
from core.world.entities import AnimalManager, EnemyManager, PickupManager, ProjectileManager
from core.rendering.world_renderer import WorldRenderer
from core.data.save_manager import SaveManager
from core.data.ressources import TILE_SIZE as SOURCE_TILE_SIZE, WORLD_SCALE
from core.editor.autotile import (
    EMPTY, FLOOR, WALL, build_walls_around, unbuild_walls_around, erase_at,
    resolve_sprite_grid, resolve_sprite_grid_region,
)


DEFAULT_GRID_SAVE_PATH = "room_001"

__all__ = ["DEFAULT_GRID_SAVE_PATH", "Dungeon", "corner_cells"]


def corner_cells(rect, tile_size):
    """The 4 grid cells covering `rect`'s corners -- rect.right - 1/
    rect.bottom - 1 rather than the raw edges, so a rect exactly aligned to
    a tile boundary doesn't spill into the neighboring cell. Shared by every
    "is this whole rect walkable" check (Dungeon.is_rect_walkable,
    DungeonAssembly.is_rect_walkable, Explorator._is_walkable) so there's
    only one place to get the corner math right -- this exact geometry has
    already needed two rounds of bugfixing this session (a void/wall corner
    mismatch that could deadlock movement right at a room boundary)."""
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

    def __init__(self, width: int = 20, height: int = 20) -> None:
        self.width = width
        self.height = height
        self.tile_size = self.TILE_SIZE

        self.logical_grid = [[EMPTY for _ in range(width)] for _ in range(height)]
        self.sprite_grid = [[-1 for _ in range(width)] for _ in range(height)]

        # Bumped by anything that mutates logical_grid's actual cell values
        # -- paint_cell (Creator painting/erasing) and destroy_area
        # (exploration-time destruction) -- lets a cache keyed on it (see
        # DungeonAssembly._border_cells_by_room, WorldRenderer's own ledge
        # cache) know when previously-computed terrain-derived data has gone
        # stale, without needing to be told explicitly by every caller.
        self.terrain_version = 0

        # Only ever toggled in Creator (see core.editor.ui.ToolPaletteUI --
        # derived there as floor_tool_active and wall_tool_active, True only
        # when both the Sol and Mur buttons are active) -- Explorator never
        # paints, so this is moot on its own dungeons. When False, painting/
        # erasing touch only the clicked cell, no automatic wall halo -- a
        # prerequisite for a destructible world, where a wall broken at
        # runtime must never get "healed" by a later rebuild.
        self.autotile_enabled = True

        # Autotile pack names (core.data.ressources.save_autotile_pack) this
        # room paints FLOOR/WALL cells with instead of the built-in interior
        # tileset -- None (the default for every room, forever, unless
        # explicitly set by Creator's right-click theme picker, see
        # core.editor.ui.AutotileThemePanelUI) means exactly today's
        # behavior. Plain attributes, not constructor params -- assigned
        # after the fact the same way autotile_enabled itself is toggled,
        # not baked into __init__'s signature.
        self.floor_theme = None
        self.wall_theme = None

        self.object_manager = ObjectManager(self)
        self.animal_manager = AnimalManager(self)
        self.enemy_manager = EnemyManager(self)
        self.pickup_manager = PickupManager(self)
        self.projectile_manager = ProjectileManager(self)
        self.renderer = WorldRenderer()
        self.save = SaveManager()

    # ------------------------------------------------------------------
    # Grille logique
    # ------------------------------------------------------------------

    def resync_sprite_grid(self) -> None:
        """Recomputes sprite_grid from the current logical_grid without ever
        touching it (no wall regeneration) -- used after loading, so a save's
        already-correct `cells` (walls included) is trusted as-is instead of
        being re-derived from its floor cells every time a room opens.
        Reads self.floor_theme/wall_theme -- also the method Creator calls
        right after changing either (see AutotileThemePanelUI/the bitmap
        editor) so an already-open room re-resolves against the new theme
        immediately."""
        self.sprite_grid = resolve_sprite_grid(self.logical_grid, self.floor_theme, self.wall_theme)

    def paint_cell(self, grid_x: int, grid_y: int, erase: bool = False, cell_type: int = FLOOR, wall_gate=None) -> None:
        """Autotile (when enabled) is purely incremental -- only the clicked
        cell's own immediate neighborhood is ever touched (build_walls_around/
        unbuild_walls_around), never a full-grid rescan. That full rescan
        (the old build_walls()) is exactly what made re-enabling autotile
        after painting a lot of floor with it off wall everything at once on
        the very next click, instead of just that one cell.

        cell_type only ever matters in the non-autotile paint branch --
        autotile ON always paints FLOOR (a WALL only ever appears there as
        build_walls_around's own side effect). It's what lets Creator's
        Sol/Mur tools (core.editor.ui.ToolPaletteUI) paint a raw WALL cell
        directly when only "Mur" is active, something no caller could do
        before this parameter existed.

        wall_gate is forwarded as-is to build_walls_around's own `gate`
        (autotile ON only) -- lets a caller meter/limit each individual
        halo cell (e.g. Creator gating on card stock for a partial fill)
        without this method or build_walls_around needing to know why."""
        if not (0 <= grid_x < self.width and 0 <= grid_y < self.height):
            return

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

        # Bounded to the clicked cell's own neighborhood (see
        # resolve_sprite_grid_region/LOCAL_EDIT_SPRITE_RADIUS) instead of a
        # full-grid rescan -- this runs on every cell of a click-drag paint
        # stroke, potentially dozens of times a second, while a sprite only
        # ever depends on its own 4 cardinal neighbors regardless of how big
        # the room is.
        resolve_sprite_grid_region(
            self.logical_grid, self.sprite_grid, grid_x, grid_y,
            floor_pack=self.floor_theme, wall_pack=self.wall_theme,
        )
        self.object_manager.prune_invalid()
        self.terrain_version += 1

    def update(self, dt: float, player_refs=()) -> None:
        self.object_manager.update(dt)
        self.animal_manager.update(dt, player_refs=player_refs)
        self.enemy_manager.update(dt, player_refs=player_refs)
        self.pickup_manager.update(dt)
        self.projectile_manager.update(dt, player_refs=player_refs)

    def destroy_area(self, center_x: int, center_y: int, radius_tiles: int) -> None:
        """Carves a circular hole into the terrain -- both FLOOR and WALL
        cells within `radius_tiles` of (center_x, center_y) become EMPTY.
        Unlike paint_cell, this never re-walls the boundary afterwards
        (build_walls_around would instantly "heal" the hole shut) -- an
        explosion (see ProjectileManager) is meant to leave a permanent gap,
        not perform an edit. prune_invalid() then drops any object (a vase,
        a torch, a gate...) that no longer sits on a cell its placement rule
        allows, same as any other terrain edit."""
        for dy in range(-radius_tiles, radius_tiles + 1):
            for dx in range(-radius_tiles, radius_tiles + 1):
                if dx * dx + dy * dy > radius_tiles * radius_tiles:
                    continue
                x, y = center_x + dx, center_y + dy
                if 0 <= x < self.width and 0 <= y < self.height:
                    self.logical_grid[y][x] = EMPTY

        # Same bounded-region update as paint_cell -- the carved circle
        # itself is exactly radius_tiles, +1 more for the cardinal-neighbor
        # sprite dependency (see resolve_sprite_grid_region).
        resolve_sprite_grid_region(
            self.logical_grid, self.sprite_grid, center_x, center_y, radius=radius_tiles + 1,
            floor_pack=self.floor_theme, wall_pack=self.wall_theme,
        )
        self.object_manager.prune_invalid()
        self.terrain_version += 1

    def spawn_animals(self) -> None:
        """(Re)build the live wandering Animal entities for this room's placed
        animal objects -- call once after loading, not on every edit. See
        AnimalManager.spawn(); Creator never calls this, so its static preview
        only ever shows a placed animal's frame-0 icon, not a live one."""
        self.animal_manager.spawn()

    def spawn_enemies(self) -> None:
        """Same rule as spawn_animals -- EnemyManager.spawn(), only ever
        called by Explorator after loading a room."""
        self.enemy_manager.spawn()

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
        """True if (grid_x, grid_y) is out of this dungeon's own bounds or an
        EMPTY logical cell -- e.g. a hole carved by destroy_area, or simply
        past the room's edge. Shared by every live entity manager's own
        void-culling (AnimalManager/EnemyManager/PickupManager.update) and
        by Explorator._is_void_at's single-room branch, which used to
        duplicate this exact check locally."""
        if not (0 <= grid_x < self.width and 0 <= grid_y < self.height):
            return True
        return self.logical_grid[grid_y][grid_x] == EMPTY

    # ------------------------------------------------------------------
    # Rendu
    # ------------------------------------------------------------------

    def render(self, screen, camera, spawn_preview=None, hide_object_types=None, show_link_indicators=False,
               skip_foreground_objects=False, skip_animals=False, skip_enemies=False, show_grid=True,
               hide_border_cells=None):
        self.renderer.render(
            screen, self, camera,
            spawn_preview=spawn_preview,
            hide_object_types=hide_object_types,
            show_link_indicators=show_link_indicators,
            skip_foreground_objects=skip_foreground_objects,
            show_grid=show_grid,
            hide_border_cells=hide_border_cells,
        )
        if not skip_animals:
            self.animal_manager.draw(screen, camera)
        if not skip_enemies:
            self.enemy_manager.draw(screen, camera)
        self.pickup_manager.draw(screen, camera)
        self.projectile_manager.draw(screen, camera)

    def render_foreground(self, screen, camera, hide_object_types=None):
        """Objects flagged draw_after_player (e.g. torch), meant to be drawn after the player sprite."""
        self.renderer.render_foreground_objects(screen, self, camera, hide_object_types=hide_object_types)
