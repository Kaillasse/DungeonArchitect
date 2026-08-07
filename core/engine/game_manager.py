#gere les differents modes de jeu : menu, editeur de map, et rogue like top down

import os

import pygame
from core.editor.creator import Creator
from core.exploration.explorator import Explorator
from core.ui.menu import Menu
from core.engine.gamestate import GameState
from core.data.settings import Settings
from core.ui.widgets import BorderManager

class GameManager:
    def __init__(self, screen, settings=None):
        self.screen = screen
        self.settings = settings if settings is not None else Settings()
        # Le smoke-test headless (DUNGEONARCHITECT_HEADLESS) attend le comportement
        # historique de Creator.run() (sauvegarde immediate + sortie) ; le menu n'a
        # pas de bypass headless, donc on saute directement l'editeur.
        headless = os.environ.get("DUNGEONARCHITECT_HEADLESS") == "1"
        self.state = GameState.CREATOR if headless else GameState.MENU
        self.running = True
        self.pending_room = None
        # Zoom value to seed the destination state's camera with right
        # after applying pending_room -- set by the home-room zoom-switch
        # (Creator/Explorator) and by Menu's boot-into-home redirect, so
        # the new state opens already on the correct side of its own
        # threshold instead of its camera's own stale/default zoom (see
        # core.world.home).
        self.pending_zoom_carry = None
        # (world_x, world_y) to center the destination camera on, right
        # after applying pending_zoom_carry -- set by Explorator's
        # zoom-switch back to Creator (see core.world.home) so Creator
        # opens centered on where the player actually was, instead of
        # Creator's own camera keeping whatever stale pan position it was
        # left at last time it was open (the "camera bouge" jump the user
        # reported). Exploration never needs the equivalent: its own
        # per-frame camera-follow already recenters on the player the very
        # first frame regardless of carried position.
        self.pending_camera_center = None
        # One-shot: True until the first time Menu.run() actually executes
        # with a known player name, at which point it redirects straight
        # into home instead of showing the main list (see
        # Menu._redirect_to_home). Irrelevant in headless mode -- Menu is
        # never reached there.
        self.boot_into_home = True
        self.clock = pygame.time.Clock()
        self.menu = Menu(self)
        self.creator = Creator(self)
        self.explorator = Explorator(self)

        # BorderManager is a singleton first-initialized by whichever of the
        # above constructed it first (Menu, in practice) -- apply the
        # persisted border choice once construction is done, same spirit as
        # loading any other saved setting.
        BorderManager().set_tile(*self.settings.border_cell)

    def apply_display_settings(self, fullscreen, resolution=None):
        """Switch fullscreen/windowed (and optionally resolution) immediately,
        propagating the new screen Surface to every state that caches one --
        Menu/Creator/Explorator each store self.screen once at construction
        (their child widgets always take screen as a render() parameter, never
        cache it, so nothing else needs updating). Persists via Settings.save()."""
        self.settings.display["fullscreen"] = fullscreen
        if resolution is not None:
            self.settings.display["resolution"] = list(resolution)

        size, flags = self.settings.display_mode()
        screen = pygame.display.set_mode(size, flags)

        self.screen = screen
        self.menu.screen = screen
        self.creator.screen = screen
        self.explorator.screen = screen

        self.settings.save()

    def run(self):
        while self.running:
            if self.state == GameState.MENU:
                self.menu.run()

            elif self.state == GameState.CREATOR:
                if self.pending_room is not None:
                    self.creator.open_room(self.pending_room)
                    self.pending_room = None
                    if self.pending_zoom_carry is not None:
                        self.creator.camera.zoom = self.pending_zoom_carry
                        self.pending_zoom_carry = None
                    if self.pending_camera_center is not None:
                        cx, cy = self.pending_camera_center
                        self.creator.camera.center_on(cx, cy, self.screen.get_width(), self.screen.get_height())
                        self.pending_camera_center = None
                self.creator.run()

            elif self.state == GameState.EXPLORATION:
                if self.pending_room is not None:
                    kind, name = self.pending_room
                    if kind == "donjon":
                        self.explorator.open_donjon(name)
                    else:
                        self.explorator.open_room(name)
                    self.pending_room = None
                    if self.pending_zoom_carry is not None:
                        self.explorator.camera.zoom = self.pending_zoom_carry
                        self.pending_zoom_carry = None
                self.explorator.run()
