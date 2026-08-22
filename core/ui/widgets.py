"""Shared UI widgets used across game states (menu, editor, ...)."""

from __future__ import annotations

import os
import pygame

from core.ui.fonts import get_font

# ---------------------------------------------------------------------
# Border Manager
# ---------------------------------------------------------------------


class BorderManager:
    """Simple singleton used to draw 9-slice borders."""

    _instance = None

    BORDER_SIZE = 64
    CORNER_SIZE = 16

    # Cap on how many distinct (width, height) scaled variants draw() keeps
    # cached at once (see draw()'s own comment) -- a panel dragged through a
    # continuous resize would otherwise visit a new pixel size on almost
    # every frame, growing this dict without bound for the lifetime of the
    # process. Cleared wholesale rather than evicted LRU-style once hit --
    # this singleton is shared by every panel in the app, so a resize drag
    # ending just means the next few draw() calls rebuild a small working
    # set again, which is still far cheaper than never caching at all.
    MAX_SCALED_CACHE = 64

    def __new__(cls, border_asset_path="assets/UI/allborder.png"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, border_asset_path="assets/UI/allborder.png"):
        if self._initialized:
            return

        self.border_asset_path = border_asset_path
        self.border = None
        self._sheet = None
        self.rows = 0
        self.cols = 0
        self.current_cell = (0, 0)
        # (width, height) -> {"center"/"top"/"bottom"/"left"/"right": scaled
        # Surface} -- see draw()'s own comment for why this exists and
        # set_tile()/load_border() for why it's cleared whenever self.border
        # itself changes underneath it.
        self._scaled_cache = {}

        self.load_border()

        self._initialized = True

    # -------------------------------------------------------------

    def load_border(self):

        if os.path.exists(self.border_asset_path):

            self._sheet = pygame.image.load(self.border_asset_path).convert_alpha()
            self.rows = self._sheet.get_height() // self.BORDER_SIZE
            self.cols = self._sheet.get_width() // self.BORDER_SIZE

            self.set_tile(0, 0)

        else:

            self.border = self._create_fallback()
            self._scaled_cache = {}

    # -------------------------------------------------------------

    def set_tile(self, row, col):
        """Switch the active 9-slice to a different cell of the same border
        sheet -- a no-op if no sheet was loaded (fallback mode). Since this
        singleton is shared by every panel in the app (Menu, RoomBrowser,
        Creator's UI), changing it here updates every panel's look the next
        time it draws, with no other code needing to react."""
        if self._sheet is None:
            return

        row = max(0, min(self.rows - 1, row))
        col = max(0, min(self.cols - 1, col))

        c = self.BORDER_SIZE
        tile = self._sheet.subsurface((col * c, row * c, c, c)).copy()
        self.border = self._create_nine_slice(tile)
        self.current_cell = (row, col)
        self._scaled_cache = {}

    # -------------------------------------------------------------

    def _create_fallback(self):

        surf = pygame.Surface((64, 64), pygame.SRCALPHA)
        surf.fill((40, 40, 40))
        pygame.draw.rect(surf, (255, 255, 255), surf.get_rect(), 3)

        return self._create_nine_slice(surf)

    # -------------------------------------------------------------

    def _create_nine_slice(self, surface):

        c = self.CORNER_SIZE
        w, h = surface.get_size()

        return {
            "tl": surface.subsurface((0, 0, c, c)).copy(),
            "tr": surface.subsurface((w - c, 0, c, c)).copy(),
            "bl": surface.subsurface((0, h - c, c, c)).copy(),
            "br": surface.subsurface((w - c, h - c, c, c)).copy(),
            "top": surface.subsurface((c, 0, w - 2 * c, c)).copy(),
            "bottom": surface.subsurface((c, h - c, w - 2 * c, c)).copy(),
            "left": surface.subsurface((0, c, c, h - 2 * c)).copy(),
            "right": surface.subsurface((w - c, c, c, h - 2 * c)).copy(),
            "center": surface.subsurface((c, c, w - 2 * c, h - 2 * c)).copy(),
        }

    # -------------------------------------------------------------

    def draw(self, screen, rect):

        if self.border is None:
            return

        c = self.CORNER_SIZE

        x = rect.x
        y = rect.y
        w = rect.width
        h = rect.height

        b = self.border

        # draw() is the single most-invoked drawing call in the whole UI
        # layer (every bordered panel/button, every frame it's visible), but
        # a panel's rect size only actually changes while it's being
        # resized/dragged -- rescaling all 5 edge/center pieces via
        # pygame.transform.scale on every single call regardless was pure
        # waste the overwhelming rest of the time. Cached per (w, h), reused
        # across frames until the size (or the border tile itself, see
        # set_tile/load_border) actually changes.
        scaled = self._scaled_cache.get((w, h))
        if scaled is None:
            scaled = {}
            if w > c * 2 and h > c * 2:
                scaled["center"] = pygame.transform.scale(b["center"], (w - c * 2, h - c * 2))
            if w > c * 2:
                scaled["top"] = pygame.transform.scale(b["top"], (w - c * 2, c))
                scaled["bottom"] = pygame.transform.scale(b["bottom"], (w - c * 2, c))
            if h > c * 2:
                scaled["left"] = pygame.transform.scale(b["left"], (c, h - c * 2))
                scaled["right"] = pygame.transform.scale(b["right"], (c, h - c * 2))

            if len(self._scaled_cache) >= self.MAX_SCALED_CACHE:
                self._scaled_cache.clear()
            self._scaled_cache[(w, h)] = scaled

        # Centre
        if "center" in scaled:
            screen.blit(scaled["center"], (x + c, y + c))

        # Haut / bas
        if "top" in scaled:
            screen.blit(scaled["top"], (x + c, y))
            screen.blit(scaled["bottom"], (x + c, y + h - c))

        # Gauche / droite
        if "left" in scaled:
            screen.blit(scaled["left"], (x, y + c))
            screen.blit(scaled["right"], (x + w - c, y + c))

        # Coins
        screen.blit(b["tl"], (x, y))
        screen.blit(b["tr"], (x + w - c, y))
        screen.blit(b["bl"], (x, y + h - c))
        screen.blit(b["br"], (x + w - c, y + h - c))

    # -------------------------------------------------------------

    def draw_centered_label(self, screen, rect, font, text, color=(255, 255, 255)):
        """The "bordered button" pattern repeated throughout menu.py and
        editor/ui.py: this border's 9-slice drawn at `rect`, then `text`
        (rendered with `font`) centered inside it. Callers that need the
        rendered Surface itself (none currently do) can still call draw()
        and font.render() by hand -- this is just the common case."""
        self.draw(screen, rect)
        surface = font.render(text, True, color)
        screen.blit(surface, (rect.centerx - surface.get_width() / 2, rect.centery - surface.get_height() / 2))

    ENABLED_COLOR = (255, 255, 255)
    DISABLED_COLOR = (110, 110, 110)

    def draw_enabled_label(self, screen, rect, font, text, enabled):
        """draw_centered_label, greyed out when `enabled` is False -- the
        "Valider"/"Generer" confirm-button pattern repeated across
        RoomPanelUI, GeneratorPanelUI, and Menu's room-picker."""
        self.draw_centered_label(screen, rect, font, text, self.ENABLED_COLOR if enabled else self.DISABLED_COLOR)


# ---------------------------------------------------------------------
# Stepper ("-  N  +" row)
# ---------------------------------------------------------------------


class Stepper:
    """A "-  N  +" row: three rects (minus/count/plus) laid out left to
    right from a single origin, with min/max-clamped value changes on
    click -- editor/ui.py's GeneratorPanelUI (room count) and ChestPanelUI
    (one per currency/item loot row) each used to hand-roll this exact rect
    layout at slightly different sizes; this is the shared shape, they own
    the value itself (a Stepper holds no state of its own besides its
    rects and bounds)."""

    def __init__(self, x, y, button_size, count_width, minimum, maximum):
        self.minus_rect = pygame.Rect(x, y, button_size, button_size)
        self.count_rect = pygame.Rect(self.minus_rect.right + 4, y, count_width, button_size)
        self.plus_rect = pygame.Rect(self.count_rect.right + 4, y, button_size, button_size)
        self.minimum = minimum
        self.maximum = maximum

    @property
    def bottom(self):
        return self.plus_rect.bottom

    def contains(self, pos):
        return self.minus_rect.collidepoint(pos) or self.plus_rect.collidepoint(pos)

    def handle_click(self, pos, value):
        """Returns the new, clamped value if `pos` hit -/+, else None (the
        caller tells the two apart by checking for None -- 0 is a valid
        clamped value, so this can't just return a falsy sentinel)."""
        if self.minus_rect.collidepoint(pos):
            return max(self.minimum, value - 1)
        if self.plus_rect.collidepoint(pos):
            return min(self.maximum, value + 1)
        return None

    def render(self, screen, border, font, value):
        border.draw_centered_label(screen, self.minus_rect, font, "-")
        border.draw_centered_label(screen, self.count_rect, font, str(value))
        border.draw_centered_label(screen, self.plus_rect, font, "+")


# ---------------------------------------------------------------------
# Slider (horizontal track + handle numeric input)
# ---------------------------------------------------------------------


class Slider:
    """A horizontal "track + handle" numeric input over an integer
    [minimum, maximum] range -- click anywhere on the track to jump the
    handle there, or press-and-drag the handle itself across a wide range
    in one gesture (StormPanelUI's own motivation for using this over
    Stepper's +/- buttons, confirmed with the user, 2026-08-22: some of
    its ranges are wide enough that dozens of +/-1 clicks were tedious).

    Deliberately stateless (no "am I currently being dragged" flag of its
    own) -- unlike Stepper, a slider drag must keep tracking the mouse
    across multiple MOUSEMOTION events spanning several frames, but
    StormPanelUI (the only caller so far) rebuilds a fresh Slider instance
    from scratch on every single call to keep move() a plain x/y update
    (see its own docstring) -- an instance-owned drag flag would silently
    reset every time and a drag could never actually continue. The
    CALLER owns "which field is currently being dragged" instead (a
    plain key it remembers across calls) and always routes drag-continue
    events straight to handle_drag() for that one field, bypassing the
    track-collision check in handle_click() entirely once a drag has
    started (so the drag doesn't stop just because the mouse strayed
    above/below the track's own y-range, standard slider behavior)."""

    HANDLE_WIDTH = 10

    def __init__(self, x, y, width, height, minimum, maximum):
        self.track_rect = pygame.Rect(x, y, width, height)
        self.minimum = minimum
        self.maximum = maximum

    def _value_to_x(self, value):
        span = self.maximum - self.minimum
        usable = self.track_rect.width - self.HANDLE_WIDTH
        t = 0.0 if span <= 0 else (value - self.minimum) / span
        return self.track_rect.x + self.HANDLE_WIDTH / 2 + max(0.0, min(1.0, t)) * usable

    def _x_to_value(self, x):
        usable = self.track_rect.width - self.HANDLE_WIDTH
        if usable <= 0:
            return self.minimum
        t = (x - self.track_rect.x - self.HANDLE_WIDTH / 2) / usable
        t = max(0.0, min(1.0, t))
        return round(self.minimum + t * (self.maximum - self.minimum))

    def contains(self, pos):
        return self.track_rect.collidepoint(pos)

    def handle_click(self, pos):
        """A MOUSEBUTTONDOWN at `pos` -- returns the new clamped value if
        `pos` hit the track (jump-to-click), else None. The caller starts
        tracking a drag on a non-None return, same as handle_drag below."""
        if self.track_rect.collidepoint(pos):
            return self._x_to_value(pos[0])
        return None

    def handle_drag(self, pos):
        """A MOUSEMOTION while this field is the caller's own remembered
        "currently dragging" one -- always returns a new clamped value
        (x is clamped to the track's own range even if `pos` has drifted
        outside it vertically or horizontally)."""
        return self._x_to_value(pos[0])

    def render(self, screen, value, track_color=(55, 55, 68), fill_color=(90, 150, 220), handle_color=(235, 235, 245)):
        pygame.draw.rect(screen, track_color, self.track_rect, border_radius=3)
        handle_x = self._value_to_x(value)
        fill_rect = pygame.Rect(self.track_rect.x, self.track_rect.y, max(0, round(handle_x - self.track_rect.x)), self.track_rect.height)
        pygame.draw.rect(screen, fill_color, fill_rect, border_radius=3)
        handle_rect = pygame.Rect(0, 0, self.HANDLE_WIDTH, self.track_rect.height + 6)
        handle_rect.center = (handle_x, self.track_rect.centery)
        pygame.draw.rect(screen, handle_color, handle_rect, border_radius=2)


# ---------------------------------------------------------------------
# Layout column (vertical rect-stacking cursor)
# ---------------------------------------------------------------------


class LayoutColumn:
    """A vertical cursor for laying out a column of rects without hand-
    computing `self.y + <magic offset>` for every field -- the pattern that
    made `SpriteEditorPanelUI._layout()` (originally 197 lines of literal
    y-offsets, one panel adding a field away from silently overlapping
    another) fragile: adding a field meant recomputing every offset below
    it by hand and cross-referencing prose comments to confirm mutually-
    exclusive sub-sections didn't actually collide.

    Holds no state beyond `x`/`y`/`width` -- `y` is a plain mutable
    attribute, not hidden behind a method, specifically so a caller can
    snapshot/restore it around two mutually-exclusive sub-blocks that are
    meant to start at the same y (e.g. a "tuile-only" vs "pack-only" field
    group, never rendered at once) -- `saved_y = column.y; ...; column.y =
    saved_y` -- rather than this class inventing a "branch" abstraction
    with no second proven use case yet."""

    def __init__(self, x, y, width):
        self.x = x
        self.y = y
        self.width = width

    def rect(self, height, width=None):
        """One rect at the current cursor, `width` defaulting to the
        column's own width -- advances the cursor by `height`."""
        r = pygame.Rect(self.x, self.y, width if width is not None else self.width, height)
        self.y += height
        return r

    def gap(self, height):
        """Advances the cursor without producing a rect -- spacing between
        sections. Returns self so calls can chain, e.g. `column.gap(8).rect(32)`."""
        self.y += height
        return self

    def row(self, count, height, gap=4):
        """`count` equal-width rects side by side at the current cursor
        (splitting the column's own width, same idiom every hand-rolled
        mode-button/toggle row in this codebase already used) -- advances
        the cursor by `height` once, not per rect."""
        w = (self.width - gap * (count - 1)) // count
        rects = []
        x = self.x
        for _ in range(count):
            rects.append(pygame.Rect(x, self.y, w, height))
            x += w + gap
        self.y += height
        return rects


# ---------------------------------------------------------------------
# Panel frame (draggable/collapsible title bar wrapper)
# ---------------------------------------------------------------------


def _lerp(a, b, t):
    return a + (b - a) * t


def _ease(t):
    """Smoothstep -- eases both ends of a 0..1 progress value so animated
    motion (PanelOpenAnimation) reads as deliberate rather than linear/
    robotic."""
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _lerp_rect(start, end, t):
    t = _ease(t)
    return pygame.Rect(
        round(_lerp(start.x, end.x, t)), round(_lerp(start.y, end.y, t)),
        round(_lerp(start.width, end.width, t)), round(_lerp(start.height, end.height, t)),
    )


class PanelOpenAnimation:
    """Procedural open/close choreography between a PanelTab (its bottom-
    left bookmark spot, collapsed state) and its PanelFrame (docked, fully
    open state) -- confirmed with the user, 2026-08-22. One instance lives
    on each PanelFrame (see PanelFrame.transition); Creator triggers it
    (tab click to open, PanelFrame's own close button to close) and reads
    current_phase()/current_rect() each frame to know what to draw instead
    of the frame's normal chrome/body while `is_animating`.

    Opening plays 4 fixed-duration phases in order, using the tab's and
    the panel's own CURRENT (last known, e.g. profile-restored) positions
    as endpoints, never a hardcoded one:
      shrink       -- the tab collapses in place into a small square
      travel       -- the square glides to the panel's title bar's left edge
      expand_title -- the square stretches sideways into the full title
                       bar, revealing the panel's name
      expand_body  -- the bar stretches downward into the full panel body
    Closing plays the exact reverse (shrink_body, shrink_title, travel_back,
    grow) ending back at the tab's own spot.

    Purely a phase/progress/rect state machine -- draws nothing itself."""

    SQUARE_SIZE = 20
    PHASE_DURATION = 0.14  # seconds per phase -- ~0.56s for the full sequence

    _OPEN_PHASES = ("shrink", "travel", "expand_title", "expand_body")
    _CLOSE_PHASES = ("shrink_body", "shrink_title", "travel_back", "grow")

    def __init__(self):
        self.phases = None
        self.phase_index = 0
        self.t = 0.0
        self.tab_rect = None
        self.tab_square_rect = None
        self.title_rect = None
        self.title_square_rect = None
        self.combined_rect = None

    @property
    def is_idle(self):
        return self.phases is None

    @property
    def is_animating(self):
        return self.phases is not None

    def _prime(self, tab_rect, title_rect, combined_rect):
        """Captures every endpoint rect fresh, at the moment an animation
        starts -- tab_rect is wherever the tab visually is RIGHT NOW
        (mid-hover-rise or resting, doesn't matter), title_rect/
        combined_rect come from the panel's current x/y/width/height. The
        two intermediate squares are derived from these so both directions
        of the animation always land exactly on the real title bar and the
        real tab, however either has moved since the last time this ran."""
        self.tab_rect = pygame.Rect(tab_rect)
        self.tab_square_rect = pygame.Rect(0, 0, self.SQUARE_SIZE, self.SQUARE_SIZE)
        self.tab_square_rect.center = self.tab_rect.center
        self.title_rect = pygame.Rect(title_rect)
        self.title_square_rect = pygame.Rect(0, 0, self.SQUARE_SIZE, self.SQUARE_SIZE)
        self.title_square_rect.midleft = self.title_rect.midleft
        self.combined_rect = pygame.Rect(combined_rect)

    def start_open(self, tab_rect, title_rect, combined_rect):
        self._prime(tab_rect, title_rect, combined_rect)
        self.phases = self._OPEN_PHASES
        self.phase_index = 0
        self.t = 0.0

    def start_close(self, tab_rect, title_rect, combined_rect):
        self._prime(tab_rect, title_rect, combined_rect)
        self.phases = self._CLOSE_PHASES
        self.phase_index = 0
        self.t = 0.0

    def update(self, dt):
        """Advances the running sequence, if any. Returns "opened"/"closed"
        the one frame a sequence finishes (so Creator can flip `collapsed`
        and persist it), None every other frame including while idle."""
        if self.phases is None:
            return None
        was_opening = self.phases is self._OPEN_PHASES
        self.t += dt / self.PHASE_DURATION
        while self.phases is not None and self.t >= 1.0:
            self.t -= 1.0
            self.phase_index += 1
            if self.phase_index >= len(self.phases):
                self.phases = None
                self.phase_index = 0
                self.t = 0.0
                return "opened" if was_opening else "closed"
        return None

    @property
    def current_phase(self):
        return None if self.phases is None else self.phases[self.phase_index]

    def current_rect(self):
        """The single rect to draw this frame's in-flight square/bar/box
        at, for whichever phase is currently active -- None while idle."""
        phase = self.current_phase
        if phase is None:
            return None
        endpoints = {
            "shrink": (self.tab_rect, self.tab_square_rect),
            "travel": (self.tab_square_rect, self.title_square_rect),
            "expand_title": (self.title_square_rect, self.title_rect),
            "expand_body": (self.title_rect, self.combined_rect),
            "shrink_body": (self.combined_rect, self.title_rect),
            "shrink_title": (self.title_rect, self.title_square_rect),
            "travel_back": (self.title_square_rect, self.tab_square_rect),
            "grow": (self.tab_square_rect, self.tab_rect),
        }
        start, end = endpoints[phase]
        return _lerp_rect(start, end, self.t)


class PanelFrame:
    """Wraps one of Creator's docked panels (ToolPaletteUI, CardPanelUI,
    RoomPanelUI, GeneratorPanelUI -- anything exposing x/y/width/height/
    render(screen)/contains(pos) plus a move(dx, dy) it implements itself,
    since each one caches its own child rects differently) with a
    `collapsed` flag and a minimal title bar (name + a close button) drawn
    just above it while open, so a docked panel can be hidden/shown and
    the player can still tell what's on screen (confirmed with the user,
    2026-08-22 -- an earlier pass dropped the bar entirely in favor of the
    bottom-left PanelTab alone, which turned out to read as unlabelled
    clutter once several panels were open at once).

    The title bar (minus its close button) is still a drag handle
    (2026-08-22: reintroduced -- turned out to matter a lot in practice,
    letting the player put each panel wherever suits their layout)
    dragged via handle_title_drag(), gated by Creator to only fully-open,
    non-animating frames. Opening goes through a PanelTab
    (core.editor.creator._panel_tab_entries) and closing through this
    frame's own close_button_rect(), both driving a PanelOpenAnimation
    (self.transition) that animates between the tab's spot and this
    frame's own CURRENT x/y/width/height rather than teleporting -- since
    title_rect()/body_rect() are always read fresh off self.panel.x/y/
    width/height, wherever the player last dragged a panel to is exactly
    where its next open/close animation will start/end, no extra plumbing
    needed. Creator owns triggering that animation and reading
    transition.current_rect()/current_phase() to know what to draw instead
    of render() while transition.is_animating -- this class only exposes
    the rects/state needed for that (title_rect/body_rect/
    close_button_rect/transition).

    Deliberately NOT an event-dispatch layer over the wrapped panel's own
    handle_event -- Creator keeps calling each panel's existing
    click-routing exactly as before (hit_autotile_toggle, object palette
    drag-start, room/generator panel confirm actions), just gated by
    `not frame.collapsed` -- which Creator keeps True for the entire
    opening animation and sets True the instant closing starts, so normal
    interaction never reaches a panel that isn't ACTUALLY fully on screen
    yet/anymore.
    """

    TITLE_HEIGHT = 24
    CLOSE_BUTTON_SIZE = 18
    # How many pixels of the title bar must stay on-screen horizontally --
    # keeps a panel restored from a stale/off-screen saved position still
    # reachable, without forcing the whole (possibly much wider) panel body
    # back on-screen too.
    MIN_VISIBLE_X = 60

    def __init__(self, panel, title, on_change=None):
        self.panel = panel
        self.title = title
        self.on_change = on_change
        self.collapsed = False
        self.transition = PanelOpenAnimation()

        self._dragging = False
        self._drag_last_pos = None

        self.border = BorderManager()
        self.font = get_font("title", 15)

    def title_rect(self):
        return pygame.Rect(self.panel.x, self.panel.y - self.TITLE_HEIGHT, self.panel.width, self.TITLE_HEIGHT)

    def body_rect(self):
        return pygame.Rect(self.panel.x, self.panel.y, self.panel.width, self.panel.height)

    def close_button_rect(self):
        title = self.title_rect()
        return pygame.Rect(
            title.right - self.CLOSE_BUTTON_SIZE - 4,
            title.y + (title.height - self.CLOSE_BUTTON_SIZE) / 2,
            self.CLOSE_BUTTON_SIZE, self.CLOSE_BUTTON_SIZE,
        )

    def _clamp_panel_xy(self, x, y):
        """Keeps the title bar fully on-screen when restoring a saved
        layout: its top edge never above the screen (the bug that stranded
        the Forge panel, whose saved y went negative and put its whole
        title bar above y=0) and at least MIN_VISIBLE_X of its width
        on-screen horizontally. The panel body itself is free to hang off
        any edge. Self-heals a stale/out-of-bounds saved layout on
        restore (see move_to)."""
        surface = pygame.display.get_surface()
        if surface is None:
            return x, y
        screen_w, screen_h = surface.get_size()
        min_visible = min(self.MIN_VISIBLE_X, self.panel.width)
        x = max(min_visible - self.panel.width, min(x, screen_w - min_visible))
        y = max(self.TITLE_HEIGHT, min(y, screen_h - self.TITLE_HEIGHT))
        return x, y

    def move_to(self, x, y):
        """Absolute reposition -- used only to restore a saved layout now
        (no more live drag). Delegates to the wrapped panel's own
        move(dx, dy) so the restore path shifts icon rects, Stepper rects,
        etc. exactly the same way any other relocation would."""
        x, y = self._clamp_panel_xy(x, y)
        self.panel.move(x - self.panel.x, y - self.panel.y)

    def handle_title_drag(self, event):
        """Drag-to-reposition via the title bar, excluding the close
        button (Creator checks that separately, before this, so a close
        click can never also start a drag). Returns True if this event was
        about dragging and should not be forwarded to anything else.
        Creator only ever calls this for a frame that's fully open and not
        mid-animation -- same gating as every other interaction here."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.close_button_rect().collidepoint(event.pos):
                return False
            if self.title_rect().collidepoint(event.pos):
                self._dragging = True
                self._drag_last_pos = event.pos
                return True
            return False

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._dragging:
                self._dragging = False
                self._drag_last_pos = None
                self._notify_change()
                return True
            return False

        if event.type == pygame.MOUSEMOTION and self._dragging and self._drag_last_pos is not None:
            dx = event.pos[0] - self._drag_last_pos[0]
            dy = event.pos[1] - self._drag_last_pos[1]
            target_x, target_y = self._clamp_panel_xy(self.panel.x + dx, self.panel.y + dy)
            self.panel.move(target_x - self.panel.x, target_y - self.panel.y)
            self._drag_last_pos = event.pos
            return True

        return False

    def contains(self, pos):
        """True if `pos` hits the title bar or body of a panel that is
        ACTUALLY fully open right now (not collapsed, not mid-animation)
        -- used by Creator both to bring this frame to front and to decide
        whether a click here should block a click from reaching the grid
        underneath (see Creator's existing panel_click gating). Always
        False during a transition -- nothing real is sitting at this
        frame's rect yet/anymore, only the animated square/bar Creator
        draws separately."""
        if self.collapsed or self.transition.is_animating:
            return False
        return self.title_rect().collidepoint(pos) or self.panel.contains(pos)

    def _notify_change(self):
        if self.on_change is not None:
            self.on_change(self)

    def render_chrome(self, screen):
        """The minimal title bar alone -- name + close button, no drag
        handle. Used both by render() (normal, fully-open state) and by
        Creator's transition rendering once the expand_title/shrink_body
        phase has it at full size (see PanelOpenAnimation)."""
        title_rect = self.title_rect()
        self.border.draw(screen, title_rect)
        label = self.font.render(self.title, True, (255, 255, 255))
        screen.blit(label, (title_rect.x + 8, title_rect.centery - label.get_height() / 2))
        self.border.draw_centered_label(screen, self.close_button_rect(), self.font, "x")

    def render(self, screen, **panel_kwargs):
        """**panel_kwargs is forwarded to the wrapped panel's own render
        (e.g. ToolPaletteUI.render(screen, autotile_enabled=...)) -- this
        class doesn't need to know each panel's particular render
        signature, just pass whatever the caller gave it through. Only
        meaningful while fully open -- Creator never calls this during a
        transition (see PanelOpenAnimation's own rendering in Creator)."""
        if self.collapsed:
            return
        self.render_chrome(screen)
        self.panel.render(screen, **panel_kwargs)


class ModalFadeState:
    """Tracks a simple fade in/out alpha (0..255) for a full-screen modal
    panel that owns its own is_open/open()/close() -- SettingsPanelUI,
    SpriteEditorPanelUI -- neither of which is a good fit for
    PanelOpenAnimation's tab-travel choreography (both are genuinely
    full-screen, not a small docked rect with a "last known position" to
    animate to/from; SettingsPanelUI in particular is shared between
    Creator and Explorator, so reshaping it into a dockable panel would
    ripple well past this file). update() just watches whatever `is_open`
    the caller passes each frame and ramps toward 255 (fully visible) or 0
    -- no hook into open()/close() needed, so it works with either panel
    completely unmodified. Confirmed with the user, 2026-08-22: "un petit
    fondu... ça ira très bien" -- a fade only, not the full animation."""

    FADE_SPEED = 900  # alpha units/sec, ~0.28s for a full 0->255 fade

    def __init__(self):
        self.alpha = 0.0

    def update(self, dt, is_open):
        target = 255.0 if is_open else 0.0
        if self.alpha < target:
            self.alpha = min(target, self.alpha + self.FADE_SPEED * dt)
        elif self.alpha > target:
            self.alpha = max(target, self.alpha - self.FADE_SPEED * dt)

    @property
    def visible(self):
        return self.alpha > 0


class PanelTab:
    """A small bookmark-style tab that opens/closes one docked PanelFrame --
    see Creator, the only caller. Lives in a row anchored to the screen's
    bottom-left corner: at rest, only PEEK_HEIGHT pokes above the bottom
    edge -- just enough to always show its symbol (see ICON_TOP_MARGIN/
    ICON_SIZE) -- and on hover it rises exactly far enough to reveal its
    OWN full title text (self._reveal_height, see __init__), no further --
    "no more than needed, but always enough to read" (2026-08-22, confirmed
    with the user). self.HEIGHT is therefore computed per-instance from
    the title's own rendered length, not a shared constant -- a short
    title like "Forge" needs (and rises) far less than "Generation
    procedurale". Its own bottom edge still never becomes visible even
    fully hovered (HEIGHT is always taller than what actually gets
    revealed, see HEIGHT_HIDDEN_MARGIN), so it keeps reading as a drawer
    still anchored below the screen rather than a floating card. The
    title lives INSIDE the tab, rotated 90 degrees, immediately below the
    symbol (LABEL_TOP_MARGIN kept small on purpose -- "contre le sprite")
    -- not above the tab like an earlier pass had it.

    Purely a rect/hover-progress/click helper -- it renders itself and
    tracks its own hover animation, but knows nothing about PanelFrame,
    gating, or z-order; Creator owns the entry list (which tabs exist, in
    what order, whether each is currently visible) and what a click does
    (toggle collapsed, bring the frame to front, persist the layout).
    layout() must be called once per frame (index = this tab's position
    among the currently-visible ones) before update()/render()."""

    WIDTH = 44
    # How much of the icon (see ICON_TOP_MARGIN/ICON_SIZE below) must clear
    # the screen's bottom edge at rest -- always exactly enough to show the
    # whole symbol plus a small buffer, never partially cropped. Same for
    # every tab regardless of title length -- nothing but the icon shows
    # at rest anyway.
    PEEK_HEIGHT = 44
    # How much of self.HEIGHT stays below the screen's bottom edge even at
    # full hover (self._reveal_height, not self.HEIGHT, is what actually
    # gets revealed) -- keeps the tab reading as anchored/half-hidden
    # rather than a fully floating card regardless of title length.
    HEIGHT_HIDDEN_MARGIN = 40
    GAP = 6
    LEFT_MARGIN = 10
    RISE_SPEED = 8.0  # hover_progress units/sec, 0..1

    # How much a symbol's white pixels dim when the tab isn't hovered (its
    # black outline is left exactly alone either way) -- confirmed with
    # the user, 2026-08-22.
    ICON_DIM_FACTOR = 0.5
    # A pixel counts as "white" (dimmable) once every channel is at least
    # this bright -- assets/UI/symbol.png is clean black/white/transparent
    # pixel art with no real anti-aliasing, so this only exists as a safety
    # margin, not to blend a gradient.
    ICON_WHITE_THRESHOLD = 200
    ICON_TOP_MARGIN = 8
    ICON_SIZE = 32
    # Gap between the icon's own bottom edge and where the rotated title
    # starts -- kept small on purpose, the title should sit right up
    # against the symbol rather than floating in the middle of the tab.
    LABEL_TOP_MARGIN = 3
    # Breathing room below the rotated title's own far end before
    # HEIGHT_HIDDEN_MARGIN's hidden zone begins.
    LABEL_BOTTOM_PADDING = 6

    def __init__(self, title, backing, icon=None):
        self.title = title
        self.backing = backing
        self.icon = icon
        self.hover_progress = 0.0
        self.font = get_font("title", 13)
        # How tall a fully-hovered tab needs to be on screen to show the
        # icon AND the complete rotated title (title's own rendered PIXEL
        # WIDTH becomes its height once rotated 90 degrees) -- computed
        # once here from this tab's own title/font, not per-frame; layout()
        # reads it every frame, render() uses it to place the title flush
        # under the icon. self.HEIGHT (the tab's actual drawn/backing
        # size) is always taller than this by HEIGHT_HIDDEN_MARGIN so the
        # tab's own bottom edge/border stays off-screen even fully risen.
        self._reveal_height = (
            self.ICON_TOP_MARGIN + self.ICON_SIZE + self.LABEL_TOP_MARGIN
            + self.font.size(title)[0] + self.LABEL_BOTTOM_PADDING
        )
        self.HEIGHT = self._reveal_height + self.HEIGHT_HIDDEN_MARGIN
        self.rect = pygame.Rect(0, 0, self.WIDTH, self.HEIGHT)
        self.border = BorderManager()
        self._scaled_backing = None
        # Two baked variants of `icon`, built once on first render (see
        # _dimmed_icon/render): _icon_dim has its white pixels at
        # ICON_DIM_FACTOR alpha, _icon_full is the source unchanged. Drawn
        # one atop the other each frame with the top one's OWN alpha set to
        # hover_progress*255 -- since both share IDENTICAL black/
        # transparent pixels, only the white blends, crossfading smoothly
        # from dim to full as the tab rises instead of popping instantly.
        self._icon_dim = None
        self._icon_full = None

    @staticmethod
    def _dimmed_icon(icon, factor, threshold):
        dimmed = icon.copy()
        width, height = dimmed.get_size()
        for x in range(width):
            for y in range(height):
                r, g, b, a = dimmed.get_at((x, y))
                if a > 0 and r >= threshold and g >= threshold and b >= threshold:
                    dimmed.set_at((x, y), (r, g, b, round(a * factor)))
        return dimmed

    def layout(self, index, screen_size):
        _screen_w, screen_h = screen_size
        rest_y = screen_h - self.PEEK_HEIGHT
        risen_y = screen_h - self._reveal_height
        x = self.LEFT_MARGIN + index * (self.WIDTH + self.GAP)
        y = rest_y + (risen_y - rest_y) * self.hover_progress
        self.rect = pygame.Rect(x, round(y), self.WIDTH, self.HEIGHT)

    def update(self, dt, mouse_pos):
        target = 1.0 if self.rect.collidepoint(mouse_pos) else 0.0
        if self.hover_progress < target:
            self.hover_progress = min(target, self.hover_progress + self.RISE_SPEED * dt)
        elif self.hover_progress > target:
            self.hover_progress = max(target, self.hover_progress - self.RISE_SPEED * dt)

    def render(self, screen):
        if self._scaled_backing is None:
            self._scaled_backing = pygame.transform.smoothscale(self.backing, (self.WIDTH, self.HEIGHT))
        screen.blit(self._scaled_backing, self.rect.topleft)
        self.border.draw(screen, self.rect)
        icon_bottom = self.rect.top + self.ICON_TOP_MARGIN + self.ICON_SIZE
        if self.icon is not None:
            if self._icon_dim is None:
                self._icon_full = self.icon
                self._icon_dim = self._dimmed_icon(self.icon, self.ICON_DIM_FACTOR, self.ICON_WHITE_THRESHOLD)
            icon_rect = self._icon_dim.get_rect(midtop=(self.rect.centerx, self.rect.top + self.ICON_TOP_MARGIN))
            screen.blit(self._icon_dim, icon_rect)
            full = self._icon_full.copy()
            full.set_alpha(round(255 * self.hover_progress))
            screen.blit(full, icon_rect)
        if self.hover_progress > 0.02:
            # Title lives INSIDE the tab, below the symbol, rotated 90
            # degrees counter-clockwise ("vers la gauche" -- reads bottom
            # to top) -- replaces an earlier pass that floated it above
            # the tab instead. Anchored right up against the icon
            # (LABEL_TOP_MARGIN, "contre le sprite") rather than centered
            # in the leftover space below it -- self._reveal_height/
            # layout() already guarantee exactly this much room is on
            # screen once fully hovered. Fades in with the same
            # hover_progress as the icon crossfade, since at rest this
            # whole area sits below the visible peek anyway.
            label = self.font.render(self.title, True, (255, 255, 255))
            rotated = pygame.transform.rotate(label, 90)
            rotated.set_alpha(round(255 * self.hover_progress))
            label_top = icon_bottom + self.LABEL_TOP_MARGIN
            screen.blit(rotated, rotated.get_rect(midtop=(self.rect.centerx, label_top)))


# ---------------------------------------------------------------------
# Border picker (Settings > Bordure)
# ---------------------------------------------------------------------


class BorderPicker:
    """Clickable grid of every raw tile in a BorderManager's sheet -- clicking
    one calls border_manager.set_tile(row, col) directly (so every panel in
    the app, this picker's own background included, re-skins immediately)
    and, if provided, on_select(row, col) so the caller can persist the
    choice. A no-op grid (nothing to click) if the manager has no sheet
    loaded (fallback mode)."""

    CELL_SIZE = 48
    GAP = 4
    HIGHLIGHT_COLOR = (255, 220, 120)

    def __init__(self, x, y, border_manager, on_select=None):
        self.x = x
        self.y = y
        self.border_manager = border_manager
        self.on_select = on_select

    @property
    def width(self):
        cols = max(1, self.border_manager.cols)
        return cols * (self.CELL_SIZE + self.GAP) + self.GAP

    @property
    def height(self):
        rows = max(1, self.border_manager.rows)
        return rows * (self.CELL_SIZE + self.GAP) + self.GAP

    def _cell_rect(self, row, col):
        return pygame.Rect(
            self.x + self.GAP + col * (self.CELL_SIZE + self.GAP),
            self.y + self.GAP + row * (self.CELL_SIZE + self.GAP),
            self.CELL_SIZE,
            self.CELL_SIZE,
        )

    def handle_event(self, event):
        """Returns True if this event was consumed (a swatch was clicked)."""
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False

        for row in range(self.border_manager.rows):
            for col in range(self.border_manager.cols):
                if self._cell_rect(row, col).collidepoint(event.pos):
                    self.border_manager.set_tile(row, col)
                    if self.on_select is not None:
                        self.on_select(row, col)
                    return True

        return False

    def render(self, screen):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        self.border_manager.draw(screen, panel_rect)

        sheet = self.border_manager._sheet
        if sheet is None:
            return

        size = self.border_manager.BORDER_SIZE
        for row in range(self.border_manager.rows):
            for col in range(self.border_manager.cols):
                rect = self._cell_rect(row, col)
                tile = sheet.subsurface((col * size, row * size, size, size))
                scaled = pygame.transform.scale(tile, (self.CELL_SIZE, self.CELL_SIZE))
                screen.blit(scaled, rect.topleft)

                if (row, col) == self.border_manager.current_cell:
                    pygame.draw.rect(screen, self.HIGHLIGHT_COLOR, rect, 3)


# ---------------------------------------------------------------------
# Context menu (right-click popup)
# ---------------------------------------------------------------------


class ContextMenu:
    """A small right-click popup: a fixed screen position + a list of
    (label, action_id) rows. Purely a hit-tester/renderer with no notion of
    what an action actually does -- the caller (RoomBrowser today) owns
    opening it and reacting to whatever handle_event returns. Generic on
    purpose, same spirit as Stepper -- nothing here is room-specific, so a
    later right-click menu elsewhere (a placed object, say) can reuse it as-is.
    """

    ROW_HEIGHT = 26
    WIDTH = 150
    DISMISS = "__dismiss__"

    def __init__(self):
        self.options = None  # list of (label, action_id), or None if closed
        self.pos = (0, 0)
        self.border = BorderManager()
        self.font = get_font("button", 15)

    @property
    def is_open(self):
        return self.options is not None

    def open(self, pos, options):
        self.pos = pos
        self.options = list(options)

    def close(self):
        self.options = None

    def _row_rect(self, index):
        x, y = self.pos
        return pygame.Rect(x, y + index * self.ROW_HEIGHT, self.WIDTH, self.ROW_HEIGHT)

    def handle_event(self, event):
        """Returns the chosen action_id on a row click, ContextMenu.DISMISS
        on any other click (closes without an action -- click-away-to-close),
        or None if this event wasn't a click at all (still open, nothing to
        report yet)."""
        if not self.is_open or event.type != pygame.MOUSEBUTTONDOWN:
            return None
        for index, (_, action_id) in enumerate(self.options):
            if self._row_rect(index).collidepoint(event.pos):
                self.close()
                return action_id
        self.close()
        return self.DISMISS

    def render(self, screen):
        if not self.is_open:
            return
        for index, (label, _action_id) in enumerate(self.options):
            self.border.draw_centered_label(screen, self._row_rect(index), self.font, label)


# ---------------------------------------------------------------------
# Text input box (single-line, blinking cursor)
# ---------------------------------------------------------------------


class TextInputBox:
    """A single-line text field. Reuses the exact input-handling pattern
    Menu's own "name_entry" mode already hand-rolls (core.ui.menu.Menu --
    KEYDOWN: K_RETURN confirms, K_BACKSPACE erases, event.unicode.isprintable()
    + a length cap appends) -- extracted here so a second caller
    (RoomBrowser's rename prompt) doesn't have to duplicate it."""

    def __init__(self, x, y, width, height, value="", max_length=32, mask_char=None):
        self.rect = pygame.Rect(x, y, width, height)
        self.value = value
        self.max_length = max_length
        # A password field's own actual characters, e.g. "*" -- self.value
        # itself always holds the real typed text (handle_event/the caller
        # reading .value need that), only render() ever substitutes this.
        # None (every other caller) renders .value as typed, unchanged.
        self.mask_char = mask_char
        self.border = BorderManager()
        self.font = get_font("text", 16)

    def handle_event(self, event):
        """Returns True once Enter confirms a non-empty value, False if
        Escape cancels, None otherwise (still being edited, or Enter on an
        empty value -- ignored rather than treated as a cancel, so a typo'd-
        down-to-nothing field doesn't silently close on the player)."""
        if event.type != pygame.KEYDOWN:
            return None
        if event.key == pygame.K_RETURN:
            return True if self.value.strip() else None
        if event.key == pygame.K_ESCAPE:
            return False
        if event.key == pygame.K_BACKSPACE:
            self.value = self.value[:-1]
        elif event.unicode and event.unicode.isprintable():
            if len(self.value) < self.max_length:
                self.value += event.unicode
        return None

    def render(self, screen):
        cursor = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else ""
        displayed = self.mask_char * len(self.value) if self.mask_char else self.value
        self.border.draw_centered_label(screen, self.rect, self.font, displayed + cursor)


# ---------------------------------------------------------------------
# Room browser
# ---------------------------------------------------------------------


class RoomBrowser:
    """Scrollable, selectable list of room names with a drag slider. Purely a list-selector -- callers decide what "confirming" a selection means."""

    ROW_HEIGHT = 30
    VISIBLE_ROWS = 5
    SLIDER_WIDTH = 12

    def __init__(self, x, y, width=240, multi_select=False, on_rename=None, on_delete=None, can_rename=None):
        self.x = x
        self.y = y
        self.width = width
        self.multi_select = multi_select

        self.rooms = []
        self.selected = None
        self.selected_set = set()
        self.scroll = 0
        self._dragging_slider = False

        # Right-click rename/delete (optional -- None means the caller
        # doesn't want this at all, e.g. Menu's own room-picker doesn't wire
        # these). RoomBrowser doesn't know about RoomManager/Creator itself,
        # only "a name was chosen for this action" -- the caller decides
        # what actually happens on disk. can_rename(name) -> bool, if given,
        # hides "Renommer" for a name it returns False for (e.g. a player's
        # own home_<name> room, which Creator refuses to let get renamed).
        self.on_rename = on_rename
        self.on_delete = on_delete
        self.can_rename = can_rename
        self._context_menu = ContextMenu()
        self._context_target_index = None
        self._rename_box = None
        self._delete_confirm_index = None

        self.border = BorderManager()
        self.font = get_font("button", 16)

    @property
    def height(self):
        return self.ROW_HEIGHT * self.VISIBLE_ROWS

    @staticmethod
    def _label(entry):
        """Entries are either a plain string, or a (label, value) tuple -- e.g. to
        distinguish two kinds of entry (room vs. donjon) sharing one list."""
        return entry[0] if isinstance(entry, tuple) else entry

    @staticmethod
    def _value(entry):
        return entry[1] if isinstance(entry, tuple) else entry

    @classmethod
    def _room_name_for_context(cls, entry):
        """The room-name string a right-click context menu should operate
        on for `entry`, or None if this entry isn't a room at all --
        RoomPanelUI's "Charger" list also lists donjons, tagged as
        ("donjon", name) inside the (label, value) tuple (its "load" mode
        entries look like (label, (kind, name)), one tuple nested in
        another) -- those never get a rename/delete menu. Every other shape
        (a plain string, or an ordinary (label, name) pair) is treated as a
        real room name -- if it happens not to correspond to an actual file
        (e.g. RoomPanelUI's "+ Nouvelle salle" placeholder row), the
        RoomManager-level operation the caller performs just no-ops on a
        missing file, same as it already does for any other stale name."""
        value = cls._value(entry)
        if isinstance(value, tuple) and len(value) == 2 and value[0] in ("room", "donjon"):
            kind, name = value
            return name if kind == "room" else None
        return value

    @property
    def selected_name(self):
        if self.selected is None or self.selected >= len(self.rooms):
            return None
        return self._value(self.rooms[self.selected])

    @property
    def selected_names(self):
        return [self._value(entry) for i, entry in enumerate(self.rooms) if i in self.selected_set]

    @property
    def is_modal(self):
        """True while a rename box, delete confirmation, or context menu
        is open. These can render/need input OUTSIDE this browser's own
        row-list bounds (see _context_menu.pos, positioned at the click
        that opened it) -- a caller that normally only forwards an event
        here after its own `.contains(pos)` check (so a click meant for
        something else on screen isn't misrouted) must instead forward
        EVERY event here unconditionally while this is true, or the popup
        renders but never actually receives input."""
        return self._rename_box is not None or self._delete_confirm_index is not None or self._context_menu.is_open

    def set_rooms(self, rooms, preselect_all=False):
        self.rooms = list(rooms)
        self.selected = None
        self.selected_set = set(range(len(self.rooms))) if preselect_all else set()
        self.scroll = 0

    def _max_scroll(self):
        return max(0, len(self.rooms) - self.VISIBLE_ROWS)

    def _visible_count(self):
        return min(self.VISIBLE_ROWS, len(self.rooms) - self.scroll)

    def _row_rect(self, row_index):
        return pygame.Rect(
            self.x,
            self.y + row_index * self.ROW_HEIGHT,
            self.width - self.SLIDER_WIDTH - 4,
            self.ROW_HEIGHT,
        )

    def row_at(self, pos):
        """The real index into self.rooms (i.e. self.scroll + visible slot)
        that pos falls on, or None if pos misses every currently visible
        row. Public, pure query -- unlike _row_rect (indexed by on-screen
        slot, not by an actual room/entry), this is what a caller needs to
        go from "the mouse is here" to "which entry is that" without
        knowing this class's row-geometry/scroll internals (see
        core.editor.ui.CardPanelUI's standard-mode drag-start, the first
        caller)."""
        for slot_index in range(self._visible_count()):
            if self._row_rect(slot_index).collidepoint(pos):
                return self.scroll + slot_index
        return None

    def arm_delete_confirm(self, name, pos):
        """Opens the exact same Yes/No delete-confirmation popup the
        right-click context menu's "Supprimer" option opens, for a caller
        that wants to trigger it from a fixed button instead of a row's own
        context menu (e.g. a dedicated "Supprimer" button next to the
        list -- see SpriteEditorPanelUI's pack delete button). No-op if
        `name` isn't a row currently in this browser or on_delete isn't
        wired -- same silent-refusal spirit as the context menu itself
        never offering "Supprimer" without on_delete set."""
        if self.on_delete is None:
            return
        for index, room in enumerate(self.rooms):
            if self._room_name_for_context(room) == name:
                self._context_menu.pos = pos
                self._delete_confirm_index = index
                return

    def _slider_track_rect(self):
        return pygame.Rect(self.x + self.width - self.SLIDER_WIDTH, self.y, self.SLIDER_WIDTH, self.height)

    def _slider_thumb_rect(self):
        track = self._slider_track_rect()
        max_scroll = self._max_scroll()

        if max_scroll == 0:
            return track

        thumb_h = max(20, track.height * self.VISIBLE_ROWS / len(self.rooms))
        thumb_y = track.y + (track.height - thumb_h) * (self.scroll / max_scroll)

        return pygame.Rect(track.x, thumb_y, track.width, thumb_h)

    def contains(self, pos):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        return panel_rect.collidepoint(pos)

    def handle_wheel(self, pos, direction):
        """Scrolls by one row per wheel tick while `pos` is anywhere over
        this browser -- confirmed with the user: grabbing the thin slider
        thumb precisely shouldn't be the only way to scroll, hovering the
        panel and using the wheel should work too, same "more permissive"
        precedent the sprite editor's own hover+scroll controls already
        set. `direction` is event.y's raw sign (positive = wheel up = wards
        row 0, matching every other scroll control in this project).
        Returns True if this browser had scroll room and consumed the
        event, False otherwise (nothing to scroll, or pos isn't over it) --
        same "did I consume this" contract handle_event's own return value
        already uses, so a caller can fall through to something else
        (world-camera zoom) when this returns False."""
        if not self.contains(pos):
            return False
        max_scroll = self._max_scroll()
        if max_scroll <= 0:
            return False
        self.scroll = max(0, min(max_scroll, self.scroll - direction))
        return True

    def _delete_confirm_rects(self):
        x, y = self._context_menu.pos
        return pygame.Rect(x, y, 70, 28), pygame.Rect(x + 74, y, 70, 28)

    def handle_event(self, event):
        """Returns True if this event was consumed (row click, slider drag,
        or absorbed by an open rename/delete popup)."""

        # A pending rename box, delete confirmation, or context menu is
        # modal within this browser -- it absorbs every event until
        # resolved, same principle as Creator's chest_panel/role_panel
        # being modal within Creator. At most one of these three is ever
        # active at once (each one's resolution clears itself before the
        # next can open).
        if self._rename_box is not None:
            result = self._rename_box.handle_event(event)
            if result is not None:
                old_name = self._room_name_for_context(self.rooms[self._context_target_index])
                new_name = self._rename_box.value.strip()
                self._rename_box = None
                self._context_target_index = None
                if result and self.on_rename is not None and new_name and new_name != old_name:
                    self.on_rename(old_name, new_name)
            return True

        if self._delete_confirm_index is not None:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                yes_rect, no_rect = self._delete_confirm_rects()
                target_index = self._delete_confirm_index
                self._delete_confirm_index = None
                if yes_rect.collidepoint(event.pos) and self.on_delete is not None:
                    self.on_delete(self._room_name_for_context(self.rooms[target_index]))
                # else (No, or clicked elsewhere): just cancels.
            return True

        if self._context_menu.is_open:
            action = self._context_menu.handle_event(event)
            if action == "rename":
                name = self._room_name_for_context(self.rooms[self._context_target_index])
                x, y = self._context_menu.pos
                self._rename_box = TextInputBox(x, y, 220, 30, value=name)
            elif action == "delete":
                self._delete_confirm_index = self._context_target_index
            elif action is not None:
                self._context_target_index = None
            return True

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            if self.on_rename is None and self.on_delete is None:
                return False
            for row_index in range(self._visible_count()):
                if self._row_rect(row_index).collidepoint(event.pos):
                    room_index = self.scroll + row_index
                    name = self._room_name_for_context(self.rooms[room_index])
                    if name is None:
                        return True  # a donjon row -- consumed, no menu
                    options = []
                    if self.on_rename is not None and (self.can_rename is None or self.can_rename(name)):
                        options.append(("Renommer", "rename"))
                    if self.on_delete is not None:
                        options.append(("Supprimer", "delete"))
                    if options:
                        self._context_menu.open(event.pos, options)
                        self._context_target_index = room_index
                    return True
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:

            if self._max_scroll() > 0 and self._slider_thumb_rect().collidepoint(event.pos):
                self._dragging_slider = True
                return True

            for row_index in range(self._visible_count()):
                if self._row_rect(row_index).collidepoint(event.pos):
                    room_index = self.scroll + row_index
                    if self.multi_select:
                        if room_index in self.selected_set:
                            self.selected_set.discard(room_index)
                        else:
                            self.selected_set.add(room_index)
                    else:
                        self.selected = room_index
                    return True

            return self.contains(event.pos)

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._dragging_slider:
                self._dragging_slider = False
                return True
            return False

        if event.type == pygame.MOUSEMOTION and self._dragging_slider:
            track = self._slider_track_rect()
            max_scroll = self._max_scroll()
            if max_scroll > 0:
                rel = (event.pos[1] - track.y) / track.height
                self.scroll = max(0, min(max_scroll, round(rel * max_scroll)))
            return True

        return False

    def render(self, screen):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        self.border.draw(screen, panel_rect)

        for row_index in range(self._visible_count()):
            room_index = self.scroll + row_index
            rect = self._row_rect(row_index)

            is_selected = room_index in self.selected_set if self.multi_select else room_index == self.selected
            color = (255, 220, 120) if is_selected else (255, 255, 255)

            label = self._label(self.rooms[room_index])
            if self.multi_select:
                label = ("[x] " if is_selected else "[ ] ") + label

            text = self.font.render(label, True, color)

            screen.blit(text, (rect.x + 8, rect.centery - text.get_height() / 2))

        if self._max_scroll() > 0:
            pygame.draw.rect(screen, (60, 60, 70), self._slider_track_rect())
            pygame.draw.rect(screen, (150, 150, 150), self._slider_thumb_rect())

        self._context_menu.render(screen)

        if self._rename_box is not None:
            self._rename_box.render(screen)

        if self._delete_confirm_index is not None:
            name = self._room_name_for_context(self.rooms[self._delete_confirm_index])
            yes_rect, no_rect = self._delete_confirm_rects()
            prompt = self.font.render(f"Supprimer {name} ?", True, (255, 220, 120))
            screen.blit(prompt, (yes_rect.x, yes_rect.y - prompt.get_height() - 4))
            self.border.draw_centered_label(screen, yes_rect, self.font, "Oui")
            self.border.draw_centered_label(screen, no_rect, self.font, "Non")
