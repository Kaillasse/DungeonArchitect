"""Procedural card-tearing animation -- replaces a per-cut_y pre-baked
frame set entirely: cut_y and progress are just numbers fed to
create_tear_state(), which slices the ACTUAL pixels of whatever card_image
it's given (any pygame.Surface, any size -- built for the ~64x96 card
backing but not hardcoded to it) along a jagged, deterministic boundary and
returns the two resulting pieces, each with its own drift/rotation for the
current progress.

Deliberately knows nothing about cards, capacities, or which piece a
gameplay property ends up on -- core.editor.ui.mechanics_panel.MechanicsPanelUI
owns that decision entirely (_try_tear), this module only turns
(card_image, cut_y, progress) into pixels. That's the whole contract.
"""

from __future__ import annotations

import math
import random

import pygame

# How many pixels of jagged wobble the tear boundary gets, and how far apart
# (in columns) its control points sit -- deterministic per (width, height,
# cut_y), see _tear_boundary, so the SAME call always produces the SAME
# jagged shape (no flicker across frames of one drag). Small values on
# purpose: a 64px-wide card doesn't want a chaotic edge, just enough to read
# as torn paper rather than a ruler-straight cut.
TEAR_AMPLITUDE_PX = 2
TEAR_SEGMENT_PX = 8

# How far the TOP piece drifts/rotates at progress=1.0 (while still being
# dragged, before any release-throw -- see THROW_* below for what happens
# after commit), and how quickly that ramps up (an exponent >1 on progress
# means most of the movement happens in the back half of the drag,
# matching the "prep, then it lets go" feel the phases describe) -- see
# _piece_transform. The BOTTOM piece never moves at all (confirmed with
# the user: keeps the torn-out property legible/stationary throughout the
# whole gesture) -- there's nothing to tune for it. DRIFT_FRACTION/
# DROP_FRACTION are fractions of card_image's own width/height (not fixed
# pixel counts -- this tears the whole Forge panel now, hundreds of px,
# and a fixed few-px drift tuned for a small ~64x96 card was invisible at
# that scale, confirmed with the user), moving the top piece toward +x
# (the tear direction, same as the drag) and -y (upward, lifting off the
# card -- not straight down into it). ROTATION_DEG is negative (clockwise)
# for the same "follow the drag direction" reason.
SEPARATION_EXPONENT = 1.5
DRIFT_FRACTION = 0.10
DROP_FRACTION = 0.14
TOP_ROTATION_DEG = -8

# A brief, fading tremble right at the start of the drag (Phase 1 -- "la
# carte reste pratiquement intacte... eventuellement un tres leger
# tremblement"), purely a function of progress like everything else here
# (never wall-clock time -- progress already IS the animation clock, driven
# by drag distance in MechanicsPanelUI, so re-deriving motion from time
# here would desync from a paused/reversed drag).
TREMBLE_WINDOW = 0.18
TREMBLE_FREQUENCY = 60
TREMBLE_AMPLITUDE_PX = 1.4


class TearPiece:
    """One half of a torn card_image. `surface` is cropped to its own
    bounding box (not the full card size) so rotation pivots around the
    PIECE's own center, not the original card's center. `anchor` is where
    that cropped surface's top-left sits in the ORIGINAL card_image's own
    coordinate space at progress=0 (before any drift) -- combined with
    `offset` (the current progress' drift, in the same space) and `angle`
    (rotation in degrees) by blit_tear_piece to place it on screen."""

    __slots__ = ("surface", "anchor", "offset", "angle")

    def __init__(self, surface, anchor, offset, angle):
        self.surface = surface
        self.anchor = anchor
        self.offset = offset
        self.angle = angle


class TearState:
    """The result of create_tear_state -- just the two pieces. Whatever a
    caller does with them (draw both, only one, neither) is entirely its
    own business; this carries no card/gameplay identity at all."""

    __slots__ = ("top", "bottom")

    def __init__(self, top, bottom):
        self.top = top
        self.bottom = bottom


def _tear_boundary(width, height, cut_y):
    """One y value per column x -- a smooth, deterministic jagged curve
    wobbling around cut_y (linear interpolation between a handful of
    random control points spaced TEAR_SEGMENT_PX apart, same idea as cheap
    1D value noise). Seeded from (width, height, cut_y) alone -- no
    randomness that isn't fully reproducible from the function's own
    arguments, so calling this twice with the same card size/cut_y always
    draws the exact same tear line, across frames or even across
    unrelated cards of the same size."""
    rng = random.Random((width, height, round(cut_y * 4)))
    point_count = max(2, width // TEAR_SEGMENT_PX + 2)
    control_points = [rng.uniform(-TEAR_AMPLITUDE_PX, TEAR_AMPLITUDE_PX) for _ in range(point_count)]

    boundary = []
    for x in range(width):
        t = x / TEAR_SEGMENT_PX
        index = int(t)
        frac = t - index
        lo = control_points[min(index, point_count - 1)]
        hi = control_points[min(index + 1, point_count - 1)]
        wobble = lo + (hi - lo) * frac
        boundary.append(max(1, min(height - 1, round(cut_y + wobble))))
    return boundary


def _extract_pieces(card_image, boundary):
    """Splits card_image into (top_full, bottom_full) -- both the same
    size as card_image, each holding only its own side of the jagged
    boundary (SRCALPHA, the other side left fully transparent), every
    pixel at its ORIGINAL position. Reassembling them at offset (0,0) with
    no rotation reproduces card_image exactly -- that's what progress=0
    looks like, deliberately: no separate "intact" rendering path needed,
    it falls out of this for free."""
    width, height = card_image.get_size()
    top_full = pygame.Surface((width, height), pygame.SRCALPHA)
    bottom_full = pygame.Surface((width, height), pygame.SRCALPHA)
    for x, y in enumerate(boundary):
        if y > 0:
            top_full.blit(card_image, (x, 0), (x, 0, 1, y))
        if y < height:
            bottom_full.blit(card_image, (x, y), (x, y, 1, height - y))
    return top_full, bottom_full


def _piece_transform(progress, is_top, width, height):
    """(dx, dy, angle_degrees) for one piece at this progress -- the
    BOTTOM piece is always (0, 0, 0), full stop (keeps whatever's below
    the cut legible/stationary for the whole gesture). Only the top piece
    moves: rotation ALONE isn't physically right for a tear -- ripping
    paper, one side/corner detaches before the other, so the piece can't
    just spin in place around its own center, it has to actually travel
    too (confirmed with the user) -- in the tear direction (+x, same as
    the drag) and upward (-y, it's lifting off the card, not sinking into
    it).

    Drift is a FRACTION of the image's own width/height, not a fixed
    pixel count -- this now tears the whole Forge panel (hundreds of px),
    not just a small ~64x96 card, and a fixed few-px drift that read fine
    at card scale was completely imperceptible blown up to panel scale
    (confirmed with the user: "il reste a ajouter la translation" after an
    earlier version already had one, just far too small to see)."""
    if not is_top:
        return 0.0, 0.0, 0.0

    separation = progress ** SEPARATION_EXPONENT
    dx = DRIFT_FRACTION * width * separation
    dy = -DROP_FRACTION * height * separation
    angle = TOP_ROTATION_DEG * separation

    if 0 < progress < TREMBLE_WINDOW:
        fade = 1 - progress / TREMBLE_WINDOW
        dx += math.sin(progress * TREMBLE_FREQUENCY) * TREMBLE_AMPLITUDE_PX * fade

    return dx, dy, angle


def _crop_piece(full_surface, progress, is_top, width, height):
    rect = full_surface.get_bounding_rect()
    if rect.width <= 0 or rect.height <= 0:
        # This half is empty at this cut_y (e.g. cut_y clamped to the very
        # top/bottom edge) -- a 1x1 transparent placeholder rather than a
        # zero-size Surface, which pygame.transform.rotate/get_rect choke on.
        cropped = pygame.Surface((1, 1), pygame.SRCALPHA)
        anchor = (0, 0)
    else:
        cropped = full_surface.subsurface(rect).copy()
        anchor = rect.topleft
    dx, dy, angle = _piece_transform(progress, is_top, width, height)
    return TearPiece(cropped, anchor, (dx, dy), angle)


def create_tear_state(card_image, cut_y, progress):
    """The whole public API: given ANY card image, a cut height, and how
    far along the tear is (0.0 intact, 1.0 fully separated), returns the
    two pieces ready to draw -- see blit_tear_piece. `cut_y` is a plain
    pixel coordinate into card_image (any value works, clamped to stay
    inside it -- never a lookup into a fixed set of pre-supported
    heights). `progress` is clamped to [0, 1]."""
    progress = max(0.0, min(1.0, progress))
    width, height = card_image.get_size()
    cut_y = max(1, min(height - 1, round(cut_y)))

    boundary = _tear_boundary(width, height, cut_y)
    top_full, bottom_full = _extract_pieces(card_image, boundary)

    return TearState(
        _crop_piece(top_full, progress, True, width, height),
        _crop_piece(bottom_full, progress, False, width, height),
    )


def blit_tear_piece(screen, piece, origin):
    """Draws one TearPiece onto `screen`, `origin` being where the
    original card_image's (0, 0) maps to in screen space. Rotation pivots
    around the piece's own center (its anchor + offset), not the card's --
    see TearPiece's own docstring for why that needed cropping to the
    piece's bounding box up front. Returns (drawn_surface, drawn_rect) --
    the exact surface/rect just blitted (post-rotation, if any) -- so a
    caller can pick this position back up later without redoing the
    rotation math itself (see start_throw: the throw's own starting point
    is wherever the top piece visually was on the LAST drag frame, for
    continuity between the drag and the release).

    Unrotated pieces (angle == 0, always true at progress=0 -- see
    _piece_transform) skip the center-based path entirely and blit at an
    exact top-left instead: get_rect(center=...) rounds a fractional
    center (e.g. an odd-height piece's own half-height) to the nearest
    int, which is invisible once something's actually rotating/drifting
    but silently shifted the "intact" progress=0 case by up to a pixel --
    caught by an ad hoc reconstruction check during development (this
    repo has no persisted test suite, see CLAUDE.md): progress=0 must be
    pixel-identical to the original card_image."""
    ox, oy = origin
    ax, ay = piece.anchor
    dx, dy = piece.offset
    if not piece.angle:
        rect = pygame.Rect(round(ox + ax + dx), round(oy + ay + dy), *piece.surface.get_size())
        screen.blit(piece.surface, rect)
        return piece.surface, rect
    center = (
        ox + ax + piece.surface.get_width() / 2 + dx,
        oy + ay + piece.surface.get_height() / 2 + dy,
    )
    rotated = pygame.transform.rotate(piece.surface, piece.angle)
    rect = rotated.get_rect(center=center)
    screen.blit(rotated, rect)
    return rotated, rect


# -- Post-release "throw" (see MechanicsPanelUI._try_tear/handle_event's
# commit branch) -- entirely separate from create_tear_state's own
# drag-time transform above: this is purely a visual flourish that plays
# out AFTER the tear is already committed (the gameplay side -- consuming
# the base card, crediting a property card -- has already happened by the
# time this starts, see module docstring's logic/rendering split), driven
# by wall-clock time via update_throw(dt) since there's no more mouse
# input positioning it once the player has released the button. ------

THROW_DURATION = 0.45  # seconds
# A raw mouse-velocity reading (px/sec) is usually far faster than looks
# natural applied directly to a thrown object -- scaled down rather than
# capped, so a genuinely fast flick still reads as faster than a slow one.
# Bumped up once already (confirmed with the user: the base throw read too
# short/weak).
THROW_VELOCITY_SCALE = 0.4


class ThrowState:
    """The torn-off top piece flying away after release, shrinking to
    nothing over THROW_DURATION -- see start_throw/update_throw/
    blit_throw. `surface` is whatever blit_tear_piece last actually drew
    (already rotated), `origin` is that same rect's top-left, so the very
    first throw frame lines up exactly with the last drag frame -- no
    visible jump at the moment of release."""

    __slots__ = ("surface", "origin", "velocity", "elapsed")

    def __init__(self, surface, origin, velocity):
        self.surface = surface
        self.origin = origin
        self.velocity = velocity
        self.elapsed = 0.0


def start_throw(surface, origin, mouse_velocity, min_velocity_x=0.0):
    """Begins a throw for `surface` (see ThrowState) launched at
    `mouse_velocity` (px/sec -- the player's own cursor speed at the
    moment of release, see MechanicsPanelUI's velocity tracking), scaled
    down by THROW_VELOCITY_SCALE. `min_velocity_x` (already in "final
    launch speed" terms, not raw mouse px/sec -- the caller computes it
    directly from how fast the piece needs to travel) floors the X
    component so the piece ALWAYS heads rightward at at least that speed,
    regardless of which way the player was actually moving the cursor at
    release -- confirmed with the user: it should always end up to the
    right of wherever it started, at minimum. Y is never floored -- only
    the tear direction has a guaranteed minimum, vertical motion stays
    whatever the release velocity actually was."""
    vx, vy = mouse_velocity
    vx = max(vx * THROW_VELOCITY_SCALE, min_velocity_x)
    vy = vy * THROW_VELOCITY_SCALE
    return ThrowState(surface, origin, (vx, vy))


def update_throw(throw, dt):
    """Advances `throw` by `dt` seconds. Returns True while still active,
    False once THROW_DURATION has elapsed -- the caller (MechanicsPanelUI.
    update) should drop its reference to `throw` once this returns False,
    same "caller owns the state, this module only advances/draws it"
    split as create_tear_state's own (category, kind) staying entirely
    the caller's business."""
    throw.elapsed += dt
    return throw.elapsed < THROW_DURATION


def blit_throw(screen, throw):
    """Draws `throw` at its current position (origin + velocity*elapsed),
    shrunk and faded linearly to nothing by THROW_DURATION -- "retrecit
    jusqu'a disparaitre", confirmed with the user. No-op once fully
    shrunk (scale<=0), same spirit as _crop_piece's own degenerate-size
    guard."""
    scale = max(0.0, 1.0 - throw.elapsed / THROW_DURATION)
    if scale <= 0.0:
        return
    width = max(1, round(throw.surface.get_width() * scale))
    height = max(1, round(throw.surface.get_height() * scale))
    scaled = pygame.transform.smoothscale(throw.surface, (width, height))
    scaled.set_alpha(round(255 * scale))
    center = (
        throw.origin[0] + throw.velocity[0] * throw.elapsed + throw.surface.get_width() * scale / 2,
        throw.origin[1] + throw.velocity[1] * throw.elapsed + throw.surface.get_height() * scale / 2,
    )
    rect = scaled.get_rect(center=center)
    screen.blit(scaled, rect)
