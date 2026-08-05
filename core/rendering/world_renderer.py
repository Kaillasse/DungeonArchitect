import pygame

from core.data.ressources import TILE_SIZE, load_tileset, get_tile_surface
from core.editor.autotile import EMPTY, DEFAULT_FLOOR_SPRITE
from core.world.object_manager import OBJECT_TYPES, load_object_frames


class WorldRenderer:
    """Draws a Dungeon. Holds no world data — only pygame surface caches."""

    GRID_LINE_COLOR = (80, 80, 80)
    SPAWN_PREVIEW_COLOR = (0, 255, 0)
    LINK_INDICATOR_COLOR = (60, 220, 90)
    LINK_INDICATOR_RADIUS = 5

    # basictileset.png (6 cols x 5 rows, the only sheet load_tileset ever
    # resolves to -- no tileset.png exists) -- a decorative ledge/edge tile
    # drawn one cell south of every non-empty cell whose south neighbor is
    # EMPTY, purely cosmetic: that cell stays EMPTY in logical_grid, so
    # Explorator._is_void still treats it as void (the player falls there
    # same as any other void cell, this just avoids a flat black gap at the
    # visible edge of a room).
    BORDER_TILE_INDEX = 24

    def __init__(self):
        self.tileset = load_tileset()
        self._tile_cache = {}
        self._object_sprites = {}
        self._object_sprite_cache = {}

    def _get_object_frames(self, object_type, variant=None):
        cache_key = (object_type, variant)
        if cache_key not in self._object_sprites:
            self._object_sprites[cache_key] = load_object_frames(object_type, variant)
        return self._object_sprites[cache_key]

    def _get_scaled_tile(self, tile_index, zoom, tile_px, columns):
        cache_key = (tile_index, zoom)
        if cache_key not in self._tile_cache:
            tile_surface = get_tile_surface(self.tileset, tile_index, tile_size=TILE_SIZE, columns=columns)
            self._tile_cache[cache_key] = pygame.transform.scale(tile_surface, (tile_px, tile_px))
        return self._tile_cache[cache_key]

    def render(self, screen, dungeon, camera, spawn_preview=None, hide_object_types=None, show_link_indicators=False, skip_foreground_objects=False, show_grid=True):
        zoom = camera.zoom
        tile_size = dungeon.tile_size
        tile_px = tile_size * zoom
        columns = self.tileset.get_width() // TILE_SIZE
        doorway_cells = self._doorway_cells(dungeon)

        for y, row in enumerate(dungeon.sprite_grid):
            for x, tile_index in enumerate(row):
                if tile_index < 0:
                    continue

                if (x, y) in doorway_cells:
                    tile_index = DEFAULT_FLOOR_SPRITE

                scaled = self._get_scaled_tile(tile_index, zoom, tile_px, columns)

                world_x = x * tile_size
                world_y = y * tile_size
                screen_x, screen_y = camera.world_to_screen(world_x, world_y)
                screen.blit(scaled, (screen_x, screen_y))

        for y, row in enumerate(dungeon.logical_grid):
            for x, cell in enumerate(row):
                if cell == EMPTY:
                    continue
                south_y = y + 1
                if south_y >= dungeon.height or dungeon.logical_grid[south_y][x] == EMPTY:
                    scaled = self._get_scaled_tile(self.BORDER_TILE_INDEX, zoom, tile_px, columns)
                    screen_x, screen_y = camera.world_to_screen(x * tile_size, south_y * tile_size)
                    screen.blit(scaled, (screen_x, screen_y))

        self._draw_objects(
            screen, dungeon, camera,
            hide_object_types=hide_object_types,
            skip_foreground=skip_foreground_objects,
        )

        if show_grid:
            for gy in range(dungeon.height + 1):
                world_y = gy * tile_size
                p1 = camera.world_to_screen(0, world_y)
                p2 = camera.world_to_screen(dungeon.width * tile_size, world_y)
                pygame.draw.line(screen, self.GRID_LINE_COLOR, p1, p2)

            for gx in range(dungeon.width + 1):
                world_x = gx * tile_size
                p1 = camera.world_to_screen(world_x, 0)
                p2 = camera.world_to_screen(world_x, dungeon.height * tile_size)
                pygame.draw.line(screen, self.GRID_LINE_COLOR, p1, p2)

        if spawn_preview is not None:
            gx, gy = spawn_preview
            wx, wy = dungeon.grid_to_world(gx, gy)
            sx, sy = camera.world_to_screen(wx, wy)

            pygame.draw.circle(
                screen,
                self.SPAWN_PREVIEW_COLOR,
                (int(sx), int(sy)),
                int(tile_size * zoom / 4),
                2,
            )

        if show_link_indicators:
            self._draw_link_indicators(screen, dungeon, camera)

    @staticmethod
    def _doorway_cells(dungeon):
        """Every cell covered by a gate/wall entry-exit's footprint. A gate/wall
        can only ever be placed on a WALL cell that already reads as a clean
        doorway (ObjectManager.is_valid_doorway), so its mere presence is
        enough -- no need to re-validate the shape here. Drawing FLOOR under
        it instead of the underlying WALL sprite is purely cosmetic (the
        logical_grid cell stays WALL, so autotiling/doorway-validity/the
        procedural assembler are untouched) -- it just stops the player from
        feeling like they're walking into solid wall texture when the
        gate/wall itself is open (or even closed, since the door sprite is
        what visually reads as blocking, not a wall texture peeking through)."""
        cells = set()
        for obj in dungeon.object_manager.objects:
            if OBJECT_TYPES[obj["type"]]["placement"] != "doorway":
                continue
            size_x, size_y = OBJECT_TYPES[obj["type"]]["size"]
            for dx in range(size_x):
                for dy in range(size_y):
                    cells.add((obj["x"] + dx, obj["y"] + dy))
        return cells

    def render_foreground_objects(self, screen, dungeon, camera, hide_object_types=None):
        """Objects ObjectManager.is_foreground_object() flags (e.g. an L/R torch) -- call this after drawing the player sprite."""
        self._draw_objects(screen, dungeon, camera, hide_object_types=hide_object_types, foreground_only=True)

    def _draw_objects(self, screen, dungeon, camera, hide_object_types=None, foreground_only=False, skip_foreground=False):
        hide_object_types = hide_object_types or ()
        zoom = camera.zoom
        tile_size = dungeon.tile_size

        for obj in dungeon.object_manager.objects:
            if obj["type"] in hide_object_types:
                continue

            is_foreground = dungeon.object_manager.is_foreground_object(obj)

            if foreground_only and not is_foreground:
                continue

            if skip_foreground and is_foreground:
                continue

            frames = self._get_object_frames(obj["type"], obj.get("variant"))
            frame_index = min(obj.get("frame", 0), len(frames) - 1)

            size_cells_x, size_cells_y = OBJECT_TYPES[obj["type"]]["size"]
            cache_key = (obj["type"], obj.get("variant"), frame_index, zoom)
            scaled_sprite = self._object_sprite_cache.get(cache_key)
            if scaled_sprite is None:
                size = (
                    int(size_cells_x * tile_size * zoom),
                    int(size_cells_y * tile_size * zoom),
                )
                scaled_sprite = pygame.transform.scale(frames[frame_index], size)
                self._object_sprite_cache[cache_key] = scaled_sprite

            # Anchored to the footprint's left/bottom edge (not the origin cell's
            # center) so a multi-cell object like "wall" fills exactly the cells
            # it occupies instead of straddling half a tile into its neighbors.
            left_world_x = obj["x"] * tile_size
            bottom_world_y = (obj["y"] + size_cells_y) * tile_size
            sx, sy = camera.world_to_screen(left_world_x, bottom_world_y)

            screen.blit(
                scaled_sprite,
                (
                    sx,
                    sy - scaled_sprite.get_height(),
                ),
            )

    def _draw_link_indicators(self, screen, dungeon, camera):
        for obj in dungeon.object_manager.objects:
            if not dungeon.object_manager.is_linkable(obj["type"]):
                continue

            sx, sy = camera.world_to_screen(*dungeon.object_indicator_position(obj))

            for link_target in obj.get("links", []):
                lsx, lsy = camera.world_to_screen(*dungeon.object_indicator_position(link_target))
                pygame.draw.line(screen, self.LINK_INDICATOR_COLOR, (sx, sy), (lsx, lsy), 2)

            pygame.draw.circle(screen, self.LINK_INDICATOR_COLOR, (int(sx), int(sy)), self.LINK_INDICATOR_RADIUS)
