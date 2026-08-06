from __future__ import annotations


class Camera:
    def __init__(self, x: float = 0.0, y: float = 0.0, zoom: float = 1.0, min_zoom: float = 0.5, max_zoom: float = 4.0):
        self.x = float(x)
        self.y = float(y)
        self.min_zoom = float(min_zoom)
        self.max_zoom = float(max_zoom)
        self.zoom = float(zoom)

    def zoom_at(self, screen_x: float, screen_y: float, delta: float = 0.0, screen_width: float | None = None, screen_height: float | None = None):
        if delta == 0:
            return self.zoom

        old_zoom = self.zoom
        next_zoom = old_zoom * (1.2 if delta > 0 else 0.8)
        next_zoom = max(self.min_zoom, min(self.max_zoom, next_zoom))

        if screen_width is None:
            screen_width = 1.0
        if screen_height is None:
            screen_height = 1.0

        anchor_world_x, anchor_world_y = self.screen_to_world(screen_x, screen_y)
        self.zoom = next_zoom
        self.x = anchor_world_x - screen_x / self.zoom
        self.y = anchor_world_y - screen_y / self.zoom
        return self.zoom

    def world_to_screen(self, world_x, world_y):
        if hasattr(world_x, "x") and hasattr(world_x, "y"):
            world_x, world_y = world_x.x, world_x.y

        screen_x = (world_x - self.x) * self.zoom
        screen_y = (world_y - self.y) * self.zoom
        return screen_x, screen_y

    def screen_to_world(self, screen_x, screen_y):
        world_x = screen_x / self.zoom + self.x
        world_y = screen_y / self.zoom + self.y
        return world_x, world_y

    def center_on(self, world_x, world_y, screen_width, screen_height):
        self.x = world_x - screen_width / (2 * self.zoom)
        self.y = world_y - screen_height / (2 * self.zoom)
        return self.x, self.y