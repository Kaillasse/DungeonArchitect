"""Centralized SFX playback via pygame.mixer.

A singleton (same shape as core.ui.widgets.BorderManager) so every caller shares one
cache of loaded pygame.mixer.Sound objects instead of reloading the same
.wav repeatedly. Falls back to a silent no-op if the mixer can't initialize
(no audio device -- keeps headless smoke tests/CI working without a real
audio backend) or a listed file doesn't exist yet, so playing an event that
isn't wired up (or can't be) is simply a no-op, never a crash.
"""

from __future__ import annotations

import array
import random
from pathlib import Path

import pygame

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOUND_DIRECTORY = PROJECT_ROOT / "assets" / "sound"

# array.array typecode for each pygame.mixer sample format (from
# pygame.mixer.get_init()'s "size" -- positive = unsigned, negative =
# signed, magnitude = bits per sample) -- see _resample_sound. Only the
# formats pygame.mixer.init() can actually produce are listed; an unknown
# one (shouldn't happen) just disables pitch-shifting, never crashes.
_SAMPLE_TYPECODES = {8: "B", -8: "b", 16: "H", -16: "h", 32: "I", -32: "i"}

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


def _resample_sound(sound, rate):
    """A NEW pygame.mixer.Sound built from `sound`'s own raw samples,
    resampled by `rate` (>1 = higher pitch/faster, <1 = lower pitch/slower)
    -- the classic "cheap" pitch shift via speed change (duration moves
    with pitch too, same tradeoff every simple game-audio pitch-randomizer
    makes), picking the nearest source frame per output frame rather than
    interpolating -- perceptually fine for short SFX, and avoids a second,
    slower pass per sample. Pure stdlib (the `array` module), no numpy --
    this project's requirements.txt stays pygame-only. Returns None (caller
    falls back to the unpitched sound) if the mixer's format isn't one
    _SAMPLE_TYPECODES recognizes, or on any decode/encode error."""
    try:
        init = pygame.mixer.get_init()
        if init is None:
            return None
        _freq, fmt, channels = init
        typecode = _SAMPLE_TYPECODES.get(fmt)
        if typecode is None:
            return None
        channels = max(1, channels)

        samples = array.array(typecode)
        samples.frombytes(sound.get_raw())
        frame_count = len(samples) // channels
        if frame_count == 0:
            return None

        new_frame_count = max(1, int(frame_count / rate))
        out = array.array(typecode)
        for i in range(new_frame_count):
            src_index = min(frame_count - 1, int(i * rate))
            base = src_index * channels
            out.extend(samples[base:base + channels])

        return pygame.mixer.Sound(buffer=out.tobytes())
    except (pygame.error, ValueError, OverflowError, MemoryError):
        return None


def play_card_sound(sounds, key, fallback_event=None, pitch_range=None):
    """Plays sounds.get(key) via SoundManager.play_path if the card
    actually has one assigned, else fallback_event via the legacy
    SOUND_FILES-keyed play() if given -- the one place every per-card
    sound trigger (Enemy attack/damaged/death, button interact, dynamite
    throw) goes through, so "the card's own sound wins, the old hardcoded
    event is the fallback for a card that never had one assigned" is
    expressed once instead of re-implemented at each call site. `sounds`
    may be None (a type/item with no "sounds" field at all). `pitch_range`
    -- (min, max), see core.world.object_manager's "sound_pitch" mechanics
    field -- picks a fresh random multiplier EVERY call within that range
    (a repeated attack/footstep/etc should never sound identical twice);
    ignored (played at normal pitch) if None, a degenerate [x, x] pair, or
    the fallback-event path (legacy SOUND_FILES events don't carry a pitch
    range at all)."""
    manager = SoundManager()
    filename = (sounds or {}).get(key)
    if filename:
        pitch = None
        if pitch_range and len(pitch_range) == 2:
            lo, hi = sorted(pitch_range)
            if hi > lo:
                pitch = random.uniform(lo, hi)
        manager.play_path(filename, pitch=pitch)
    elif fallback_event:
        manager.play(fallback_event)


def list_available_sound_files():
    """Every .wav under SOUND_DIRECTORY, sorted -- the picklist a card's own
    "sounds" field (see core.world.object_manager's "sounds" mechanics
    field / core.editor.ui.mechanics_panel.MechanicsPanelUI) is assigned
    from. A plain filesystem scan, not SOUND_FILES' curated event->file map
    above -- a card sound is chosen by filename directly, not through a
    named gameplay event."""
    if not SOUND_DIRECTORY.exists():
        return []
    return sorted(path.name for path in SOUND_DIRECTORY.glob("*.wav"))


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

    # Random pitch is quantized to this step before resampling+caching --
    # continuous per-play randomness (random.uniform in play_card_sound)
    # still sounds varied at this granularity to the ear, but it bounds how
    # many distinct resampled Sounds ever actually get computed per (file,
    # range) to a small, fixed set (e.g. a 0.85-1.15 range is ~15 buckets)
    # instead of resampling fresh -- a real per-sample Python loop, see
    # _resample_sound -- on every single play.
    PITCH_QUANTIZE_STEP = 0.02

    def play_path(self, filename, pitch=None):
        """Same loading/caching/no-op-on-failure contract as before, but
        keyed by a raw filename (relative to SOUND_DIRECTORY) instead of a
        SOUND_FILES event key -- for a per-card sound (see
        core.world.object_manager's "sounds" mechanics field), whose
        filename is arbitrary player-chosen data, not a fixed gameplay
        event. `pitch` (a multiplier, 1.0 = unchanged) plays a resampled,
        separately-cached variant instead of the plain file -- see
        _pitched_sound. Cached separately from play()'s _sounds (keyed by
        f"path:{filename}") so a filename that also happens to be used as a
        SOUND_FILES value doesn't share a cache slot with a differently-
        volumed instance."""
        if not self._enabled or not filename:
            return

        if pitch is not None and abs(pitch - 1.0) > 0.01:
            sound = self._pitched_sound(filename, pitch)
        else:
            sound = self._load_path_sound(filename)

        if sound is not None:
            sound.play()

    def _load_path_sound(self, filename):
        cache_key = f"path:{filename}"
        sound = self._sounds.get(cache_key)
        if sound is None:
            path = SOUND_DIRECTORY / filename
            if not path.exists():
                return None
            try:
                sound = pygame.mixer.Sound(str(path))
            except pygame.error:
                return None
            sound.set_volume(self._volume)
            self._sounds[cache_key] = sound
        return sound

    def _pitched_sound(self, filename, pitch):
        """A resampled variant of `filename`, quantized to
        PITCH_QUANTIZE_STEP and cached under its own key -- computed once
        per (filename, quantized pitch) pair, reused after that. Falls back
        to the plain (unpitched) sound if the base file is missing or
        resampling fails for any reason (e.g. an exotic mixer format
        _resample_sound doesn't recognize) -- pitch is a decoration, never
        something worth losing the sound entirely over."""
        quantized = round(pitch / self.PITCH_QUANTIZE_STEP) * self.PITCH_QUANTIZE_STEP
        cache_key = f"pitch:{filename}:{quantized:.2f}"
        cached = self._sounds.get(cache_key)
        if cached is not None:
            return cached

        base = self._load_path_sound(filename)
        if base is None:
            return None
        shifted = _resample_sound(base, quantized)
        if shifted is None:
            return base
        shifted.set_volume(self._volume)
        self._sounds[cache_key] = shifted
        return shifted
