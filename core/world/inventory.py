"""Minimal inventory data model: just the structure InventoryPanel reads to
draw itself, plus main_slots/currency, which PickupManager.collect mutates
directly. grid_slots has no producer yet -- nothing currently drops loot
into the 15-slot general inventory, only into a main_slot or currency."""

from __future__ import annotations

from pathlib import Path

import pygame

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Item:
    def __init__(self, item_id, name, icon_path, icon_rect=None):
        self.item_id = item_id
        self.name = name
        self.icon_path = icon_path  # relative to assets/
        self.icon_rect = icon_rect  # optional (x, y, w, h) crop -- e.g. a single frame of a spritesheet
        self._icon = None

    def get_icon(self):
        if self._icon is None:
            sheet = pygame.image.load(PROJECT_ROOT / "assets" / self.icon_path).convert_alpha()
            self._icon = sheet.subsurface(self.icon_rect).copy() if self.icon_rect else sheet
        return self._icon


class Inventory:
    GRID_ROWS = 3
    GRID_COLS = 5

    def __init__(self):
        self.main_slots = {"attack": None, "interact": None, "passive": None}
        self.grid_slots = [None] * (self.GRID_ROWS * self.GRID_COLS)
        self.currency = {"gold": 0, "blue": 0}
