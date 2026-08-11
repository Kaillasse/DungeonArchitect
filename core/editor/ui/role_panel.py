"""RolePanelUI -- split out of the old monolithic core/editor/ui.py."""

import pygame

from core.ui.widgets import BorderManager


class RolePanelUI:
    """Opened by right-clicking a placed E/S object's indicator dot (see
    Creator's event loop -- ObjectManager.is_es_type; left-click on the
    same dot keeps its existing meaning, either a chest's ChestPanelUI or
    gate/wall's link-drag, unchanged). Lets the room designer pick this
    object's role -- "connector" (today's default, an ordinary inter-room
    link), "dungeon_entrance" (only ever meaningful in home -- see
    ObjectManager.ES_ROLES/set_role), or "dungeon_exit" (a new win
    condition). "Entree de donjon" is greyed out unless the caller says
    the current room allows it (Creator._is_home_room()) -- the room
    restriction lives in Creator, this widget just renders whatever it's
    told. Same modal-while-open shape as ChestPanelUI."""

    ROW_HEIGHT = 34
    ROW_SPACING = 8
    PANEL_WIDTH = 260

    ROLES = (
        ("connector", "Classique"),
        ("dungeon_entrance", "Entree de donjon"),
        ("dungeon_exit", "Sortie de donjon"),
    )

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 16)
        self.title_font = pygame.font.SysFont("arial", 18)
        self.obj = None  # the placed object dict currently being edited, or None if closed
        self.allow_dungeon_entrance = False

    @property
    def is_open(self):
        return self.obj is not None

    def open(self, obj, allow_dungeon_entrance):
        self.obj = obj
        self.allow_dungeon_entrance = allow_dungeon_entrance

    def close(self):
        self.obj = None

    def _row_rect(self, index):
        y = self.y + 30 + index * (self.ROW_HEIGHT + self.ROW_SPACING)
        return pygame.Rect(self.x, y, self.PANEL_WIDTH, self.ROW_HEIGHT)

    def _close_rect(self):
        return self._row_rect(len(self.ROLES))

    def _row_enabled(self, role):
        return role != "dungeon_entrance" or self.allow_dungeon_entrance

    def contains(self, pos):
        if not self.is_open:
            return False
        panel_rect = pygame.Rect(self.x, self.y, self.PANEL_WIDTH, self._close_rect().bottom - self.y + 10)
        return panel_rect.collidepoint(pos)

    def handle_event(self, event):
        """Returns the chosen role once a row is clicked, else None -- the
        caller (Creator) applies it via ObjectManager.set_role, same
        "widget returns a value, caller applies it" shape as
        GeneratorPanelUI/RoomPanelUI."""
        if not self.is_open or event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        for index, (role, _label) in enumerate(self.ROLES):
            if self._row_enabled(role) and self._row_rect(index).collidepoint(event.pos):
                return role

        if self._close_rect().collidepoint(event.pos):
            self.close()

        return None

    def render(self, screen):
        if not self.is_open:
            return

        title = self.title_font.render("Role de l'entree/sortie", True, (255, 255, 255))
        screen.blit(title, (self.x, self.y))

        for index, (role, label) in enumerate(self.ROLES):
            rect = self._row_rect(index)
            enabled = self._row_enabled(role)
            selected = self.obj.get("role", "connector") == role
            text = f"> {label}" if selected else label
            color = (255, 220, 120) if selected else None
            if enabled:
                self.border.draw_centered_label(screen, rect, self.font, text, color or (255, 255, 255))
            else:
                self.border.draw_enabled_label(screen, rect, self.font, text, False)

        self.border.draw_centered_label(screen, self._close_rect(), self.font, "Fermer")


# ---------------------------------------------------------------------
# Chest panel (loot editor for a placed chest, e.g. lilchest)
# ---------------------------------------------------------------------
