"""Minimal inventory data model: just the structure InventoryPanel reads to
draw itself. No add/remove/equip logic yet -- there's no loot/pickup system
in the game to drive it, so this is intentionally a shell (see CLAUDE.md
roadmap for the "coquille" scope decision)."""

from __future__ import annotations

from pathlib import Path

import pygame

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Item:
    def __init__(self, item_id, name, icon_path):
        self.item_id = item_id
        self.name = name
        self.icon_path = icon_path  # relative to assets/
        self._icon = None

    def get_icon(self):
        if self._icon is None:
            self._icon = pygame.image.load(PROJECT_ROOT / "assets" / self.icon_path).convert_alpha()
        return self._icon


class Inventory:
    GRID_ROWS = 3
    GRID_COLS = 5

    def __init__(self):
        self.main_slots = {"attack": None, "interact": None, "passive": None}
        self.grid_slots = [None] * (self.GRID_ROWS * self.GRID_COLS)
        self.currency = {"gold": 0, "blue": 0}
