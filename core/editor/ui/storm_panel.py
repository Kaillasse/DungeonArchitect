"""StormPanelUI -- in-game config for core.rendering.storm.StormGenerator.
See that module's own docstring for the system itself; this is just the
Creator-side editing surface (docked/animated/tabbed exactly like every
other panel here, see Creator._panel_tab_entries) -- it mutates
self.storm.config directly and in place, so a change here is visible
immediately, in Creator's own view and in Menu/Explorator's (same shared
instance, see GameManager.storm_generator)."""

import pygame

from core.ui.widgets import BorderManager, Slider, TextInputBox
from core.ui.fonts import get_font
from core.rendering.storm import (
    MODE_CIRCULAR, MODE_RECTILINEAR, OVERRIDABLE_COMMON_ATTRS,
    OVERRIDABLE_CIRCULAR_ATTRS, OVERRIDABLE_RECTILINEAR_ATTRS,
    list_storm_backgrounds, list_storm_presets,
)


class _AssetOverrideProxy:
    """Read/write proxy over one StormAssetWeight's own `overrides` dict,
    for ONE base object (a StormConfig, or its .circular/.rectilinear) --
    lets the exact same (label, getter, attr, min, max) row description a
    global slider already uses drive a per-asset override slider too,
    unmodified: getattr falls back to the base object's own value when
    this asset hasn't overridden that attr (mirrors core.rendering.storm.
    _resolved, which StormParticle actually spawns from -- this class is
    purely the UI-editing mirror of that same fallback rule); setattr
    always writes into the override dict, never the base object itself."""

    def __init__(self, asset, base):
        object.__setattr__(self, "_asset", asset)
        object.__setattr__(self, "_base", base)

    def __getattr__(self, name):
        return self._asset.overrides.get(name, getattr(self._base, name))

    def __setattr__(self, name, value):
        self._asset.overrides[name] = value


class StormPanelUI:
    PANEL_WIDTH = 320
    ROW_HEIGHT = 24
    ROW_GAP = 4
    SECTION_GAP = 10
    LABEL_WIDTH = 190
    SLIDER_HEIGHT = 10
    TITLE_HEIGHT = 30

    # (label, getter(config) -> object actually holding the attr, attr
    # name, minimum, maximum) -- one row each, in this order. getter lets
    # the circular/rectilinear rows below share the exact same rendering/
    # click-handling code as the common ones despite living one level
    # deeper (config.circular.radius_min instead of config.density).
    COMMON_FIELDS = [
        # Densite/Intensite used to read as near-duplicates -- Intensite is
        # now a master dial that also scales speed+opacity (see
        # StormParticle.__init__), Densite only ever changes the target
        # particle COUNT. Labels spell that out directly since it isn't
        # obvious from the name alone.
        ("Densite (nb)", lambda c: c, "density", 0, 200),
        ("Intensite % (global)", lambda c: c, "intensity", 0, 200),
        ("Vitesse min", lambda c: c, "speed_min", 0, 400),
        ("Vitesse max", lambda c: c, "speed_max", 0, 400),
        ("Taille min", lambda c: c, "size_min", 2, 300),
        ("Taille max", lambda c: c, "size_max", 2, 300),
        ("Rotation (deg/s)", lambda c: c, "rotation_speed_max", 0, 360),
        ("Opacite min %", lambda c: c, "opacity_min", 0, 100),
        ("Opacite max %", lambda c: c, "opacity_max", 0, 100),
        ("Duree de vie min (s)", lambda c: c, "lifetime_min", 1, 30),
        ("Duree de vie max (s)", lambda c: c, "lifetime_max", 1, 30),
        ("Parallaxe %", lambda c: c, "parallax", 0, 100),
    ]
    CIRCULAR_FIELDS = [
        ("Rayon min", lambda c: c.circular, "radius_min", 0, 900),
        ("Rayon max", lambda c: c.circular, "radius_max", 0, 900),
        ("Vitesse angulaire", lambda c: c.circular, "angular_speed", 0, 180),
        ("Oscillation rayon %", lambda c: c.circular, "radius_wobble", 0, 100),
        ("Profondeur %", lambda c: c.circular, "depth", 0, 100),
    ]
    RECTILINEAR_FIELDS = [
        ("Direction (deg)", lambda c: c.rectilinear, "direction_deg", 0, 359),
        ("Dispersion (px)", lambda c: c.rectilinear, "spread", 0, 800),
    ]

    def __init__(self, storm_generator, x=460, y=180):
        self.storm = storm_generator
        self.x = x
        self.y = y
        self.width = self.PANEL_WIDTH
        self.height = 400  # real value computed by _compute_layout() below

        self.border = BorderManager()
        self.title_font = get_font("title", 18)
        self.font = get_font("button", 14)
        self.label_font = get_font("button", 13)

        # Which field's slider is currently being dragged, or None -- see
        # the module/Slider docstrings for why this lives here rather than
        # on a Slider instance (a fresh one is built every single call to
        # _compute_layout(), so it can't remember anything across frames
        # itself). ("stepper", attr) for a numeric field, ("asset",
        # id(asset)) for one asset's weight slider, or ("asset_angle",
        # id(asset)) for its orientation offset slider -- all stay stable
        # across calls since the underlying config/asset objects (unlike
        # the row tuples wrapping them) are never recreated, see _rows().
        self._dragging_key = None

        # Collapses just the mode-specific fine-tuning block (circular's
        # radius/speed/wobble/sens, or rectilinear's direction/dispersion)
        # -- confirmed with the user, 2026-08-22 -- independent of
        # collapsing the whole panel via its own PanelFrame/tab.
        self._mode_section_collapsed = False
        # Same idea, for the COMMON_FIELDS block (confirmed with the user,
        # 2026-08-22) -- these two collapse independently of each other.
        self._global_section_collapsed = False

        # Per-asset "Reglages individuels" sections start collapsed (an
        # asset with no overrides at all is the common case) -- a set of
        # id(asset) for the ones the player has actually expanded, rather
        # than a per-asset flag on StormAssetWeight itself, since this is
        # purely a UI convenience state, not something worth persisting
        # into a saved preset/current.json (see storm.py's own
        # _config_to_dict, which never touches this).
        self._expanded_asset_overrides = set()

        # Presets (2026-08-22, confirmed with the user) -- a name field +
        # Sauvegarder button at the bottom of the panel, and the saved
        # list itself (click to load, small "x" to delete). The name box
        # is the one persistent, stateful sub-widget here (everything else
        # is rebuilt fresh every call, see _compute_layout's own
        # docstring) -- its typed .value has to survive across frames the
        # same way RoomBrowser/GeneratorPanelUI's own persistent child
        # widgets already do elsewhere in this codebase; only its .rect
        # gets repositioned each layout call.
        self._preset_name_box = TextInputBox(0, 0, 200, 24, max_length=40)
        self._preset_name_focused = False
        self._preset_status = ""

    def move(self, dx, dy):
        # Nothing here caches an absolute rect (see _compute_layout's own
        # docstring) -- moving the panel is just moving its origin.
        self.x += dx
        self.y += dy

    @property
    def wants_keyboard(self):
        """True while the preset-name field is focused -- Creator's own
        KEYDOWN handling (TAB to switch to Exploration, ESC back to Menu)
        checks this first and forwards to handle_event instead, so typing
        a preset name never accidentally triggers either (see Creator.run
        -- MOUSEBUTTONDOWN/MOUSEMOTION/MOUSEBUTTONUP already always reach
        this panel while it's open, only KEYDOWN needed this extra gate)."""
        return self._preset_name_focused

    # -- per-asset override field tables ---------------------------------

    def _asset_override_fields(self, config):
        """(label, base_getter, attr, minimum, maximum) rows an asset's
        own "Reglages individuels" section should show right now -- the
        exact same COMMON_FIELDS/CIRCULAR_FIELDS/RECTILINEAR_FIELDS rows
        the GLOBAL sliders use, filtered down to whatever core.rendering.
        storm actually allows a per-asset override for (density/
        intensity/parallax/center/clockwise stay global-only, see
        OVERRIDABLE_COMMON_ATTRS's own comment for why) -- one shared
        source of truth in storm.py so this list can never drift from
        what StormParticle actually resolves per-asset."""
        fields = [f for f in self.COMMON_FIELDS if f[2] in OVERRIDABLE_COMMON_ATTRS]
        if config.mode == MODE_CIRCULAR:
            fields += [f for f in self.CIRCULAR_FIELDS if f[2] in OVERRIDABLE_CIRCULAR_ATTRS]
        else:
            fields += [f for f in self.RECTILINEAR_FIELDS if f[2] in OVERRIDABLE_RECTILINEAR_ATTRS]
        return fields

    # -- shared layout/row model -----------------------------------------

    def _rows(self):
        """Ordered row descriptors, rebuilt from the live config every
        call -- switching mode, or an asset appearing/disappearing from
        assets/storm/img/, changes which rows exist the very next call.
        _compute_layout/handle_event/render all walk this exact same
        list, in the exact same order, so none of them can ever disagree
        about what's on screen.

        Fixed top-to-bottom order (confirmed with the user, 2026-08-22):
        effet on/off; fond (background); reglages globaux (collapsible);
        circulaire/rectiligne; reglage fin (collapsible), sens, assets
        utilises (each with its own optional per-asset overrides);
        presets, at the very bottom."""
        config = self.storm.config
        rows = [("enabled",), ("background",), ("global_section_toggle",)]
        if not self._global_section_collapsed:
            rows += [("stepper",) + field for field in self.COMMON_FIELDS]
        rows.append(("mode",))
        rows.append(("mode_section_toggle",))
        if not self._mode_section_collapsed:
            if config.mode == MODE_CIRCULAR:
                rows += [("stepper",) + field for field in self.CIRCULAR_FIELDS]
            else:
                rows += [("stepper",) + field for field in self.RECTILINEAR_FIELDS]
        if config.mode == MODE_CIRCULAR:
            # Outside the collapsible fine-tuning block on purpose -- a
            # frequently-toggled setting, not really a "fine-tuning
            # slider" (confirmed with the user, 2026-08-22).
            rows.append(("clockwise",))
        rows.append(("assets_header",))
        if config.assets:
            for asset in config.assets:
                rows.append(("asset", asset))
                rows.append(("asset_rotation", asset))
                rows.append(("asset_overrides_toggle", asset))
                if id(asset) in self._expanded_asset_overrides:
                    for label, base_getter, attr, lo, hi in self._asset_override_fields(config):
                        rows.append(("asset_override_stepper", asset, label, base_getter, attr, lo, hi))
        else:
            rows.append(("assets_empty",))
        rows.append(("presets_header",))
        rows.append(("preset_save_row",))
        presets = list_storm_presets()
        if presets:
            for name in presets:
                rows.append(("preset_row", name))
        else:
            rows.append(("presets_empty",))
        return rows

    def _compute_layout(self):
        """(row, layout) pairs -- layout is a single Rect for a toggle-
        style row, a (rect, rect) pair for the mode switch, a Slider for
        a numeric field ("stepper" rows -- kept that internal row-kind
        name even though the widget itself changed, so nothing else about
        the row model needed touching), or (rect, Slider) for an asset row
        (its own enable-toggle rect + weight slider). Nothing here is
        cached: a fresh Slider/Rect is built from self.x/self.y on every
        single call (contains/handle_event/render/the height property
        each call this once per event or frame) -- more object churn than
        caching would need, but at ~25 rows of plain Rect/Slider
        construction that's negligible, and it's what lets move() stay a
        two-line x/y-only update instead of having to know how to shift
        every field's own cached rect (RoomPanelUI/GeneratorPanelUI's
        older, more error-prone shape)."""
        x, y = self.x, self.y + self.TITLE_HEIGHT
        layout = []
        for row in self._rows():
            kind = row[0]
            if kind in (
                "enabled", "clockwise", "assets_header", "assets_empty",
                "mode_section_toggle", "global_section_toggle", "background",
                "presets_header", "presets_empty",
            ):
                layout.append((row, pygame.Rect(x, y, self.PANEL_WIDTH, self.ROW_HEIGHT)))
                y += self.ROW_HEIGHT + self.ROW_GAP
            elif kind == "mode":
                half = (self.PANEL_WIDTH - 4) // 2
                rect_a = pygame.Rect(x, y, half, self.ROW_HEIGHT)
                rect_b = pygame.Rect(x + half + 4, y, half, self.ROW_HEIGHT)
                layout.append((row, (rect_a, rect_b)))
                y += self.ROW_HEIGHT + self.SECTION_GAP
            elif kind == "stepper":
                _label, _getter, _attr, minimum, maximum = row[1:]
                slider_width = self.PANEL_WIDTH - self.LABEL_WIDTH
                slider = Slider(
                    x + self.LABEL_WIDTH, y + (self.ROW_HEIGHT - self.SLIDER_HEIGHT) // 2,
                    slider_width, self.SLIDER_HEIGHT, minimum, maximum,
                )
                layout.append((row, slider))
                y += self.ROW_HEIGHT + self.ROW_GAP
            elif kind == "asset":
                toggle_rect = pygame.Rect(x, y, self.PANEL_WIDTH - 96, self.ROW_HEIGHT)
                weight_slider = Slider(
                    x + self.PANEL_WIDTH - 90, y + (self.ROW_HEIGHT - self.SLIDER_HEIGHT) // 2,
                    90, self.SLIDER_HEIGHT, 0, 10,
                )
                layout.append((row, (toggle_rect, weight_slider)))
                y += self.ROW_HEIGHT + self.ROW_GAP
            elif kind == "asset_rotation":
                asset = row[1]
                toggle_rect = pygame.Rect(x + 16, y, self.PANEL_WIDTH - 106, self.ROW_HEIGHT)
                # Only exists (and is only drawn/clickable) while the asset
                # actually faces its own motion -- a fixed angle offset is
                # meaningless for a free-spinning/static-tilt asset, same
                # "hide what doesn't currently apply" spirit as the mode-
                # specific fields above.
                angle_slider = None
                if asset.face_motion:
                    angle_slider = Slider(
                        x + self.PANEL_WIDTH - 90, y + (self.ROW_HEIGHT - self.SLIDER_HEIGHT) // 2,
                        90, self.SLIDER_HEIGHT, 0, 359,
                    )
                layout.append((row, (toggle_rect, angle_slider)))
                y += self.ROW_HEIGHT + self.ROW_GAP
            elif kind == "asset_overrides_toggle":
                rect = pygame.Rect(x + 16, y, self.PANEL_WIDTH - 16, self.ROW_HEIGHT)
                layout.append((row, rect))
                y += self.ROW_HEIGHT + self.ROW_GAP
            elif kind == "asset_override_stepper":
                _asset, _label, _base_getter, _attr, minimum, maximum = row[1:]
                slider_width = self.PANEL_WIDTH - self.LABEL_WIDTH - 16
                slider = Slider(
                    x + 16 + self.LABEL_WIDTH, y + (self.ROW_HEIGHT - self.SLIDER_HEIGHT) // 2,
                    slider_width, self.SLIDER_HEIGHT, minimum, maximum,
                )
                layout.append((row, slider))
                y += self.ROW_HEIGHT + self.ROW_GAP
            elif kind == "preset_save_row":
                self._preset_name_box.rect.topleft = (x, y)
                self._preset_name_box.rect.size = (self.PANEL_WIDTH - 96, self.ROW_HEIGHT)
                save_rect = pygame.Rect(x + self.PANEL_WIDTH - 90, y, 90, self.ROW_HEIGHT)
                layout.append((row, (self._preset_name_box.rect, save_rect)))
                y += self.ROW_HEIGHT + self.ROW_GAP
            elif kind == "preset_row":
                load_rect = pygame.Rect(x, y, self.PANEL_WIDTH - 30, self.ROW_HEIGHT)
                delete_rect = pygame.Rect(x + self.PANEL_WIDTH - 26, y, 26, self.ROW_HEIGHT)
                layout.append((row, (load_rect, delete_rect)))
                y += self.ROW_HEIGHT + self.ROW_GAP
        self.height = (y - self.y) + 8
        return layout

    def contains(self, pos):
        self._compute_layout()  # refreshes self.height
        return pygame.Rect(self.x, self.y, self.width, self.height).collidepoint(pos)

    # -- events -----------------------------------------------------------

    def _commit(self):
        """Persists the live config to disk (see StormGenerator.
        save_current) -- called after every COMMITTED change (a click, or
        a drag's own release), never mid-drag (that would mean a disk
        write on every single MOUSEMOTION), so a session interrupted at
        any point still resumes close to where it was left, without
        spamming the filesystem while a slider is actively being
        dragged."""
        self.storm.save_current()

    def handle_event(self, event):
        config = self.storm.config

        # A drag in progress always wins, for every event type, no
        # position-based row lookup needed -- see Slider/self._dragging_key's
        # own docstrings for why this bypasses the per-row hit-testing
        # below entirely once started.
        if self._dragging_key is not None:
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._dragging_key = None
                self._commit()
                return
            if event.type == pygame.MOUSEMOTION:
                self._apply_dragging_value(config, event.pos)
                return

        if event.type == pygame.KEYDOWN and self._preset_name_focused:
            result = self._preset_name_box.handle_event(event)
            if result is True:
                # Enter, with a non-empty value (see TextInputBox's own
                # contract) -- same action as clicking "Sauvegarder".
                saved_name = self.storm.save_preset(self._preset_name_box.value)
                self._preset_status = f"Sauvegarde : {saved_name}"
                self._preset_name_focused = False
            elif result is False:
                # Escape -- just unfocus, keeps whatever was typed rather
                # than clearing it, in case it was a near-miss typo.
                self._preset_name_focused = False
            return

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return

        # Any click outside the name box unfocuses it -- checked once, up
        # front, rather than duplicated into every other branch below.
        clicked_name_box = self._preset_name_box.rect.collidepoint(event.pos)
        if not clicked_name_box:
            self._preset_name_focused = False

        for row, layout in self._compute_layout():
            kind = row[0]
            if kind == "enabled" and layout.collidepoint(event.pos):
                config.enabled = not config.enabled
                self._commit()
                return
            if kind == "background" and layout.collidepoint(event.pos):
                self._cycle_background(config)
                self._commit()
                return
            if kind == "clockwise" and layout.collidepoint(event.pos):
                config.circular.clockwise = not config.circular.clockwise
                self._commit()
                return
            if kind == "mode_section_toggle" and layout.collidepoint(event.pos):
                self._mode_section_collapsed = not self._mode_section_collapsed
                return
            if kind == "global_section_toggle" and layout.collidepoint(event.pos):
                self._global_section_collapsed = not self._global_section_collapsed
                return
            if kind == "mode":
                rect_a, rect_b = layout
                if rect_a.collidepoint(event.pos):
                    config.mode = MODE_CIRCULAR
                    self._commit()
                    return
                if rect_b.collidepoint(event.pos):
                    config.mode = MODE_RECTILINEAR
                    self._commit()
                    return
            elif kind == "stepper":
                _label, getter, attr, _lo, _hi = row[1:]
                new_value = layout.handle_click(event.pos)
                if new_value is not None:
                    setattr(getter(config), attr, new_value)
                    self._dragging_key = ("stepper", attr)
                    return
            elif kind == "asset":
                asset = row[1]
                toggle_rect, weight_slider = layout
                if toggle_rect.collidepoint(event.pos):
                    asset.enabled = not asset.enabled
                    self._commit()
                    return
                new_weight = weight_slider.handle_click(event.pos)
                if new_weight is not None:
                    asset.weight = new_weight
                    self._dragging_key = ("asset", id(asset))
                    return
            elif kind == "asset_rotation":
                asset = row[1]
                toggle_rect, angle_slider = layout
                if toggle_rect.collidepoint(event.pos):
                    asset.face_motion = not asset.face_motion
                    self._commit()
                    return
                if angle_slider is not None:
                    new_angle = angle_slider.handle_click(event.pos)
                    if new_angle is not None:
                        asset.angle_offset = new_angle
                        self._dragging_key = ("asset_angle", id(asset))
                        return
            elif kind == "asset_overrides_toggle":
                asset = row[1]
                if layout.collidepoint(event.pos):
                    key = id(asset)
                    if key in self._expanded_asset_overrides:
                        self._expanded_asset_overrides.discard(key)
                    else:
                        self._expanded_asset_overrides.add(key)
                    return
            elif kind == "asset_override_stepper":
                asset, _label, base_getter, attr, _lo, _hi = row[1:]
                target = _AssetOverrideProxy(asset, base_getter(config))
                new_value = layout.handle_click(event.pos)
                if new_value is not None:
                    setattr(target, attr, new_value)
                    self._dragging_key = ("asset_override_stepper", (id(asset), attr))
                    return
            elif kind == "preset_save_row":
                name_rect, save_rect = layout
                if name_rect.collidepoint(event.pos):
                    self._preset_name_focused = True
                    return
                if save_rect.collidepoint(event.pos) and self._preset_name_box.value.strip():
                    saved_name = self.storm.save_preset(self._preset_name_box.value)
                    self._preset_status = f"Sauvegarde : {saved_name}"
                    return
            elif kind == "preset_row":
                name = row[1]
                load_rect, delete_rect = layout
                if delete_rect.collidepoint(event.pos):
                    self.storm.delete_preset(name)
                    self._preset_status = f"Supprime : {name}"
                    return
                if load_rect.collidepoint(event.pos):
                    if self.storm.load_preset(name):
                        self._preset_status = f"Charge : {name}"
                        self._commit()
                    return

    def _cycle_background(self, config):
        """Click-to-cycle through every PNG under assets/storm/background/
        plus "none" -- a plain list-index rotation rather than a
        dedicated picker widget, same shape as the existing Sens/Mode
        toggle rows (StormPanelUI has no scrollable-list widget of its
        own to reach for here, and the background pool is expected to
        stay small)."""
        options = [None] + list_storm_backgrounds()
        try:
            index = options.index(config.background_path)
        except ValueError:
            index = 0
        config.background_path = options[(index + 1) % len(options)]

    def _apply_dragging_value(self, config, pos):
        """Routes an in-progress drag's MOUSEMOTION straight to whichever
        field self._dragging_key names, re-finding its freshly-built
        Slider this call rather than reusing a stale one from whenever the
        drag started (self.x/self.y -- and therefore every rect -- could
        have changed if the panel itself moved mid-drag, though nothing
        currently lets that happen at the same time)."""
        kind, identity = self._dragging_key
        for row, layout in self._compute_layout():
            if kind == "stepper" and row[0] == "stepper" and row[3] == identity:
                getter, attr = row[2], row[3]
                setattr(getter(config), attr, layout.handle_drag(pos))
                return
            if kind == "asset" and row[0] == "asset" and id(row[1]) == identity:
                _toggle_rect, weight_slider = layout
                row[1].weight = weight_slider.handle_drag(pos)
                return
            if kind == "asset_angle" and row[0] == "asset_rotation" and id(row[1]) == identity:
                _toggle_rect, angle_slider = layout
                if angle_slider is not None:
                    row[1].angle_offset = angle_slider.handle_drag(pos)
                return
            if kind == "asset_override_stepper" and row[0] == "asset_override_stepper":
                asset, _label, base_getter, attr = row[1], row[2], row[3], row[4]
                if (id(asset), attr) == identity:
                    target = _AssetOverrideProxy(asset, base_getter(config))
                    setattr(target, attr, layout.handle_drag(pos))
                    return

    # -- render -------------------------------------------------------------

    def render(self, screen):
        config = self.storm.config

        title = self.title_font.render("Generateur de tempete", True, (255, 255, 255))
        screen.blit(title, (self.x, self.y))

        total_weight = sum(a.weight for a in config.assets if a.enabled) or 1

        for row, layout in self._compute_layout():
            kind = row[0]
            if kind == "enabled":
                color = (140, 255, 160) if config.enabled else (255, 140, 140)
                self.border.draw_centered_label(screen, layout, self.font, f"Effet : {'ON' if config.enabled else 'OFF'}", color)
            elif kind == "mode":
                rect_a, rect_b = layout
                circular_color = (255, 220, 120) if config.mode == MODE_CIRCULAR else (255, 255, 255)
                rectilinear_color = (255, 220, 120) if config.mode == MODE_RECTILINEAR else (255, 255, 255)
                self.border.draw_centered_label(screen, rect_a, self.font, "Circulaire", circular_color)
                self.border.draw_centered_label(screen, rect_b, self.font, "Rectiligne", rectilinear_color)
            elif kind == "clockwise":
                label = "Sens : Horaire" if config.circular.clockwise else "Sens : Antihoraire"
                self.border.draw_centered_label(screen, layout, self.font, label)
            elif kind == "mode_section_toggle":
                arrow = "v" if not self._mode_section_collapsed else ">"
                mode_label = "Circulaire" if config.mode == MODE_CIRCULAR else "Rectiligne"
                self.border.draw_centered_label(screen, layout, self.font, f"Reglages fins ({mode_label}) {arrow}")
            elif kind == "global_section_toggle":
                arrow = "v" if not self._global_section_collapsed else ">"
                self.border.draw_centered_label(screen, layout, self.font, f"Reglages globaux {arrow}")
            elif kind == "background":
                name = config.background_path.rsplit("/", 1)[-1] if config.background_path else "Aucun"
                self.border.draw_centered_label(screen, layout, self.font, f"Fond : {name}")
            elif kind == "stepper":
                label, getter, attr, _lo, _hi = row[1:]
                value = int(round(getattr(getter(config), attr)))
                label_surface = self.label_font.render(f"{label}: {value}", True, (220, 220, 220))
                screen.blit(label_surface, (self.x, layout.track_rect.centery - label_surface.get_height() / 2))
                layout.render(screen, value)
            elif kind == "assets_header":
                label_surface = self.label_font.render("Assets (assets/storm/img/)", True, (180, 200, 255))
                screen.blit(label_surface, (self.x, layout.y + 2))
            elif kind == "assets_empty":
                label_surface = self.label_font.render("Aucune image dans assets/storm/img/", True, (220, 160, 120))
                screen.blit(label_surface, (self.x, layout.y + 2))
            elif kind == "asset":
                asset = row[1]
                toggle_rect, weight_slider = layout
                percent = round(100 * asset.weight / total_weight) if asset.enabled else 0
                name = asset.path.rsplit("/", 1)[-1]
                check = "[x] " if asset.enabled else "[ ] "
                color = (255, 255, 255) if asset.enabled else (140, 140, 140)
                label_surface = self.label_font.render(f"{check}{name} ({percent}%)", True, color)
                screen.blit(label_surface, (toggle_rect.x, toggle_rect.centery - label_surface.get_height() / 2))
                weight_slider.render(screen, asset.weight)
            elif kind == "asset_rotation":
                asset = row[1]
                toggle_rect, angle_slider = layout
                check = "[x] " if asset.face_motion else "[ ] "
                text = f"{check}Face au mouvement"
                if angle_slider is not None:
                    text += f" ({asset.angle_offset} deg)"
                label_surface = self.label_font.render(text, True, (190, 190, 200))
                screen.blit(label_surface, (toggle_rect.x, toggle_rect.centery - label_surface.get_height() / 2))
                if angle_slider is not None:
                    angle_slider.render(screen, asset.angle_offset)
            elif kind == "asset_overrides_toggle":
                asset = row[1]
                expanded = id(asset) in self._expanded_asset_overrides
                arrow = "v" if expanded else ">"
                override_count = len(asset.overrides)
                suffix = f" ({override_count})" if override_count else ""
                self.border.draw_centered_label(screen, layout, self.font, f"Reglages individuels{suffix} {arrow}")
            elif kind == "asset_override_stepper":
                asset, label, base_getter, attr, _lo, _hi = row[1:]
                target = _AssetOverrideProxy(asset, base_getter(config))
                value = int(round(getattr(target, attr)))
                overridden = attr in asset.overrides
                color = (255, 220, 140) if overridden else (170, 170, 180)
                label_surface = self.label_font.render(f"{label}: {value}", True, color)
                screen.blit(label_surface, (self.x + 16, layout.track_rect.centery - label_surface.get_height() / 2))
                layout.render(screen, value)
            elif kind == "presets_header":
                label_surface = self.label_font.render("Presets", True, (180, 200, 255))
                screen.blit(label_surface, (self.x, layout.y + 2))
                if self._preset_status:
                    status_surface = self.label_font.render(self._preset_status, True, (160, 220, 160))
                    screen.blit(status_surface, (self.x + 100, layout.y + 2))
            elif kind == "presets_empty":
                label_surface = self.label_font.render("Aucun preset enregistre", True, (160, 160, 170))
                screen.blit(label_surface, (self.x, layout.y + 2))
            elif kind == "preset_save_row":
                _name_rect, save_rect = layout
                self._preset_name_box.render(screen)
                self.border.draw_centered_label(screen, save_rect, self.font, "Sauvegarder")
            elif kind == "preset_row":
                name = row[1]
                load_rect, delete_rect = layout
                label_surface = self.label_font.render(name, True, (220, 220, 230))
                screen.blit(label_surface, (load_rect.x + 6, load_rect.centery - label_surface.get_height() / 2))
                self.border.draw_centered_label(screen, delete_rect, self.font, "x", (255, 150, 150))
