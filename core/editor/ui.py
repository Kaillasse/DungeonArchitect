"""UI helpers for the dungeon editor."""

from __future__ import annotations

import pygame

from core.ui import BorderManager
from core.world.object_manager import OBJECT_LIST, load_object_frames

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
