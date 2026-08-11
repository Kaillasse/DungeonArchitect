"""ToolPaletteUI -- split out of the old monolithic core/editor/ui.py."""

import pygame

from core.ui.widgets import BorderManager


class ToolPaletteUI:
    """"Tuile de base" panel -- two independent toggle buttons, Sol (floor)
    and Mur (wall), each showing its own remaining card stock (see
    core.data.cards' "tile_floor"/"tile_wall" -- Vision produit v0.05's
    Card system, tools connected to the collection). Replaces the old
    "Outils" panel's purely-decorative "Sol" label plus a single separate
    Autotile ON/OFF toggle: Creator now derives autotile_enabled itself as
    floor_tool_active AND wall_tool_active (both buttons active = today's
    default full-autotile paint behavior; exactly one active = a raw,
    non-autotile Sol-only or Mur-only paint -- see
    Creator._paint_at_mouse). This class only ever reports which rect was
    clicked -- it owns neither the active/inactive state nor the stock
    numbers, both live on Creator (same "the panel doesn't own the toggled
    state" convention the old hit_autotile_toggle already followed)."""

    def __init__(self, width: int = 220, height: int = 132):

        self.width = width
        self.height = height

        self.x = 10
        self.y = 10

        self.font = pygame.font.SysFont("arial", 18)
        self.title_font = pygame.font.SysFont("arial", 20)

        self.border = BorderManager()

    # -------------------------------------------------------------

    def move(self, dx, dy):
        """Every rect here (_floor_rect/_wall_rect) is already recomputed
        from self.x/self.y on demand, so shifting the origin is enough --
        see PanelFrame, which drives this via drag/restore."""
        self.x += dx
        self.y += dy

    def _floor_rect(self):
        return pygame.Rect(self.x + 12, self.y + 40, self.width - 24, 30)

    def _wall_rect(self):
        return pygame.Rect(self.x + 12, self.y + 74, self.width - 24, 28)

    # -------------------------------------------------------------

    def render(self, screen, floor_active=True, wall_active=True, floor_stock=0, wall_stock=0):

        panel_rect = pygame.Rect(
            self.x,
            self.y,
            self.width,
            self.height,
        )

        self.border.draw(screen, panel_rect)

        screen.blit(
            self.title_font.render("Tuile de base", True, (255, 255, 255)),
            (self.x + 16, self.y + 12),
        )

        floor_rect = self._floor_rect()
        self.border.draw(screen, floor_rect)

        screen.blit(
            self.font.render(
                f"> Sol ({floor_stock})" if floor_active else f"Sol ({floor_stock})",
                True,
                (255, 255, 255) if floor_active else (200, 140, 60),
            ),
            (floor_rect.x + 12, floor_rect.y + 5),
        )

        wall_rect = self._wall_rect()
        self.border.draw(screen, wall_rect)

        screen.blit(
            self.font.render(
                f"> Mur ({wall_stock})" if wall_active else f"Mur ({wall_stock})",
                True,
                (255, 255, 255) if wall_active else (200, 140, 60),
            ),
            (wall_rect.x + 10, wall_rect.y + 4),
        )

        screen.blit(
            self.font.render(
                "Clic droit : effacer",
                True,
                (180, 180, 180),
            ),
            (self.x + 12, self.y + 108),
        )

    # -------------------------------------------------------------

    def hit_floor_toggle(self, position: tuple[int, int]) -> bool:
        return self._floor_rect().collidepoint(position)

    def hit_wall_toggle(self, position: tuple[int, int]) -> bool:
        return self._wall_rect().collidepoint(position)

    def contains(self, position: tuple[int, int]) -> bool:
        x, y = position
        return (
            self.x <= x <= self.x + self.width
            and self.y <= y <= self.y + self.height
        )

    def handle_click(self, position: tuple[int, int]) -> bool:
        # Despite the name, this has always been a pure containment check
        # (nothing here mutates state) -- kept as-is since Creator already
        # calls it; contains() above is the same check under the name
        # PanelFrame expects from every wrapped panel.
        return self.contains(position)


# ---------------------------------------------------------------------
# Room panel (save / load / delete)
# ---------------------------------------------------------------------
