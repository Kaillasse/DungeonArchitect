#gere les differents modes de jeu : menu, editeur de map, et rogue like top down

import os

import pygame
from core.editor.creator import Creator
from core.explorator import Explorator
from core.menu import Menu
from core.engine.gamestate import GameState

class GameManager:
    def __init__(self, screen):
        self.screen = screen
        # Le smoke-test headless (DUNGEONARCHITECT_HEADLESS) attend le comportement
        # historique de Creator.run() (sauvegarde immediate + sortie) ; le menu n'a
        # pas de bypass headless, donc on saute directement l'editeur.
        headless = os.environ.get("DUNGEONARCHITECT_HEADLESS") == "1"
        self.state = GameState.CREATOR if headless else GameState.MENU
        self.running = True
        self.pending_room = None
        self.clock = pygame.time.Clock()
        self.menu = Menu(self)
        self.creator = Creator(self)
        self.explorator = Explorator(self)

    def run(self):
        while self.running:
            if self.state == GameState.MENU:
                self.menu.run()

            elif self.state == GameState.CREATOR:
                if self.pending_room is not None:
                    self.creator.open_room(self.pending_room)
                    self.pending_room = None
                self.creator.run()

            elif self.state == GameState.EXPLORATION:
                if self.pending_room is not None:
                    self.explorator.open_room(self.pending_room)
                    self.pending_room = None
                self.explorator.run()
