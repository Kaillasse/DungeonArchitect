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
    """Every simulation/render loop in Explorator iterates
    self.players.values() rather than reaching for one hardcoded instance, so
    adding a session is additive, not a rewrite (see Phase 2's local co-op
    proof of concept, which finally adds a real second one)."""

    def __init__(self, player_id, input_source_kind="keyboard", joystick=None):
        self.player_id = player_id
        self.player = Player()
        self.inventory = Inventory()
        self.inventory_panel = InventoryPanel(self.inventory)
        self.input = InputState()
        # "keyboard" (Settings-driven, player 1 only) | "secondary_keyboard"
        # | "gamepad" (joystick set, see core/engine/input.py's read_*/
        # *_matches_event pairs) -- which device Explorator._read_input/
        # _handle_session_event should read this session from.
        self.input_source_kind = input_source_kind
        self.joystick = joystick
        # One-shot action ids (Explorator.ONE_SHOT_ACTIONS) buffered by this
        # session's own event matches during run()'s event loop, applied at
        # the start of the next update() -- per-session since Phase 2 has
        # more than one independently event-driven session.
        self.pending_actions = []
        self.inventory_open = False
        self.footstep_timer = 0.0
        self.footstep_alt = 0
