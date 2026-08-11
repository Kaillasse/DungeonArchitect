"""AutotileThemePanelUI -- split out of the old monolithic core/editor/ui.py."""

import pygame

from core.ui.widgets import BorderManager
from core.data.ressources import list_autotile_packs, load_autotile_pack


class AutotileThemePanelUI:
    """Opened by right-clicking ToolPaletteUI's Sol or Mur button (see
    Creator's event loop) -- lists every registered autotile pack (core.
    data.ressources.list_autotile_packs) whose role matches, plus a first
    "Interieur (par defaut)" row that reverts to no theme at all
    (dungeon.floor_theme/wall_theme = None). Same modal-while-open shape as
    RolePanelUI/ChestPanelUI, except handle_event needs to distinguish "no
    click yet" from "the player explicitly chose the default (None)" --
    both would otherwise collapse to the same falsy return -- so it returns
    (changed: bool, pack_name_or_None) instead of a bare value."""

    ROW_HEIGHT = 34
    ROW_SPACING = 6
    PANEL_WIDTH = 260
    DEFAULT_LABEL = "Interieur (par defaut)"

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 16)
        self.title_font = pygame.font.SysFont("arial", 18)
        self.role = None  # "floor"/"wall", or None while closed
        self.current_theme = None
        self._pack_names = []

    @property
    def is_open(self):
        return self.role is not None

    def open(self, role, current_theme):
        self.role = role
        self.current_theme = current_theme
        self._pack_names = [
            name for name in list_autotile_packs()
            if (load_autotile_pack(name) or {}).get("role") == role
        ]

    def close(self):
        self.role = None

    def _rows(self):
        return [self.DEFAULT_LABEL] + self._pack_names

    def _row_rect(self, index):
        y = self.y + 34 + index * (self.ROW_HEIGHT + self.ROW_SPACING)
        return pygame.Rect(self.x, y, self.PANEL_WIDTH, self.ROW_HEIGHT)

    def _close_rect(self):
        return self._row_rect(len(self._rows()))

    def contains(self, pos):
        if not self.is_open:
            return False
        panel_rect = pygame.Rect(self.x, self.y, self.PANEL_WIDTH, self._close_rect().bottom - self.y + 10)
        return panel_rect.collidepoint(pos)

    def handle_event(self, event):
        """(changed, pack_name_or_None) -- changed is True only the frame a
        row/close was actually clicked; Creator applies the selection then
        (dungeon.floor_theme/wall_theme + resync_sprite_grid()), same
        "widget reports, caller applies" shape as RolePanelUI."""
        if not self.is_open or event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False, None

        rows = self._rows()
        for index, _label in enumerate(rows):
            if self._row_rect(index).collidepoint(event.pos):
                self.close()
                return True, (None if index == 0 else rows[index])

        if self._close_rect().collidepoint(event.pos):
            self.close()

        return False, None

    def render(self, screen):
        if not self.is_open:
            return

        title = "Theme de sol" if self.role == "floor" else "Theme de mur"
        title_surface = self.title_font.render(title, True, (255, 255, 255))
        screen.blit(title_surface, (self.x, self.y))

        rows = self._rows()
        for index, label in enumerate(rows):
            rect = self._row_rect(index)
            pack_name = None if index == 0 else label
            selected = pack_name == self.current_theme
            text = f"> {label}" if selected else label
            color = (255, 220, 120) if selected else (255, 255, 255)
            self.border.draw_centered_label(screen, rect, self.font, text, color)

        self.border.draw_centered_label(screen, self._close_rect(), self.font, "Fermer")


# ---------------------------------------------------------------------
# Sprite editor (fondation "carte" -- charger un fichier, decouper une
# region, l'enregistrer directement comme une nouvelle carte)
# ---------------------------------------------------------------------
