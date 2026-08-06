"""UI helpers for the dungeon editor."""

from __future__ import annotations

import pygame

from core.ui.widgets import BorderManager, RoomBrowser, Stepper
from core.world.object_manager import OBJECT_LIST, load_object_frames, CURRENCY_FILES, ITEM_DEFINITIONS
from core.data.ressources import list_donjons

# ---------------------------------------------------------------------
# Tool palette
# ---------------------------------------------------------------------


class ToolPaletteUI:

    def __init__(self, width: int = 220, height: int = 132):

        self.width = width
        self.height = height

        self.x = 10
        self.y = 10

        self.font = pygame.font.SysFont("arial", 18)
        self.title_font = pygame.font.SysFont("arial", 20)

        self.border = BorderManager()

    # -------------------------------------------------------------

    def _tool_rect(self):
        return pygame.Rect(self.x + 12, self.y + 40, self.width - 24, 30)

    def _autotile_rect(self):
        return pygame.Rect(self.x + 12, self.y + 74, self.width - 24, 28)

    # -------------------------------------------------------------

    def render(self, screen, autotile_enabled=True):

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

        tool_rect = self._tool_rect()
        self.border.draw(screen, tool_rect)

        screen.blit(
            self.font.render("Sol", True, (255, 255, 255)),
            (tool_rect.x + 12, tool_rect.y + 5),
        )

        autotile_rect = self._autotile_rect()
        self.border.draw(screen, autotile_rect)

        screen.blit(
            self.font.render(
                f"Autotile : {'ON' if autotile_enabled else 'OFF'}",
                True,
                (255, 255, 255) if autotile_enabled else (200, 140, 60),
            ),
            (autotile_rect.x + 10, autotile_rect.y + 4),
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

    def hit_autotile_toggle(self, position: tuple[int, int]) -> bool:
        return self._autotile_rect().collidepoint(position)

    def handle_click(self, position: tuple[int, int]) -> bool:

        x, y = position

        return (
            self.x <= x <= self.x + self.width
            and self.y <= y <= self.y + self.height
        )

class ObjectPalette:

    COLUMNS = 5

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

        origin_x = self.x + 10
        origin_y = self.y + 30
        step = self.icon_size + self.spacing

        for index, obj_type in enumerate(OBJECT_LIST):

            frames = load_object_frames(obj_type)

            column = index % self.COLUMNS
            row = index // self.COLUMNS

            self.icons[obj_type] = {

                "frames": frames,
                "frame": 0,
                "timer": 0,

                "rect": pygame.Rect(
                    origin_x + column * step,
                    origin_y + row * step,
                    32,
                    32,
                )

            }

        rows = -(-len(OBJECT_LIST) // self.COLUMNS)  # ceil division
        self.height = 30 + rows * step + 10



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


# ---------------------------------------------------------------------
# Room panel (save / load / delete)
# ---------------------------------------------------------------------


class RoomPanelUI:
    """3-button save/load/delete panel; each opens a RoomBrowser sub-panel with a Valider button."""

    NEW_ROOM_LABEL = "+ Nouvelle salle"

    BUTTON_WIDTH = 100
    BUTTON_HEIGHT = 36
    LABELS_ACTIONS = (
        ("Sauvegarder", "save"),
        ("Charger", "load"),
        ("Supprimer", "delete"),
    )

    def __init__(self, room_manager, x=460, y=10):

        self.room_manager = room_manager
        self.x = x
        self.y = y

        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 16)

        self.mode = None

        panel_width = self.BUTTON_WIDTH * len(self.LABELS_ACTIONS)
        self.browser = RoomBrowser(x, y + self.BUTTON_HEIGHT + 8, width=panel_width)
        self.confirm_rect = pygame.Rect(x, self.browser.y + self.browser.height + 8, panel_width, 32)

    def _button_rect(self, index):
        return pygame.Rect(self.x + index * self.BUTTON_WIDTH, self.y, self.BUTTON_WIDTH, self.BUTTON_HEIGHT)

    def _open(self, mode):
        self.mode = mode

        if mode == "load":
            entries = [(f"[Salle] {name}", ("room", name)) for name in self.room_manager.scan()]
            entries += [(f"[Donjon] {name}", ("donjon", name)) for name in list_donjons()]
            self.browser.set_rooms(entries)
            return

        rooms = self.room_manager.scan()
        if mode == "save":
            rooms = [self.NEW_ROOM_LABEL] + rooms
        self.browser.set_rooms(rooms)

    def contains(self, pos):

        for index in range(len(self.LABELS_ACTIONS)):
            if self._button_rect(index).collidepoint(pos):
                return True

        if self.mode is None:
            return False

        return self.browser.contains(pos) or self.confirm_rect.collidepoint(pos)

    def handle_event(self, event):
        """Returns (mode, room_name) once the user confirms a selection, else None."""

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:

            for index, (_, action) in enumerate(self.LABELS_ACTIONS):
                if self._button_rect(index).collidepoint(event.pos):
                    self._open(action)
                    return None

            if (
                self.mode is not None
                and self.confirm_rect.collidepoint(event.pos)
                and self.browser.selected_name is not None
            ):
                name = self.browser.selected_name

                if name == self.NEW_ROOM_LABEL:
                    name = self.room_manager.next_new_room_name()

                mode = self.mode
                self.mode = None

                return (mode, name)

        if self.mode is not None:
            self.browser.handle_event(event)

        return None

    def render(self, screen):

        for index, (label, _) in enumerate(self.LABELS_ACTIONS):
            self.border.draw_centered_label(screen, self._button_rect(index), self.font, label)

        if self.mode is None:
            return

        self.browser.render(screen)

        enabled = self.browser.selected_name is not None
        self.border.draw_enabled_label(screen, self.confirm_rect, self.font, "Valider", enabled)


# ---------------------------------------------------------------------
# Generator panel (procedural assembler)
# ---------------------------------------------------------------------


class GeneratorPanelUI:
    """Procedural assembler settings: which rooms to draw from, how many to assemble, and a Generer button."""

    STEP_BUTTON_SIZE = 32
    COUNT_DISPLAY_WIDTH = 60
    PANEL_WIDTH = 240
    MIN_COUNT = 1
    MAX_COUNT = 20

    def __init__(self, room_manager, x=460, y=260):

        self.room_manager = room_manager
        self.x = x
        self.y = y

        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 16)
        self.title_font = pygame.font.SysFont("arial", 18)

        self.room_count = 3

        self.pool_browser = RoomBrowser(x, y + 26, width=self.PANEL_WIDTH, multi_select=True)
        self.pool_browser.set_rooms(self.room_manager.scan(), preselect_all=True)

        stepper_y = self.pool_browser.y + self.pool_browser.height + 10
        self.stepper = Stepper(x, stepper_y, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, self.MIN_COUNT, self.MAX_COUNT)

        self.generate_rect = pygame.Rect(x, stepper_y + self.STEP_BUTTON_SIZE + 10, self.PANEL_WIDTH, 36)

        self.status_text = ""

    def refresh_rooms(self):
        """Call when the room list on disk may have changed (e.g. after a save/delete)."""
        previously_selected = set(self.pool_browser.selected_names)
        self.pool_browser.set_rooms(self.room_manager.scan())
        self.pool_browser.selected_set = {
            i for i, name in enumerate(self.pool_browser.rooms) if name in previously_selected
        }

    def contains(self, pos):
        return (
            self.pool_browser.contains(pos)
            or self.stepper.contains(pos)
            or self.generate_rect.collidepoint(pos)
        )

    def handle_event(self, event):
        """Returns (room_names, room_count) once "Generer" is clicked with a non-empty pool, else None."""

        self.pool_browser.handle_event(event)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:

            new_count = self.stepper.handle_click(event.pos, self.room_count)
            if new_count is not None:
                self.room_count = new_count

            elif self.generate_rect.collidepoint(event.pos):
                room_names = self.pool_browser.selected_names
                if room_names:
                    return (room_names, self.room_count)

        return None

    def render(self, screen):

        title = self.title_font.render("Generation procedurale", True, (255, 255, 255))
        screen.blit(title, (self.x, self.y))

        self.pool_browser.render(screen)

        self.stepper.render(screen, self.border, self.font, self.room_count)

        enabled = bool(self.pool_browser.selected_names)
        self.border.draw_enabled_label(screen, self.generate_rect, self.font, "Generer", enabled)

        if self.status_text:
            status = self.font.render(self.status_text, True, (200, 200, 200))
            screen.blit(status, (self.x, self.generate_rect.bottom + 8))


# ---------------------------------------------------------------------
# Chest panel (loot editor for a placed chest, e.g. lilchest)
# ---------------------------------------------------------------------


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
        self.font = pygame.font.SysFont("arial", 16)
        self.title_font = pygame.font.SysFont("arial", 18)
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

    def _close_rect(self):
        stepper = self._row_stepper(len(self._rows()) - 1)
        return pygame.Rect(self.x, stepper.bottom + 12, self.PANEL_WIDTH, 32)

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

        self.border.draw_centered_label(screen, self._close_rect(), self.font, "Fermer")
