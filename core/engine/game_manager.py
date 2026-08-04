#gere les differents modes de jeu : menu, editeur de map, et rogue like top down

import pygame
from core.editor.creator import Creator
from core.explorator import Explorator
from core.engine.gamestate import GameState

class GameManager:
    def __init__(self, screen):
        self.screen = screen
        self.state = GameState.CREATOR
        self.running = True
        self.clock = pygame.time.Clock()
        self.creator = Creator(self)
        self.explorator = Explorator(self)

    def run(self):
        while self.running:
            if self.state == GameState.CREATOR:
                self.creator.run()
            elif self.state == GameState.EXPLORATION:
                self.explorator.run()
