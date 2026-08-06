"""Bundles everything about exploration that's per-player, not per-world-
session -- the live Player entity, their own Inventory/InventoryPanel, this
frame's InputState, whether THEIR inventory panel is open, and their own
footstep-audio cadence. Lives in core/exploration/ alongside explorator.py
and inventory_ui.py -- not core/world/ (it imports InventoryPanel, a UI
concern) and not core/engine/ (it's specific to the exploration flow, not
generic state-machine plumbing)."""

from __future__ import annotations

from core.engine.input import InputState
from core.exploration.inventory_ui import InventoryPanel
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
        # *_matches_event pairs) | "network" (Phase 3 -- a remote client's
        # session, driven by network_input below instead of a local device)
        # -- which device Explorator._read_input/_handle_session_event
        # should read this session from.
        self.input_source_kind = input_source_kind
        self.joystick = joystick
        # Latest InputState decoded from that client's most recent "input"
        # message (None until the first one arrives) -- only ever set/read
        # for "network" sessions, see Explorator._read_input's "network"
        # branch (core/network/server.py writes this from its connection
        # reader thread; the main tick thread only ever reads it).
        self.network_input = None
        # Phase 4 (client-side prediction) bookkeeping. last_input_seq is
        # server-side only: the seq of the most recent "input" message
        # GameServer._drain_incoming applied to this session, echoed back per
        # tick in protocol.build_snapshot so the owning client knows which of
        # its own buffered inputs are now confirmed. pending_inputs/
        # next_input_seq are client-side only, and only meaningful for that
        # client's own local session: (seq, direction, running, dt) tuples
        # not yet acknowledged by the server, replayed by
        # Explorator._reconcile_local_player on top of each new authoritative
        # snapshot -- see Explorator._predict_local_movement.
        self.last_input_seq = 0
        self.pending_inputs = []
        self.next_input_seq = 0
        # One-shot action ids (Explorator.ONE_SHOT_ACTIONS) buffered by this
        # session's own event matches during run()'s event loop, applied at
        # the start of the next update() -- per-session since Phase 2 has
        # more than one independently event-driven session.
        self.pending_actions = []
        self.inventory_open = False
        self.footstep_timer = 0.0
        self.footstep_alt = 0

    def update_frozen(self, dt):
        """Ticks idle animation only -- shared by Explorator.update()'s
        victory (whole-session) and per-player inventory-open freezes."""
        if self.player.action is None:
            self.player.animation = "idle"
        self.player.update(dt)
