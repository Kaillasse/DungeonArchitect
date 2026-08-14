"""StashPanelUI -- shows cards found during a run (Profile.card_stash, see
core.world.entities.CardPickup/Explorator._bank_found_cards) but not yet
deposited into the permanent collection (Profile.card_collection). A found
card is only ever "real" once dragged from here onto CardPanelUI (see
Creator._resolve_dragged_card's "stash" drag_source branch) -- nothing here
is placeable in the world or openable in the Forge, unlike an owned
collection card.

Deliberately much smaller than CardPanelUI: a single fixed-size icon grid
(same visual idiom as CardPanelUI's enlarged mode -- stacked copies via
CardRenderer, see _draw_stack there), no list/detail mode, no resize handle,
no right-click focus-zoom. This is a utility panel, not the primary card
browsing experience.
"""

import pygame

from core.ui.widgets import BorderManager
from core.editor.ui.card_renderer import CardRenderer


class StashPanelUI:
    WIDTH = 220
    HEIGHT = 160
    TITLE_OFFSET = 8

    GRID_CARD_HEIGHT = 72
    GRID_CELL_SPACING = 10
    STACK_MAX_VISIBLE = 3
    STACK_OFFSET = 4
    SLIDER_WIDTH = 10

    def __init__(self, x, y, renderer):
        self.x = x
        self.y = y
        self.width = self.WIDTH
        self.height = self.HEIGHT

        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 16)
        self.badge_font = pygame.font.SysFont("arial", 13, bold=True)

        # Shared with CardPanelUI/Creator -- same reasoning as CardPanelUI's
        # own self._renderer: one composited-card cache, not a second one.
        self._renderer = renderer

        # (card_id, count), owned>0 only -- rebuilt by refresh().
        self._owned = []
        self._scroll_row = 0
        self._dragging_slider = False

    def move(self, dx, dy):
        self.x += dx
        self.y += dy

    def contains(self, pos):
        return pygame.Rect(self.x, self.y, self.width, self.height).collidepoint(pos)

    def refresh(self, profile):
        """Reloads from profile.card_stash -- called wherever Creator
        already calls _refresh_card_panel, same "cheap enough to rebuild
        outright" reasoning (a run rarely banks more than a handful of
        distinct card ids)."""
        renderer = self._renderer
        renderer.clear_cache()
        self._owned = [
            (card_id, count) for card_id, count in profile.card_stash.items() if count > 0
        ]
        self._scroll_row = 0

    # -- grid layout/scroll (mirrors CardPanelUI's enlarged mode, fixed size) --

    def _grid_area_rect(self):
        return pygame.Rect(
            self.x, self.y + self.TITLE_OFFSET + 20, self.width - self.SLIDER_WIDTH - 4,
            self.height - self.TITLE_OFFSET - 20,
        )

    def _slot_size(self):
        stack_extra = self.STACK_OFFSET * (self.STACK_MAX_VISIBLE - 1)
        card_width = round(self.GRID_CARD_HEIGHT * CardRenderer.BACKING_SIZE[0] / CardRenderer.BACKING_SIZE[1])
        return (
            card_width + stack_extra + self.GRID_CELL_SPACING,
            self.GRID_CARD_HEIGHT + self.GRID_CELL_SPACING,
        )

    def _columns(self):
        slot_w, _ = self._slot_size()
        return max(1, self._grid_area_rect().width // slot_w)

    def _visible_rows(self):
        _, slot_h = self._slot_size()
        return max(1, self._grid_area_rect().height // slot_h)

    def _max_scroll_rows(self):
        columns = self._columns()
        total_rows = -(-len(self._owned) // columns) if self._owned else 0
        return max(0, total_rows - self._visible_rows())

    def _stack_layout(self):
        area = self._grid_area_rect()
        slot_w, slot_h = self._slot_size()
        columns = self._columns()
        layout = []
        for index, (card_id, count) in enumerate(self._owned):
            row, col = divmod(index, columns)
            row -= self._scroll_row
            if row < 0 or row >= self._visible_rows():
                continue
            rect = pygame.Rect(area.x + col * slot_w, area.y + row * slot_h, slot_w, slot_h)
            layout.append((card_id, count, rect))
        return layout

    def _slider_track_rect(self):
        return pygame.Rect(
            self.x + self.width - self.SLIDER_WIDTH, self._grid_area_rect().y,
            self.SLIDER_WIDTH, self._grid_area_rect().height,
        )

    def _slider_thumb_rect(self):
        track = self._slider_track_rect()
        max_scroll = self._max_scroll_rows()
        total_rows = max(1, self._visible_rows() + max_scroll)
        thumb_h = max(16, round(track.height * self._visible_rows() / total_rows))
        thumb_y = track.y if max_scroll == 0 else track.y + round((track.height - thumb_h) * self._scroll_row / max_scroll)
        return pygame.Rect(track.x, thumb_y, track.width, thumb_h)

    def handle_event(self, event):
        """Returns a card_id if this event just started dragging a stash
        entry -- unlike CardPanelUI, no placeable-type gate at all: every
        entry here is by definition something the player found and can
        deposit, regardless of card_type."""
        max_scroll = self._max_scroll_rows()
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if max_scroll > 0 and self._slider_thumb_rect().collidepoint(event.pos):
                self._dragging_slider = True
                return None
            for card_id, _count, rect in self._stack_layout():
                if rect.collidepoint(event.pos):
                    return card_id
            return None
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging_slider = False
            return None
        if event.type == pygame.MOUSEMOTION and self._dragging_slider:
            track = self._slider_track_rect()
            if track.height > 0 and max_scroll > 0:
                ratio = (event.pos[1] - track.y) / track.height
                self._scroll_row = max(0, min(max_scroll, round(ratio * max_scroll)))
        return None

    def handle_wheel(self, pos, direction):
        if not self.contains(pos):
            return False
        max_scroll = self._max_scroll_rows()
        if max_scroll <= 0:
            return False
        self._scroll_row = max(0, min(max_scroll, self._scroll_row - direction))
        return True

    def render(self, screen):
        title = self.font.render("Cartes trouvees", True, (220, 220, 220))
        screen.blit(title, (self.x + 4, self.y))

        area = self._grid_area_rect()
        self.border.draw(screen, pygame.Rect(self.x, area.y, self.width, area.height))

        if not self._owned:
            hint = self.badge_font.render("(vide)", True, (150, 150, 150))
            screen.blit(hint, (area.x + 10, area.y + 10))
            return

        previous_clip = screen.get_clip()
        screen.set_clip(area)
        for card_id, count, rect in self._stack_layout():
            self._draw_stack(screen, self._renderer.get_card(card_id), count, rect)
        screen.set_clip(previous_clip)

        if self._max_scroll_rows() > 0:
            self.border.draw(screen, self._slider_track_rect())
            pygame.draw.rect(screen, (150, 150, 150), self._slider_thumb_rect())

    def _draw_stack(self, screen, card, count, slot_rect):
        """Same "up to STACK_MAX_VISIBLE offset copies, then a xN badge"
        idiom as CardPanelUI._draw_stack, simplified (no hover-enlarge,
        no completeness warning -- a found card is never "incomplete", a
        PNJ can't be earned as loot)."""
        surface = self._renderer.get_surface(card, self.GRID_CARD_HEIGHT)
        visible_copies = min(count, self.STACK_MAX_VISIBLE)

        for copy_index in range(visible_copies):
            screen.blit(surface, (slot_rect.x + copy_index * self.STACK_OFFSET, slot_rect.y))

        if count > self.STACK_MAX_VISIBLE:
            badge_text = f"x{count}"
            badge = self.badge_font.render(badge_text, True, (255, 255, 255))
            badge_bg = pygame.Rect(0, 0, badge.get_width() + 6, badge.get_height() + 4)
            badge_bg.bottomright = (
                slot_rect.x + (visible_copies - 1) * self.STACK_OFFSET + surface.get_width(),
                slot_rect.y + surface.get_height(),
            )
            pygame.draw.rect(screen, (30, 30, 30), badge_bg, border_radius=4)
            screen.blit(badge, (badge_bg.x + 3, badge_bg.y + 2))
