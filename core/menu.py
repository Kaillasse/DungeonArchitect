"""Contient toute la logique du game state Menu (ecran titre)."""

from __future__ import annotations

import pygame

from core.engine.gamestate import GameState


class Menu:

    OPTIONS = (
        ("Editeur de salle", GameState.CREATOR),
        ("Explorer", GameState.EXPLORATION),
    )

    OPTION_WIDTH = 320
    OPTION_HEIGHT = 50
    OPTION_SPACING = 16
    OPTIONS_TOP = 260

    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.screen = game_manager.screen

        self.title_font = pygame.font.SysFont("arial", 48)
        self.option_font = pygame.font.SysFont("arial", 28)

        self.selected = 0
        self.clock = pygame.time.Clock()

    def _option_rect(self, index):
        x = self.screen.get_width() / 2 - self.OPTION_WIDTH / 2
        y = self.OPTIONS_TOP + index * (self.OPTION_HEIGHT + self.OPTION_SPACING)
        return pygame.Rect(x, y, self.OPTION_WIDTH, self.OPTION_HEIGHT)

    def _select(self, index):
        self.game_manager.state = self.OPTIONS[index][1]

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
                        self.game_manager.running = False
                        running = False

                    elif event.key in (pygame.K_UP, pygame.K_z):
                        self.selected = (self.selected - 1) % len(self.OPTIONS)

                    elif event.key in (pygame.K_DOWN, pygame.K_s):
                        self.selected = (self.selected + 1) % len(self.OPTIONS)

                    elif event.key == pygame.K_RETURN:
                        self._select(self.selected)
                        running = False

                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:

                    for index in range(len(self.OPTIONS)):
                        if self._option_rect(index).collidepoint(event.pos):
                            self._select(index)
                            running = False

                elif event.type == pygame.MOUSEMOTION:

                    for index in range(len(self.OPTIONS)):
                        if self._option_rect(index).collidepoint(event.pos):
                            self.selected = index

            self.screen.fill((20, 20, 30))

            title = self.title_font.render("Dungeon Architect", True, (255, 255, 255))
            self.screen.blit(
                title,
                (self.screen.get_width() / 2 - title.get_width() / 2, 140),
            )

            for index, (label, _) in enumerate(self.OPTIONS):

                rect = self._option_rect(index)
                is_selected = index == self.selected

                pygame.draw.rect(self.screen, (60, 60, 70), rect)
                pygame.draw.rect(
                    self.screen,
                    (255, 220, 120) if is_selected else (150, 150, 150),
                    rect,
                    2,
                )

                color = (255, 220, 120) if is_selected else (255, 255, 255)
                text = self.option_font.render(label, True, color)

                self.screen.blit(
                    text,
                    (rect.centerx - text.get_width() / 2, rect.centery - text.get_height() / 2),
                )

            pygame.display.flip()
