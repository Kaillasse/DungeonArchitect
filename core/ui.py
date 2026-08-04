"""Shared UI widgets used across game states (menu, editor, ...)."""

from __future__ import annotations

import os
import pygame

# ---------------------------------------------------------------------
# Border Manager
# ---------------------------------------------------------------------


class BorderManager:
    """Simple singleton used to draw 9-slice borders."""

    _instance = None

    BORDER_SIZE = 64
    CORNER_SIZE = 16

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

        self.load_border()

        self._initialized = True

    # -------------------------------------------------------------

    def load_border(self):

        if os.path.exists(self.border_asset_path):

            sheet = pygame.image.load(self.border_asset_path).convert_alpha()

            first_border = sheet.subsurface((0, 0, 64, 64)).copy()

            self.border = self._create_nine_slice(first_border)

        else:

            self.border = self._create_fallback()

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

        # Centre
        if w > c * 2 and h > c * 2:
            screen.blit(
                pygame.transform.scale(
                    b["center"],
                    (w - c * 2, h - c * 2),
                ),
                (x + c, y + c),
            )

        # Haut / bas
        if w > c * 2:
            screen.blit(
                pygame.transform.scale(b["top"], (w - c * 2, c)),
                (x + c, y),
            )

            screen.blit(
                pygame.transform.scale(b["bottom"], (w - c * 2, c)),
                (x + c, y + h - c),
            )

        # Gauche / droite
        if h > c * 2:
            screen.blit(
                pygame.transform.scale(b["left"], (c, h - c * 2)),
                (x, y + c),
            )

            screen.blit(
                pygame.transform.scale(b["right"], (c, h - c * 2)),
                (x + w - c, y + c),
            )

        # Coins
        screen.blit(b["tl"], (x, y))
        screen.blit(b["tr"], (x + w - c, y))
        screen.blit(b["bl"], (x, y + h - c))
        screen.blit(b["br"], (x + w - c, y + h - c))
