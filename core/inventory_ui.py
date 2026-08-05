"""InventoryPanel: the "E" overlay drawn on top of Explorator while the world
is paused. Not in core/ui.py -- that file is reserved for widgets actually
shared across game states (BorderManager/RoomBrowser/BorderPicker); this
panel is Explorator-only, same separation as core/editor/ui.py for Creator's
own panels."""

from __future__ import annotations

import pygame

from core.ui import BorderManager
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
        self.label_font = pygame.font.SysFont("arial", 16)
        self.count_font = pygame.font.SysFont("arial", 20)

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

    def _panel_rect(self, screen):
        return pygame.Rect(
            screen.get_width() / 2 - self.PANEL_WIDTH / 2,
            screen.get_height() / 2 - self.PANEL_HEIGHT / 2,
            self.PANEL_WIDTH, self.PANEL_HEIGHT,
        )

    def _draw_slot(self, screen, rect, item):
        self.border.draw(screen, rect)
        if item is not None:
            icon = pygame.transform.scale(item.get_icon(), (rect.width - 12, rect.height - 12))
            screen.blit(icon, (rect.centerx - icon.get_width() / 2, rect.centery - icon.get_height() / 2))

    def render(self, screen, player):
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, self.OVERLAY_ALPHA))
        screen.blit(overlay, (0, 0))

        panel_rect = self._panel_rect(screen)
        self.border.draw(screen, panel_rect)

        self._render_player_preview(screen, panel_rect, player)
        self._render_main_slots(screen, panel_rect)
        self._render_currency(screen, panel_rect)
        self._render_grid_slots(screen, panel_rect)

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
            frames = self._currency_frames[key]
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
