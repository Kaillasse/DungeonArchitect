"""Contient toute la logique du game state Menu (ecran titre)."""

from __future__ import annotations

import pygame

from core.engine.gamestate import GameState
from core.ui import BorderManager


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
        self.clock = pygame.time.Clock()

    def _options(self):
        return self.SETTINGS_OPTIONS if self.mode == "settings" else self.MAIN_OPTIONS

    def _option_rect(self, index):
        x = self.screen.get_width() / 2 - self.OPTION_WIDTH / 2
        y = self.OPTIONS_TOP + index * (self.OPTION_HEIGHT + self.OPTION_SPACING)
        return pygame.Rect(x, y, self.OPTION_WIDTH, self.OPTION_HEIGHT)

    def _activate(self, action):
        """Handle a chosen option. Returns True if the menu loop should stop."""

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

        self.game_manager.state = action
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
                        if self.mode == "settings":
                            self.mode = "main"
                            self.selected = 0
                        else:
                            self.game_manager.running = False
                            running = False

                    elif event.key in (pygame.K_UP, pygame.K_z):
                        self.selected = (self.selected - 1) % len(self._options())

                    elif event.key in (pygame.K_DOWN, pygame.K_s):
                        self.selected = (self.selected + 1) % len(self._options())

                    elif event.key == pygame.K_RETURN:
                        _, action = self._options()[self.selected]
                        if self._activate(action):
                            running = False

                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:

                    options = self._options()
                    for index in range(len(options)):
                        if self._option_rect(index).collidepoint(event.pos):
                            _, action = options[index]
                            if self._activate(action):
                                running = False
                            break

                elif event.type == pygame.MOUSEMOTION:

                    options = self._options()
                    for index in range(len(options)):
                        if self._option_rect(index).collidepoint(event.pos):
                            self.selected = index

            self._render()

    def _render(self):

        self.screen.fill((20, 20, 30))

        title_text = "Parametres" if self.mode == "settings" else "Dungeon Architect"
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
