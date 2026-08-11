"""Shared mixin(s) for a handful of Creator panels -- split out of the old monolithic core/editor/ui.py."""

import pygame


class _ResizableCornerMixin:
    """Shared bottom-right resize-handle drag state/hit-test, used by both
    CardPanelUI and GeneratorPanelUI -- kept out of PanelFrame (which wraps
    5 panels total, only 2 of which need resize) per the same reasoning
    CardPanelUI's own resize handle was originally kept panel-local for. A
    subclass must set self.x/self.y/self.width/self.height/self._resizing/
    self._resize_last_pos and the class constants STANDARD_WIDTH/
    STANDARD_HEIGHT/MAX_WIDTH/MAX_HEIGHT before this is used."""

    RESIZE_HANDLE_SIZE = 14

    def _resize_handle_rect(self):
        size = self.RESIZE_HANDLE_SIZE
        return pygame.Rect(self.x + self.width - size, self.y + self.height - size, size, size)

    def _handle_resize_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._resize_handle_rect().collidepoint(event.pos):
                self._resizing = True
                self._resize_last_pos = event.pos
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._resizing:
                self._resizing = False
                self._resize_last_pos = None
                return True
        elif event.type == pygame.MOUSEMOTION and self._resizing and self._resize_last_pos is not None:
            dx = event.pos[0] - self._resize_last_pos[0]
            dy = event.pos[1] - self._resize_last_pos[1]
            self.width = max(self.STANDARD_WIDTH, min(self.MAX_WIDTH, self.width + dx))
            self.height = max(self.STANDARD_HEIGHT, min(self.MAX_HEIGHT, self.height + dy))
            self._resize_last_pos = event.pos
            return True
        return False

    def _draw_resize_handle(self, screen):
        handle_rect = self._resize_handle_rect()
        pygame.draw.polygon(
            screen, (200, 200, 200),
            [(handle_rect.right, handle_rect.top), (handle_rect.right, handle_rect.bottom), (handle_rect.left, handle_rect.bottom)],
        )

# ---------------------------------------------------------------------
# Tool palette
# ---------------------------------------------------------------------
