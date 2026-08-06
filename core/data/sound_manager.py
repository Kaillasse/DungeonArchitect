"""Centralized SFX playback via pygame.mixer.

A singleton (same shape as core.ui.BorderManager) so every caller shares one
cache of loaded pygame.mixer.Sound objects instead of reloading the same
.wav repeatedly. Falls back to a silent no-op if the mixer can't initialize
(no audio device -- keeps headless smoke tests/CI working without a real
audio backend) or a listed file doesn't exist yet, so playing an event that
isn't wired up (or can't be) is simply a no-op, never a crash.
"""

from __future__ import annotations

from pathlib import Path

import pygame

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOUND_DIRECTORY = PROJECT_ROOT / "assets" / "sound"

# event key -> filename (relative to assets/sound/). Add an entry here once
# its file actually exists; anything not listed is simply never played --
# this doubles as the checklist of which events are actually wired up so far.
SOUND_FILES = {
    "player_footstep_1": "player_footstep_concrete_1.wav",
    "player_footstep_2": "player_footstep_concrete_2.wav",
    "player_attack": "playerattack.wav",
    "skeleton1_attack": "skel1attack.wav",
    "skeleton2_attack": "skel2attack.wav",
    "skeleton_damaged": "skeldamaged.wav",
    "button_pressed": "buttonpressed.wav",
    "gold_collect": "coin_collect.wav",
    "blue_collect": "bluecoin_collect.wav",
    "dynamite_interact": "lightning_dyn.wav",
}


class SoundManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._sounds = {}
        self._volume = 1.0
        self._enabled = True
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        except pygame.error:
            self._enabled = False

    def set_volume(self, volume):
        """Applied to every already-loaded Sound immediately, and to any
        Sound loaded from here on (see play()) -- Settings is the only
        caller right now (the "Volume" screen), but nothing here depends on
        that."""
        self._volume = max(0.0, min(1.0, volume))
        for sound in self._sounds.values():
            sound.set_volume(self._volume)

    def play(self, event_key):
        """No-op if the mixer isn't available, event_key isn't in
        SOUND_FILES yet, or the file is missing/fails to load -- callers
        never need to guard this themselves."""
        if not self._enabled:
            return

        filename = SOUND_FILES.get(event_key)
        if filename is None:
            return

        sound = self._sounds.get(event_key)
        if sound is None:
            path = SOUND_DIRECTORY / filename
            if not path.exists():
                return
            try:
                sound = pygame.mixer.Sound(str(path))
            except pygame.error:
                return
            sound.set_volume(self._volume)
            self._sounds[event_key] = sound

        sound.play()
