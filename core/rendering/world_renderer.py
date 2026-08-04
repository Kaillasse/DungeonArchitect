import pygame

from core.data.ressources import TILE_SIZE, load_tileset, get_tile_surface
from core.world.object_manager import OBJECT_TYPES, load_object_frames


class WorldRenderer:
    """Draws a Dungeon. Holds no world data — only pygame surface caches."""

    GRID_LINE_COLOR = (80, 80, 80)
    SPAWN_PREVIEW_COLOR = (0, 255, 0)
    LINK_INDICATOR_COLOR = (60, 220, 90)
    LINK_INDICATOR_RADIUS = 5

    def __init__(self):
        self.tileset = load_tileset()
        self._tile_cache = {}
        self._object_sprites = {}

    def _get_object_sprite(self, object_type, variant=None):
        cache_key = (object_type, variant)
        if cache_key not in self._object_sprites:
            self._object_sprites[cache_key] = load_object_frames(object_type, variant)[0]
        return self._object_sprites[cache_key]

    def _get_scaled_tile(self, tile_index, zoom, tile_px, columns):
        cache_key = (tile_index, zoom)
        if cache_key not in self._tile_cache:
            tile_surface = get_tile_surface(self.tileset, tile_index, tile_size=TILE_SIZE, columns=columns)
            self._tile_cache[cache_key] = pygame.transform.scale(tile_surface, (tile_px, tile_px))
        return self._tile_cache[cache_key]

    def render(self, screen, dungeon, camera, spawn_preview=None, hide_object_types=None, show_link_indicators=False):
        hide_object_types = hide_object_types or ()
        zoom = camera.zoom
        tile_size = dungeon.tile_size
        tile_px = tile_size * zoom
        columns = self.tileset.get_width() // TILE_SIZE

        for y, row in enumerate(dungeon.sprite_grid):
            for x, tile_index in enumerate(row):
                if tile_index < 0:
                    continue

                scaled = self._get_scaled_tile(tile_index, zoom, tile_px, columns)

                world_x = x * tile_size
                world_y = y * tile_size
                screen_x, screen_y = camera.world_to_screen(world_x, world_y)
                screen.blit(scaled, (screen_x, screen_y))

        for obj in dungeon.object_manager.objects:
            if obj["type"] in hide_object_types:
                continue

            sprite = self._get_object_sprite(obj["type"], obj.get("variant"))

            size_cells_x, size_cells_y = OBJECT_TYPES[obj["type"]]["size"]
            size = (
                int(size_cells_x * tile_size * zoom),
                int(size_cells_y * tile_size * zoom),
            )
            scaled_sprite = pygame.transform.scale(sprite, size)

            wx, wy = dungeon.grid_to_world(obj["x"], obj["y"])
            sx, sy = camera.world_to_screen(wx, wy)

            screen.blit(
                scaled_sprite,
                (
                    sx - scaled_sprite.get_width() / 2,
                    sy - scaled_sprite.get_height(),
                ),
            )

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

    def _draw_link_indicators(self, screen, dungeon, camera):
        for obj in dungeon.object_manager.objects:
            if not dungeon.object_manager.is_linkable(obj["type"]):
                continue

            sx, sy = camera.world_to_screen(*dungeon.object_indicator_position(obj))

            for link_target in obj.get("links", []):
                lsx, lsy = camera.world_to_screen(*dungeon.object_indicator_position(link_target))
                pygame.draw.line(screen, self.LINK_INDICATOR_COLOR, (sx, sy), (lsx, lsy), 2)

            pygame.draw.circle(screen, self.LINK_INDICATOR_COLOR, (int(sx), int(sy)), self.LINK_INDICATOR_RADIUS)
