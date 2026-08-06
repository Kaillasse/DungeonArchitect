"""Contient toute la logique du game state Menu (ecran titre)."""

from __future__ import annotations

import pygame

from core.engine.gamestate import GameState
from core.data.ressources import list_rooms, list_donjons, next_new_room_name
from core.data.settings import ACTIONS, ACTION_KINDS
from core.ui import BorderManager, BorderPicker, RoomBrowser


class Menu:

    MAIN_OPTIONS = (
        ("Editeur de salle", GameState.CREATOR),
        ("Explorer", GameState.EXPLORATION),
        ("Parametres", "settings"),
        ("Quitter", "quit"),
    )

    SETTINGS_OPTIONS = (
        ("Touches", "keys"),
        ("Affichage", "display"),
        ("Bordure", "border"),
        ("Volume", "volume"),
        ("Retour", "back"),
    )

    VOLUME_STEP = 0.1

    # Windowed-mode presets cycled by the "Affichage" screen's resolution button.
    DISPLAY_PRESETS = ((1280, 720), (1600, 900), (1920, 1080))

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
        self.small_font = pygame.font.SysFont("arial", 18)

        self.mode = "main"
        self.selected = 0

        self.room_target_state = None
        x = self.screen.get_width() / 2 - self.OPTION_WIDTH / 2
        self.room_browser = RoomBrowser(x, self.OPTIONS_TOP, width=self.OPTION_WIDTH)

        # "Touches" sub-screen: action_id awaiting a new key/click, or None.
        self.awaiting_action = None

        # "Bordure" sub-screen -- same "computed once from the screen size at
        # construction time" limitation RoomBrowser already has above, so a
        # display-resolution change afterwards leaves it positioned for the
        # old size (pre-existing pattern, not new here).
        border_manager = BorderManager()
        picker_width = max(1, border_manager.cols) * (BorderPicker.CELL_SIZE + BorderPicker.GAP) + BorderPicker.GAP
        border_x = self.screen.get_width() / 2 - picker_width / 2
        self.border_picker = BorderPicker(border_x, self.OPTIONS_TOP, border_manager, on_select=self._on_border_selected)

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

    # -- "Touches" sub-screen: one compact row per action, plus a back row.
    # Deliberately smaller/tighter than _option_rect's rows -- 8 actions + a
    # back row at the main OPTION_HEIGHT/SPACING would run off the bottom of
    # a 720px-tall window.
    KEYBIND_ROW_HEIGHT = 36
    KEYBIND_ROW_SPACING = 6
    KEYBIND_TOP = 200
    KEYBIND_WIDTH = 420

    def _keybind_row_rect(self, index):
        x = self.screen.get_width() / 2 - self.KEYBIND_WIDTH / 2
        y = self.KEYBIND_TOP + index * (self.KEYBIND_ROW_HEIGHT + self.KEYBIND_ROW_SPACING)
        return pygame.Rect(x, y, self.KEYBIND_WIDTH, self.KEYBIND_ROW_HEIGHT)

    # -- "Affichage" sub-screen: fullscreen toggle, resolution cycle, back --
    # reuses the same row layout as the main/settings option list.
    def _display_rects(self):
        return self._option_rect(0), self._option_rect(1), self._option_rect(2)

    # -- "Volume" sub-screen: a -/value/+ stepper sharing row 0's bounding
    # box, back button reusing row 1 -- same "reuse the main list's rects"
    # trick as _display_rects.
    def _volume_stepper_rects(self):
        row_rect = self._option_rect(0)
        minus = pygame.Rect(row_rect.x, row_rect.y, 50, row_rect.height)
        plus = pygame.Rect(row_rect.right - 50, row_rect.y, 50, row_rect.height)
        display_rect = pygame.Rect(minus.right + 4, row_rect.y, plus.x - minus.right - 8, row_rect.height)
        return minus, display_rect, plus

    def _volume_back_rect(self):
        return self._option_rect(1)

    # -- "Bordure" sub-screen: back button positioned right under the picker.
    def _border_back_rect(self):
        x = self.border_picker.x
        y = self.border_picker.y + self.border_picker.height + 12
        return pygame.Rect(x, y, self.border_picker.width, 44)

    def _on_border_selected(self, row, col):
        self.game_manager.settings.border_cell = [row, col]
        self.game_manager.settings.save()

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

        if action == "keys":
            self.mode = "settings_keys"
            self.awaiting_action = None
            return False

        if action == "display":
            self.mode = "settings_display"
            return False

        if action == "border":
            self.mode = "settings_border"
            return False

        if action == "volume":
            self.mode = "settings_volume"
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

                    if self.mode == "settings_keys" and self.awaiting_action is not None:
                        # ESCAPE cancels the capture instead of navigating away
                        # -- any other key becomes the new binding (every
                        # action accepts a "key" binding, see ACTION_KINDS).
                        if event.key != pygame.K_ESCAPE:
                            self.game_manager.settings.set_binding(
                                self.awaiting_action, {"kind": "key", "code": event.key}
                            )
                        self.awaiting_action = None

                    elif event.key == pygame.K_ESCAPE:
                        if self.mode in ("settings_keys", "settings_display", "settings_border", "settings_volume"):
                            self.mode = "settings"
                        elif self.mode != "main":
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

                    if self.mode == "settings_keys" and self.awaiting_action is not None:
                        # Only counts as the capture if this action accepts a
                        # mouse binding -- otherwise ignored, still awaiting a
                        # key. Either way this click is consumed here, so it
                        # can't also hit-test a row below in the same frame.
                        if "mouse" in ACTION_KINDS[self.awaiting_action]:
                            self.game_manager.settings.set_binding(
                                self.awaiting_action, {"kind": "mouse", "button": event.button}
                            )
                            self.awaiting_action = None

                    elif self.mode in ("main", "settings"):

                        options = self._options()
                        for index in range(len(options)):
                            if self._option_rect(index).collidepoint(event.pos):
                                _, action = options[index]
                                if self._activate(action):
                                    running = False
                                break

                    elif self.mode == "settings_keys":

                        for index, (action_id, _, _, _) in enumerate(ACTIONS):
                            if self._keybind_row_rect(index).collidepoint(event.pos):
                                self.awaiting_action = action_id
                                break
                        else:
                            if self._keybind_row_rect(len(ACTIONS)).collidepoint(event.pos):
                                self.mode = "settings"

                    elif self.mode == "settings_display":

                        settings = self.game_manager.settings
                        fullscreen_rect, resolution_rect, back_rect = self._display_rects()

                        if fullscreen_rect.collidepoint(event.pos):
                            self.game_manager.apply_display_settings(not settings.display["fullscreen"])

                        elif not settings.display["fullscreen"] and resolution_rect.collidepoint(event.pos):
                            current = tuple(settings.display["resolution"])
                            current_index = self.DISPLAY_PRESETS.index(current) if current in self.DISPLAY_PRESETS else -1
                            next_preset = self.DISPLAY_PRESETS[(current_index + 1) % len(self.DISPLAY_PRESETS)]
                            self.game_manager.apply_display_settings(False, resolution=next_preset)

                        elif back_rect.collidepoint(event.pos):
                            self.mode = "settings"

                    elif self.mode == "settings_border":

                        if not self.border_picker.handle_event(event):
                            if self._border_back_rect().collidepoint(event.pos):
                                self.mode = "settings"

                    elif self.mode == "settings_volume":

                        settings = self.game_manager.settings
                        minus_rect, _display_rect, plus_rect = self._volume_stepper_rects()

                        if minus_rect.collidepoint(event.pos):
                            settings.adjust_volume(-self.VOLUME_STEP)

                        elif plus_rect.collidepoint(event.pos):
                            settings.adjust_volume(self.VOLUME_STEP)

                        elif self._volume_back_rect().collidepoint(event.pos):
                            self.mode = "settings"

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

        TITLES = {
            "rooms": "Choisir une salle",
            "settings": "Parametres",
            "settings_keys": "Touches",
            "settings_display": "Affichage",
            "settings_border": "Bordure",
            "settings_volume": "Volume",
        }
        title_text = TITLES.get(self.mode, "Dungeon Architect")

        title = self.title_font.render(title_text, True, (255, 255, 255))
        self.screen.blit(
            title,
            (self.screen.get_width() / 2 - title.get_width() / 2, 140),
        )

        if self.mode == "rooms":

            self.room_browser.render(self.screen)

            confirm_rect = self._room_confirm_rect()
            enabled = self.room_browser.selected_name is not None
            color = (255, 255, 255) if enabled else (110, 110, 110)
            self.border.draw_centered_label(self.screen, confirm_rect, self.option_font, "Valider", color)

            back_rect = self._room_back_rect()
            self.border.draw_centered_label(self.screen, back_rect, self.option_font, "Retour")

        elif self.mode == "settings_keys":

            settings = self.game_manager.settings

            for index, (action_id, label, _, _) in enumerate(ACTIONS):
                rect = self._keybind_row_rect(index)

                if self.awaiting_action == action_id:
                    row_text = "En attente d'une touche/clic... (ECHAP annule)"
                    color = (255, 220, 120)
                else:
                    row_text = f"{label} : {settings.display_name(action_id)}"
                    color = (255, 255, 255)

                self.border.draw_centered_label(self.screen, rect, self.small_font, row_text, color)

            back_rect = self._keybind_row_rect(len(ACTIONS))
            self.border.draw_centered_label(self.screen, back_rect, self.small_font, "Retour")

        elif self.mode == "settings_display":

            settings = self.game_manager.settings
            fullscreen_rect, resolution_rect, back_rect = self._display_rects()

            fs_label = f"Plein ecran : {'ON' if settings.display['fullscreen'] else 'OFF'}"
            self.border.draw_centered_label(self.screen, fullscreen_rect, self.option_font, fs_label)

            width, height = settings.display["resolution"]
            res_color = (110, 110, 110) if settings.display["fullscreen"] else (255, 255, 255)
            res_label = f"Resolution : {width}x{height}"
            self.border.draw_centered_label(self.screen, resolution_rect, self.option_font, res_label, res_color)

            self.border.draw_centered_label(self.screen, back_rect, self.option_font, "Retour")

        elif self.mode == "settings_border":

            self.border_picker.render(self.screen)

            back_rect = self._border_back_rect()
            self.border.draw_centered_label(self.screen, back_rect, self.option_font, "Retour")

        elif self.mode == "settings_volume":

            settings = self.game_manager.settings
            minus_rect, display_rect, plus_rect = self._volume_stepper_rects()

            self.border.draw_centered_label(self.screen, minus_rect, self.option_font, "-")
            self.border.draw_centered_label(
                self.screen, display_rect, self.option_font, f"{round(settings.volume * 100)}%"
            )
            self.border.draw_centered_label(self.screen, plus_rect, self.option_font, "+")

            self.border.draw_centered_label(self.screen, self._volume_back_rect(), self.option_font, "Retour")

        else:

            for index, (label, _) in enumerate(self._options()):

                rect = self._option_rect(index)
                is_selected = index == self.selected
                color = (255, 220, 120) if is_selected else (255, 255, 255)
                self.border.draw_centered_label(self.screen, rect, self.option_font, label, color)

        pygame.display.flip()
