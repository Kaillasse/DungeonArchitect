"""Logical dungeon grid: edition, save/load, and rendering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List
from core.tools import OBJECT_TYPES
from core.ui import ObjectPalette


import pygame

from core.autotile import EMPTY, FLOOR, WALL, build_walls, erase_at, resolve_sprite_grid
from core.ressources import (
    ROOMS_DIRECTORY,
    TILE_SIZE,
    get_tile_surface,
    load_tile_metadata,
    load_tileset,
)

DEFAULT_GRID_SAVE_PATH = "room_001"

__all__ = ["DEFAULT_GRID_SAVE_PATH", "DungeonGrid"]


def _empty_logical_grid(width: int, height: int) -> List[List[int]]:
    return [[EMPTY for _ in range(width)] for _ in range(height)]


def _migrate_legacy_tiles(
    tiles: List[List[int]], category_map: Dict[int, str]
) -> List[List[int]]:
    logical_grid: List[List[int]] = []
    for row in tiles:
        logical_row: List[int] = []
        for tile_index in row:
            if tile_index < 0:
                logical_row.append(EMPTY)
                continue
            category = category_map.get(tile_index, "other")
            if category == "floor":
                logical_row.append(FLOOR)
            elif category == "wall":
                logical_row.append(WALL)
            else:
                logical_row.append(EMPTY)
        logical_grid.append(logical_row)
    build_walls(logical_grid)
    return logical_grid


class DungeonGrid:
    """Editable dungeon grid backed by logical tile types."""

    def __init__(self, width: int = 20, height: int = 20) -> None:
        self.width = width
        self.height = height
        self.tile_size = TILE_SIZE
        self.tile_metadata = load_tile_metadata()
        self.tileset = load_tileset()
        self.logical_grid = _empty_logical_grid(width, height)
        self.sprite_grid = resolve_sprite_grid(self.logical_grid)
        self.objects = []
        self.object_types = OBJECT_TYPES
        self.object_palette = ObjectPalette()
    def _rebuild(self) -> None:
        build_walls(self.logical_grid)
        self.sprite_grid = resolve_sprite_grid(self.logical_grid)

    def get_room_path(self, room_name: str) -> Path:
        return ROOMS_DIRECTORY / f"{room_name}.json"

    def paint_cell(self, grid_x: int, grid_y: int, erase: bool = False) -> None:
        if not (0 <= grid_x < self.width and 0 <= grid_y < self.height):
            return
        if erase:
            erase_at(self.logical_grid, grid_x, grid_y)
        else:
            self.logical_grid[grid_y][grid_x] = FLOOR
        self._rebuild()

    def render(
        self,
        screen,
        camera=None,
        zoom=1,
        spawn_preview=None,
    ):

        columns = self.tileset.get_width() // self.tile_size
        effective_zoom = zoom if camera is None else camera.zoom
        tile_px = self.tile_size * effective_zoom

        if not hasattr(self, "_tile_cache"):
            self._tile_cache = {}

        if camera is None:
            camera = type(
                "_FallbackCamera",
                (),
                {
                    "x": 0.0,
                    "y": 0.0,
                    "zoom": effective_zoom,
                    "world_to_screen": lambda self, world_x, world_y: (offset_x + world_x * effective_zoom, offset_y + world_y * effective_zoom),
                },
            )()

        for y, row in enumerate(self.sprite_grid):
            for x, tile_index in enumerate(row):
                tile_surface = get_tile_surface(
                    self.tileset, tile_index, tile_size=self.tile_size, columns=columns
                )
                cache_key = (tile_index, effective_zoom)
                if cache_key not in self._tile_cache:
                    self._tile_cache[cache_key] = pygame.transform.scale(tile_surface, (tile_px, tile_px))
                scaled = self._tile_cache[cache_key]

                world_x = x * self.tile_size
                world_y = y * self.tile_size
                screen_x, screen_y = camera.world_to_screen(world_x, world_y)
                screen.blit(scaled, (screen_x, screen_y))

        for obj in self.objects:

            sprite = self.object_palette.get_current_frame(
                obj["type"]
            )


            scale = camera.zoom

            size = (
                int(sprite.get_width() * scale),
                int(sprite.get_height() * scale)
            )


            scaled_sprite = pygame.transform.scale(
                sprite,
                size
            )


            wx, wy = self.grid_to_world(
                obj["x"],
                obj["y"]
            )


            sx, sy = camera.world_to_screen(
                wx,
                wy
            )


            screen.blit(
                scaled_sprite,
                (
                    sx - scaled_sprite.get_width() // 2,
                    sy - scaled_sprite.get_height()
                )
            )
        for y in range(self.height + 1):
            world_y = y * self.tile_size
            p1 = camera.world_to_screen(0, world_y)
            p2 = camera.world_to_screen(self.width * self.tile_size, world_y)
            pygame.draw.line(screen, (80, 80, 80), p1, p2)

        for x in range(self.width + 1):
            world_x = x * self.tile_size
            p1 = camera.world_to_screen(world_x, 0)
            p2 = camera.world_to_screen(world_x, self.height * self.tile_size)
            pygame.draw.line(screen, (80, 80, 80), p1, p2)

        if spawn_preview is not None:

            gx, gy = spawn_preview

            wx, wy = self.grid_to_world(gx, gy)

            sx, sy = camera.world_to_screen(wx, wy)

            pygame.draw.circle(

                screen,

                (0,255,0),

                (int(sx),int(sy)),

                int(self.tile_size*camera.zoom/4),

                2

            )


    def to_json(self):
        return {
            "version": 4,
            "width": self.width,
            "height": self.height,
            "objects": self.objects,
            "cells": self.logical_grid,
        }

    def save_to_json(self, room_name= "room_001"):
        output = self.get_room_path(room_name)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as handle:
            json.dump(self.to_json(), handle, indent=2, ensure_ascii=False)
        return output

    def load_from_json(self, room_name="room_001"):
        input_file = self.get_room_path(room_name)
        if not input_file.exists() or input_file.stat().st_size == 0:
            return

        try:
            with input_file.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, json.JSONDecodeError):
            return

        self.width = int(payload.get("width", self.width))
        self.height = int(payload.get("height", self.height))

        self.objects = payload.get("objects", [])

        if payload.get("version") == 2 or "cells" in payload:
            self.logical_grid = [list(row) for row in payload.get("cells", self.logical_grid)]
        else:
            category_map = {
                index: data["category"] for index, data in self.tile_metadata.items()
            }
            self.logical_grid = _migrate_legacy_tiles(
                [list(row) for row in payload.get("tiles", self.logical_grid)],
                category_map,
            )

        self._rebuild()

    def add_object(self, object_type, grid_x, grid_y):

        print(
            object_type,
            grid_x,
            grid_y,
            self.logical_grid[grid_y][grid_x]
        )
        print(grid_x, grid_y)

        if not (0 <= grid_x < self.width):
            return False

        if not (0 <= grid_y < self.height):
            return False

        if self.logical_grid[grid_y][grid_x] != FLOOR:
            return False

        self.objects.append({

            "type": object_type,

            "x": grid_x,

            "y": grid_y,

        })

        return True

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

    def get_spawn_world_position(self):

        for obj in self.objects:

            if obj["type"] == "spawn":

                return self.grid_to_world(
                    obj["x"],
                    obj["y"],
                )

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

            if (
                grid_x < 0
                or grid_y < 0
                or grid_x >= self.width
                or grid_y >= self.height
            ):
                return False

            if self.logical_grid[grid_y][grid_x] == WALL:
                return False

        return True
