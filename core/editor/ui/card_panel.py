"""CardPanelUI -- split out of the old monolithic core/editor/ui.py."""

import pygame

from core.ui.widgets import BorderManager, RoomBrowser
from core.world.object_manager import OBJECT_TYPES
from core.data.cards import CardManager, room_name_from_card_id
from core.data.profile_manager import ADMINGOD_STOCK
from core.editor.ui.mixins import _ResizableCornerMixin
from core.editor.ui.card_renderer import CardRenderer


class CardPanelUI(_ResizableCornerMixin):
    """Docked, always-draggable like every other Creator panel. At its
    default ("standard") size it's exactly the original read-only list:
    every known card (core.data.cards.CardManager.list_known_card_ids())
    with a text detail readout for whichever row is selected. Dragging the
    resize handle (bottom-right corner) past STANDARD_WIDTH switches to a
    visual grid of only the cards the player actually *owns* -- duplicates
    stack with a slight rightward offset, hovering a stack enlarges it
    +25% in place, and holding right-click on one blows it up at the
    center of the screen for as long as the button stays down (no modal to
    dismiss -- releasing just returns it to normal, see Creator._paint_at_
    mouse's own "no dismissal needed, purely momentary" precedent isn't
    literally reused code, just the same interaction philosophy)."""

    STANDARD_WIDTH = 280
    DETAIL_HEIGHT = 90
    MAX_WIDTH = 900
    MAX_HEIGHT = 700

    # Enlarged-mode grid layout (all in screen pixels at 1x -- this UI
    # doesn't share the world camera's zoom).
    GRID_CARD_HEIGHT = 120
    GRID_CELL_SPACING = 14
    STACK_OFFSET = 6
    STACK_MAX_VISIBLE = 5  # beyond this many copies, a "xN" badge instead of more offset copies
    HOVER_SCALE = 1.25
    FOCUS_HEIGHT = 420
    SLIDER_WIDTH = 12

    def __init__(self, x, y, renderer):
        self.x = x
        self.y = y
        self.width = self.STANDARD_WIDTH

        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 16)
        self.badge_font = pygame.font.SysFont("arial", 13, bold=True)

        self.browser = RoomBrowser(x, y + 34, width=self.width)
        self.detail_rect = pygame.Rect(x, self.browser.y + self.browser.height + 8, self.width, self.DETAIL_HEIGHT)
        # Standard mode's own total height, from the panel's own y down to
        # the bottom of the detail box -- also the minimum height a resize
        # can shrink back down to.
        self.STANDARD_HEIGHT = (self.browser.y + self.browser.height + 8 + self.DETAIL_HEIGHT) - self.y
        self.height = self.STANDARD_HEIGHT

        # card_id, in the same order as whatever's currently loaded into
        # self.browser -- RoomBrowser only ever tracks a selected *label*/
        # index, so this is what lets render() go from "which row is
        # selected" back to "which card is that" for the standard-mode
        # detail readout.
        self._card_ids = []
        # (card_id, count) for owned cards only, enlarged-mode's own list --
        # separate from _card_ids since standard mode still lists everything
        # known, not just owned.
        self._owned = []
        # card_id -> count, same data as _owned but keyed for O(1) lookup --
        # used by standard-mode drag-start (_handle_list_event), which needs
        # "is this card owned" for any row, not just the owned ones _owned
        # already enumerates.
        self._owned_counts = {}

        # Shared with Creator (drag-follow sprite, moving-object sprite) so
        # assets/cards/card.png and the composited-card cache are only ever
        # loaded/built once, not duplicated between this panel and Creator's
        # own drag rendering.
        self._renderer = renderer

        self._resizing = False
        self._resize_last_pos = None
        self._scroll_row = 0
        self._dragging_slider = False
        self._focused_card_id = None

    @property
    def _enlarged(self):
        return self.width > self.STANDARD_WIDTH or self.height > self.STANDARD_HEIGHT

    def move(self, dx, dy):
        """See PanelFrame, which drives this via drag/restore -- same shape
        as RoomPanelUI.move: self.browser recomputes its own child rects on
        demand (plain reassignment is enough), detail_rect is a cached Rect
        and needs its own move_ip. Enlarged-mode grid cell rects are never
        cached (recomputed fresh every frame from self.x/self.y in
        _stack_layout), so nothing else needs moving here."""
        self.x += dx
        self.y += dy
        self.browser.x += dx
        self.browser.y += dy
        self.detail_rect.move_ip(dx, dy)

    def contains(self, pos):
        return pygame.Rect(self.x, self.y, self.width, self.height).collidepoint(pos)

    def refresh(self, profile):
        """Reloads the card list from CardManager().list_known_card_ids()
        and each one's owned count from profile.card_collection. Called
        once per entry into Creator (see Creator._refresh_card_panel), same
        as _refresh_object_palette -- cheap enough (today's roster is under
        20 entries) to just rebuild outright rather than diff. Also clears
        the renderer's cache and resets scroll, since a fresh entry can
        follow a card_collection change (giving/spending cards) that the
        enlarged grid needs to reflect.

        clear_cache() runs BEFORE the loop below (not after, as it used to)
        so the loop's own self._renderer.get_card(card_id) calls populate a
        fresh cache instead of one that's immediately thrown away -- the
        very first render after a refresh no longer has to re-resolve every
        visible card from disk a second time."""
        self._renderer.clear_cache()
        self._card_ids = CardManager().list_known_card_ids()
        entries = []
        self._owned = []
        self._owned_counts = {}
        for card_id in self._card_ids:
            card = self._renderer.get_card(card_id)
            if card.card_type == "room":
                # A room-card's existence is 1:1 with its saved file, not a
                # card_collection stock -- always "owned" (see the Card
                # system's room-card plan).
                owned = 1
                entries.append(f"{card.name} ({card.card_type}) -- disponible")
            elif profile.admingod:
                # Every card reads as owned/unlimited under admingod,
                # regardless of what's actually in card_collection --
                # otherwise a card never explicitly granted (e.g. one just
                # registered via the sprite editor this session) wouldn't
                # even show up here to be dragged, since this panel only
                # ever lists owned > 0 cards.
                owned = ADMINGOD_STOCK
                entries.append(f"{card.name} ({card.card_type}) -- illimitees")
            else:
                owned = profile.card_collection.get(card_id, 0)
                entries.append(f"{card.name} ({card.card_type}) -- possedees: {owned}")
            self._owned_counts[card_id] = owned
            if owned > 0:
                self._owned.append((card_id, owned))
        self.browser.set_rooms(entries)
        self._scroll_row = 0

    # -- enlarged-mode grid layout/scroll --

    def _grid_area_rect(self):
        return pygame.Rect(self.x, self.y + 34, self.width - self.SLIDER_WIDTH - 4, self.height - 34)

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
        total_rows = -(-len(self._owned) // columns) if self._owned else 0  # ceil div
        return max(0, total_rows - self._visible_rows())

    def _stack_layout(self):
        """(card_id, count, rect) for every stack currently visible (post-
        scroll) in the grid -- the single source of truth used by both
        render() and _handle_grid_event() so hit-testing always matches
        what was actually drawn."""
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
        return pygame.Rect(self.x + self.width - self.SLIDER_WIDTH, self.y + 34, self.SLIDER_WIDTH, self.height - 34)

    def _slider_thumb_rect(self):
        track = self._slider_track_rect()
        max_scroll = self._max_scroll_rows()
        total_rows = max(1, self._visible_rows() + max_scroll)
        thumb_h = max(20, round(track.height * self._visible_rows() / total_rows))
        thumb_y = track.y if max_scroll == 0 else track.y + round((track.height - thumb_h) * self._scroll_row / max_scroll)
        return pygame.Rect(track.x, thumb_y, track.width, thumb_h)

    def _handle_grid_event(self, event):
        """Returns a card_id if this event just started dragging a
        placeable (OBJECT_LIST-backed) stack -- see handle_event."""
        max_scroll = self._max_scroll_rows()
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if max_scroll > 0 and self._slider_thumb_rect().collidepoint(event.pos):
                self._dragging_slider = True
                return None
            for card_id, _count, rect in self._stack_layout():
                # OBJECT_TYPES (a dict) instead of OBJECT_LIST (a plain
                # list, kept only for the palette's own display order) --
                # same membership, O(1) instead of O(len(OBJECT_LIST)) per
                # card checked here, and every OBJECT_LIST entry is always
                # also an OBJECT_TYPES key (register_custom_type/
                # _write_custom_type keep them in lockstep).
                if rect.collidepoint(event.pos) and (card_id in OBJECT_TYPES or room_name_from_card_id(card_id) is not None):
                    return card_id
            return None
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self._dragging_slider = False
            elif event.button == 3:
                self._focused_card_id = None
            return None
        elif event.type == pygame.MOUSEMOTION and self._dragging_slider:
            track = self._slider_track_rect()
            if track.height > 0 and max_scroll > 0:
                ratio = (event.pos[1] - track.y) / track.height
                self._scroll_row = max(0, min(max_scroll, round(ratio * max_scroll)))
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            for card_id, _count, rect in self._stack_layout():
                if rect.collidepoint(event.pos):
                    self._focused_card_id = card_id
                    break
        return None

    def _handle_list_event(self, event):
        """Returns a card_id if this event just started dragging a
        placeable, owned card from the standard-mode list -- checked in
        addition to (not instead of) the normal row-selection click, so
        the detail readout keeps working exactly as before."""
        drag_card_id = None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            row_index = self.browser.row_at(event.pos)
            if row_index is not None and 0 <= row_index < len(self._card_ids):
                card_id = self._card_ids[row_index]
                draggable = card_id in OBJECT_TYPES or room_name_from_card_id(card_id) is not None
                if draggable and self._owned_counts.get(card_id, 0) > 0:
                    drag_card_id = card_id
        self.browser.handle_event(event)
        return drag_card_id

    def handle_event(self, event):
        """Returns a card_id if this event just started a drag on a
        placeable (OBJECT_LIST-backed), owned card -- from either display
        mode (see class docstring) -- so Creator can turn that into
        object_tool.start_drag(card_id, event.pos). None otherwise
        (resize/scroll/focus/selection all still work exactly as before,
        just via this same call)."""
        if self._handle_resize_event(event):
            return None
        if self._enlarged:
            return self._handle_grid_event(event)
        return self._handle_list_event(event)

    def handle_wheel(self, pos, direction):
        """Scrolls while `pos` (pygame.mouse.get_pos(), Creator's own
        caller) is anywhere over this panel -- confirmed with the user:
        hovering the panel should be enough, not just grabbing the thin
        slider thumb precisely. Enlarged mode scrolls its own row-based
        _scroll_row directly (no RoomBrowser involved there); standard mode
        delegates to self.browser's own RoomBrowser.handle_wheel. Returns
        True if consumed, so Creator knows not to fall through to zooming
        the world camera instead (see Creator's own MOUSEWHEEL handling)."""
        if self._enlarged:
            if not self.contains(pos):
                return False
            max_scroll = self._max_scroll_rows()
            if max_scroll <= 0:
                return False
            self._scroll_row = max(0, min(max_scroll, self._scroll_row - direction))
            return True
        return self.browser.handle_wheel(pos, direction)

    # -- render --

    def render(self, screen):
        if self._enlarged:
            self._render_grid(screen)
        else:
            self._render_standard(screen)

        self._draw_resize_handle(screen)

    def _render_standard(self, screen):
        self.browser.render(screen)

        self.border.draw(screen, self.detail_rect)
        if self.browser.selected is not None and 0 <= self.browser.selected < len(self._card_ids):
            card_id = self._card_ids[self.browser.selected]
            card = self._renderer.get_card(card_id)
            room_name = room_name_from_card_id(card_id)
            if room_name is not None:
                props = self._renderer.get_room_properties(room_name)
                lines = [
                    f"Nom : {card.name}",
                    f"Dimensions : {props['width']}x{props['height']}",
                    f"E/S : {props['es_count']}",
                    f"Objets : {sum(props['entities'].values())}",
                    f"Contenu du pack : {sum(props['manifest'].values())} cartes",
                ]
            else:
                lines = [
                    f"Nom : {card.name}",
                    f"Type : {card.card_type}",
                    f"Images : {len(card.images)}",
                    f"Effets : {len(card.effects)}",
                ]
                if card.card_type == "pnj":
                    is_complete, missing = self._renderer.get_completeness(card)
                    lines.append("Complet" if is_complete else "Manque : " + ", ".join(missing))
            for index, line in enumerate(lines):
                surface = self.font.render(line, True, (220, 220, 220))
                screen.blit(surface, (self.detail_rect.x + 8, self.detail_rect.y + 6 + index * 20))
        else:
            hint = self.font.render("Selectionnez une carte", True, (150, 150, 150))
            screen.blit(hint, (self.detail_rect.x + 8, self.detail_rect.y + 6))

    def _render_grid(self, screen):
        area = self._grid_area_rect()
        self.border.draw(screen, pygame.Rect(self.x, area.y, self.width, area.height))

        if not self._owned:
            hint = self.font.render("Aucune carte possedee", True, (150, 150, 150))
            screen.blit(hint, (area.x + 10, area.y + 10))
            return

        mouse_pos = pygame.mouse.get_pos()
        previous_clip = screen.get_clip()
        screen.set_clip(area)

        deferred_hover = None
        for card_id, count, rect in self._stack_layout():
            if rect.collidepoint(mouse_pos):
                deferred_hover = (card_id, count, rect)
                continue
            self._draw_stack(screen, self._renderer.get_card(card_id), count, rect, self.GRID_CARD_HEIGHT)

        # The hovered stack is drawn last (on top of its neighbors) and at
        # HOVER_SCALE, centered on its own slot -- see class docstring.
        if deferred_hover is not None:
            card_id, count, rect = deferred_hover
            self._draw_stack(screen, self._renderer.get_card(card_id), count, rect, round(self.GRID_CARD_HEIGHT * self.HOVER_SCALE), center_on=rect.center)

        screen.set_clip(previous_clip)

        if self._max_scroll_rows() > 0:
            self.border.draw(screen, self._slider_track_rect())
            pygame.draw.rect(screen, (150, 150, 150), self._slider_thumb_rect())

        if self._focused_card_id is not None:
            focused_card = self._renderer.get_card(self._focused_card_id)
            surface = self._renderer.get_surface(focused_card, self.FOCUS_HEIGHT)
            screen.blit(surface, (screen.get_width() / 2 - surface.get_width() / 2, screen.get_height() / 2 - surface.get_height() / 2))

    def _draw_stack(self, screen, card, count, slot_rect, pixel_height, center_on=None):
        """Up to STACK_MAX_VISIBLE copies, each offset STACK_OFFSET px to
        the right of the previous, back-to-front (the last one drawn -- the
        rightmost -- is the fully visible "top" of the stack). Beyond that
        many copies, a "xN" badge on the top card instead of more offset
        (an unbounded stack would eventually overflow neighboring slots)."""
        surface = self._renderer.get_surface(card, pixel_height)
        visible_copies = min(count, self.STACK_MAX_VISIBLE)
        offset = round(self.STACK_OFFSET * (pixel_height / self.GRID_CARD_HEIGHT))

        if center_on is not None:
            base_x = center_on[0] - surface.get_width() / 2 - offset * (visible_copies - 1) / 2
            base_y = center_on[1] - surface.get_height() / 2
        else:
            base_x = slot_rect.x
            base_y = slot_rect.y

        for copy_index in range(visible_copies):
            screen.blit(surface, (base_x + copy_index * offset, base_y))

        if count > self.STACK_MAX_VISIBLE:
            badge_text = f"x{count}"
            badge = self.badge_font.render(badge_text, True, (255, 255, 255))
            badge_bg = pygame.Rect(0, 0, badge.get_width() + 6, badge.get_height() + 4)
            badge_bg.bottomright = (base_x + (visible_copies - 1) * offset + surface.get_width(), base_y + surface.get_height())
            pygame.draw.rect(screen, (30, 30, 30), badge_bg, border_radius=4)
            screen.blit(badge, (badge_bg.x + 3, badge_bg.y + 2))

        is_complete, _missing = self._renderer.get_completeness(card)
        if not is_complete:
            # Top-left corner, opposite the "xN" stack badge above (bottom-
            # right) -- no overlap. Orange "!" -- a PNJ registered from a
            # single tagged tile (see object_manager.register_npc_type) is
            # a normal, expected in-progress state, not an error, so this
            # flags rather than alarms.
            warn = self.badge_font.render("!", True, (30, 20, 0))
            warn_bg = pygame.Rect(0, 0, warn.get_width() + 8, warn.get_height() + 6)
            warn_bg.topleft = (base_x, base_y)
            pygame.draw.rect(screen, (240, 160, 40), warn_bg, border_radius=4)
            screen.blit(warn, (warn_bg.x + 4, warn_bg.y + 3))


# ---------------------------------------------------------------------
# Generator panel (procedural assembler)
# ---------------------------------------------------------------------
