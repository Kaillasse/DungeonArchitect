"""UI helpers for the dungeon editor."""

from __future__ import annotations

import pygame

from core.ui import BorderManager, RoomBrowser
from core.world.object_manager import OBJECT_LIST, load_object_frames
from core.data.ressources import list_donjons

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

            rect = self._button_rect(index)
            self.border.draw(screen, rect)

            text = self.font.render(label, True, (255, 255, 255))
            screen.blit(text, (rect.centerx - text.get_width() / 2, rect.centery - text.get_height() / 2))

        if self.mode is None:
            return

        self.browser.render(screen)

        self.border.draw(screen, self.confirm_rect)

        enabled = self.browser.selected_name is not None
        color = (255, 255, 255) if enabled else (110, 110, 110)
        text = self.font.render("Valider", True, color)
        screen.blit(
            text,
            (self.confirm_rect.centerx - text.get_width() / 2, self.confirm_rect.centery - text.get_height() / 2),
        )


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
        self.minus_rect = pygame.Rect(x, stepper_y, self.STEP_BUTTON_SIZE, self.STEP_BUTTON_SIZE)
        self.count_rect = pygame.Rect(
            self.minus_rect.right + 4, stepper_y, self.COUNT_DISPLAY_WIDTH, self.STEP_BUTTON_SIZE
        )
        self.plus_rect = pygame.Rect(self.count_rect.right + 4, stepper_y, self.STEP_BUTTON_SIZE, self.STEP_BUTTON_SIZE)

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
            or self.minus_rect.collidepoint(pos)
            or self.plus_rect.collidepoint(pos)
            or self.generate_rect.collidepoint(pos)
        )

    def handle_event(self, event):
        """Returns (room_names, room_count) once "Generer" is clicked with a non-empty pool, else None."""

        self.pool_browser.handle_event(event)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:

            if self.minus_rect.collidepoint(event.pos):
                self.room_count = max(self.MIN_COUNT, self.room_count - 1)

            elif self.plus_rect.collidepoint(event.pos):
                self.room_count = min(self.MAX_COUNT, self.room_count + 1)

            elif self.generate_rect.collidepoint(event.pos):
                room_names = self.pool_browser.selected_names
                if room_names:
                    return (room_names, self.room_count)

        return None

    def render(self, screen):

        title = self.title_font.render("Generation procedurale", True, (255, 255, 255))
        screen.blit(title, (self.x, self.y))

        self.pool_browser.render(screen)

        self.border.draw(screen, self.minus_rect)
        minus_text = self.font.render("-", True, (255, 255, 255))
        screen.blit(
            minus_text,
            (self.minus_rect.centerx - minus_text.get_width() / 2, self.minus_rect.centery - minus_text.get_height() / 2),
        )

        self.border.draw(screen, self.count_rect)
        count_text = self.font.render(str(self.room_count), True, (255, 255, 255))
        screen.blit(
            count_text,
            (self.count_rect.centerx - count_text.get_width() / 2, self.count_rect.centery - count_text.get_height() / 2),
        )

        self.border.draw(screen, self.plus_rect)
        plus_text = self.font.render("+", True, (255, 255, 255))
        screen.blit(
            plus_text,
            (self.plus_rect.centerx - plus_text.get_width() / 2, self.plus_rect.centery - plus_text.get_height() / 2),
        )

        self.border.draw(screen, self.generate_rect)
        enabled = bool(self.pool_browser.selected_names)
        color = (255, 255, 255) if enabled else (110, 110, 110)
        gen_text = self.font.render("Generer", True, color)
        screen.blit(
            gen_text,
            (self.generate_rect.centerx - gen_text.get_width() / 2, self.generate_rect.centery - gen_text.get_height() / 2),
        )

        if self.status_text:
            status = self.font.render(self.status_text, True, (200, 200, 200))
            screen.blit(status, (self.x, self.generate_rect.bottom + 8))
