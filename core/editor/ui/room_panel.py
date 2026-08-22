"""RoomPanelUI -- split out of the old monolithic core/editor/ui.py."""

import pygame

from core.ui.widgets import BorderManager, RoomBrowser
from core.ui.fonts import get_font
from core.data.ressources import list_donjons


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

    def __init__(self, room_manager, x=460, y=10, on_rename=None, on_delete=None, can_rename=None):

        self.room_manager = room_manager
        self.x = x
        self.y = y

        self.border = BorderManager()
        self.font = get_font("button", 16)

        self.mode = None

        self.width = self.BUTTON_WIDTH * len(self.LABELS_ACTIONS)
        self.browser = RoomBrowser(
            x, y + self.BUTTON_HEIGHT + 8, width=self.width,
            on_rename=on_rename, on_delete=on_delete, can_rename=can_rename,
        )
        self.confirm_rect = pygame.Rect(x, self.browser.y + self.browser.height + 8, self.width, 32)

    @property
    def height(self):
        """Dynamic, unlike every other docked panel's fixed self.height --
        this one's real footprint depends on self.mode: just the button
        row when no browser is open, extended down through the browser +
        Valider button once one is (see _open/render). A plain attribute
        would go stale the moment mode changes; PanelFrame (title_rect/
        body_rect, its own open/close animation's endpoints) always wants
        whatever's true RIGHT NOW, so this is computed on every read
        instead of cached."""
        if self.mode is None:
            return self.BUTTON_HEIGHT
        return self.confirm_rect.bottom - self.y

    def move(self, dx, dy):
        """See PanelFrame, which drives this via drag/restore. self.browser
        recomputes its own child rects from browser.x/browser.y on demand
        (RoomBrowser, unlike Stepper, never caches an absolute rect), so a
        plain reassignment is enough there; confirm_rect is a plain cached
        Rect and needs its own move_ip."""
        self.x += dx
        self.y += dy
        self.browser.x += dx
        self.browser.y += dy
        self.confirm_rect.move_ip(dx, dy)

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

    def refresh_rooms(self):
        """Call after a room's name changed/disappeared on disk (a rename
        or delete via the browser's own right-click menu -- see
        Creator._rename_room/_delete_room) so a currently-open list
        reflects it immediately instead of showing a stale name until
        Sauvegarder/Charger/Supprimer is clicked again. A no-op while no
        mode is open (self.browser isn't showing anything to refresh)."""
        if self.mode is not None:
            self._open(self.mode)

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
# Card rendering (Vision produit v0.05 -- visual card collection).
# Composites a Card's sprite/name/type/effects onto the shared 64x96
# assets/cards/card.png backing -- see CardPanelUI, the only caller.
# ---------------------------------------------------------------------
