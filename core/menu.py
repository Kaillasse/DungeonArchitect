"""Contient toute la logique du game state Menu (ecran titre)."""

from __future__ import annotations

import pygame

from core.engine.gamestate import GameState
from core.data.ressources import list_rooms, list_donjons, next_new_room_name
from core.ui import BorderManager, RoomBrowser


class Menu:

    MAIN_OPTIONS = (
        ("Editeur de salle", GameState.CREATOR),
        ("Explorer", GameState.EXPLORATION),
        ("Parametres", "settings"),
        ("Quitter", "quit"),
    )

    SETTINGS_OPTIONS = (
        ("Retour", "back"),
    )

    NEW_ROOM_LABEL = "+ Nouvelle salle"

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

        self.mode = "main"
        self.selected = 0

        self.room_target_state = None
        x = self.screen.get_width() / 2 - self.OPTION_WIDTH / 2
        self.room_browser = RoomBrowser(x, self.OPTIONS_TOP, width=self.OPTION_WIDTH)

        self.clock = pygame.time.Clock()

    def _options(self):
        return self.SETTINGS_OPTIONS if self.mode == "settings" else self.MAIN_OPTIONS

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
        """Handle a chosen main/settings option. Returns True if the menu loop should stop."""

        if action == "settings":
            self.mode = "settings"
            self.selected = 0
            return False

        if action == "back":
            self.mode = "main"
            self.selected = 0
            return False

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

        running = True

        while running:

            self.clock.tick(60)

            for event in pygame.event.get():

                if event.type == pygame.QUIT:
                    self.game_manager.running = False
                    running = False

                elif event.type == pygame.KEYDOWN:

                    if event.key == pygame.K_ESCAPE:
                        if self.mode != "main":
                            self.mode = "main"
                            self.selected = 0
                        else:
                            self.game_manager.running = False
                            running = False

                    elif self.mode in ("main", "settings"):

                        if event.key in (pygame.K_UP, pygame.K_z):
                            self.selected = (self.selected - 1) % len(self._options())

                        elif event.key in (pygame.K_DOWN, pygame.K_s):
                            self.selected = (self.selected + 1) % len(self._options())

                        elif event.key == pygame.K_RETURN:
                            _, action = self._options()[self.selected]
                            if self._activate(action):
                                running = False

                    elif self.mode == "rooms" and event.key == pygame.K_RETURN:
                        if self._confirm_room():
                            running = False

                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:

                    if self.mode in ("main", "settings"):

                        options = self._options()
                        for index in range(len(options)):
                            if self._option_rect(index).collidepoint(event.pos):
                                _, action = options[index]
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

                    if self.mode in ("main", "settings"):
                        options = self._options()
                        for index in range(len(options)):
                            if self._option_rect(index).collidepoint(event.pos):
                                self.selected = index

                    elif self.mode == "rooms":
                        self.room_browser.handle_event(event)

                elif event.type == pygame.MOUSEBUTTONUP and self.mode == "rooms":
                    self.room_browser.handle_event(event)

            self._render()

    def _render(self):

        self.screen.fill((20, 20, 30))

        if self.mode == "rooms":
            title_text = "Choisir une salle"
        elif self.mode == "settings":
            title_text = "Parametres"
        else:
            title_text = "Dungeon Architect"

        title = self.title_font.render(title_text, True, (255, 255, 255))
        self.screen.blit(
            title,
            (self.screen.get_width() / 2 - title.get_width() / 2, 140),
        )

        if self.mode == "settings":

            placeholder = self.option_font.render("(a venir)", True, (150, 150, 150))
            self.screen.blit(
                placeholder,
                (self.screen.get_width() / 2 - placeholder.get_width() / 2, 200),
            )

        if self.mode == "rooms":

            self.room_browser.render(self.screen)

            confirm_rect = self._room_confirm_rect()
            self.border.draw(self.screen, confirm_rect)
            enabled = self.room_browser.selected_name is not None
            color = (255, 255, 255) if enabled else (110, 110, 110)
            confirm_text = self.option_font.render("Valider", True, color)
            self.screen.blit(
                confirm_text,
                (confirm_rect.centerx - confirm_text.get_width() / 2, confirm_rect.centery - confirm_text.get_height() / 2),
            )

            back_rect = self._room_back_rect()
            self.border.draw(self.screen, back_rect)
            back_text = self.option_font.render("Retour", True, (255, 255, 255))
            self.screen.blit(
                back_text,
                (back_rect.centerx - back_text.get_width() / 2, back_rect.centery - back_text.get_height() / 2),
            )

        else:

            for index, (label, _) in enumerate(self._options()):

                rect = self._option_rect(index)
                self.border.draw(self.screen, rect)

                is_selected = index == self.selected
                color = (255, 220, 120) if is_selected else (255, 255, 255)
                text = self.option_font.render(label, True, color)

                self.screen.blit(
                    text,
                    (rect.centerx - text.get_width() / 2, rect.centery - text.get_height() / 2),
                )

        pygame.display.flip()
