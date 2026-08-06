"""Per-frame input snapshot for one player -- generic engine plumbing (a
sibling of Camera), not Explorator-specific state. Reading an InputState
(read_local_keyboard_input) is a pure function fully separate from applying
one (Explorator._apply_requested_actions/_simulate_movement) -- this split
is what lets a future non-local source (network input) become a drop-in
replacement for read_local_keyboard_input's *return value*, without any
simulation code needing to know or care where an InputState came from."""

from __future__ import annotations

from dataclasses import dataclass, field

import pygame


@dataclass
class InputState:
    move_direction: pygame.Vector2 = field(default_factory=pygame.Vector2)  # raw axis input, not normalized
    running: bool = False
    requested_actions: tuple = ()  # one-shot action ids (Explorator.ONE_SHOT_ACTIONS) buffered this frame
    inventory_toggle: bool = False  # shape-parity only -- see Explorator's "input timing" note


def read_local_keyboard_input(settings) -> InputState:
    """Polls pygame.key.get_pressed() for continuous movement/run state only
    -- no event access here (pygame.event.get() is already drained by the
    caller's own event loop each frame), so requested_actions/
    inventory_toggle always come back at their defaults and get filled in
    separately from that frame's buffered events."""
    keys = pygame.key.get_pressed()
    direction = pygame.Vector2()

    if settings.is_action_pressed("move_up", keys):
        direction.y -= 1
    if settings.is_action_pressed("move_down", keys):
        direction.y += 1
    if settings.is_action_pressed("move_left", keys):
        direction.x -= 1
    if settings.is_action_pressed("move_right", keys):
        direction.x += 1

    return InputState(move_direction=direction, running=settings.is_action_pressed("run", keys))
