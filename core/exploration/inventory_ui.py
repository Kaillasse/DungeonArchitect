"""InventoryPanel: the "E" overlay drawn on top of Explorator while the world
is paused. Not in core/ui/widgets.py -- that file is reserved for widgets
actually shared across game states (BorderManager/RoomBrowser/BorderPicker);
this panel is Explorator-only, same separation as core/editor/ui.py for
Creator's own panels -- it lives in core/exploration/ alongside explorator.py
and player_session.py instead."""

from __future__ import annotations

import pygame

from core.ui.widgets import BorderManager
from core.ui.fonts import get_font
from core.world.object_manager import CURRENCY_FILES, load_currency_frames


class InventoryPanel:
    PANEL_WIDTH = 640
    PANEL_HEIGHT = 600

    SLOT_SIZE = 56
    SLOT_GAP = 8

    PREVIEW_SCALE = 4
    ANIMATION_SPEED = 0.15

    OVERLAY_ALPHA = 150

    MAIN_SLOT_LABELS = (("attack", "Attaque"), ("interact", "Interaction"), ("passive", "Passif"))

    def __init__(self, inventory):
        self.inventory = inventory
        self.border = BorderManager()
        self.label_font = get_font("text", 16)
        self.count_font = get_font("text", 20)

        # Own animation timers -- deliberately never touch the real Player's
        # .frame/.animation_timer, so opening/closing the panel repeatedly
        # can't perturb the player's actual in-world animation state.
        self._preview_frame = 0
        self._preview_timer = 0.0

        self._currency_frames = {key: load_currency_frames(key) for key in CURRENCY_FILES}
        self._currency_frame_index = 0
        self._currency_timer = 0.0

    def update(self, dt):
        self._preview_timer += dt
        if self._preview_timer >= self.ANIMATION_SPEED:
            self._preview_timer = 0
            self._preview_frame += 1

        self._currency_timer += dt
        if self._currency_timer >= self.ANIMATION_SPEED:
            self._currency_timer = 0
            self._currency_frame_index += 1

    # ------------------------------------------------------------------

    def _panel_rect(self, screen, region=None):
        """region=None centers on the whole screen (solo case, pixel-identical
        to before Phase 2's local co-op); region=(left, width) centers within
        that horizontal slice instead -- used when more than one session has
        its panel open at once (see Explorator.render)."""
        if region is None:
            center_x = screen.get_width() / 2
        else:
            left, width = region
            center_x = left + width / 2
        return pygame.Rect(
            center_x - self.PANEL_WIDTH / 2,
            screen.get_height() / 2 - self.PANEL_HEIGHT / 2,
            self.PANEL_WIDTH, self.PANEL_HEIGHT,
        )

    def _draw_slot(self, screen, rect, item):
        self.border.draw(screen, rect)
        if item is not None:
            icon = pygame.transform.scale(item.get_icon(), (rect.width - 12, rect.height - 12))
            screen.blit(icon, (rect.centerx - icon.get_width() / 2, rect.centery - icon.get_height() / 2))
            # A stacked grid_slots entry (see core.world.inventory.CardStub)
            # carries a count > 1 -- a plain main_slots Item never does
            # (getattr default covers it), so this is silently a no-op there.
            count = getattr(item, "count", 1)
            if count > 1:
                count_text = self.label_font.render(str(count), True, (255, 255, 255))
                screen.blit(count_text, (rect.right - count_text.get_width() - 4, rect.bottom - count_text.get_height() - 2))

    def render(self, screen, player, region=None):
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, self.OVERLAY_ALPHA))
        screen.blit(overlay, (0, 0))

        panel_rect = self._panel_rect(screen, region)
        self.border.draw(screen, panel_rect)

        self._render_player_preview(screen, panel_rect, player)
        self._render_main_slots(screen, panel_rect)
        self._render_currency(screen, panel_rect)
        self._render_grid_slots(screen, panel_rect)
        self._render_settings_button(screen, panel_rect)

    SETTINGS_BUTTON_SIZE = (130, 34)

    def _settings_button_rect(self, panel_rect):
        width, height = self.SETTINGS_BUTTON_SIZE
        return pygame.Rect(panel_rect.right - width - 14, panel_rect.bottom - height - 14, width, height)

    def _render_settings_button(self, screen, panel_rect):
        self.border.draw_centered_label(screen, self._settings_button_rect(panel_rect), self.label_font, "Parametres")

    def handle_click(self, screen, pos, region=None):
        """True if `pos` hit the Parametres button -- the only clickable
        thing this otherwise purely-decorative overlay has (see this
        module's own docstring: no drag/drop exists here yet). Recomputes
        panel_rect itself from the same (screen, region) render() was just
        given, rather than making every caller keep its own copy of that
        rect around just for this one hit-test."""
        return self._settings_button_rect(self._panel_rect(screen, region)).collidepoint(pos)

    def _render_player_preview(self, screen, panel_rect, player):
        frames = player.sprites.get("idle", {}).get("front")
        if not frames:
            return
        frame = frames[self._preview_frame % len(frames)]
        scaled = pygame.transform.scale_by(frame, self.PREVIEW_SCALE)

        area_center_x = panel_rect.x + 150
        area_center_y = panel_rect.centery
        screen.blit(scaled, (area_center_x - scaled.get_width() / 2, area_center_y - scaled.get_height() / 2))

    def _main_slot_rect(self, panel_rect, index):
        x = panel_rect.x + 320
        y = panel_rect.y + 40 + index * (self.SLOT_SIZE + 34)
        return pygame.Rect(x, y, self.SLOT_SIZE, self.SLOT_SIZE)

    def _render_main_slots(self, screen, panel_rect):
        for index, (slot_key, label) in enumerate(self.MAIN_SLOT_LABELS):
            rect = self._main_slot_rect(panel_rect, index)
            text = self.label_font.render(label, True, (220, 220, 220))
            screen.blit(text, (rect.x, rect.y - text.get_height() - 2))
            self._draw_slot(screen, rect, self.inventory.main_slots.get(slot_key))

    def _render_currency(self, screen, panel_rect):
        first_slot = self._main_slot_rect(panel_rect, len(self.MAIN_SLOT_LABELS) - 1)
        y = first_slot.bottom + 24
        x = panel_rect.x + 320

        for key in ("gold", "blue"):
            frames = self._currency_frames[key]["spin"]
            icon = frames[self._currency_frame_index % len(frames)]
            scaled_icon = pygame.transform.scale(icon, (28, 28))
            screen.blit(scaled_icon, (x, y))

            count_text = self.count_font.render(str(self.inventory.currency[key]), True, (255, 255, 255))
            screen.blit(count_text, (x + 34, y + 2))

            x += 90

    def _grid_slot_rect(self, panel_rect, row, col):
        grid_width = self.inventory.GRID_COLS * (self.SLOT_SIZE + self.SLOT_GAP) - self.SLOT_GAP
        start_x = panel_rect.centerx - grid_width / 2
        start_y = panel_rect.y + 360

        return pygame.Rect(
            start_x + col * (self.SLOT_SIZE + self.SLOT_GAP),
            start_y + row * (self.SLOT_SIZE + self.SLOT_GAP),
            self.SLOT_SIZE, self.SLOT_SIZE,
        )

    def _render_grid_slots(self, screen, panel_rect):
        for row in range(self.inventory.GRID_ROWS):
            for col in range(self.inventory.GRID_COLS):
                index = row * self.inventory.GRID_COLS + col
                rect = self._grid_slot_rect(panel_rect, row, col)
                self._draw_slot(screen, rect, self.inventory.grid_slots[index])
