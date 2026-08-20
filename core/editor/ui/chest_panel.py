"""ChestPanelUI -- split out of the old monolithic core/editor/ui.py."""

import pygame

from core.ui.widgets import BorderManager, Stepper
from core.ui.fonts import get_font
from core.world.object_manager import CURRENCY_FILES, ITEM_DEFINITIONS


class ChestPanelUI:
    """Opened by clicking a placed chest's indicator dot (see Creator's
    indicator-click handler, which checks ObjectManager.is_chest first) --
    lets the room designer customize how much of each currency type, and how
    many of the one item type, the chest drops once opened, instead of
    always using ObjectManager.add_object's hardcoded defaults. Acts as a
    modal while open: Creator suspends every other tool/panel so painting
    can't happen "underneath" an open chest's loot editor."""

    STEP_BUTTON_SIZE = 28
    COUNT_DISPLAY_WIDTH = 50
    ROW_HEIGHT = 30
    ROW_SPACING = 10
    PANEL_WIDTH = 260
    MIN_COUNT = 0
    MAX_COUNT = 99

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.border = BorderManager()
        self.font = get_font("button", 16)
        self.title_font = get_font("title", 18)
        self.chest = None  # the placed object dict currently being edited, or None if closed

    @property
    def is_open(self):
        return self.chest is not None

    def open(self, chest_obj):
        self.chest = chest_obj

    def close(self):
        self.chest = None

    def _rows(self):
        """(label, loot_dict, key) for every adjustable row -- one per
        currency type (self.chest["loot"]), then one per existing item type
        (self.chest["item_loot"]) -- currently just dynamite, i.e. exactly
        the "1 slot d'item" this was specified with; a second item type
        later would just add a second row here for free."""
        rows = [(f"Pieces ({currency})", self.chest["loot"], currency) for currency in CURRENCY_FILES]
        rows += [
            (f"Objet ({definition['name']})", self.chest["item_loot"], item_id)
            for item_id, definition in ITEM_DEFINITIONS.items()
        ]
        return rows

    def _row_stepper(self, index):
        y = self.y + 34 + index * (self.ROW_HEIGHT + self.ROW_SPACING)
        return Stepper(self.x, y, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, self.MIN_COUNT, self.MAX_COUNT)

    def _role_rect(self):
        """Loot/Sortie-de-donjon toggle -- ObjectManager.CHEST_ROLES. A
        plain click-to-cycle row rather than the Stepper machinery the
        rows above use (only 2 states, no numeric value), so it mutates
        self.chest["role"] directly in handle_event the same way the
        stepper rows already mutate self.chest["loot"]/["item_loot"] in
        place -- both bypass ObjectManager.set_role's validation since
        this widget only ever writes one of the two valid chest role
        strings itself."""
        stepper = self._row_stepper(len(self._rows()) - 1)
        return pygame.Rect(self.x, stepper.bottom + 12, self.PANEL_WIDTH, 32)

    def _close_rect(self):
        return pygame.Rect(self.x, self._role_rect().bottom + 12, self.PANEL_WIDTH, 32)

    def contains(self, pos):
        if not self.is_open:
            return False
        panel_rect = pygame.Rect(self.x, self.y, self.PANEL_WIDTH, self._close_rect().bottom - self.y + 10)
        return panel_rect.collidepoint(pos)

    def handle_event(self, event):
        if not self.is_open or event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return

        for index, (_, loot, key) in enumerate(self._rows()):
            new_value = self._row_stepper(index).handle_click(event.pos, loot.get(key, 0))
            if new_value is not None:
                loot[key] = new_value
                return

        if self._role_rect().collidepoint(event.pos):
            self.chest["role"] = "dungeon_exit" if self.chest.get("role", "loot") == "loot" else "loot"
            return

        if self._close_rect().collidepoint(event.pos):
            self.close()

    def render(self, screen):
        if not self.is_open:
            return

        title = self.title_font.render("Contenu du coffre", True, (255, 255, 255))
        screen.blit(title, (self.x, self.y))

        for index, (label, loot, key) in enumerate(self._rows()):
            stepper = self._row_stepper(index)

            label_text = self.font.render(label, True, (220, 220, 220))
            screen.blit(label_text, (self.x, stepper.minus_rect.y - label_text.get_height() - 2))

            stepper.render(screen, self.border, self.font, loot.get(key, 0))

        role = self.chest.get("role", "loot")
        role_label = "Role : Sortie de donjon" if role == "dungeon_exit" else "Role : Loot"
        self.border.draw_centered_label(screen, self._role_rect(), self.font, role_label)

        self.border.draw_centered_label(screen, self._close_rect(), self.font, "Fermer")


# ---------------------------------------------------------------------
# Autotile theme picker (clic droit sur le bouton Sol/Mur de ToolPaletteUI)
# ---------------------------------------------------------------------
