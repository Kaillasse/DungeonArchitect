"""UI helpers for the dungeon editor."""

from __future__ import annotations

import os
import pygame

from core.world.object_manager import OBJECT_LIST, load_object_frames

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


# ---------------------------------------------------------------------
# Tool palette
# ---------------------------------------------------------------------


class ToolPaletteUI:

    def __init__(self, width: int = 220, height: int = 120):

        self.width = width
        self.height = height

        self.x = 10
        self.y = 10

        self.font = pygame.font.SysFont("arial", 18)
        self.title_font = pygame.font.SysFont("arial", 20)

        self.border = BorderManager()

    # -------------------------------------------------------------

    def render(self, screen):

        panel_rect = pygame.Rect(
            self.x,
            self.y,
            self.width,
            self.height,
        )

        self.border.draw(screen, panel_rect)

        screen.blit(
            self.title_font.render("Outils", True, (255, 255, 255)),
            (self.x + 16, self.y + 12),
        )

        tool_rect = pygame.Rect(
            self.x + 12,
            self.y + 44,
            self.width - 24,
            36,
        )

        self.border.draw(screen, tool_rect)

        screen.blit(
            self.font.render("Sol", True, (255, 255, 255)),
            (tool_rect.x + 12, tool_rect.y + 8),
        )

        screen.blit(
            self.font.render(
                "Clic droit : effacer",
                True,
                (180, 180, 180),
            ),
            (self.x + 12, self.y + 90),
        )

    # -------------------------------------------------------------

    def handle_click(self, position: tuple[int, int]) -> bool:

        x, y = position

        return (
            self.x <= x <= self.x + self.width
            and self.y <= y <= self.y + self.height
        )

class ObjectPalette:

    def __init__(self):

        self.border = BorderManager()

        self.x = 10
        self.y = 140

        self.width = 220
        self.height = 90

        self.icon_size = 32
        self.spacing = 6

        self.icons = {}

        self.load_icons()
        self.dragged_object = None

    def get_current_frame(self, object_type, animate=True):

        icon = self.icons[object_type]

        if animate:
            return icon["frames"][icon["frame"]]
        else:
            return icon["frames"][0]

    def load_icons(self):

        x = self.x + 10

        for obj_type in OBJECT_LIST:

            frames = load_object_frames(obj_type)

            self.icons[obj_type] = {

                "frames": frames,
                "frame": 0,
                "timer": 0,

                "rect": pygame.Rect(
                    x,
                    self.y + 30,
                    32,
                    32,
                )

            }

            x += self.icon_size + self.spacing
            


    def render(self, screen):

        panel = pygame.Rect(
            self.x,
            self.y,
            self.width,
            self.height,
        )

        self.border.draw(screen, panel)

        for name, icon in self.icons.items():

            if name == self.dragged_object:
                continue


            screen.blit(
                icon["frames"][icon["frame"]],
                icon["rect"]
            )

    def handle_click(self, mouse_pos):

        for name, icon in self.icons.items():

            if icon["rect"].collidepoint(mouse_pos):

                self.dragged_object = name
                return name

        return None

    def update(self, dt, mouse_pos):

        for name, icon in self.icons.items():

            hovered = icon["rect"].collidepoint(mouse_pos)


            if hovered:

                icon["timer"] += dt


            elif name == self.dragged_object:

                icon["timer"] += dt


            else:

                icon["frame"] = 0
                icon["timer"] = 0
                continue


            if icon["timer"] >= 0.12:

                icon["timer"] = 0

                icon["frame"] = (
                    icon["frame"] + 1
                ) % len(icon["frames"])
