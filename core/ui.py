"""Shared UI widgets used across game states (menu, editor, ...)."""

from __future__ import annotations

import os
import pygame

# ---------------------------------------------------------------------
# Border Manager
# ---------------------------------------------------------------------


class BorderManager:
    """Simple singleton used to draw 9-slice borders."""

    _instance = None

    BORDER_SIZE = 64
    CORNER_SIZE = 16

    def __new__(cls, border_asset_path="assets/UI/allborder.png"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, border_asset_path="assets/UI/allborder.png"):
        if self._initialized:
            return

        self.border_asset_path = border_asset_path
        self.border = None
        self._sheet = None
        self.rows = 0
        self.cols = 0
        self.current_cell = (0, 0)

        self.load_border()

        self._initialized = True

    # -------------------------------------------------------------

    def load_border(self):

        if os.path.exists(self.border_asset_path):

            self._sheet = pygame.image.load(self.border_asset_path).convert_alpha()
            self.rows = self._sheet.get_height() // self.BORDER_SIZE
            self.cols = self._sheet.get_width() // self.BORDER_SIZE

            self.set_tile(0, 0)

        else:

            self.border = self._create_fallback()

    # -------------------------------------------------------------

    def set_tile(self, row, col):
        """Switch the active 9-slice to a different cell of the same border
        sheet -- a no-op if no sheet was loaded (fallback mode). Since this
        singleton is shared by every panel in the app (Menu, RoomBrowser,
        Creator's UI), changing it here updates every panel's look the next
        time it draws, with no other code needing to react."""
        if self._sheet is None:
            return

        row = max(0, min(self.rows - 1, row))
        col = max(0, min(self.cols - 1, col))

        c = self.BORDER_SIZE
        tile = self._sheet.subsurface((col * c, row * c, c, c)).copy()
        self.border = self._create_nine_slice(tile)
        self.current_cell = (row, col)

    # -------------------------------------------------------------

    def _create_fallback(self):

        surf = pygame.Surface((64, 64), pygame.SRCALPHA)
        surf.fill((40, 40, 40))
        pygame.draw.rect(surf, (255, 255, 255), surf.get_rect(), 3)

        return self._create_nine_slice(surf)

    # -------------------------------------------------------------

    def _create_nine_slice(self, surface):

        c = self.CORNER_SIZE
        w, h = surface.get_size()

        return {
            "tl": surface.subsurface((0, 0, c, c)).copy(),
            "tr": surface.subsurface((w - c, 0, c, c)).copy(),
            "bl": surface.subsurface((0, h - c, c, c)).copy(),
            "br": surface.subsurface((w - c, h - c, c, c)).copy(),
            "top": surface.subsurface((c, 0, w - 2 * c, c)).copy(),
            "bottom": surface.subsurface((c, h - c, w - 2 * c, c)).copy(),
            "left": surface.subsurface((0, c, c, h - 2 * c)).copy(),
            "right": surface.subsurface((w - c, c, c, h - 2 * c)).copy(),
            "center": surface.subsurface((c, c, w - 2 * c, h - 2 * c)).copy(),
        }

    # -------------------------------------------------------------

    def draw(self, screen, rect):

        if self.border is None:
            return

        c = self.CORNER_SIZE

        x = rect.x
        y = rect.y
        w = rect.width
        h = rect.height

        b = self.border

        # Centre
        if w > c * 2 and h > c * 2:
            screen.blit(
                pygame.transform.scale(
                    b["center"],
                    (w - c * 2, h - c * 2),
                ),
                (x + c, y + c),
            )

        # Haut / bas
        if w > c * 2:
            screen.blit(
                pygame.transform.scale(b["top"], (w - c * 2, c)),
                (x + c, y),
            )

            screen.blit(
                pygame.transform.scale(b["bottom"], (w - c * 2, c)),
                (x + c, y + h - c),
            )

        # Gauche / droite
        if h > c * 2:
            screen.blit(
                pygame.transform.scale(b["left"], (c, h - c * 2)),
                (x, y + c),
            )

            screen.blit(
                pygame.transform.scale(b["right"], (c, h - c * 2)),
                (x + w - c, y + c),
            )

        # Coins
        screen.blit(b["tl"], (x, y))
        screen.blit(b["tr"], (x + w - c, y))
        screen.blit(b["bl"], (x, y + h - c))
        screen.blit(b["br"], (x + w - c, y + h - c))


# ---------------------------------------------------------------------
# Border picker (Settings > Bordure)
# ---------------------------------------------------------------------


class BorderPicker:
    """Clickable grid of every raw tile in a BorderManager's sheet -- clicking
    one calls border_manager.set_tile(row, col) directly (so every panel in
    the app, this picker's own background included, re-skins immediately)
    and, if provided, on_select(row, col) so the caller can persist the
    choice. A no-op grid (nothing to click) if the manager has no sheet
    loaded (fallback mode)."""

    CELL_SIZE = 48
    GAP = 4
    HIGHLIGHT_COLOR = (255, 220, 120)

    def __init__(self, x, y, border_manager, on_select=None):
        self.x = x
        self.y = y
        self.border_manager = border_manager
        self.on_select = on_select

    @property
    def width(self):
        cols = max(1, self.border_manager.cols)
        return cols * (self.CELL_SIZE + self.GAP) + self.GAP

    @property
    def height(self):
        rows = max(1, self.border_manager.rows)
        return rows * (self.CELL_SIZE + self.GAP) + self.GAP

    def _cell_rect(self, row, col):
        return pygame.Rect(
            self.x + self.GAP + col * (self.CELL_SIZE + self.GAP),
            self.y + self.GAP + row * (self.CELL_SIZE + self.GAP),
            self.CELL_SIZE,
            self.CELL_SIZE,
        )

    def handle_event(self, event):
        """Returns True if this event was consumed (a swatch was clicked)."""
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False

        for row in range(self.border_manager.rows):
            for col in range(self.border_manager.cols):
                if self._cell_rect(row, col).collidepoint(event.pos):
                    self.border_manager.set_tile(row, col)
                    if self.on_select is not None:
                        self.on_select(row, col)
                    return True

        return False

    def render(self, screen):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        self.border_manager.draw(screen, panel_rect)

        sheet = self.border_manager._sheet
        if sheet is None:
            return

        size = self.border_manager.BORDER_SIZE
        for row in range(self.border_manager.rows):
            for col in range(self.border_manager.cols):
                rect = self._cell_rect(row, col)
                tile = sheet.subsurface((col * size, row * size, size, size))
                scaled = pygame.transform.scale(tile, (self.CELL_SIZE, self.CELL_SIZE))
                screen.blit(scaled, rect.topleft)

                if (row, col) == self.border_manager.current_cell:
                    pygame.draw.rect(screen, self.HIGHLIGHT_COLOR, rect, 3)


# ---------------------------------------------------------------------
# Room browser
# ---------------------------------------------------------------------


class RoomBrowser:
    """Scrollable, selectable list of room names with a drag slider. Purely a list-selector -- callers decide what "confirming" a selection means."""

    ROW_HEIGHT = 30
    VISIBLE_ROWS = 5
    SLIDER_WIDTH = 12

    def __init__(self, x, y, width=240, multi_select=False):
        self.x = x
        self.y = y
        self.width = width
        self.multi_select = multi_select

        self.rooms = []
        self.selected = None
        self.selected_set = set()
        self.scroll = 0
        self._dragging_slider = False

        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 16)

    @property
    def height(self):
        return self.ROW_HEIGHT * self.VISIBLE_ROWS

    @staticmethod
    def _label(entry):
        """Entries are either a plain string, or a (label, value) tuple -- e.g. to
        distinguish two kinds of entry (room vs. donjon) sharing one list."""
        return entry[0] if isinstance(entry, tuple) else entry

    @staticmethod
    def _value(entry):
        return entry[1] if isinstance(entry, tuple) else entry

    @property
    def selected_name(self):
        if self.selected is None or self.selected >= len(self.rooms):
            return None
        return self._value(self.rooms[self.selected])

    @property
    def selected_names(self):
        return [self._value(entry) for i, entry in enumerate(self.rooms) if i in self.selected_set]

    def set_rooms(self, rooms, preselect_all=False):
        self.rooms = list(rooms)
        self.selected = None
        self.selected_set = set(range(len(self.rooms))) if preselect_all else set()
        self.scroll = 0

    def _max_scroll(self):
        return max(0, len(self.rooms) - self.VISIBLE_ROWS)

    def _visible_count(self):
        return min(self.VISIBLE_ROWS, len(self.rooms) - self.scroll)

    def _row_rect(self, row_index):
        return pygame.Rect(
            self.x,
            self.y + row_index * self.ROW_HEIGHT,
            self.width - self.SLIDER_WIDTH - 4,
            self.ROW_HEIGHT,
        )

    def _slider_track_rect(self):
        return pygame.Rect(self.x + self.width - self.SLIDER_WIDTH, self.y, self.SLIDER_WIDTH, self.height)

    def _slider_thumb_rect(self):
        track = self._slider_track_rect()
        max_scroll = self._max_scroll()

        if max_scroll == 0:
            return track

        thumb_h = max(20, track.height * self.VISIBLE_ROWS / len(self.rooms))
        thumb_y = track.y + (track.height - thumb_h) * (self.scroll / max_scroll)

        return pygame.Rect(track.x, thumb_y, track.width, thumb_h)

    def contains(self, pos):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        return panel_rect.collidepoint(pos)

    def handle_event(self, event):
        """Returns True if this event was consumed (row click, slider drag)."""

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:

            if self._max_scroll() > 0 and self._slider_thumb_rect().collidepoint(event.pos):
                self._dragging_slider = True
                return True

            for row_index in range(self._visible_count()):
                if self._row_rect(row_index).collidepoint(event.pos):
                    room_index = self.scroll + row_index
                    if self.multi_select:
                        if room_index in self.selected_set:
                            self.selected_set.discard(room_index)
                        else:
                            self.selected_set.add(room_index)
                    else:
                        self.selected = room_index
                    return True

            return self.contains(event.pos)

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._dragging_slider:
                self._dragging_slider = False
                return True
            return False

        if event.type == pygame.MOUSEMOTION and self._dragging_slider:
            track = self._slider_track_rect()
            max_scroll = self._max_scroll()
            if max_scroll > 0:
                rel = (event.pos[1] - track.y) / track.height
                self.scroll = max(0, min(max_scroll, round(rel * max_scroll)))
            return True

        return False

    def render(self, screen):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        self.border.draw(screen, panel_rect)

        for row_index in range(self._visible_count()):
            room_index = self.scroll + row_index
            rect = self._row_rect(row_index)

            is_selected = room_index in self.selected_set if self.multi_select else room_index == self.selected
            color = (255, 220, 120) if is_selected else (255, 255, 255)

            label = self._label(self.rooms[room_index])
            if self.multi_select:
                label = ("[x] " if is_selected else "[ ] ") + label

            text = self.font.render(label, True, color)

            screen.blit(text, (rect.x + 8, rect.centery - text.get_height() / 2))

        if self._max_scroll() > 0:
            pygame.draw.rect(screen, (60, 60, 70), self._slider_track_rect())
            pygame.draw.rect(screen, (150, 150, 150), self._slider_thumb_rect())
