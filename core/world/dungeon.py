from core.world.object_manager import ObjectManager
from core.rendering.world_renderer import WorldRenderer
from core.data.save_manager import SaveManager
from core.data.ressources import TILE_SIZE as SOURCE_TILE_SIZE, WORLD_SCALE
from core.editor.autotile import EMPTY, FLOOR, build_walls, erase_at, resolve_sprite_grid


DEFAULT_GRID_SAVE_PATH = "room_001"

__all__ = ["DEFAULT_GRID_SAVE_PATH", "Dungeon"]


class Dungeon:
    """Owns the world data (grid, size) and orchestrates its components. Draws nothing, saves nothing, and doesn't manage objects itself."""

    TILE_SIZE = SOURCE_TILE_SIZE * WORLD_SCALE

    def __init__(self, width: int = 20, height: int = 20) -> None:
        self.width = width
        self.height = height
        self.tile_size = self.TILE_SIZE

        self.logical_grid = [[EMPTY for _ in range(width)] for _ in range(height)]
        self.sprite_grid = [[-1 for _ in range(width)] for _ in range(height)]

        self.object_manager = ObjectManager(self)
        self.renderer = WorldRenderer()
        self.save = SaveManager()

    # ------------------------------------------------------------------
    # Grille logique
    # ------------------------------------------------------------------

    def rebuild(self) -> None:
        build_walls(self.logical_grid)
        self.sprite_grid = resolve_sprite_grid(self.logical_grid)

    def paint_cell(self, grid_x: int, grid_y: int, erase: bool = False) -> None:
        if not (0 <= grid_x < self.width and 0 <= grid_y < self.height):
            return
        if erase:
            erase_at(self.logical_grid, grid_x, grid_y)
        else:
            self.logical_grid[grid_y][grid_x] = FLOOR
        self.rebuild()
        self.object_manager.prune_invalid()

    def update(self, dt: float) -> None:
        self.object_manager.update(dt)

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
        corners = (
            (rect.left, rect.top),
            (rect.right - 1, rect.top),
            (rect.left, rect.bottom - 1),
            (rect.right - 1, rect.bottom - 1),
        )

        for x, y in corners:
            grid_x = x // self.tile_size
            grid_y = y // self.tile_size

            if not self.object_manager.is_cell_walkable(grid_x, grid_y):
                return False

        return True

    # ------------------------------------------------------------------
    # Rendu
    # ------------------------------------------------------------------

    def render(self, screen, camera, spawn_preview=None, hide_object_types=None, show_link_indicators=False, skip_foreground_objects=False, hide_cells=None):
        self.renderer.render(
            screen, self, camera,
            spawn_preview=spawn_preview,
            hide_object_types=hide_object_types,
            show_link_indicators=show_link_indicators,
            skip_foreground_objects=skip_foreground_objects,
            hide_cells=hide_cells,
        )

    def render_foreground(self, screen, camera, hide_object_types=None, hide_cells=None):
        """Objects flagged draw_after_player (e.g. torch), meant to be drawn after the player sprite."""
        self.renderer.render_foreground_objects(screen, self, camera, hide_object_types=hide_object_types, hide_cells=hide_cells)
