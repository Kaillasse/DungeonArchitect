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
from core.data import account_manager
from core.data.ressources import (
    list_rooms, list_donjons, next_new_room_name, set_active_account, apply_starter_pack_to_account,
)
from core.ui.widgets import BorderManager, RoomBrowser, TextInputBox
from core.ui.fonts import get_font
from core.world.home import ensure_home_room
from core.engine.camera import Camera


class Menu:

    MAIN_OPTIONS = (
        ("Editeur de salle", GameState.CREATOR),
        ("Explorer", GameState.EXPLORATION),
        ("Changer de compte", "switch_account"),
        ("Quitter", "quit"),
    )

    NEW_ROOM_LABEL = "+ Nouvelle salle"
    PSEUDO_MAX_LENGTH = account_manager.MAX_PSEUDO_LENGTH

    OPTION_WIDTH = 320
    OPTION_HEIGHT = 50
    OPTION_SPACING = 16
    OPTIONS_TOP = 220

    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.screen = game_manager.screen

        self.border = BorderManager()
        self.title_font = get_font("title", 48)
        self.option_font = get_font("button", 28)
        self.small_font = get_font("text", 18)

        self.mode = "main"
        self.selected = 0

        # Forced first mode whenever no local account is logged in yet (see
        # core.data.settings.Settings.local_player_name, now the ACTIVE
        # ACCOUNT's pseudo rather than a freely-typed name) -- checked at
        # the top of run() rather than here, since __init__ can run before
        # settings are fully loaded in some call sites. Two fields (pseudo,
        # password) sharing _option_rect(0)/_option_rect(1)'s bounding
        # boxes, same "reuse the row layout" trick the room-picker rows
        # already use -- see _pseudo_field_rect/_password_field_rect.
        # mask_char on the password box only -- see TextInputBox's own
        # field, its `.value` still always holds the real typed text.
        self._pseudo_input = TextInputBox(
            *self._option_rect(0).topleft, self.OPTION_WIDTH, self.OPTION_HEIGHT,
            max_length=self.PSEUDO_MAX_LENGTH,
        )
        self._password_input = TextInputBox(
            *self._option_rect(1).topleft, self.OPTION_WIDTH, self.OPTION_HEIGHT,
            max_length=64, mask_char="*",
        )
        self._login_focus = "pseudo"  # or "password" -- which field TAB/typing routes into
        self._login_status = ""  # error feedback ("mauvais mot de passe", etc.)

        self.room_target_state = None
        x = self.screen.get_width() / 2 - self.OPTION_WIDTH / 2
        self.room_browser = RoomBrowser(x, self.OPTIONS_TOP, width=self.OPTION_WIDTH)

        self.clock = pygame.time.Clock()
        # Never moved -- Menu has no real camera of its own (see this
        # class's own docstring), this exists purely so
        # game_manager.storm_generator.render() has *something* to read
        # .x/.y off for its parallax offset. A static (0, 0) camera just
        # means the background particle layer never parallax-shifts here,
        # which is the correct/expected degradation: it still animates
        # (circular/rectilinear motion is independent of any camera), just
        # without a pan-driven depth cue there's no player-driven pan to
        # react to in the first place.
        self._storm_camera = Camera()

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

    # -- "login" mode: pseudo field, password field, a "Valider" row below
    # both -- same "reuse _option_rect's bounding box" trick as the
    # room-picker rows. One "Valider" does double duty as both "log in" (an
    # already-taken pseudo, verified against its stored hash) and "create
    # my account" (a pseudo nobody's used yet) -- see _attempt_login.
    def _login_confirm_rect(self):
        return self._option_rect(2)

    def _focused_login_field(self):
        return self._pseudo_input if self._login_focus == "pseudo" else self._password_input

    def _attempt_login(self):
        """Returns True once a real account is active (login succeeded, or
        a brand-new pseudo just got registered) and the menu loop should
        stop showing this mode -- False otherwise, with self._login_status
        set to explain why (missing fields, wrong password) so render()
        has something to show. An unknown pseudo always creates a new
        account rather than rejecting -- there's no separate "create
        account" mode to switch into, see the class's own "login" section
        docstring."""
        pseudo = self._pseudo_input.value.strip()
        password = self._password_input.value
        if not pseudo or not password:
            self._login_status = "Pseudo et mot de passe requis."
            return False

        if account_manager.account_exists(pseudo):
            confirmed_pseudo = account_manager.verify_login(pseudo, password)
            if confirmed_pseudo is None:
                self._login_status = "Mot de passe incorrect."
                return False
        else:
            try:
                confirmed_pseudo = account_manager.create_account(pseudo, password)
            except account_manager.AccountError as exc:
                self._login_status = str(exc)
                return False
            apply_starter_pack_to_account(confirmed_pseudo)

        set_active_account(confirmed_pseudo)
        self.game_manager.settings.set_local_player_name(confirmed_pseudo)
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

        if action == "switch_account":
            self._switch_account()
            return True

        # action is a GameState (CREATOR or EXPLORATION) -- pick a room first
        self._open_room_browser(action)
        return False

    def _switch_account(self):
        """Logs the current account out and drops back to the login
        screen -- clears the persisted local_player_name (so a fresh
        launch doesn't auto-login back into the account just left) and the
        active account ressources.py resolves rooms/donjons against, same
        "log out" shape any account system needs to actually support
        `AccountManager` letting several different accounts share one
        machine, which auto-login-forever alone wouldn't."""
        self.game_manager.settings.set_local_player_name("")
        set_active_account(None)
        self.mode = "login"
        self._pseudo_input.value = ""
        self._password_input.value = ""
        self._login_focus = "pseudo"
        self._login_status = ""

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

        # account_exists() guards against a stale local_player_name that
        # predates the account system (a freely-typed name, never a real
        # account -- no assets/accounts/<name>.json credentials file ever
        # written for it): trusting it blindly skipped the login screen
        # forever and silently activated a "ghost" account that had never
        # gone through create_account, so it never got the starter pack
        # either (see done.txt, 2026-08-18). Falls through to the login
        # mode below exactly like a first-ever launch would.
        has_real_account = bool(self.game_manager.settings.local_player_name) and account_manager.account_exists(
            self.game_manager.settings.local_player_name
        )
        if not has_real_account:
            self.game_manager.settings.set_local_player_name("")
            self.mode = "login"
            self._pseudo_input.value = ""
            self._password_input.value = ""
            self._login_focus = "pseudo"
            self._login_status = ""
        else:
            # Already logged in (a saved local_player_name survives across
            # launches, same "ask once, persist forever" convention as
            # every other Settings field) -- (re)activates the matching
            # account every time Menu.run() starts, not just once at
            # process start, since this same instance is re-entered on
            # every ESC-from-gameplay return to the menu too.
            set_active_account(self.game_manager.settings.local_player_name)
            if self.game_manager.boot_into_home:
                self.game_manager.boot_into_home = False
                self._redirect_to_home()
                return

        running = True

        while running:

            dt = self.clock.tick(60) / 1000
            self.game_manager.storm_generator.update(dt, self.screen.get_size())

            for event in pygame.event.get():

                if event.type == pygame.QUIT:
                    self.game_manager.running = False
                    running = False

                elif event.type == pygame.KEYDOWN:

                    if event.key == pygame.K_ESCAPE:
                        if self.mode == "login":
                            # No "back" to fall to without a logged-in
                            # account -- quitting is the only escape hatch,
                            # same as ESC from "main".
                            self.game_manager.running = False
                            running = False
                        elif self.mode != "main":
                            self.mode = "main"
                            self.selected = 0
                        else:
                            self.game_manager.running = False
                            running = False

                    elif self.mode == "login":
                        if event.key == pygame.K_TAB:
                            self._login_focus = "password" if self._login_focus == "pseudo" else "pseudo"
                        elif event.key == pygame.K_RETURN:
                            if self._login_focus == "pseudo":
                                # Enter on the pseudo field just advances to
                                # the password field -- only Enter on the
                                # password field actually submits, so a
                                # returning user typing their pseudo then
                                # hitting Enter out of habit doesn't
                                # prematurely attempt a passwordless login.
                                self._login_focus = "password"
                            elif self._attempt_login():
                                running = False
                        else:
                            self._focused_login_field().handle_event(event)

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

                    if self.mode == "login":

                        if self._option_rect(0).collidepoint(event.pos):
                            self._login_focus = "pseudo"
                        elif self._option_rect(1).collidepoint(event.pos):
                            self._login_focus = "password"
                        elif self._login_confirm_rect().collidepoint(event.pos):
                            if self._attempt_login():
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
        self.game_manager.storm_generator.render(self.screen, self._storm_camera)

        TITLES = {
            "login": "Pseudo et mot de passe",
            "rooms": "Choisir une salle",
        }
        title_text = TITLES.get(self.mode, "Dungeon Architect")

        title = self.title_font.render(title_text, True, (255, 255, 255))
        self.screen.blit(
            title,
            (self.screen.get_width() / 2 - title.get_width() / 2, 140),
        )

        if self.mode == "login":

            # A thin highlight around whichever field TAB/a click last
            # focused -- the only visual cue distinguishing the two
            # otherwise-identical-looking fields, since neither one is
            # ever disabled/greyed out the way the room-picker's "Valider"
            # is.
            focused_rect = self._option_rect(0 if self._login_focus == "pseudo" else 1)
            pygame.draw.rect(self.screen, (255, 220, 120), focused_rect.inflate(6, 6), 2, border_radius=4)

            self._pseudo_input.render(self.screen)
            self._password_input.render(self.screen)

            confirm_rect = self._login_confirm_rect()
            enabled = bool(self._pseudo_input.value.strip()) and bool(self._password_input.value)
            self.border.draw_enabled_label(self.screen, confirm_rect, self.option_font, "Valider", enabled)

            if self._login_status:
                status = self.small_font.render(self._login_status, True, (255, 140, 140))
                self.screen.blit(status, (confirm_rect.x, confirm_rect.bottom + 10))
            else:
                hint = self.small_font.render(
                    "Pseudo connu -> connexion. Nouveau pseudo -> creation de compte.",
                    True, (180, 180, 180),
                )
                self.screen.blit(hint, (confirm_rect.x, confirm_rect.bottom + 10))

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
