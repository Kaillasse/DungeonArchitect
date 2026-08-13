"""SettingsPanelUI -- the "Parametres" screen (keybindings, display,
border theme, volume), extracted out of Menu so it can be opened as a
modal overlay from Explorator's inventory panel AND from Creator, instead
of only being reachable through the main Menu -- which otherwise has no
real purpose once a session is already running (home is always reachable
directly now, see Explorator._return_to_home/CLAUDE.md's home-first
navigation). One shared instance lives on GameManager (constructed once,
alongside menu/creator/explorator) so both entry points -- and the
underlying Settings object itself -- stay a single source of truth rather
than each state owning its own independent copy of this UI.

Deliberately NOT in core/ui/widgets.py, which is reserved for smaller
widgets actually composed together by other UI (BorderManager/RoomBrowser/
BorderPicker) -- this is a whole self-contained modal screen with its own
open/close/mode state machine, closer in shape to a Creator UI panel than
a widget, just living in core/ui/ (not core/editor/ui/) since it's shared
across states instead of Creator-only."""

from __future__ import annotations

import pygame

from core.data.settings import ACTIONS, ACTION_KINDS
from core.ui.widgets import BorderManager, BorderPicker


class SettingsPanelUI:
    OPTIONS = (
        ("Touches", "keys"),
        ("Affichage", "display"),
        ("Bordure", "border"),
        ("Volume", "volume"),
        ("Fermer", "close"),
    )

    VOLUME_STEP = 0.1
    DISPLAY_PRESETS = ((1280, 720), (1600, 900), (1920, 1080))

    OPTION_WIDTH = 320
    OPTION_HEIGHT = 50
    OPTION_SPACING = 16
    OPTIONS_TOP = 120

    KEYBIND_ROW_HEIGHT = 36
    KEYBIND_ROW_SPACING = 6
    KEYBIND_TOP = 100
    KEYBIND_WIDTH = 420

    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.screen = game_manager.screen  # kept in sync by GameManager.apply_display_settings

        self.is_open = False
        # "root" (the OPTIONS list) or one of "keys"/"display"/"border"/
        # "volume" -- mirrors Menu's old mode names (minus the "settings_"
        # prefix, which only ever existed to disambiguate from Menu's OWN
        # main/name_entry/rooms modes, irrelevant here).
        self.mode = "root"
        self.selected = 0
        self.awaiting_action = None

        self.border = BorderManager()
        self.title_font = pygame.font.SysFont("arial", 36)
        self.option_font = pygame.font.SysFont("arial", 28)
        self.small_font = pygame.font.SysFont("arial", 18)

        border_manager = BorderManager()
        picker_width = max(1, border_manager.cols) * (BorderPicker.CELL_SIZE + BorderPicker.GAP) + BorderPicker.GAP
        border_x = self.screen.get_width() / 2 - picker_width / 2
        self.border_picker = BorderPicker(border_x, self.OPTIONS_TOP, border_manager, on_select=self._on_border_selected)

    def open(self):
        self.is_open = True
        self.mode = "root"
        self.selected = 0
        self.awaiting_action = None

    def close(self):
        self.is_open = False
        self.awaiting_action = None

    # -- layout (recomputed from self.screen on every call, never cached,
    # same reasoning as Menu's own rects -- correct across a fullscreen/
    # resolution change while this panel happens to be open) --

    def _option_rect(self, index):
        x = self.screen.get_width() / 2 - self.OPTION_WIDTH / 2
        y = self.OPTIONS_TOP + index * (self.OPTION_HEIGHT + self.OPTION_SPACING)
        return pygame.Rect(x, y, self.OPTION_WIDTH, self.OPTION_HEIGHT)

    def _keybind_row_rect(self, index):
        x = self.screen.get_width() / 2 - self.KEYBIND_WIDTH / 2
        y = self.KEYBIND_TOP + index * (self.KEYBIND_ROW_HEIGHT + self.KEYBIND_ROW_SPACING)
        return pygame.Rect(x, y, self.KEYBIND_WIDTH, self.KEYBIND_ROW_HEIGHT)

    def _display_rects(self):
        return self._option_rect(0), self._option_rect(1), self._option_rect(2)

    def _volume_stepper_rects(self):
        row_rect = self._option_rect(0)
        minus = pygame.Rect(row_rect.x, row_rect.y, 50, row_rect.height)
        plus = pygame.Rect(row_rect.right - 50, row_rect.y, 50, row_rect.height)
        display_rect = pygame.Rect(minus.right + 4, row_rect.y, plus.x - minus.right - 8, row_rect.height)
        return minus, display_rect, plus

    def _volume_back_rect(self):
        return self._option_rect(1)

    def _border_back_rect(self):
        x = self.border_picker.x
        y = self.border_picker.y + self.border_picker.height + 12
        return pygame.Rect(x, y, self.border_picker.width, 44)

    def _on_border_selected(self, row, col):
        self.game_manager.settings.border_cell = [row, col]
        self.game_manager.settings.save()

    def _activate(self, action):
        if action == "close":
            self.close()
            return
        if action == "keys":
            self.mode = "keys"
            self.awaiting_action = None
            return
        if action == "display":
            self.mode = "display"
            return
        if action == "border":
            self.mode = "border"
            return
        if action == "volume":
            self.mode = "volume"
            return

    # -- events --

    def handle_event(self, event):
        """Consumes every event while open -- callers gate this the same
        modal way chest_panel/role_panel/etc. already are in Creator (see
        their own docstrings): check self.is_open first, forward every
        event here, and don't fall through to normal gameplay/editor
        handling for as long as it's True."""
        if event.type == pygame.KEYDOWN:
            if self.mode == "keys" and self.awaiting_action is not None:
                if event.key != pygame.K_ESCAPE:
                    self.game_manager.settings.set_binding(
                        self.awaiting_action, {"kind": "key", "code": event.key}
                    )
                self.awaiting_action = None
                return

            if event.key == pygame.K_ESCAPE:
                if self.mode != "root":
                    self.mode = "root"
                else:
                    self.close()
                return

            if self.mode == "root":
                if event.key in (pygame.K_UP, pygame.K_z):
                    self.selected = (self.selected - 1) % len(self.OPTIONS)
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    self.selected = (self.selected + 1) % len(self.OPTIONS)
                elif event.key == pygame.K_RETURN:
                    _, action = self.OPTIONS[self.selected]
                    self._activate(action)
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.mode == "keys" and self.awaiting_action is not None:
                if "mouse" in ACTION_KINDS[self.awaiting_action]:
                    self.game_manager.settings.set_binding(
                        self.awaiting_action, {"kind": "mouse", "button": event.button}
                    )
                    self.awaiting_action = None
                return

            if self.mode == "root":
                for index, (_, action) in enumerate(self.OPTIONS):
                    if self._option_rect(index).collidepoint(event.pos):
                        self._activate(action)
                        return
                return

            if self.mode == "keys":
                for index, (action_id, _, _, _) in enumerate(ACTIONS):
                    if self._keybind_row_rect(index).collidepoint(event.pos):
                        self.awaiting_action = action_id
                        return
                if self._keybind_row_rect(len(ACTIONS)).collidepoint(event.pos):
                    self.mode = "root"
                return

            if self.mode == "display":
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
                    self.mode = "root"
                return

            if self.mode == "border":
                if not self.border_picker.handle_event(event):
                    if self._border_back_rect().collidepoint(event.pos):
                        self.mode = "root"
                return

            if self.mode == "volume":
                settings = self.game_manager.settings
                minus_rect, _display_rect, plus_rect = self._volume_stepper_rects()
                if minus_rect.collidepoint(event.pos):
                    settings.adjust_volume(-self.VOLUME_STEP)
                elif plus_rect.collidepoint(event.pos):
                    settings.adjust_volume(self.VOLUME_STEP)
                elif self._volume_back_rect().collidepoint(event.pos):
                    self.mode = "root"
                return
            return

        if event.type == pygame.MOUSEMOTION and self.mode == "root":
            for index in range(len(self.OPTIONS)):
                if self._option_rect(index).collidepoint(event.pos):
                    self.selected = index
            return

    # -- render --

    TITLES = {
        "root": "Parametres",
        "keys": "Touches",
        "display": "Affichage",
        "border": "Bordure",
        "volume": "Volume",
    }

    def render(self, screen):
        """Full-screen modal overlay -- same "dim everything behind it"
        treatment InventoryPanel already uses, since this can be opened
        from on top of either Explorator's or Creator's own view."""
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        screen.blit(overlay, (0, 0))

        title = self.title_font.render(self.TITLES.get(self.mode, "Parametres"), True, (255, 255, 255))
        screen.blit(title, (screen.get_width() / 2 - title.get_width() / 2, 40))

        if self.mode == "keys":
            settings = self.game_manager.settings
            for index, (action_id, label, _, _) in enumerate(ACTIONS):
                rect = self._keybind_row_rect(index)
                if self.awaiting_action == action_id:
                    row_text = "En attente d'une touche/clic... (ECHAP annule)"
                    color = (255, 220, 120)
                else:
                    row_text = f"{label} : {settings.display_name(action_id)}"
                    color = (255, 255, 255)
                self.border.draw_centered_label(screen, rect, self.small_font, row_text, color)

            back_rect = self._keybind_row_rect(len(ACTIONS))
            self.border.draw_centered_label(screen, back_rect, self.small_font, "Retour")

        elif self.mode == "display":
            settings = self.game_manager.settings
            fullscreen_rect, resolution_rect, back_rect = self._display_rects()

            fs_label = f"Plein ecran : {'ON' if settings.display['fullscreen'] else 'OFF'}"
            self.border.draw_centered_label(screen, fullscreen_rect, self.option_font, fs_label)

            width, height = settings.display["resolution"]
            res_color = (110, 110, 110) if settings.display["fullscreen"] else (255, 255, 255)
            res_label = f"Resolution : {width}x{height}"
            self.border.draw_centered_label(screen, resolution_rect, self.option_font, res_label, res_color)

            self.border.draw_centered_label(screen, back_rect, self.option_font, "Retour")

        elif self.mode == "border":
            self.border_picker.render(screen)
            back_rect = self._border_back_rect()
            self.border.draw_centered_label(screen, back_rect, self.option_font, "Retour")

        elif self.mode == "volume":
            settings = self.game_manager.settings
            minus_rect, display_rect, plus_rect = self._volume_stepper_rects()

            self.border.draw_centered_label(screen, minus_rect, self.option_font, "-")
            self.border.draw_centered_label(
                screen, display_rect, self.option_font, f"{round(settings.volume * 100)}%"
            )
            self.border.draw_centered_label(screen, plus_rect, self.option_font, "+")
            self.border.draw_centered_label(screen, self._volume_back_rect(), self.option_font, "Retour")

        else:
            for index, (label, _) in enumerate(self.OPTIONS):
                rect = self._option_rect(index)
                is_selected = index == self.selected
                color = (255, 220, 120) if is_selected else (255, 255, 255)
                self.border.draw_centered_label(screen, rect, self.option_font, label, color)
