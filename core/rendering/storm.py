"""Storm generator -- a purely cosmetic, screen-covering "particle system
for decorative 2D assets" background layer (leaves/dust/debris/etc.
drifting across the view). Deliberately has NO gameplay coupling: it never
touches Dungeon/Player/collision/entities, and only ever READS a Camera's
x/y (for its own parallax offset -- see StormGenerator.render) without
ever depending on anything else about it. See core.editor.ui.storm_panel.
StormPanelUI for the in-game config UI (Creator-only, live-edits the
shared config) and GameManager.storm_generator for where the single
shared instance lives (one config for the whole session, read by Menu/
Creator/Explorator alike -- confirmed with the user, 2026-08-22).

Coordinate space: every particle lives in plain "storm space", which is
just screen-pixel space at a neutral (0, 0) camera offset -- update() never
looks at a Camera at all, only render() does, purely to shift the whole
layer by camera.x/y * (parallax / 100) at draw time, CLAMPED to
+/-StormGenerator.MAX_PARALLAX_OFFSET px (2026-08-22 -- an earlier version
wrapped this modulo the screen size instead, which sounds equivalent but
isn't: camera.x/y is an arbitrary, unbounded world-pixel coordinate -- it
can already be far from zero even while the player perceives themselves as
"centered" on their own room, e.g. after Dungeon.grow shifts a grid's
internal origin and recenters the camera to compensate. Multiplying that
by parallax and only wrapping the OFFSET (never re-wrapping the resulting
screen position after adding it to an on-screen particle) could push
particles arbitrarily far past the visible edge with nothing bringing them
back -- read as "the storm is offset from the room" at moderate camera
positions and "the storm disappeared" once camera.x*parallax comfortably
exceeded the screen size. Clamping instead guarantees the layer can never
drift further than MAX_PARALLAX_OFFSET from its neutral centered position,
regardless of how large camera.x/y ever gets.) Camera ZOOM is deliberately
NOT applied -- keeping particle size independent of the player's own zoom
level is simpler and avoids this "independent visual layer" reacting to a
gameplay camera action in a way that could read as broken (a leaf suddenly
the size of the screen because the player zoomed in on the dungeon)."""

from __future__ import annotations

import json
import math
import random
from collections import deque
from dataclasses import dataclass, field, fields
from pathlib import Path

import pygame

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = PROJECT_ROOT / "assets" / "storm" / "img"
# Backdrop images (2026-08-22, confirmed with the user) -- a single static
# full-screen image drawn behind every particle, entirely separate from
# the decorative sprite pool above (ASSET_DIR/list_storm_assets).
BACKGROUND_DIR = PROJECT_ROOT / "assets" / "storm" / "background"
# Where the live/session config and named presets persist -- see
# StormGenerator.save_current/save_preset/load_preset. Both just JSON
# dumps of StormConfig (via _config_to_dict/_config_from_dict below), so
# a preset IS exactly "the current live config, saved under a name" --
# no separate schema.
CURRENT_STATE_PATH = PROJECT_ROOT / "assets" / "storm" / "current.json"
PRESETS_DIR = PROJECT_ROOT / "assets" / "storm" / "presets"

MODE_CIRCULAR = "circular"
MODE_RECTILINEAR = "rectilinear"
MODES = (MODE_CIRCULAR, MODE_RECTILINEAR)


def list_storm_assets():
    """Every PNG under assets/storm/img/, as repo-relative path strings
    (sorted for a stable order) -- the pool StormGenerator seeds
    StormConfig.assets from and StormPanelUI lists as candidates. A
    missing folder yields an empty list rather than raising, same
    "quietly does nothing without the asset" fallback as BorderManager's
    own missing border sheet."""
    if not ASSET_DIR.is_dir():
        return []
    return sorted(
        str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        for path in ASSET_DIR.glob("*.png")
    )


def list_storm_backgrounds():
    """Every PNG under assets/storm/background/, same shape as
    list_storm_assets -- StormPanelUI cycles StormConfig.background_path
    through these (plus "none")."""
    if not BACKGROUND_DIR.is_dir():
        return []
    return sorted(
        str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        for path in BACKGROUND_DIR.glob("*.png")
    )


def list_storm_presets():
    """Every saved preset's own name (filename stem, not the full path) --
    see StormGenerator.save_preset/load_preset/delete_preset. Sorted for a
    stable list order in StormPanelUI; empty (not an error) if the presets
    folder doesn't exist yet (nothing saved so far)."""
    if not PRESETS_DIR.is_dir():
        return []
    return sorted(path.stem for path in PRESETS_DIR.glob("*.json"))


def _dataclass_from_dict(cls, data):
    """Builds a `cls` instance from `data`, silently ignoring any key that
    isn't one of `cls`'s own fields and leaving any missing key at that
    field's own default -- forward/backward compatible with an older or
    newer saved JSON file than the dataclass's current shape (a field
    added/removed later never makes an old preset unloadable, see
    StormGenerator._load_state's own docstring)."""
    if not isinstance(data, dict):
        return cls()
    known = {f.name for f in fields(cls)}
    return cls(**{key: value for key, value in data.items() if key in known})


def _config_to_dict(config):
    """StormConfig -> a plain JSON-able dict -- the entire "save a
    preset"/"persist the live session" story, see StormGenerator.
    save_current/save_preset. Hand-written (not dataclasses.asdict)
    specifically so StormAssetWeight.overrides -- already a plain dict --
    round-trips as-is rather than asdict's own recursive handling doing
    something unexpected with a dict-typed field."""
    return {
        "enabled": config.enabled,
        "mode": config.mode,
        "background_path": config.background_path,
        "assets": [
            {
                "path": asset.path, "weight": asset.weight, "enabled": asset.enabled,
                "face_motion": asset.face_motion, "angle_offset": asset.angle_offset,
                "overrides": dict(asset.overrides),
            }
            for asset in config.assets
        ],
        "density": config.density,
        "speed_min": config.speed_min,
        "speed_max": config.speed_max,
        "size_min": config.size_min,
        "size_max": config.size_max,
        "rotation_speed_max": config.rotation_speed_max,
        "opacity_min": config.opacity_min,
        "opacity_max": config.opacity_max,
        "lifetime_min": config.lifetime_min,
        "lifetime_max": config.lifetime_max,
        "intensity": config.intensity,
        "parallax": config.parallax,
        "circular": {f.name: getattr(config.circular, f.name) for f in fields(CircularParams)},
        "rectilinear": {f.name: getattr(config.rectilinear, f.name) for f in fields(RectilinearParams)},
    }


def _config_from_dict(data):
    """The reverse of _config_to_dict -- see _dataclass_from_dict for the
    forward/backward-compatibility contract every nested piece here
    shares. Never raises on a malformed/partial dict: unknown top-level
    keys are ignored the same way (StormConfig itself is built field by
    field below, not via _dataclass_from_dict, only because `assets`/
    `circular`/`rectilinear` need their own nested reconstruction first)."""
    if not isinstance(data, dict):
        data = {}
    config = StormConfig()
    for key in (
        "enabled", "mode", "background_path", "density", "speed_min", "speed_max",
        "size_min", "size_max", "rotation_speed_max", "opacity_min", "opacity_max",
        "lifetime_min", "lifetime_max", "intensity", "parallax",
    ):
        if key in data:
            setattr(config, key, data[key])
    config.circular = _dataclass_from_dict(CircularParams, data.get("circular"))
    config.rectilinear = _dataclass_from_dict(RectilinearParams, data.get("rectilinear"))
    assets = []
    for raw_asset in data.get("assets") or []:
        asset = _dataclass_from_dict(StormAssetWeight, raw_asset)
        overrides = raw_asset.get("overrides") if isinstance(raw_asset, dict) else None
        asset.overrides = dict(overrides) if isinstance(overrides, dict) else {}
        assets.append(asset)
    config.assets = assets
    return config


@dataclass
class StormAssetWeight:
    """One selectable decorative sprite + its relative spawn weight -- a
    weight, not an explicit percentage (confirmed acceptable with the
    user, 2026-08-22, as long as the UI reads as equivalent): normalizing
    a list of weights into percentages for display is one division per
    asset, so StormPanelUI can still show "60%" next to a weight of 6
    without the underlying data needing to special-case "must sum to
    100" -- adding/removing/reweighing one asset never has to touch any
    other asset's own number.

    face_motion/angle_offset (2026-08-22, confirmed with the user) --
    orientation is a per-ASSET choice, not a global one: face_motion=True
    (the default) makes every particle spawned from this asset continuously
    face its own motion (circular: the image's own "up" always points at
    the orbit center; rectilinear: "up" always points along the direction
    of travel) instead of a random static tilt (or, if
    StormConfig.rotation_speed_max > 0, an independent free spin) -- see
    StormParticle._facing_angle, the only place either field is read.
    angle_offset (degrees) corrects for source art whose own "up" isn't
    literally the direction that should face outward/forward -- added on
    top of the computed facing angle, so 0 always means "exactly as
    designed" regardless of what the art itself looks like."""
    path: str
    weight: int = 5
    enabled: bool = True
    face_motion: bool = True
    angle_offset: int = 0
    # Per-asset overrides (2026-08-22, confirmed with the user) -- a plain
    # {field_name: value} dict rather than a full second copy of every
    # StormConfig/CircularParams/RectilinearParams field: a field simply
    # absent here means "use the shared/global value", so an asset with no
    # overrides at all behaves EXACTLY as before this existed (existing
    # presets/current.json load unchanged, nothing to migrate). Only the
    # attrs listed in OVERRIDABLE_COMMON_ATTRS/OVERRIDABLE_CIRCULAR_ATTRS/
    # OVERRIDABLE_RECTILINEAR_ATTRS are ever read from here (density/
    # intensity/parallax/center/clockwise stay global-only -- see those
    # constants' own comments for why). Resolved by _resolved(), the one
    # place that reads this dict.
    overrides: dict = field(default_factory=dict)


@dataclass
class CircularParams:
    """Mode A -- see StormConfig's own docstring for the shared fields
    (speed/size/etc.) this supplements. center_x/center_y are FRACTIONS of
    the current screen size (0..1), not pixels, so a saved/default center
    stays "the middle of the screen" across a resize or fullscreen
    toggle instead of pointing at a stale pixel coordinate."""
    center_x: float = 0.5
    center_y: float = 0.5
    radius_min: int = 60
    radius_max: int = 260
    angular_speed: int = 20  # degrees/sec, at each particle's own radius
    clockwise: bool = True
    # % of a particle's own base radius its radius oscillates by -- avoids
    # perfectly clean circles, see the module docstring's "aspect naturel".
    radius_wobble: int = 15
    # 0..100 -- how strongly a particle's SIZE correlates with its own
    # base radius (confirmed with the user, 2026-08-22): at 0, size is
    # picked fully independently of radius (StormConfig.size_min/max,
    # unchanged from before this existed); at 100, size is fully
    # determined by radius -- size_min at radius_min, size_max at
    # radius_max, everything in between interpolated -- a cheap depth-
    # sorting cue (small = far/inner, large = near/outer) without any
    # real 3D. Values between blend the two linearly, see
    # StormParticle._init_circular.
    depth: int = 0


@dataclass
class RectilinearParams:
    """Mode B -- direction_deg is measured clockwise from +x (0 = left to
    right, 90 = top to bottom); spread is the perpendicular dispersion
    band (px) particles are scattered across around the main trajectory
    line, not a single-file stream."""
    direction_deg: int = 0
    spread: int = 220


@dataclass
class StormConfig:
    """One full storm setup -- deliberately flat/plain-data (dataclasses,
    no behavior of its own) so it doubles as the shape both a saved preset
    and the persisted live session use as-is (see _config_to_dict/
    _config_from_dict, StormGenerator.save_current/save_preset/
    load_preset, 2026-08-22) -- nothing here needs to change shape to
    support either.

    Every numeric field an in-game panel needs to expose is a plain int
    (or, for lifetime, a small float) rather than a normalized 0..1 float,
    matching the only numeric editing widget this codebase has (Slider,
    see core.editor.ui.storm_panel).
    """

    enabled: bool = True
    mode: str = MODE_CIRCULAR
    assets: list = field(default_factory=list)  # list[StormAssetWeight]
    # Repo-relative path under assets/storm/background/, or None for no
    # backdrop -- drawn full-screen, first, behind every particle (see
    # StormGenerator._render_background). Entirely separate from `assets`
    # above (the decorative sprite pool) -- confirmed with the user,
    # 2026-08-22.
    background_path: str = None

    density: int = 40  # target simultaneous particle count
    speed_min: int = 20  # px/sec -- rectilinear only (circular uses circular.angular_speed)
    speed_max: int = 60
    size_min: int = 16
    size_max: int = 48
    rotation_speed_max: int = 0  # deg/sec of independent self-rotation, 0 = none
    opacity_min: int = 60  # 0..100
    opacity_max: int = 100
    lifetime_min: int = 4  # seconds -- plain int, StormPanelUI edits it with
    lifetime_max: int = 9  # a Stepper same as every other numeric field
    intensity: int = 100  # % master multiplier applied on top of density
    parallax: int = 40  # % of the host camera's own pan this layer follows

    circular: CircularParams = field(default_factory=CircularParams)
    rectilinear: RectilinearParams = field(default_factory=RectilinearParams)


def _pick_weighted_asset(usable_assets):
    return random.choices(usable_assets, weights=[a.weight for a in usable_assets], k=1)[0]


# Which StormConfig/CircularParams/RectilinearParams attrs a
# StormAssetWeight.overrides entry is allowed to override (2026-08-22,
# confirmed with the user) -- also exactly the field list
# core.editor.ui.storm_panel.StormPanelUI's per-asset "Reglages
# individuels" section renders, so the two can never drift apart. Density/
# intensity/parallax stay global-only -- each spawn already picks ONE
# asset by weight (_pick_weighted_asset), there's no per-asset population
# target to speak of. clockwise/center_x/center_y (circular) stay global
# too -- a per-asset spin direction/center reads as a bug more than a
# feature (the whole point of a shared orbit is that everything shares
# ONE center to actually look like a single vortex).
OVERRIDABLE_COMMON_ATTRS = (
    "speed_min", "speed_max", "size_min", "size_max", "rotation_speed_max",
    "opacity_min", "opacity_max", "lifetime_min", "lifetime_max",
)
OVERRIDABLE_CIRCULAR_ATTRS = ("radius_min", "radius_max", "angular_speed", "radius_wobble", "depth")
OVERRIDABLE_RECTILINEAR_ATTRS = ("direction_deg", "spread")


def _resolved(asset, base, name):
    """`base`'s own `name` attr, unless `asset.overrides` has its own
    value for it -- the ONLY place StormAssetWeight.overrides is ever
    read. `base` is whichever object actually owns that attr normally
    (StormConfig itself, or its .circular/.rectilinear) -- same "getter"
    shape core.editor.ui.storm_panel.StormPanelUI's field tables already
    use, so a per-asset override slider can bind to the exact same
    (label, getter, attr, min, max) row description as the global one,
    just resolved through this function instead of a plain getattr."""
    return asset.overrides.get(name, getattr(base, name))


class StormParticle:
    """One live decorative instance -- everything here is plain per-
    particle state (position/age/rotation/etc.), randomized once at spawn
    from the shared StormConfig's min/max ranges so no two particles ever
    share an identical size/speed/rotation/trajectory (see the module's
    "aspect naturel" goal). update() is pure simulation, no rendering/
    camera involved at all; draw() projects the particle's own storm-space
    position by a caller-supplied screen-space offset (the parallax shift)
    and blits a pre-baked rotated/scaled `image` the caller (StormGenerator.
    render, which owns the actual rotated-surface cache -- see its own
    docstring for why that moved out of here, 2026-08-22) hands it each
    frame."""

    # Fraction of a particle's own lifetime spent fading in/out at each
    # end, so nothing just pops into or out of existence.
    FADE_FRACTION = 0.15

    def __init__(self, config, surface, screen_size, asset):
        self.surface = surface
        self.mode = config.mode
        self.asset = asset
        self.age = 0.0
        lifetime_min = _resolved(asset, config, "lifetime_min")
        lifetime_max = _resolved(asset, config, "lifetime_max")
        self.lifetime = random.uniform(lifetime_min, max(lifetime_min, lifetime_max))
        size_min = _resolved(asset, config, "size_min")
        size_max = _resolved(asset, config, "size_max")
        self.size = random.randint(size_min, max(size_min, size_max))
        # Intensity is a MASTER "how strong does the whole effect feel"
        # dial, deliberately distinct from density ("how many particles")
        # -- confirmed with the user, 2026-08-22, after density/intensity
        # read as near-duplicates when intensity only scaled the target
        # particle COUNT (see StormGenerator._target_count, which still
        # does that too). Here it also scales speed (both modes, see
        # _init_circular/_init_rectilinear) and opacity together, so
        # turning it up makes the effect more numerous AND faster AND
        # more visible all at once, while density alone only ever changes
        # how many particles there are. Global-only (not per-asset
        # overridable), same reasoning as density itself.
        intensity_factor = config.intensity / 100.0
        opacity_min = _resolved(asset, config, "opacity_min")
        opacity_max = _resolved(asset, config, "opacity_max")
        self.opacity = min(100, round(random.randint(opacity_min, max(opacity_min, opacity_max)) * intensity_factor))
        self.face_motion = asset.face_motion
        self.angle_offset = asset.angle_offset

        screen_w, screen_h = screen_size
        if self.mode == MODE_CIRCULAR:
            self._init_circular(config, asset, screen_w, screen_h, intensity_factor)
        else:
            self._init_rectilinear(config, asset, screen_w, screen_h, intensity_factor)

        # Initial rotation -- set here (after the mode-specific init above
        # has computed self.angle/self.direction) rather than inline with
        # the other random per-particle fields, since the face_motion
        # branch needs those to already exist for its very first frame,
        # not just from the next update() call onward.
        rotation_speed_max = _resolved(asset, config, "rotation_speed_max")
        if self.face_motion:
            self.rotation = self._facing_rotation()
            self.rotation_speed = 0.0
        else:
            self.rotation = random.uniform(0, 360)
            self.rotation_speed = (
                random.uniform(-rotation_speed_max, rotation_speed_max)
                if rotation_speed_max > 0 else 0.0
            )

    # -- spawn --------------------------------------------------------

    def _init_circular(self, config, asset, screen_w, screen_h, intensity_factor):
        params = config.circular
        self.center = pygame.Vector2(params.center_x * screen_w, params.center_y * screen_h)
        radius_min = _resolved(asset, params, "radius_min")
        radius_max = _resolved(asset, params, "radius_max")
        self.base_radius = random.uniform(radius_min, max(radius_min, radius_max))
        self.angle = random.uniform(0, 2 * math.pi)
        direction = 1.0 if params.clockwise else -1.0
        # Per-particle speed variance (+/-30%) -- a mass of particles
        # orbiting at exactly one shared angular speed reads as a single
        # rigid disc rather than a "storm" of individually-drifting bits.
        # intensity_factor (see __init__) scales the base angular speed
        # itself, on top of that per-particle variance.
        angular_speed = _resolved(asset, params, "angular_speed")
        self.angular_speed = math.radians(angular_speed * intensity_factor) * direction * random.uniform(0.7, 1.3)
        radius_wobble = _resolved(asset, params, "radius_wobble")
        self.wobble_amp = self.base_radius * (radius_wobble / 100.0)
        self.wobble_phase = random.uniform(0, 2 * math.pi)
        self.wobble_speed = random.uniform(0.5, 1.5)
        self.position = self._circular_position()

        # Depth-sorted size (see CircularParams.depth's own docstring) --
        # blends self.size (already randomized generically in __init__)
        # toward a value purely interpolated from where this particle's
        # own base_radius falls in [radius_min, radius_max]. Computed once
        # here from the STABLE base_radius, not the wobbling per-frame
        # radius -- the depth cue is about the orbit's own inner/outer
        # band, not a per-frame flicker as radius_wobble oscillates.
        depth = _resolved(asset, params, "depth")
        if depth > 0 and radius_max > radius_min:
            size_min = _resolved(asset, config, "size_min")
            size_max = _resolved(asset, config, "size_max")
            t = (self.base_radius - radius_min) / (radius_max - radius_min)
            t = max(0.0, min(1.0, t))
            depth_size = size_min + t * (size_max - size_min)
            blend = depth / 100.0
            self.size = round(self.size * (1 - blend) + depth_size * blend)

    def _init_rectilinear(self, config, asset, screen_w, screen_h, intensity_factor):
        params = config.rectilinear
        direction_deg = _resolved(asset, params, "direction_deg")
        # +/-8 degree per-particle jitter around the configured direction
        # -- a perfectly parallel stream of sprites is exactly the
        # "cloned objects on a grid" look this system wants to avoid.
        angle = math.radians(direction_deg + random.uniform(-8, 8))
        self.direction = pygame.Vector2(math.cos(angle), math.sin(angle))
        speed_min = _resolved(asset, config, "speed_min")
        speed_max = _resolved(asset, config, "speed_max")
        self.speed = random.uniform(speed_min, max(speed_min, speed_max)) * intensity_factor
        spread = _resolved(asset, params, "spread")
        perpendicular = pygame.Vector2(-self.direction.y, self.direction.x)
        span = max(screen_w, screen_h) * 1.4
        base = pygame.Vector2(screen_w / 2, screen_h / 2) - self.direction * span / 2
        base += perpendicular * random.uniform(-spread / 2, spread / 2)
        # Random head-start along the travel line itself, not just at the
        # entry edge -- staggers arrivals instead of a wall of particles
        # all appearing on the same edge at once.
        base += self.direction * random.uniform(0, span)
        self._base_position = base
        self.wobble_amp = random.uniform(4, 14)
        self.wobble_phase = random.uniform(0, 2 * math.pi)
        self.wobble_speed = random.uniform(1.0, 2.5)
        self._bounds = pygame.Rect(-96, -96, screen_w + 192, screen_h + 192)
        self.position = self._rectilinear_position()

    def _circular_position(self):
        radius = self.base_radius + self.wobble_amp * math.sin(self.wobble_phase)
        offset = pygame.Vector2(math.cos(self.angle), math.sin(self.angle)) * radius
        return self.center + offset

    def _rectilinear_position(self):
        perpendicular = pygame.Vector2(-self.direction.y, self.direction.x)
        wobble = perpendicular * (self.wobble_amp * math.sin(self.wobble_phase))
        return self._base_position + wobble

    # -- simulation -----------------------------------------------------

    @staticmethod
    def _facing_angle(dx, dy, angle_offset):
        """The rotation (degrees, in pygame.transform.rotate's own
        counter-clockwise sense) that makes a sprite whose own "up" is the
        top of its source image face the screen-space direction (dx, dy)
        -- any magnitude, only the direction matters. Derived once by
        hand and left as a plain formula rather than re-derived inline
        everywhere it's needed (circular's face-center and rectilinear's
        face-direction-of-travel both reduce to this same call with a
        different (dx, dy))."""
        return (math.degrees(math.atan2(-dy, dx)) - 90 + angle_offset) % 360

    def _facing_rotation(self):
        if self.mode == MODE_CIRCULAR:
            # Direction from the particle TOWARD the orbit center is the
            # negative of its own radial (center-to-particle) direction.
            return self._facing_angle(-math.cos(self.angle), -math.sin(self.angle), self.angle_offset)
        return self._facing_angle(self.direction.x, self.direction.y, self.angle_offset)

    def update(self, dt):
        """Returns False once this particle should be removed (lifetime
        elapsed, or -- rectilinear only -- it has drifted well past the
        screen bounds), True otherwise."""
        self.age += dt
        if self.age >= self.lifetime:
            return False
        self.wobble_phase += self.wobble_speed * dt

        if self.mode == MODE_CIRCULAR:
            self.angle += self.angular_speed * dt
            self.position = self._circular_position()
        else:
            self._base_position += self.direction * self.speed * dt
            self.position = self._rectilinear_position()

        if self.face_motion:
            self.rotation = self._facing_rotation()
        else:
            self.rotation = (self.rotation + self.rotation_speed * dt) % 360

        if self.mode == MODE_CIRCULAR:
            return True
        return self._bounds.collidepoint(self.position)

    def _fade(self):
        if self.lifetime <= 0:
            return 1.0
        t = self.age / self.lifetime
        fade_in = min(1.0, t / self.FADE_FRACTION)
        fade_out = min(1.0, (1.0 - t) / self.FADE_FRACTION)
        return max(0.0, min(fade_in, fade_out))

    # -- rendering --------------------------------------------------------

    def draw(self, screen, offset_x, offset_y, image):
        """`image` is this frame's already rotated/scaled surface for this
        particle's (asset, size, rotation) -- see StormGenerator._rotated_
        surface, the shared cache that bakes it (almost always reused
        across many particles, hence "shared": never mutate it in place).
        .copy() here is what makes that safe -- set_alpha() below would
        otherwise mutate the SHARED cached surface's alpha for every other
        particle currently reusing it too, since alpha is the one thing
        that's essentially always different per particle (fade/opacity)
        even when rotation/size/asset all match. Copying a few-dozen-px
        surface is far cheaper than the rotate/smoothscale it's saving,
        so this still nets a large win."""
        image = image.copy()
        alpha = round(self.opacity * 2.55 * self._fade())
        image.set_alpha(max(0, min(255, alpha)))
        screen_pos = (self.position.x + offset_x, self.position.y + offset_y)
        screen.blit(image, image.get_rect(center=screen_pos))


class StormGenerator:
    """Owns one StormConfig and every live StormParticle. update(dt,
    screen_size) advances the whole simulation in pure storm-space (no
    camera involved); render(screen, camera) projects+draws each particle
    shifted by the configured parallax offset. One shared instance lives
    on GameManager (see its own construction) -- Menu/Creator/Explorator
    all update+render the SAME instance/config every frame (global/
    session scope, confirmed with the user 2026-08-22), so a live edit
    made through StormPanelUI (Creator-only) is immediately visible
    everywhere else too, with nothing to explicitly sync.

    Also owns the shared rotated/scaled-surface cache (see
    _rotated_surface, 2026-08-22) -- moved here from being per-particle
    specifically so many particles sharing the same asset/size/rotation
    (the common case, especially with "face au mouvement" driving
    rotation deterministically off shared motion math rather than each
    particle's own random spin) reuse ONE baked surface instead of each
    re-baking its own copy. That sharing is what makes a fine rotation
    bucket affordable -- the earlier per-particle cache had to use a
    coarse bucket to stay cheap, which read as visibly "saccadé" (choppy)
    for a particle whose rotation is continuously tracking its own smooth
    motion, exactly the case face_motion added.

    Three further optimizations on top of that shared cache (2026-08-22,
    all three confirmed with the user, the storm still being noticeably
    heavier at max settings than felt right even with sharing):

    1. Rotation wheel pre-baking (_queue_wheel/_advance_wheel_baking) --
       a continuously-rotating (face_motion) particle crosses into a new
       angle bucket almost every frame, so on-demand baking alone was
       still re-baking constantly in steady state, not just once at
       startup. The first time a given (asset, size bucket, angle bucket
       resolution) combination is seen, its ENTIRE rotation wheel (every
       angle bucket, not just the one just requested) gets queued; a
       small fixed budget of wheel frames gets baked per update() call
       until it's done, spread across several frames rather than either
       one big stutter or endless piecemeal misses. Once a wheel is
       complete, every future angle for that combo is a pure cache hit,
       permanently.
    2. Coarser size bucketing (SIZE_BUCKET_PX) -- fewer distinct size
       buckets means fewer distinct wheels ever need baking at all, and
       more particles landing on ones that already exist even before
       their own wheel finishes.
    3. Adaptive rotation resolution (_current_rotation_bucket_deg) -- the
       angle bucket itself widens once there are enough simultaneously
       active particles that fine 2-degree steps would mean an
       impractical number of cache entries/wheel frames; fine detail is
       kept exactly where it's most visible (few particles on screen),
       coarser where it barely reads as different (a great many small
       particles at once)."""

    # Hard ceiling regardless of density/intensity -- the actual safety
    # net against a runaway config (e.g. density=200 and intensity=200%
    # stacked) tanking the framerate; density/intensity themselves stay
    # free to go past what's "reasonable" in the UI, this just clamps the
    # real cost.
    MAX_PARTICLES = 400
    # Roughly how many particles join per second while ramping up to the
    # target count -- an instant burst back to full density (e.g. right
    # after raising it, or right after enabling the storm) reads as
    # mechanical; trickling in over a second or two doesn't.
    SPAWN_RATE = 40.0
    # How far (px) the parallax shift in render() is allowed to push the
    # whole layer from its neutral centered position, regardless of how
    # large camera.x/y * parallax gets -- see the module docstring's
    # 2026-08-22 note for why this replaced a modulo wrap.
    MAX_PARALLAX_OFFSET = 220
    # Optimization 3 -- rotation bucket widens as active particle count
    # grows: (particle_count_ceiling, bucket_degrees) pairs, checked in
    # order, first match wins. 2 degrees reads as smooth even for a
    # continuously-rotating particle; coarser steps only kick in once
    # there are enough particles on screen that the difference stops
    # being the bottleneck's dominant cost.
    ROTATION_BUCKET_THRESHOLDS = (
        (120, 2),
        (250, 4),
        (None, 6),
    )
    # Optimization 2 -- size is bucketed too (StormConfig.size_min/max is
    # randomized per particle across a continuous range, so without
    # bucketing almost every particle would land on its own unique size
    # and the shared cache would rarely hit at all). Widened from an
    # initial 4px -- imperceptible at the sizes this system draws at
    # (StormConfig.size_min defaults to 16) and roughly halves how many
    # distinct rotation wheels (optimization 1) ever need baking.
    SIZE_BUCKET_PX = 8
    # Optimization 1 -- how many angle-frames of a rotation wheel get
    # pre-baked per update() call while one is in progress. High enough
    # that a newly-introduced (asset, size) combo warms up in well under
    # a second even at the finest bucket (180 steps at 2 degrees), low
    # enough that it never dominates a single frame's own cost.
    WHEEL_BAKE_BUDGET_PER_FRAME = 24

    def __init__(self):
        self.particles = []
        self._surface_cache = {}
        self._rotated_cache = {}
        self._spawn_accumulator = 0.0
        # (surface id, size bucket, bucket_deg) -> next wheel step index
        # still needing baking -- present as a key means that combo's
        # wheel has been queued at least once (even once complete, the
        # entry just stays at step >= total, cheap to leave in place
        # rather than pruning).
        self._wheel_progress = {}
        # FIFO of (surface, size_bucket, bucket_deg) tuples still needing
        # more wheel frames baked -- see _advance_wheel_baking.
        self._wheel_queue = deque()
        # Cache for the background image, scaled once per (path,
        # screen_size) pair rather than every frame -- see
        # _render_background.
        self._background_key = None
        self._background_scaled = None

        # Session persistence (2026-08-22, confirmed with the user) --
        # whatever was last saved to CURRENT_STATE_PATH (see save_current,
        # called by StormPanelUI after every committed edit) takes over
        # from a fresh StormConfig()'s own defaults, so settings survive a
        # restart. A missing/corrupt file just falls back to defaults +
        # auto-discovered assets, same as a first-ever launch -- never
        # raises, this runs unconditionally at construction time.
        self.config = self._load_state(CURRENT_STATE_PATH)
        if self.config is None:
            self.config = StormConfig()
            default_assets = list_storm_assets()
            if default_assets:
                self.config.assets = [StormAssetWeight(path=path) for path in default_assets]

    def _load_surface(self, path):
        surface = self._surface_cache.get(path)
        if surface is None:
            surface = pygame.image.load(path).convert_alpha()
            self._surface_cache[path] = surface
        return surface

    # -- persistence (session state + named presets) --------------------

    @staticmethod
    def _load_state(path):
        """Returns a StormConfig loaded from `path`, or None if the file
        doesn't exist or isn't valid JSON -- callers decide what "no saved
        state" means (a fresh default StormConfig, in every caller here).
        Deliberately never raises: a hand-edited/corrupted save file
        should degrade to "start fresh", not crash Creator/Menu/Explorator
        construction."""
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return None
        return _config_from_dict(data)

    @staticmethod
    def _write_state(path, config):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(_config_to_dict(config), handle, indent=2, ensure_ascii=False)

    def save_current(self):
        """Persists the live config so the NEXT session starts from it --
        called by StormPanelUI once per committed edit (a slider release,
        a toggle click), never per in-progress drag frame, see its own
        docstring. Best-effort: a write failure (read-only filesystem,
        etc.) is swallowed rather than crashing the editor over a purely
        cosmetic layer's own settings."""
        try:
            self._write_state(CURRENT_STATE_PATH, self.config)
        except OSError:
            pass

    @staticmethod
    def _safe_preset_filename(name):
        """A preset name typed by the player, made safe as a bare
        filename -- strips anything that isn't alnum/space/-/_ and
        collapses whitespace, same spirit as every other free-text-name-
        becomes-a-filename spot in this codebase (e.g. room names)."""
        cleaned = "".join(ch for ch in name if ch.isalnum() or ch in " -_").strip()
        return cleaned or "preset"

    def save_preset(self, name):
        """Saves the live config under `name` -- overwrites silently if a
        preset with that (sanitized) name already exists, same "last save
        wins" convention as every other named-slot save in this project
        (room save/overwrite). Returns the actual filename stem used (the
        sanitized name), so the caller can reflect what actually got
        saved if the typed name needed cleaning."""
        safe_name = self._safe_preset_filename(name)
        self._write_state(PRESETS_DIR / f"{safe_name}.json", self.config)
        return safe_name

    def load_preset(self, name):
        """Replaces the live config with `name`'s saved preset -- returns
        True on success. Clears every live particle so the transition is
        immediate/clean (an old particle spawned under the previous
        config/assets could otherwise keep flying under stale rules for
        the rest of its own lifetime, mixing old and new behavior on
        screen right after loading)."""
        loaded = self._load_state(PRESETS_DIR / f"{self._safe_preset_filename(name)}.json")
        if loaded is None:
            return False
        self.config = loaded
        self.particles = []
        return True

    def delete_preset(self, name):
        try:
            (PRESETS_DIR / f"{self._safe_preset_filename(name)}.json").unlink()
        except OSError:
            pass

    def _current_rotation_bucket_deg(self):
        count = len(self.particles)
        for ceiling, degrees in self.ROTATION_BUCKET_THRESHOLDS:
            if ceiling is None or count <= ceiling:
                return degrees
        return self.ROTATION_BUCKET_THRESHOLDS[-1][1]

    def _bake_rotated(self, surface, size_bucket, angle_bucket):
        scaled = pygame.transform.smoothscale(surface, (size_bucket, size_bucket))
        return pygame.transform.rotate(scaled, angle_bucket) if angle_bucket else scaled

    def _rotated_surface(self, surface, size, rotation, bucket_deg):
        """The shared rotated+scaled cache -- see this class's own
        docstring. Never mutate the returned Surface (StormParticle.draw
        already copies it before touching alpha, for exactly this
        reason). Also queues (but does not itself bake) the full rotation
        wheel for this (surface, size, bucket_deg) combo -- see
        _advance_wheel_baking, called once per update()."""
        size_bucket = max(1, round(size / self.SIZE_BUCKET_PX) * self.SIZE_BUCKET_PX)
        angle_bucket = round(rotation / bucket_deg) * bucket_deg % 360
        key = (id(surface), size_bucket, angle_bucket)
        baked = self._rotated_cache.get(key)
        if baked is None:
            baked = self._bake_rotated(surface, size_bucket, angle_bucket)
            self._rotated_cache[key] = baked
        self._queue_wheel(surface, size_bucket, bucket_deg)
        return baked

    def _queue_wheel(self, surface, size_bucket, bucket_deg):
        wheel_key = (id(surface), size_bucket, bucket_deg)
        if wheel_key in self._wheel_progress:
            return
        self._wheel_progress[wheel_key] = 0
        self._wheel_queue.append((surface, size_bucket, bucket_deg))

    def _advance_wheel_baking(self):
        """Spends a small fixed budget baking angle-frames for whichever
        (asset, size, resolution) wheel is currently at the front of the
        queue, oldest-queued first -- see optimization 1 in this class's
        own docstring. Cheap no-op once every queued wheel is complete."""
        budget = self.WHEEL_BAKE_BUDGET_PER_FRAME
        while budget > 0 and self._wheel_queue:
            surface, size_bucket, bucket_deg = self._wheel_queue[0]
            wheel_key = (id(surface), size_bucket, bucket_deg)
            step = self._wheel_progress[wheel_key]
            steps_total = max(1, 360 // bucket_deg)
            if step >= steps_total:
                self._wheel_queue.popleft()
                continue
            angle = (step * bucket_deg) % 360
            cache_key = (id(surface), size_bucket, angle)
            if cache_key not in self._rotated_cache:
                self._rotated_cache[cache_key] = self._bake_rotated(surface, size_bucket, angle)
                budget -= 1
            self._wheel_progress[wheel_key] = step + 1

    def _target_count(self):
        if not self.config.enabled:
            return 0
        raw = self.config.density * (self.config.intensity / 100.0)
        return max(0, min(self.MAX_PARTICLES, round(raw)))

    def update(self, dt, screen_size):
        """screen_size is whatever the caller's own screen.get_size() is
        right now -- read fresh every call (not cached) so a resize/
        fullscreen toggle mid-session doesn't strand particles spawned
        for a stale window size."""
        # Unconditional, before any of this method's own early returns
        # below -- wheel pre-baking (optimization 1) must keep progressing
        # every frame regardless of whether particles are currently being
        # trimmed/spawned this exact call.
        self._advance_wheel_baking()

        self.particles = [particle for particle in self.particles if particle.update(dt)]

        target = self._target_count()
        if len(self.particles) > target:
            del self.particles[target:]
            return

        usable_assets = [asset for asset in self.config.assets if asset.enabled and asset.weight > 0]
        if not usable_assets or len(self.particles) >= target:
            self._spawn_accumulator = 0.0
            return

        self._spawn_accumulator += dt * self.SPAWN_RATE
        while self._spawn_accumulator >= 1.0 and len(self.particles) < target:
            self._spawn_accumulator -= 1.0
            asset = _pick_weighted_asset(usable_assets)
            surface = self._load_surface(asset.path)
            self.particles.append(StormParticle(self.config, surface, screen_size, asset))

    def _render_background(self, screen):
        """Draws StormConfig.background_path full-screen, first (so every
        particle draws on top of it) -- a plain static backdrop, no
        parallax/motion of its own (confirmed with the user, 2026-08-22 --
        "juste choisir quel asset utiliser en fond", not another animated
        layer). Scaled once per (path, screen size) pair and cached, same
        reasoning as the rotated-particle cache: a resize/fullscreen
        toggle mid-session invalidates it naturally since the cache key
        includes the current screen size."""
        if not self.config.enabled:
            return
        path = self.config.background_path
        if not path:
            return
        screen_size = screen.get_size()
        key = (path, screen_size)
        if self._background_key != key:
            try:
                raw = self._load_surface(path)
            except (pygame.error, OSError):
                self._background_key = key
                self._background_scaled = None
                return
            self._background_scaled = pygame.transform.smoothscale(raw, screen_size)
            self._background_key = key
        if self._background_scaled is not None:
            screen.blit(self._background_scaled, (0, 0))

    def render(self, screen, camera=None):
        """`camera` is anything exposing plain .x/.y attributes (a real
        core.engine.camera.Camera, or a caller with none -- see Menu's own
        idle stand-in) -- only ever READ, never mutated, and only for
        .x/.y (never .zoom, see the module docstring). None is also fine
        (renders with zero parallax offset)."""
        self._render_background(screen)
        if not self.particles:
            return
        parallax = self.config.parallax / 100.0
        if camera is None:
            offset_x = offset_y = 0.0
        else:
            limit = self.MAX_PARALLAX_OFFSET
            offset_x = max(-limit, min(limit, camera.x * parallax))
            offset_y = max(-limit, min(limit, camera.y * parallax))
        # Computed once per frame, not per particle -- see optimization 3
        # in this class's own docstring. Consistent across every particle
        # drawn this frame even though len(self.particles) itself never
        # changes mid-render anyway; this just avoids recomputing the same
        # answer a few hundred times.
        bucket_deg = self._current_rotation_bucket_deg()
        for particle in self.particles:
            image = self._rotated_surface(particle.surface, particle.size, particle.rotation, bucket_deg)
            particle.draw(screen, offset_x, offset_y, image)
