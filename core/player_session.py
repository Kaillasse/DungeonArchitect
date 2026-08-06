"""Bundles everything about exploration that's per-player, not per-world-
session -- the live Player entity, their own Inventory/InventoryPanel, this
frame's InputState, whether THEIR inventory panel is open, and their own
footstep-audio cadence. Lives at the top level (not core/world/, since it
imports InventoryPanel -- a UI concern -- and not core/engine/, since it's
specific to the exploration flow), the same layering as core/explorator.py
and core/inventory_ui.py themselves."""

from __future__ import annotations

from core.engine.input import InputState
from core.inventory_ui import InventoryPanel
from core.world.entities import Player
from core.world.inventory import Inventory


class PlayerSession:
    """Exactly one exists today (Explorator.players == {0: PlayerSession(0)}),
    always driven by the local keyboard -- but every simulation/render loop
    in Explorator iterates self.players.values() rather than reaching for one
    hardcoded instance, so adding a second session is additive, not a
    rewrite."""

    def __init__(self, player_id):
        self.player_id = player_id
        self.player = Player()
        self.inventory = Inventory()
        self.inventory_panel = InventoryPanel(self.inventory)
        self.input = InputState()
        self.inventory_open = False
        self.footstep_timer = 0.0
        self.footstep_alt = 0
