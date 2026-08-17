"""Procedural card-burn animation -- the post-tear counterpart to
core.editor.ui.card_tear. Once a Dechirer drag commits, card_tear's own
TearState.top piece (the piece that flies off after release -- everything
ABOVE the extracted property row; the property row itself lives on
TearState.bottom, which never moves and never burns, see card_tear's own
module docstring) no longer just flies away and shrinks -- it catches fire
at its own freshly torn edge and burns away in place instead. Same "pure
pixels in, pixels out, never mutates the source" contract as card_tear:
this module knows nothing about cards, capacities, or the Forge --
core.editor.ui.mechanics_panel.MechanicsPanelUI owns that (see its
handle_event's MOUSEBUTTONUP commit branch, which is the only caller), it
only turns (surface, elapsed_time) into a burned composite plus a handful
of flame positions to draw over it.

Unlike card_tear's create_tear_state (a pure function re-called every
frame with an explicit progress), a burn plays out over real, elapsed
time with no further input once started, so it's a small stateful class
instead -- closer to core.world.entities.Explosion/DestructionSpark's own
"construct once, update(dt) every frame, check .finished" shape than to
anything else already in this UI layer.

Algorithm: at construction, the piece is divided into a coarse grid of
CELL_PX-sided cells (NOT per-pixel -- see "Performance" below). Each cell
gets a deterministic ignite_at time, derived once from its distance to one
of a few random ignition points along the piece's own torn (bottom) edge,
divided by a propagation speed, plus a small random offset so the front
reads as ragged rather than a perfect circle -- same "few random control
points, no re-rolled randomness per frame" idea card_tear's own
_tear_boundary already uses for its jagged cut line. From ignite_at
onward, a cell's burn_progress ramps 0->1 over burn_duration: the first
DARKEN_PHASE fraction darkens it (RGB multiply), the rest fades it out
(alpha multiply) -- one combined pygame.Surface.fill(..., BLEND_RGBA_MULT)
call per repaint. A fixed, precomputed set of flame sprites (never
created/destroyed per frame -- see "Performance") rides the same
ignite_at timing, so flames naturally cluster on whatever's currently
alight and vanish once their own cell is mostly gone.

Performance: a torn Forge piece can be several hundred pixels in each
dimension (hundreds of thousands of pixels) -- a per-pixel Python loop
every frame would be far too slow. Cells fix that (a few thousand cells
instead of hundreds of thousands of pixels), and update() only ever
repaints cells that are ACTUALLY mid-burn this frame (tracked via a
sorted-by-ignite_at pending list plus an active list), never the ones
that haven't ignited yet or have already finished -- so per-frame cost
tracks the width of the current fire front, not the size of the whole
piece or how long it's been burning.

Determinism: every random draw (ignition points, per-cell noise, flame
placement/scale/desync) happens once in __init__, seeded once (an
explicit `seed`, or a fresh one if omitted -- either way, fixed for the
lifetime of one BurnAnimation instance). update() never calls random()
itself, so a given cell's progression is fully determined by elapsed
time alone -- no per-frame flicker.
"""

from __future__ import annotations

import math
import random

import pygame

from core.world.object_manager import load_flame_frames

# -- Configurable parameters (see module docstring) ----------------------

CELL_PX = 8
PROPAGATION_SPEED = 260.0       # px/sec the fire front advances from its ignition points
BURN_DURATION = 0.55            # seconds one cell takes to go from just-ignited to fully gone
# Ignition-time jitter, as a fraction of BURN_DURATION -- kept small on
# purpose (confirmed with the user, dropped from an earlier 0.35): the
# front is ALREADY organic/irregular from distance-to-nearest-source alone
# (several sources, a coarse cell grid), so a large noise term on top of
# that just reads as speckled/patchy rather than a coherent front. A small
# amount still keeps neighboring cells from igniting in perfect lockstep.
RANDOMNESS = 0.12
DARKEN_STRENGTH = 0.85          # how dark a fully-darkened cell gets before it starts fading (0=black, 1=unchanged)
ALPHA_FADE_START = 0.55         # fraction of a cell's own progress where it starts losing alpha (before that: darkening only)
IGNITION_SOURCES = 6            # how many points the fire starts from (see ignition_edge="perimeter")
FLAME_DENSITY = 14              # how many flame sprites ride the front
FLAME_ANIMATION_SPEED = 0.08    # seconds per flame frame
FLAME_SCALE_RANGE = (0.9, 1.7)
FLAME_VISIBLE_FRACTION = 0.6    # a flame is drawn only while its own cell's progress is within [0, this]


class _BurnCell:
    __slots__ = ("rect", "ignite_at")

    def __init__(self, rect, ignite_at):
        self.rect = rect
        self.ignite_at = ignite_at


class _Flame:
    __slots__ = ("x", "y", "scale", "frame_offset", "ignite_at")

    def __init__(self, x, y, scale, frame_offset, ignite_at):
        self.x = x
        self.y = y
        self.scale = scale
        self.frame_offset = frame_offset
        self.ignite_at = ignite_at


class BurnAnimation:
    """Burns `surface` (any pygame.Surface, never modified -- see
    get_surface) away over time. Construct once when a tear commits, call
    update(dt) every frame, draw via get_surface()/draw_flames(), drop the
    instance once .finished is True (same "caller owns the state, this
    class only advances/draws it" shape as core.world.entities.Explosion/
    DestructionSpark's own update(dt)+.finished)."""

    def __init__(
        self, surface, seed=None,
        cell_px=CELL_PX, propagation_speed=PROPAGATION_SPEED, burn_duration=BURN_DURATION,
        randomness=RANDOMNESS, darken_strength=DARKEN_STRENGTH, alpha_fade_start=ALPHA_FADE_START,
        ignition_sources=IGNITION_SOURCES, flame_density=FLAME_DENSITY, ignition_edge="perimeter",
    ):
        self.original = surface
        self.width, self.height = surface.get_size()
        # A working copy, progressively repainted in place -- never the
        # original (see module docstring's "never mutates the source").
        self.composite = surface.copy()
        self.elapsed = 0.0
        self.finished = self.width <= 0 or self.height <= 0

        self.cell_px = max(1, cell_px)
        self.burn_duration = max(0.01, burn_duration)
        self.darken_strength = darken_strength
        self.alpha_fade_start = alpha_fade_start
        # Where the fire starts from -- "top"/"bottom" sit every ignition
        # source along that one edge (fire sweeps directionally across the
        # piece); "perimeter" (the default everything in this codebase
        # actually uses -- confirmed with the user: "de l'exterieur vers
        # l'interieur" reads far more like paper actually catching fire
        # than a single directional sweep) scatters sources around ALL
        # FOUR edges instead, so the front closes in on the piece's own
        # center from every side at once. See _ignition_sources.
        self.ignition_edge = ignition_edge

        rng = random.Random(seed)
        cells = self._build_cells(rng, propagation_speed, randomness, ignition_sources)
        # Two views of the same _BurnCell objects: `_pending` stays sorted
        # by ignite_at so update() can advance a single index into it
        # instead of re-scanning every cell every frame; `_active` holds
        # only cells currently mid-burn (see update()).
        self._pending = sorted(cells, key=lambda cell: cell.ignite_at)
        self._pending_index = 0
        self._active = []
        self.flames = self._build_flames(rng, cells, flame_density)
        self._flame_scale_cache = {}

    def _ignition_sources(self, rng, ignition_sources):
        count = max(1, ignition_sources)
        if self.ignition_edge == "perimeter":
            sides = ("top", "bottom", "left", "right")
            return [self._point_on_edge(rng, rng.choice(sides)) for _ in range(count)]
        edge = "top" if self.ignition_edge == "top" else "bottom"
        return [self._point_on_edge(rng, edge) for _ in range(count)]

    def _point_on_edge(self, rng, edge):
        if edge == "top":
            return (rng.uniform(0, self.width), 0.0)
        if edge == "bottom":
            return (rng.uniform(0, self.width), float(self.height))
        if edge == "left":
            return (0.0, rng.uniform(0, self.height))
        return (float(self.width), rng.uniform(0, self.height))

    def _build_cells(self, rng, propagation_speed, randomness, ignition_sources):
        sources = self._ignition_sources(rng, ignition_sources)
        noise_span = self.burn_duration * randomness
        cells = []
        for gy in range(0, self.height, self.cell_px):
            for gx in range(0, self.width, self.cell_px):
                cx, cy = gx + self.cell_px / 2, gy + self.cell_px / 2
                distance = min(math.hypot(cx - sx, cy - sy) for sx, sy in sources)
                ignite_at = distance / propagation_speed + rng.uniform(-noise_span, noise_span)
                rect = pygame.Rect(
                    gx, gy, min(self.cell_px, self.width - gx), min(self.cell_px, self.height - gy),
                )
                cells.append(_BurnCell(rect, max(0.0, ignite_at)))
        return cells

    def _build_flames(self, rng, cells, flame_density):
        """A FIXED set of flame slots, chosen once -- never spawned/despawned
        per frame (see module docstring's "Performance"). Each rides the
        ignite_at of whichever cell it was sampled from, so it naturally
        appears while that patch is alight and disappears once it's mostly
        burned away (see draw_flames' FLAME_VISIBLE_FRACTION check)."""
        if not cells:
            return []
        sample_size = min(flame_density, len(cells))
        flames = []
        for cell in rng.sample(cells, sample_size):
            flames.append(_Flame(
                x=rng.uniform(cell.rect.left, cell.rect.right),
                y=rng.uniform(cell.rect.top, cell.rect.bottom),
                scale=rng.uniform(*FLAME_SCALE_RANGE),
                frame_offset=rng.uniform(0, 1000),
                ignite_at=cell.ignite_at,
            ))
        return flames

    def update(self, dt):
        if self.finished:
            return
        self.elapsed += dt

        while (
            self._pending_index < len(self._pending)
            and self._pending[self._pending_index].ignite_at <= self.elapsed
        ):
            self._active.append(self._pending[self._pending_index])
            self._pending_index += 1

        still_burning = []
        for cell in self._active:
            progress = self._cell_progress(cell)
            self._paint_cell(cell, progress)
            if progress < 1.0:
                still_burning.append(cell)
        self._active = still_burning

        if self._pending_index >= len(self._pending) and not self._active:
            self.finished = True

    def _cell_progress(self, cell):
        return max(0.0, min(1.0, (self.elapsed - cell.ignite_at) / self.burn_duration))

    def _paint_cell(self, cell, progress):
        """Resets this cell to its pristine pixels, then re-applies the
        darken/fade for the CURRENT progress -- BLEND_RGBA_MULT is
        cumulative, so re-multiplying an already-darkened cell frame after
        frame would over-darken it; repainting from the original each time
        keeps a single fill() call correct regardless of how long this
        cell has been burning. Only ever called for cells in `_active`
        (mid-burn), so this stays cheap -- see class/module docstrings."""
        self.composite.blit(self.original, cell.rect.topleft, cell.rect)
        if progress <= self.alpha_fade_start:
            darken_t = progress / self.alpha_fade_start if self.alpha_fade_start > 0 else 1.0
            value = round(255 * (1.0 - darken_t * (1.0 - self.darken_strength)))
            alpha = 255
        else:
            value = round(255 * self.darken_strength)
            fade_t = (progress - self.alpha_fade_start) / max(1e-6, 1.0 - self.alpha_fade_start)
            alpha = round(255 * (1.0 - fade_t))
        self.composite.fill((value, value, value, alpha), cell.rect, special_flags=pygame.BLEND_RGBA_MULT)

    def get_surface(self):
        """The current burned composite -- blit this at whatever screen
        position the piece was already sitting at (this animation has no
        opinion on position/camera/panel layout, see module docstring)."""
        return self.composite

    def draw_flames(self, screen, origin):
        """Draws every currently-visible flame on top of get_surface()'s
        own composite, `origin` being where that composite's own (0, 0)
        lands on `screen`. Desynchronized on purpose (each flame's own
        frame_offset, see _build_flames) so they never all show the same
        frame at once."""
        frames = load_flame_frames()
        frame_count = len(frames)
        ox, oy = origin
        for flame in self.flames:
            visible_until = flame.ignite_at + self.burn_duration * FLAME_VISIBLE_FRACTION
            if not (flame.ignite_at <= self.elapsed < visible_until):
                continue
            index = int((self.elapsed + flame.frame_offset) / FLAME_ANIMATION_SPEED) % frame_count
            sprite = self._scaled_flame_frame(frames[index], flame.scale)
            rect = sprite.get_rect(center=(ox + flame.x, oy + flame.y))
            screen.blit(sprite, rect)

    def _scaled_flame_frame(self, frame, scale):
        """Per-(frame, scale) cache -- FLAME_DENSITY is small and
        FLAME_SCALE_RANGE is continuous, but rounding scale to a coarse
        bucket keeps this cache small while remaining visually identical
        (a fraction-of-a-pixel size difference isn't perceptible on a
        ~16px flame sprite)."""
        key = (id(frame), round(scale, 1))
        cached = self._flame_scale_cache.get(key)
        if cached is None:
            size = (max(1, round(frame.get_width() * scale)), max(1, round(frame.get_height() * scale)))
            cached = pygame.transform.scale(frame, size)
            self._flame_scale_cache[key] = cached
        return cached
