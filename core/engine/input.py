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


# ---------------------------------------------------------------------
# Player 2, local co-op (Phase 2) -- fixed, code-defined mappings, not routed
# through Settings: Settings' rebinding/persistence/UI is single-scheme and
# keyboard/mouse-only, and generalizing it to multiple players/device kinds
# is out of scope for a proof of concept. Gamepad is preferred when a
# controller is connected at startup; the second keyboard scheme is a
# same-machine fallback (see Explorator's lazy-join logic).
# ---------------------------------------------------------------------

SECONDARY_KEYBOARD_BINDINGS = {
    "move_up": pygame.K_UP,
    "move_down": pygame.K_DOWN,
    "move_left": pygame.K_LEFT,
    "move_right": pygame.K_RIGHT,
    "run": pygame.K_RSHIFT,
    "jump": pygame.K_RCTRL,
    "attack": pygame.K_KP_ENTER,
    "interact": pygame.K_KP0,
    "inventory": pygame.K_KP1,
}


def read_secondary_keyboard_input() -> InputState:
    """Same shape as read_local_keyboard_input, against the fixed second
    scheme instead of Settings."""
    keys = pygame.key.get_pressed()
    direction = pygame.Vector2()

    if keys[SECONDARY_KEYBOARD_BINDINGS["move_up"]]:
        direction.y -= 1
    if keys[SECONDARY_KEYBOARD_BINDINGS["move_down"]]:
        direction.y += 1
    if keys[SECONDARY_KEYBOARD_BINDINGS["move_left"]]:
        direction.x -= 1
    if keys[SECONDARY_KEYBOARD_BINDINGS["move_right"]]:
        direction.x += 1

    return InputState(move_direction=direction, running=bool(keys[SECONDARY_KEYBOARD_BINDINGS["run"]]))


def secondary_keyboard_matches_event(action_id, event) -> bool:
    """For the second scheme's one-shot actions (jump/attack/interact/
    inventory), checked against a KEYDOWN event -- mirrors
    Settings.matches_event's "key" branch, but there's no mouse option here
    (mouse is inherently a single, already-player-1-owned device)."""
    binding = SECONDARY_KEYBOARD_BINDINGS.get(action_id)
    return binding is not None and event.type == pygame.KEYDOWN and event.key == binding


GAMEPAD_DEADZONE = 0.25  # left-stick magnitude below this reads as no input
GAMEPAD_RUN_BUTTON = 4  # left bumper, on a typical Xbox/DirectInput layout
GAMEPAD_BUTTON_BINDINGS = {
    "jump": 0,      # A / Cross
    "interact": 1,  # B / Circle
    "attack": 2,    # X / Square
    "inventory": 3,  # Y / Triangle
}


def read_gamepad_input(joystick) -> InputState:
    """Left stick (axes 0/1) for movement, with a deadzone so a controller's
    resting drift doesn't register as constant tiny movement; GAMEPAD_RUN_BUTTON
    held for running."""
    direction = pygame.Vector2(joystick.get_axis(0), joystick.get_axis(1))
    if direction.length() < GAMEPAD_DEADZONE:
        direction = pygame.Vector2()

    return InputState(move_direction=direction, running=bool(joystick.get_button(GAMEPAD_RUN_BUTTON)))


def gamepad_matches_event(joystick, action_id, event) -> bool:
    """For a gamepad session's one-shot actions, checked against a
    JOYBUTTONDOWN event -- instance_id scopes this to the specific joystick
    this session owns, so a second controller (if ever connected) can't
    drive someone else's session."""
    binding = GAMEPAD_BUTTON_BINDINGS.get(action_id)
    return (
        binding is not None
        and event.type == pygame.JOYBUTTONDOWN
        and event.button == binding
        and event.instance_id == joystick.get_instance_id()
    )
