"""Bundles everything about exploration that's per-player, not per-world-
session -- the live Player entity, their own Inventory/InventoryPanel, this
frame's InputState, whether THEIR inventory panel is open, and their own
footstep-audio cadence. Lives in core/exploration/ alongside explorator.py
and inventory_ui.py -- not core/world/ (it imports InventoryPanel, a UI
concern) and not core/engine/ (it's specific to the exploration flow, not
generic state-machine plumbing)."""

from __future__ import annotations

from core.engine.camera import Camera
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
        # This session's progression (core.data.profile_manager.Profile), or
        # None if it has no identity to track XP against -- a local co-op
        # secondary device (gamepad/2nd keyboard, see Phase 2) never gets one
        # today, and Explorator._grant_xp is a no-op for a None profile.
        self.profile = None
        # This session's own room/floor in a procedurally-assembled dungeon
        # (a PlacedRoom, see core.world.assembly), or None in single-room
        # mode. Used to be a single Explorator-level attribute shared by
        # every session -- one player crossing a door used to silently drag
        # every OTHER player's collision/rendering into the new room/floor
        # with them. Set by Explorator.open_room/open_donjon/
        # add_network_session at spawn time, then kept current per-frame by
        # Explorator._update_current_room/_attempt_fall.
        self.current_placed_room = None
        # The door object (a plain dict from some room's object list) this
        # session was last resolved to be standing on, or None -- the
        # edge-trigger state _update_current_room needs to tell "just
        # stepped onto this door" apart from "still standing on the door
        # from last frame." Also per-session now, for the same reason as
        # current_placed_room above.
        self.last_door_obj = None
        # Same edge-trigger shape as last_door_obj above, for the two new
        # E/S roles (see core.world.object_manager.get_role/set_role):
        # (grid_x, grid_y) this session was last resolved standing on a
        # dungeon_entrance/dungeon_exit-flagged object, or None -- tells
        # "just stepped onto this cell" apart from "still standing there
        # from last frame" so Explorator._check_dungeon_entrance/
        # _check_dungeon_exit don't re-trigger every single frame spent on
        # the cell. Local grid coordinates (dungeon_entrance is always
        # single-room/home; dungeon_exit's own check converts global to
        # local itself), not global -- see both methods.
        self.last_dungeon_entrance_pos = None
        self.last_dungeon_exit_pos = None
        # This session's own camera -- real split-screen (one independent
        # viewport per LOCAL session, see Explorator._viewport_rects) means
        # each local player follows their own position at their own zoom,
        # instead of the old single shared Explorator.camera trying to
        # zoom-to-fit everyone into one view. A "network"-kind session's
        # camera is simply never used for rendering (only the local
        # session(s) ever get a viewport), but costs nothing to have.
        self.camera = Camera(zoom=1.0)

    def update_frozen(self, dt):
        """Ticks idle animation only -- shared by Explorator.update()'s
        victory (whole-session) and per-player inventory-open freezes."""
        if self.player.action is None:
            self.player.animation = "idle"
        self.player.update(dt)
