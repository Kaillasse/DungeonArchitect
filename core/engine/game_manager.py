#gere les differents modes de jeu : menu, editeur de map, et rogue like top down

import os

import pygame
from core.editor.creator import Creator
from core.exploration.explorator import Explorator
from core.ui.menu import Menu
from core.engine.gamestate import GameState
from core.data.settings import Settings
from core.ui.widgets import BorderManager
from core.ui.settings_panel import SettingsPanelUI
from core.data.ressources import set_active_account
from core.rendering.storm import StormGenerator

class GameManager:
    def __init__(self, screen, settings=None):
        self.screen = screen
        self.settings = settings if settings is not None else Settings()
        # Le smoke-test headless (DUNGEONARCHITECT_HEADLESS) attend le comportement
        # historique de Creator.run() (sauvegarde immediate + sortie) ; le menu n'a
        # pas de bypass headless, donc on saute directement l'editeur.
        headless = os.environ.get("DUNGEONARCHITECT_HEADLESS") == "1"
        if headless:
            # Skips Menu entirely (see below), so no login ever runs to
            # activate an account -- rooms_directory()/donjons_directory()
            # (core.data.ressources) raise loudly with no active account at
            # all, by design, rather than silently falling back to some
            # ambiguous shared location. A fixed dummy account keeps this
            # smoke-test path exercising the exact same account-scoped
            # save/load code every real launch goes through, isolated from
            # any real player's own data.
            set_active_account("headless")
            # Profiles (assets/profiles/<name>.json) are NOT account-scoped
            # (see core.data.ressources' own account bullet in CLAUDE.md) --
            # rooms/donjons alone being isolated above still left
            # Creator._load_profile/Explorator resolving the local
            # PROFILE from settings.local_player_name, which main.py's
            # unconditional load_settings() populates with whatever a
            # RETURNING player last saved for real. A live bug, not
            # hypothetical: found 2026-08-20 when the headless smoke test,
            # run mid-session, silently loaded-and-resaved the real
            # "thib" profile (panel_layout coordinates clamped to the
            # dummy SDL driver's small surface) -- exactly the kind of
            # mutation this smoke test is supposed to never risk. Setting
            # the attribute directly (never Settings.set_local_player_name,
            # which saves to disk) keeps this in-memory-only, so the real
            # assets/settings.json is untouched either way.
            self.settings.local_player_name = "headless"
        else:
            # Creator's own __init__ (below) eagerly loads a placeholder
            # room into self.dungeon before Menu's login screen has ever
            # run -- a REAL crash reported live: rooms_directory() raised
            # "aucun compte actif" the instant Creator was constructed,
            # since normal (non-headless) startup used to leave no account
            # active until Menu.run() actually completed a login, which
            # happens well after this constructor. A returning user's own
            # account activates immediately here so that placeholder load
            # reads their real room_001 (closest to the old pre-account
            # behavior); a brand-new install (no saved local_player_name
            # yet) activates a throwaway "_pending_login" account instead
            # -- SaveManager.load tolerates a missing room file (silently
            # leaves self.dungeon blank), and Menu.run()'s own login
            # re-activates the REAL account and Creator.open_room() loads
            # the real room before anything is ever actually shown, so
            # this placeholder is never seen or written to.
            set_active_account(self.settings.local_player_name or "_pending_login")
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
        # Set by Explorator.start_hosting/join_session (via the home-only
        # MultiplayerPanelUI, M key) once a connection is live -- makes
        # run()'s EXPLORATION dispatch below route into run_networked
        # instead of the normal solo run(). _game_server/_host_announcer
        # are host-side only (None when just joined, not hosting), kept
        # here so Explorator.stop_networking can tear both down without
        # GameManager needing to know anything about how they work.
        self.network_client = None
        self._game_server = None
        self._host_announcer = None
        self.clock = pygame.time.Clock()
        # Purely cosmetic background particle layer (see core.rendering.
        # storm's own docstring) -- one shared instance/config for the
        # whole session (confirmed with the user, 2026-08-22), updated and
        # drawn by Menu/Creator/Explorator alike every frame; only
        # Creator's own StormPanelUI (a docked/tabbed panel like any
        # other, see Creator._panel_tab_entries) actually edits it.
        # Constructed before Creator below, which builds that panel around
        # this exact instance in its own __init__.
        self.storm_generator = StormGenerator()
        self.menu = Menu(self)
        self.creator = Creator(self)
        self.explorator = Explorator(self)
        # One shared instance -- opened from either Creator's UI or
        # Explorator's inventory panel, so both reach the exact same
        # is_open/mode state and the exact same underlying Settings
        # object, rather than each state owning an independent copy of
        # this whole screen (see settings_panel.py's own docstring).
        self.settings_panel = SettingsPanelUI(self)

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
        self.settings_panel.screen = screen

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
                if self.network_client is not None:
                    self.explorator.run_networked(self.network_client)
                else:
                    self.explorator.run()
