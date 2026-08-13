"""Contient toute la logique du game state Menu (ecran titre). Lives in
core/ui/ alongside widgets.py rather than core/exploration/ or
core/editor/ -- unlike Creator/Explorator it owns no world/simulation state
of its own, it's a title screen built almost entirely out of this package's
own BorderManager/RoomBrowser widgets.

Parametres used to live here (a "settings"/"settings_keys"/"settings_display"/
"settings_border"/"settings_volume" mode tree) but has been migrated to
core.ui.settings_panel.SettingsPanelUI -- a single shared instance opened
from Creator's own UI or Explorator's inventory panel instead, since Menu
itself has no real purpose once a session is already running (home is
always reachable directly, see Explorator._return_to_home)."""

from __future__ import annotations

import pygame

from core.engine.gamestate import GameState
from core.data.ressources import list_rooms, list_donjons, next_new_room_name
from core.ui.widgets import BorderManager, RoomBrowser
from core.world.home import ensure_home_room


class Menu:

    MAIN_OPTIONS = (
        ("Editeur de salle", GameState.CREATOR),
        ("Explorer", GameState.EXPLORATION),
        ("Quitter", "quit"),
    )

    NEW_ROOM_LABEL = "+ Nouvelle salle"
    NAME_MAX_LENGTH = 20

    OPTION_WIDTH = 320
    OPTION_HEIGHT = 50
    OPTION_SPACING = 16
    OPTIONS_TOP = 220

    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.screen = game_manager.screen

        self.border = BorderManager()
        self.title_font = pygame.font.SysFont("arial", 48)
        self.option_font = pygame.font.SysFont("arial", 28)
        self.small_font = pygame.font.SysFont("arial", 18)

        self.mode = "main"
        self.selected = 0

        # Forced first mode whenever no local profile identity exists yet
        # (see core.data.settings.Settings.local_player_name) -- checked at
        # the top of run() rather than here, since __init__ can run before
        # settings are fully loaded in some call sites.
        self._name_input = ""

        self.room_target_state = None
        x = self.screen.get_width() / 2 - self.OPTION_WIDTH / 2
        self.room_browser = RoomBrowser(x, self.OPTIONS_TOP, width=self.OPTION_WIDTH)

        self.clock = pygame.time.Clock()

    def _option_rect(self, index):
        x = self.screen.get_width() / 2 - self.OPTION_WIDTH / 2
        y = self.OPTIONS_TOP + index * (self.OPTION_HEIGHT + self.OPTION_SPACING)
        return pygame.Rect(x, y, self.OPTION_WIDTH, self.OPTION_HEIGHT)

    def _room_confirm_rect(self):
        x = self.screen.get_width() / 2 - self.OPTION_WIDTH / 2
        y = self.OPTIONS_TOP + self.room_browser.height + 12
        return pygame.Rect(x, y, self.OPTION_WIDTH, 44)

    def _room_back_rect(self):
        confirm = self._room_confirm_rect()
        return pygame.Rect(confirm.x, confirm.y + confirm.height + 12, confirm.width, 44)

    # -- "name_entry" mode: a text field row, a "Valider" row underneath --
    # same "reuse _option_rect's bounding box" trick as the room-picker rows.
    def _name_field_rect(self):
        return self._option_rect(0)

    def _name_confirm_rect(self):
        return self._option_rect(1)

    def _confirm_name(self):
        """Returns True if a non-empty name was accepted (and the menu loop
        should stop showing this mode)."""
        name = self._name_input.strip()
        if not name:
            return False
        self.game_manager.settings.set_local_player_name(name)
        self.game_manager.boot_into_home = False  # consumed -- redirecting right now instead
        self._redirect_to_home()
        return True

    def _redirect_to_home(self):
        """Skips the main list entirely and sends game_manager straight
        into the player's home room, in Creator (a brand-new home has no
        floor/spawn yet -- matches the original pitch's "demarre sur le
        creator stade"). Camera zoom is left alone: both Creator's and
        Explorator's cameras already start at zoom=1.0, safely inside
        core.world.home's Creator band, so no explicit seed is needed."""
        name = ensure_home_room(self.game_manager.settings.local_player_name)
        self.game_manager.pending_room = name
        self.game_manager.state = GameState.CREATOR

    def _open_room_browser(self, target_state):
        self.mode = "rooms"
        self.room_target_state = target_state

        if target_state == GameState.EXPLORATION:
            entries = [(f"[Salle] {name}", ("room", name)) for name in list_rooms()]
            entries += [(f"[Donjon] {name}", ("donjon", name)) for name in list_donjons()]
            self.room_browser.set_rooms(entries)
            return

        rooms = [self.NEW_ROOM_LABEL] + list_rooms()
        self.room_browser.set_rooms(rooms)

    def _activate(self, action):
        """Handle a chosen main option. Returns True if the menu loop should stop."""

        if action == "quit":
            self.game_manager.running = False
            return True

        # action is a GameState (CREATOR or EXPLORATION) -- pick a room first
        self._open_room_browser(action)
        return False

    def _confirm_room(self):
        """Returns True if a room was picked and the menu loop should stop."""

        selection = self.room_browser.selected_name
        if selection is None:
            return False

        if self.room_target_state == GameState.EXPLORATION:
            self.game_manager.pending_room = selection  # ("room" | "donjon", name)
        else:
            name = selection
            if name == self.NEW_ROOM_LABEL:
                name = next_new_room_name()
            self.game_manager.pending_room = name

        self.game_manager.state = self.room_target_state
        return True

    def run(self):

        pygame.display.set_caption("DungeonArchitect - Menu")

        if not self.game_manager.settings.local_player_name:
            self.mode = "name_entry"
            self._name_input = ""
        elif self.game_manager.boot_into_home:
            self.game_manager.boot_into_home = False
            self._redirect_to_home()
            return

        running = True

        while running:

            self.clock.tick(60)

            for event in pygame.event.get():

                if event.type == pygame.QUIT:
                    self.game_manager.running = False
                    running = False

                elif event.type == pygame.KEYDOWN:

                    if event.key == pygame.K_ESCAPE:
                        if self.mode == "name_entry":
                            # No "back" to fall to without a name -- quitting
                            # is the only escape hatch, same as ESC from "main".
                            self.game_manager.running = False
                            running = False
                        elif self.mode != "main":
                            self.mode = "main"
                            self.selected = 0
                        else:
                            self.game_manager.running = False
                            running = False

                    elif self.mode == "name_entry":
                        if event.key == pygame.K_RETURN:
                            if self._confirm_name():
                                running = False
                        elif event.key == pygame.K_BACKSPACE:
                            self._name_input = self._name_input[:-1]
                        elif event.unicode and event.unicode.isprintable():
                            if len(self._name_input) < self.NAME_MAX_LENGTH:
                                self._name_input += event.unicode

                    elif self.mode == "main":

                        if event.key in (pygame.K_UP, pygame.K_z):
                            self.selected = (self.selected - 1) % len(self.MAIN_OPTIONS)

                        elif event.key in (pygame.K_DOWN, pygame.K_s):
                            self.selected = (self.selected + 1) % len(self.MAIN_OPTIONS)

                        elif event.key == pygame.K_RETURN:
                            _, action = self.MAIN_OPTIONS[self.selected]
                            if self._activate(action):
                                running = False

                    elif self.mode == "rooms" and event.key == pygame.K_RETURN:
                        if self._confirm_room():
                            running = False

                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:

                    if self.mode == "name_entry":

                        if self._name_confirm_rect().collidepoint(event.pos):
                            if self._confirm_name():
                                running = False

                    elif self.mode == "main":

                        for index, (_, action) in enumerate(self.MAIN_OPTIONS):
                            if self._option_rect(index).collidepoint(event.pos):
                                if self._activate(action):
                                    running = False
                                break

                    elif self.mode == "rooms":

                        if self.room_browser.handle_event(event):
                            pass

                        elif self._room_confirm_rect().collidepoint(event.pos):
                            if self._confirm_room():
                                running = False

                        elif self._room_back_rect().collidepoint(event.pos):
                            self.mode = "main"
                            self.selected = 0

                elif event.type == pygame.MOUSEMOTION:

                    if self.mode == "main":
                        for index in range(len(self.MAIN_OPTIONS)):
                            if self._option_rect(index).collidepoint(event.pos):
                                self.selected = index

                    elif self.mode == "rooms":
                        self.room_browser.handle_event(event)

                elif event.type == pygame.MOUSEBUTTONUP and self.mode == "rooms":
                    self.room_browser.handle_event(event)

            self._render()

    def _render(self):

        self.screen.fill((20, 20, 30))

        TITLES = {
            "name_entry": "Quel est ton nom ?",
            "rooms": "Choisir une salle",
        }
        title_text = TITLES.get(self.mode, "Dungeon Architect")

        title = self.title_font.render(title_text, True, (255, 255, 255))
        self.screen.blit(
            title,
            (self.screen.get_width() / 2 - title.get_width() / 2, 140),
        )

        if self.mode == "name_entry":

            field_rect = self._name_field_rect()
            cursor = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else ""
            field_text = (self._name_input or "") + cursor
            self.border.draw_centered_label(self.screen, field_rect, self.option_font, field_text)

            confirm_rect = self._name_confirm_rect()
            enabled = bool(self._name_input.strip())
            self.border.draw_enabled_label(self.screen, confirm_rect, self.option_font, "Valider", enabled)

        elif self.mode == "rooms":

            self.room_browser.render(self.screen)

            confirm_rect = self._room_confirm_rect()
            enabled = self.room_browser.selected_name is not None
            self.border.draw_enabled_label(self.screen, confirm_rect, self.option_font, "Valider", enabled)

            back_rect = self._room_back_rect()
            self.border.draw_centered_label(self.screen, back_rect, self.option_font, "Retour")

        else:

            for index, (label, _) in enumerate(self.MAIN_OPTIONS):

                rect = self._option_rect(index)
                is_selected = index == self.selected
                color = (255, 220, 120) if is_selected else (255, 255, 255)
                self.border.draw_centered_label(self.screen, rect, self.option_font, label, color)

        pygame.display.flip()
