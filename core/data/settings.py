"""Persisted user settings: rebindable actions, display mode, and the active
BorderManager tile. Mirrors core.data.ressources's style (PROJECT_ROOT-relative
path under assets/, tolerant load with defaults on missing/corrupt file)."""

from __future__ import annotations

import json
from pathlib import Path

import pygame

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "assets" / "settings.json"

DEFAULT_RESOLUTION = (1280, 720)

MOUSE_BUTTON_NAMES = {1: "Clic gauche", 2: "Clic molette", 3: "Clic droit"}

# (action_id, french label, default binding, kinds this action accepts).
# move_*/run are continuous (polled via pygame.key.get_pressed() every frame),
# so only a keyboard key makes sense there; jump/attack/interact are one-shot
# (checked against KEYDOWN/MOUSEBUTTONDOWN events), so either kind works.
# TAB/ESC/F3 are deliberately not here -- navigation/debug shortcuts, not
# gameplay actions to remap.
ACTIONS = (
    ("move_up", "Haut", {"kind": "key", "code": pygame.K_z}, ("key",)),
    ("move_down", "Bas", {"kind": "key", "code": pygame.K_s}, ("key",)),
    ("move_left", "Gauche", {"kind": "key", "code": pygame.K_q}, ("key",)),
    ("move_right", "Droite", {"kind": "key", "code": pygame.K_d}, ("key",)),
    ("run", "Courir", {"kind": "key", "code": pygame.K_LSHIFT}, ("key",)),
    ("jump", "Sauter", {"kind": "key", "code": pygame.K_SPACE}, ("key", "mouse")),
    ("attack", "Attaquer", {"kind": "mouse", "button": 1}, ("key", "mouse")),
    ("interact", "Interagir", {"kind": "mouse", "button": 3}, ("key", "mouse")),
)

ACTION_LABELS = {action_id: label for action_id, label, _, _ in ACTIONS}
ACTION_KINDS = {action_id: kinds for action_id, _, _, kinds in ACTIONS}
_ACTION_DEFAULTS = {action_id: default for action_id, _, default, _ in ACTIONS}


def _binding_to_json(binding):
    if binding["kind"] == "key":
        return {"kind": "key", "name": pygame.key.name(binding["code"])}
    return {"kind": "mouse", "button": binding["button"]}


def _binding_from_json(payload, fallback):
    try:
        if payload.get("kind") == "key":
            return {"kind": "key", "code": pygame.key.key_code(payload["name"])}
        if payload.get("kind") == "mouse":
            return {"kind": "mouse", "button": int(payload["button"])}
    except (KeyError, TypeError, ValueError):
        pass
    return dict(fallback)


def binding_display_name(binding):
    """Human-readable label for a binding dict, e.g. "Z" or "Clic gauche"."""
    if binding["kind"] == "key":
        return pygame.key.name(binding["code"]).upper()
    return MOUSE_BUTTON_NAMES.get(binding["button"], f"Bouton {binding['button']}")


class Settings:
    def __init__(self):
        self.bindings = {action_id: dict(default) for action_id, _, default, _ in ACTIONS}
        self.display = {"fullscreen": False, "resolution": list(DEFAULT_RESOLUTION)}
        self.border_cell = [0, 0]

    # ------------------------------------------------------------------
    # Reading bindings during gameplay
    # ------------------------------------------------------------------

    def is_action_pressed(self, action_id, keys):
        """For continuous actions (movement/run), polled from pygame.key.get_pressed()."""
        binding = self.bindings[action_id]
        if binding["kind"] != "key":
            return False
        return bool(keys[binding["code"]])

    def matches_event(self, action_id, event):
        """For one-shot actions (jump/attack/interact), checked against a KEYDOWN/MOUSEBUTTONDOWN event."""
        binding = self.bindings[action_id]
        if binding["kind"] == "key":
            return event.type == pygame.KEYDOWN and event.key == binding["code"]
        if binding["kind"] == "mouse":
            return event.type == pygame.MOUSEBUTTONDOWN and event.button == binding["button"]
        return False

    def display_name(self, action_id):
        return binding_display_name(self.bindings[action_id])

    # ------------------------------------------------------------------
    # Editing (Settings screen)
    # ------------------------------------------------------------------

    def set_binding(self, action_id, binding):
        """Assign a new binding to action_id and save immediately. If another
        action already used the exact same binding, it gets action_id's old
        binding instead (a swap) -- so one input never ends up silently
        driving two actions at once, and no action ever needs an "unbound"
        state."""
        old_binding = self.bindings[action_id]
        for other_id, other_binding in self.bindings.items():
            if other_id != action_id and other_binding == binding:
                self.bindings[other_id] = old_binding
                break
        self.bindings[action_id] = binding
        self.save()

    def display_mode(self):
        """(size, flags) ready for pygame.display.set_mode(size, flags)."""
        if self.display["fullscreen"]:
            return (0, 0), pygame.FULLSCREEN
        return tuple(self.display["resolution"]), 0

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_json(self):
        return {
            "version": 1,
            "bindings": {action_id: _binding_to_json(binding) for action_id, binding in self.bindings.items()},
            "display": dict(self.display),
            "border_cell": list(self.border_cell),
        }

    @classmethod
    def from_json(cls, payload):
        settings = cls()

        bindings_payload = payload.get("bindings", {})
        for action_id in settings.bindings:
            if action_id in bindings_payload:
                settings.bindings[action_id] = _binding_from_json(
                    bindings_payload[action_id], _ACTION_DEFAULTS[action_id]
                )

        display_payload = payload.get("display", {})
        settings.display["fullscreen"] = bool(display_payload.get("fullscreen", False))
        resolution = display_payload.get("resolution")
        if isinstance(resolution, list) and len(resolution) == 2:
            settings.display["resolution"] = [int(resolution[0]), int(resolution[1])]

        border_cell = payload.get("border_cell")
        if isinstance(border_cell, list) and len(border_cell) == 2:
            settings.border_cell = [int(border_cell[0]), int(border_cell[1])]

        return settings

    def save(self):
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SETTINGS_PATH.open("w", encoding="utf-8") as handle:
            json.dump(self.to_json(), handle, indent=2, ensure_ascii=False)


def load_settings():
    """Settings loaded from SETTINGS_PATH, or defaults if missing/corrupt."""
    if not SETTINGS_PATH.exists() or SETTINGS_PATH.stat().st_size == 0:
        return Settings()

    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return Settings()

    return Settings.from_json(payload)
