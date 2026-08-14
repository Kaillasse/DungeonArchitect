"""Minimal inventory data model: just the structure InventoryPanel reads to
draw itself, plus main_slots/currency/grid_slots, which PickupManager.collect
mutates directly (via Inventory.add_card for grid_slots -- see CardStub).
grid_slots holds cards found this run (see core.world.entities.CardPickup):
its previous docstring here said it had "no producer yet" -- CardPickup
collection is that producer now."""

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


class CardStub:
    """A lightweight, get_icon()-only stand-in for Item -- what Inventory.
    grid_slots holds for a card found this run (see core.world.entities.
    CardPickup/PickupManager.collect). Deliberately not a real Item: a
    card's sprite source varies by card_type (OBJECT_TYPES/ITEM_DEFINITIONS/
    a base tile/a room thumbnail), resolved via core.data.cards.
    resolve_card_sprite rather than a fixed icon_path/icon_rect crop.
    `count` (>=1) lets repeat pickups of the same card_id stack onto one
    slot instead of consuming a second one -- see Inventory.add_card."""

    def __init__(self, card_id):
        self.card_id = card_id
        self.count = 1
        self._icon = None

    def get_icon(self):
        if self._icon is None:
            from core.data.cards import resolve_card_sprite  # deferred: avoids a cards.py <-> inventory.py cycle
            self._icon = resolve_card_sprite(self.card_id) or pygame.Surface((16, 16), pygame.SRCALPHA)
        return self._icon


class Inventory:
    GRID_ROWS = 3
    GRID_COLS = 5

    def __init__(self):
        self.main_slots = {"attack": None, "interact": None, "passive": None}
        self.grid_slots = [None] * (self.GRID_ROWS * self.GRID_COLS)
        self.currency = {"gold": 0, "blue": 0}

    def add_card(self, card_id):
        """Stacks `card_id` onto its own grid_slots entry if it already has
        one, else fills the first empty slot -- True on success, False if
        every slot is already taken by a DIFFERENT card_id (the pickup
        stays on the ground uncollected in that case, see PickupManager.
        collect's own caller in Explorator._resolve_pickups)."""
        for stub in self.grid_slots:
            if stub is not None and stub.card_id == card_id:
                stub.count += 1
                return True
        for index, stub in enumerate(self.grid_slots):
            if stub is None:
                self.grid_slots[index] = CardStub(card_id)
                return True
        return False

    def clear_cards(self):
        """Empties grid_slots -- called once a run's cards have been moved
        elsewhere (Explorator._trigger_victory banks them into
        Profile.card_stash; a fresh run/session simply never had any to
        begin with, see PlayerSession.__init__), never partway through a
        live run."""
        self.grid_slots = [None] * (self.GRID_ROWS * self.GRID_COLS)
