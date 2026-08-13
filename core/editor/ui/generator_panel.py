"""GeneratorPanelUI -- split out of the old monolithic core/editor/ui.py."""

import pygame

from core.ui.widgets import BorderManager, RoomBrowser, Stepper
from core.data.cards import room_card_id
from core.editor.ui.mixins import _ResizableCornerMixin
from core.editor.ui.card_renderer import CardRenderer


class GeneratorPanelUI(_ResizableCornerMixin):
    """Procedural assembler settings: which rooms to draw from, how many to
    assemble, and a Generer button. Resizable and toggled exactly on
    CardPanelUI's own model -- mutually exclusive, not additive: standard
    size shows the pool_browser list + stepper + Generer button (unchanged
    from before rooms became cards); enlarged shows *only* a visual card
    grid (via the shared CardRenderer) of the rooms currently in the pool
    (pool_browser.selected_names) -- no list, no stepper, no button, same
    "just the card panel" reduction CardPanelUI's own enlarged mode already
    applies. A room card is dragged in from CardPanelUI/the collection (see
    Creator's MOUSEBUTTONUP handling) -- this panel's own grid is read-only
    display, no drag-out; shrink back to standard size to adjust the pool
    via checkboxes or to reach the stepper/Generer button again."""

    STEP_BUTTON_SIZE = 32
    COUNT_DISPLAY_WIDTH = 60
    PANEL_WIDTH = 240
    MIN_COUNT = 1
    MAX_COUNT = 20

    MAX_WIDTH = 700
    MAX_HEIGHT = 900
    GRID_CARD_HEIGHT = 110
    GRID_CELL_SPACING = 14

    def __init__(self, room_manager, x=460, y=260, on_rename=None, on_delete=None, can_rename=None, renderer=None):

        self.room_manager = room_manager
        self.x = x
        self.y = y

        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 16)

        self.room_count = 3

        self.pool_browser = RoomBrowser(
            x, y + 26, width=self.PANEL_WIDTH, multi_select=True,
            on_rename=on_rename, on_delete=on_delete, can_rename=can_rename,
        )
        self.pool_browser.set_rooms(self.room_manager.scan(), preselect_all=True)

        stepper_y = self.pool_browser.y + self.pool_browser.height + 10
        self.stepper = Stepper(x, stepper_y, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, self.MIN_COUNT, self.MAX_COUNT)

        self.generate_rect = pygame.Rect(x, stepper_y + self.STEP_BUTTON_SIZE + 10, self.PANEL_WIDTH, 36)

        self.status_text = ""

        # Resizable, additive card grid (Vision produit v0.05 -- rooms as
        # cards). STANDARD_WIDTH/HEIGHT are this panel's own natural size,
        # computed here (not a class constant) since it depends on the
        # constructed sub-widgets' own layout.
        self.STANDARD_WIDTH = self.PANEL_WIDTH
        self.STANDARD_HEIGHT = (self.generate_rect.bottom + 10) - self.y
        self.width = self.STANDARD_WIDTH
        self.height = self.STANDARD_HEIGHT
        self._resizing = False
        self._resize_last_pos = None
        # Shared with Creator/CardPanelUI -- same composited-card cache, not
        # rebuilt/loaded a third time.
        self._renderer = renderer

    @property
    def _enlarged(self):
        return self.width > self.STANDARD_WIDTH or self.height > self.STANDARD_HEIGHT

    def move(self, dx, dy):
        """See PanelFrame, which drives this via drag/restore (superseded
        the old y-only set_y, used back when ObjectPalette's height change
        was the only thing that ever repositioned this panel -- now that
        the player can drag it directly, x needs to move too).
        pool_browser.x/.y are read fresh by its own _row_rect on every
        call, so a plain reassignment is enough there, but Stepper caches
        absolute rects at construction time -- those need an explicit
        move_ip, same for generate_rect."""
        if dx == 0 and dy == 0:
            return
        self.x += dx
        self.y += dy
        self.pool_browser.x += dx
        self.pool_browser.y += dy
        self.stepper.minus_rect.move_ip(dx, dy)
        self.stepper.count_rect.move_ip(dx, dy)
        self.stepper.plus_rect.move_ip(dx, dy)
        self.generate_rect.move_ip(dx, dy)

    def apply_profile(self, profile):
        """Seeds room_count/pool selection from a saved Profile (see
        core.data.profile_manager.Profile.generator_room_names/
        generator_room_count) -- called once, lazily, the first time
        Creator.run() has an actual player identity to load (Creator
        itself is constructed before Menu's name-entry screen has
        necessarily run, so this can't happen in __init__). A no-op if
        the profile has never saved a selection (generator_room_names
        empty -- a fresh profile), leaving today's "every room, count 3"
        constructor defaults in place rather than clearing the pool."""
        if not profile.generator_room_names:
            return
        self.room_count = profile.generator_room_count
        saved_names = set(profile.generator_room_names)
        self.pool_browser.selected_set = {
            i for i, name in enumerate(self.pool_browser.rooms) if name in saved_names
        }

    def refresh_rooms(self):
        """Call when the room list on disk may have changed (e.g. after a save/delete)."""
        previously_selected = set(self.pool_browser.selected_names)
        self.pool_browser.set_rooms(self.room_manager.scan())
        self.pool_browser.selected_set = {
            i for i, name in enumerate(self.pool_browser.rooms) if name in previously_selected
        }

    def contains(self, pos):
        # A superset of the old sub-widget-only check -- safe now that
        # width/height cover a real panel area (standard mode's rect still
        # equals pool_browser+stepper+generate_rect's own bounds).
        return pygame.Rect(self.x, self.y, self.width, self.height).collidepoint(pos)

    def _card_grid_rect(self):
        # Mirrors CardPanelUI._grid_area_rect -- enlarged mode shows
        # *nothing* else (list/stepper/button are hidden, see class
        # docstring), so the grid gets the whole panel below the title.
        return pygame.Rect(self.x, self.y + 34, self.width, self.height - 34)

    def _grid_columns(self):
        card_width = round(self.GRID_CARD_HEIGHT * CardRenderer.BACKING_SIZE[0] / CardRenderer.BACKING_SIZE[1])
        slot_w = card_width + self.GRID_CELL_SPACING
        return max(1, self._card_grid_rect().width // slot_w)

    def _render_card_grid(self, screen):
        """Read-only visual display of the rooms currently in the pool --
        no drag-out, no stacking (a room can only appear once), no scroll:
        pool sizes are small in practice, and this panel already caps out
        at MAX_HEIGHT (a deliberate simplification, see the plan)."""
        area = self._card_grid_rect()
        if area.height <= 0:
            return
        self.border.draw(screen, area)

        room_names = self.pool_browser.selected_names
        if not room_names:
            hint = self.font.render("Aucune salle dans le pool", True, (150, 150, 150))
            screen.blit(hint, (area.x + 10, area.y + 10))
            return

        card_width = round(self.GRID_CARD_HEIGHT * CardRenderer.BACKING_SIZE[0] / CardRenderer.BACKING_SIZE[1])
        slot_w = card_width + self.GRID_CELL_SPACING
        slot_h = self.GRID_CARD_HEIGHT + self.GRID_CELL_SPACING
        columns = self._grid_columns()

        previous_clip = screen.get_clip()
        screen.set_clip(area)
        for index, room_name in enumerate(room_names):
            row, col = divmod(index, columns)
            pos = (area.x + 8 + col * slot_w, area.y + 8 + row * slot_h)
            card = self._renderer.get_card(room_card_id(room_name))
            surface = self._renderer.get_surface(card, self.GRID_CARD_HEIGHT)
            screen.blit(surface, pos)
        screen.set_clip(previous_clip)

    def handle_event(self, event):
        """Returns (room_names, room_count) once "Generer" is clicked with a
        non-empty pool, else None. While enlarged, the list/stepper/button
        aren't shown at all (see class docstring) so none of them receive
        events either -- purely a read-only card grid, same as CardPanelUI's
        own enlarged mode reduces its own event handling."""

        if self._handle_resize_event(event):
            return None

        if self._enlarged:
            return None

        self.pool_browser.handle_event(event)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:

            new_count = self.stepper.handle_click(event.pos, self.room_count)
            if new_count is not None:
                self.room_count = new_count

            elif self.generate_rect.collidepoint(event.pos):
                room_names = self.pool_browser.selected_names
                if room_names:
                    return (room_names, self.room_count)

        return None

    def render(self, screen):

        if self._enlarged:
            self._render_card_grid(screen)
        else:
            self.pool_browser.render(screen)

            self.stepper.render(screen, self.border, self.font, self.room_count)

            enabled = bool(self.pool_browser.selected_names)
            self.border.draw_enabled_label(screen, self.generate_rect, self.font, "Generer", enabled)

            if self.status_text:
                status = self.font.render(self.status_text, True, (200, 200, 200))
                screen.blit(status, (self.x, self.generate_rect.bottom + 8))

        self._draw_resize_handle(screen)


# ---------------------------------------------------------------------
# Role panel (E/S role picker: gate/wall/cave_entrance/big_entrance)
# ---------------------------------------------------------------------
