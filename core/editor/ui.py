"""UI helpers for the dungeon editor."""

from __future__ import annotations

from pathlib import Path

import pygame

from core.ui.widgets import BorderManager, RoomBrowser, Stepper
from core.world.object_manager import OBJECT_LIST, CURRENCY_FILES, ITEM_DEFINITIONS
from core.data.ressources import list_donjons, DEFAULT_ANIM_SPEED
from core.data.cards import CardManager, resolve_card_sprite, room_card_id, room_name_from_card_id, room_card_properties

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _ResizableCornerMixin:
    """Shared bottom-right resize-handle drag state/hit-test, used by both
    CardPanelUI and GeneratorPanelUI -- kept out of PanelFrame (which wraps
    5 panels total, only 2 of which need resize) per the same reasoning
    CardPanelUI's own resize handle was originally kept panel-local for. A
    subclass must set self.x/self.y/self.width/self.height/self._resizing/
    self._resize_last_pos and the class constants STANDARD_WIDTH/
    STANDARD_HEIGHT/MAX_WIDTH/MAX_HEIGHT before this is used."""

    RESIZE_HANDLE_SIZE = 14

    def _resize_handle_rect(self):
        size = self.RESIZE_HANDLE_SIZE
        return pygame.Rect(self.x + self.width - size, self.y + self.height - size, size, size)

    def _handle_resize_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._resize_handle_rect().collidepoint(event.pos):
                self._resizing = True
                self._resize_last_pos = event.pos
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._resizing:
                self._resizing = False
                self._resize_last_pos = None
                return True
        elif event.type == pygame.MOUSEMOTION and self._resizing and self._resize_last_pos is not None:
            dx = event.pos[0] - self._resize_last_pos[0]
            dy = event.pos[1] - self._resize_last_pos[1]
            self.width = max(self.STANDARD_WIDTH, min(self.MAX_WIDTH, self.width + dx))
            self.height = max(self.STANDARD_HEIGHT, min(self.MAX_HEIGHT, self.height + dy))
            self._resize_last_pos = event.pos
            return True
        return False

    def _draw_resize_handle(self, screen):
        handle_rect = self._resize_handle_rect()
        pygame.draw.polygon(
            screen, (200, 200, 200),
            [(handle_rect.right, handle_rect.top), (handle_rect.right, handle_rect.bottom), (handle_rect.left, handle_rect.bottom)],
        )

# ---------------------------------------------------------------------
# Tool palette
# ---------------------------------------------------------------------


class ToolPaletteUI:
    """"Tuile de base" panel -- two independent toggle buttons, Sol (floor)
    and Mur (wall), each showing its own remaining card stock (see
    core.data.cards' "tile_floor"/"tile_wall" -- Vision produit v0.05's
    Card system, tools connected to the collection). Replaces the old
    "Outils" panel's purely-decorative "Sol" label plus a single separate
    Autotile ON/OFF toggle: Creator now derives autotile_enabled itself as
    floor_tool_active AND wall_tool_active (both buttons active = today's
    default full-autotile paint behavior; exactly one active = a raw,
    non-autotile Sol-only or Mur-only paint -- see
    Creator._paint_at_mouse). This class only ever reports which rect was
    clicked -- it owns neither the active/inactive state nor the stock
    numbers, both live on Creator (same "the panel doesn't own the toggled
    state" convention the old hit_autotile_toggle already followed)."""

    def __init__(self, width: int = 220, height: int = 132):

        self.width = width
        self.height = height

        self.x = 10
        self.y = 10

        self.font = pygame.font.SysFont("arial", 18)
        self.title_font = pygame.font.SysFont("arial", 20)

        self.border = BorderManager()

    # -------------------------------------------------------------

    def move(self, dx, dy):
        """Every rect here (_floor_rect/_wall_rect) is already recomputed
        from self.x/self.y on demand, so shifting the origin is enough --
        see PanelFrame, which drives this via drag/restore."""
        self.x += dx
        self.y += dy

    def _floor_rect(self):
        return pygame.Rect(self.x + 12, self.y + 40, self.width - 24, 30)

    def _wall_rect(self):
        return pygame.Rect(self.x + 12, self.y + 74, self.width - 24, 28)

    # -------------------------------------------------------------

    def render(self, screen, floor_active=True, wall_active=True, floor_stock=0, wall_stock=0):

        panel_rect = pygame.Rect(
            self.x,
            self.y,
            self.width,
            self.height,
        )

        self.border.draw(screen, panel_rect)

        screen.blit(
            self.title_font.render("Tuile de base", True, (255, 255, 255)),
            (self.x + 16, self.y + 12),
        )

        floor_rect = self._floor_rect()
        self.border.draw(screen, floor_rect)

        screen.blit(
            self.font.render(
                f"Sol ({floor_stock})",
                True,
                (255, 255, 255) if floor_active else (200, 140, 60),
            ),
            (floor_rect.x + 12, floor_rect.y + 5),
        )

        wall_rect = self._wall_rect()
        self.border.draw(screen, wall_rect)

        screen.blit(
            self.font.render(
                f"Mur ({wall_stock})",
                True,
                (255, 255, 255) if wall_active else (200, 140, 60),
            ),
            (wall_rect.x + 10, wall_rect.y + 4),
        )

        screen.blit(
            self.font.render(
                "Clic droit : effacer",
                True,
                (180, 180, 180),
            ),
            (self.x + 12, self.y + 108),
        )

    # -------------------------------------------------------------

    def hit_floor_toggle(self, position: tuple[int, int]) -> bool:
        return self._floor_rect().collidepoint(position)

    def hit_wall_toggle(self, position: tuple[int, int]) -> bool:
        return self._wall_rect().collidepoint(position)

    def contains(self, position: tuple[int, int]) -> bool:
        x, y = position
        return (
            self.x <= x <= self.x + self.width
            and self.y <= y <= self.y + self.height
        )

    def handle_click(self, position: tuple[int, int]) -> bool:
        # Despite the name, this has always been a pure containment check
        # (nothing here mutates state) -- kept as-is since Creator already
        # calls it; contains() above is the same check under the name
        # PanelFrame expects from every wrapped panel.
        return self.contains(position)


# ---------------------------------------------------------------------
# Room panel (save / load / delete)
# ---------------------------------------------------------------------


class RoomPanelUI:
    """3-button save/load/delete panel; each opens a RoomBrowser sub-panel with a Valider button."""

    NEW_ROOM_LABEL = "+ Nouvelle salle"

    BUTTON_WIDTH = 100
    BUTTON_HEIGHT = 36
    LABELS_ACTIONS = (
        ("Sauvegarder", "save"),
        ("Charger", "load"),
        ("Supprimer", "delete"),
    )

    def __init__(self, room_manager, x=460, y=10, on_rename=None, on_delete=None, can_rename=None):

        self.room_manager = room_manager
        self.x = x
        self.y = y

        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 16)

        self.mode = None

        self.width = self.BUTTON_WIDTH * len(self.LABELS_ACTIONS)
        self.browser = RoomBrowser(
            x, y + self.BUTTON_HEIGHT + 8, width=self.width,
            on_rename=on_rename, on_delete=on_delete, can_rename=can_rename,
        )
        self.confirm_rect = pygame.Rect(x, self.browser.y + self.browser.height + 8, self.width, 32)

    def move(self, dx, dy):
        """See PanelFrame, which drives this via drag/restore. self.browser
        recomputes its own child rects from browser.x/browser.y on demand
        (RoomBrowser, unlike Stepper, never caches an absolute rect), so a
        plain reassignment is enough there; confirm_rect is a plain cached
        Rect and needs its own move_ip."""
        self.x += dx
        self.y += dy
        self.browser.x += dx
        self.browser.y += dy
        self.confirm_rect.move_ip(dx, dy)

    def _button_rect(self, index):
        return pygame.Rect(self.x + index * self.BUTTON_WIDTH, self.y, self.BUTTON_WIDTH, self.BUTTON_HEIGHT)

    def _open(self, mode):
        self.mode = mode

        if mode == "load":
            entries = [(f"[Salle] {name}", ("room", name)) for name in self.room_manager.scan()]
            entries += [(f"[Donjon] {name}", ("donjon", name)) for name in list_donjons()]
            self.browser.set_rooms(entries)
            return

        rooms = self.room_manager.scan()
        if mode == "save":
            rooms = [self.NEW_ROOM_LABEL] + rooms
        self.browser.set_rooms(rooms)

    def refresh_rooms(self):
        """Call after a room's name changed/disappeared on disk (a rename
        or delete via the browser's own right-click menu -- see
        Creator._rename_room/_delete_room) so a currently-open list
        reflects it immediately instead of showing a stale name until
        Sauvegarder/Charger/Supprimer is clicked again. A no-op while no
        mode is open (self.browser isn't showing anything to refresh)."""
        if self.mode is not None:
            self._open(self.mode)

    def contains(self, pos):

        for index in range(len(self.LABELS_ACTIONS)):
            if self._button_rect(index).collidepoint(pos):
                return True

        if self.mode is None:
            return False

        return self.browser.contains(pos) or self.confirm_rect.collidepoint(pos)

    def handle_event(self, event):
        """Returns (mode, room_name) once the user confirms a selection, else None."""

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:

            for index, (_, action) in enumerate(self.LABELS_ACTIONS):
                if self._button_rect(index).collidepoint(event.pos):
                    self._open(action)
                    return None

            if (
                self.mode is not None
                and self.confirm_rect.collidepoint(event.pos)
                and self.browser.selected_name is not None
            ):
                name = self.browser.selected_name

                if name == self.NEW_ROOM_LABEL:
                    name = self.room_manager.next_new_room_name()

                mode = self.mode
                self.mode = None

                return (mode, name)

        if self.mode is not None:
            self.browser.handle_event(event)

        return None

    def render(self, screen):

        for index, (label, _) in enumerate(self.LABELS_ACTIONS):
            self.border.draw_centered_label(screen, self._button_rect(index), self.font, label)

        if self.mode is None:
            return

        self.browser.render(screen)

        enabled = self.browser.selected_name is not None
        self.border.draw_enabled_label(screen, self.confirm_rect, self.font, "Valider", enabled)


# ---------------------------------------------------------------------
# Card rendering (Vision produit v0.05 -- visual card collection).
# Composites a Card's sprite/name/type/effects onto the shared 64x96
# assets/cards/card.png backing -- see CardPanelUI, the only caller.
# ---------------------------------------------------------------------


class CardRenderer:
    """Renders one Card as a trading-card-style image at whatever
    pixel_height the caller needs (the grid's base size, its hover size, or
    the right-click-hold focus size), caching the finished composite by
    (card_id, pixel_height) -- compositing (scaling the backing, resolving
    a sprite, rendering three lines of text) is too expensive to redo every
    frame for every visible card."""

    BACKING_PATH = "cards/card.png"
    BACKING_SIZE = (64, 96)  # w, h -- the source asset's own aspect ratio

    def __init__(self):
        self._backing = pygame.image.load(PROJECT_ROOT / "assets" / self.BACKING_PATH).convert_alpha()
        self._cache = {}
        self._sprite_cache = {}

    def clear_cache(self):
        """Called by CardPanelUI.refresh() -- a freshly reloaded card's
        name/type/effects (or, later, a card-editing UI's changes) must not
        keep showing a stale composited image."""
        self._cache.clear()
        self._sprite_cache.clear()

    def get_surface(self, card, pixel_height):
        key = (card.card_id, pixel_height)
        surface = self._cache.get(key)
        if surface is None:
            surface = self._compose(card, pixel_height)
            self._cache[key] = surface
        return surface

    def _sprite_for(self, card_id):
        if card_id not in self._sprite_cache:
            self._sprite_cache[card_id] = resolve_card_sprite(card_id)
        return self._sprite_cache[card_id]

    @staticmethod
    def _render_fitted(font, text, color, max_width):
        """font.render(text), shrunk with a trailing "..." if it would
        overflow max_width -- bridged card names/effect lists are short
        today, but this keeps a future longer custom name from spilling
        off the card instead of silently overflowing."""
        surface = font.render(text, True, color)
        if surface.get_width() <= max_width or not text:
            return surface
        truncated = text
        while truncated and font.render(truncated + "...", True, color).get_width() > max_width:
            truncated = truncated[:-1]
        return font.render((truncated + "...") if truncated else "...", True, color)

    def _compose(self, card, pixel_height):
        width = max(1, round(pixel_height * self.BACKING_SIZE[0] / self.BACKING_SIZE[1]))
        surface = pygame.transform.scale(self._backing, (width, pixel_height)).copy()
        text_max_width = width - round(width * 0.1)

        name_font = pygame.font.SysFont("arial", max(8, round(pixel_height * 0.09)), bold=True)
        label_font = pygame.font.SysFont("arial", max(7, round(pixel_height * 0.055)))

        name_surface = self._render_fitted(name_font, card.name, (25, 25, 25), text_max_width)
        surface.blit(name_surface, (width / 2 - name_surface.get_width() / 2, pixel_height * 0.05))

        # A room card's "sprite" is a small top-down schematic of its own
        # saved layout (see cards.render_room_thumbnail, resolved through
        # resolve_card_sprite exactly like any other card type) -- flows
        # through this exact same generic box/scale code, no special case
        # needed here anymore.
        sprite = self._sprite_for(card.card_id)
        if sprite is not None:
            box_top = pixel_height * 0.18
            box_size = pixel_height * 0.45
            scale = box_size / max(sprite.get_width(), sprite.get_height())
            sw = max(1, round(sprite.get_width() * scale))
            sh = max(1, round(sprite.get_height() * scale))
            scaled_sprite = pygame.transform.scale(sprite, (sw, sh))
            surface.blit(scaled_sprite, (width / 2 - sw / 2, box_top + box_size / 2 - sh / 2))

        type_surface = self._render_fitted(label_font, card.card_type, (50, 50, 50), text_max_width)
        surface.blit(type_surface, (width / 2 - type_surface.get_width() / 2, pixel_height * 0.70))

        # card.effects is empty for virtually every card today -- no effect
        # engine exists yet (see core.data.cards module docstring), so this
        # almost always reads "Aucun effet". Kept generic (not hardcoded)
        # so a future hand-authored card with real effects renders them
        # here for free.
        effects_text = ", ".join(effect.get("kind", "?") for effect in card.effects) if card.effects else "Aucun effet"
        effects_surface = self._render_fitted(label_font, effects_text, (70, 70, 70), text_max_width)
        surface.blit(effects_surface, (width / 2 - effects_surface.get_width() / 2, pixel_height * 0.84))

        return surface


# ---------------------------------------------------------------------
# Card panel (Vision produit v0.05's Card system). Standard size: the
# original read-only list+detail view, unchanged. Enlarged (drag the
# bottom-right corner): a visual grid of the player's actual collection --
# see CardPanelUI's own docstring.
# ---------------------------------------------------------------------


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
        self.title_font = pygame.font.SysFont("arial", 18)
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
        self._hovered_card_id = None
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
        enlarged grid needs to reflect."""
        manager = CardManager()
        self._card_ids = manager.list_known_card_ids()
        entries = []
        self._owned = []
        self._owned_counts = {}
        for card_id in self._card_ids:
            card = manager.load(card_id)
            if card.card_type == "room":
                # A room-card's existence is 1:1 with its saved file, not a
                # card_collection stock -- always "owned" (see the Card
                # system's room-card plan).
                owned = 1
                entries.append(f"{card.name} ({card.card_type}) -- disponible")
            else:
                owned = profile.card_collection.get(card_id, 0)
                entries.append(f"{card.name} ({card.card_type}) -- possedees: {owned}")
            self._owned_counts[card_id] = owned
            if owned > 0:
                self._owned.append((card_id, owned))
        self.browser.set_rooms(entries)
        self._renderer.clear_cache()
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
                if rect.collidepoint(event.pos) and (card_id in OBJECT_LIST or room_name_from_card_id(card_id) is not None):
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
                draggable = card_id in OBJECT_LIST or room_name_from_card_id(card_id) is not None
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

    # -- render --

    def render(self, screen):
        title = self.title_font.render("Cartes", True, (255, 255, 255))
        screen.blit(title, (self.x, self.y))

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
            card = CardManager().load(card_id)
            room_name = room_name_from_card_id(card_id)
            if room_name is not None:
                props = room_card_properties(room_name)
                lines = [
                    f"Nom : {card.name}",
                    f"Dimensions : {props['width']}x{props['height']}",
                    f"E/S : {props['es_count']}",
                    f"Objets : {sum(props['entities'].values())}",
                ]
            else:
                lines = [
                    f"Nom : {card.name}",
                    f"Type : {card.card_type}",
                    f"Images : {len(card.images)}",
                    f"Effets : {len(card.effects)}",
                ]
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

        self._hovered_card_id = None
        deferred_hover = None
        manager = CardManager()
        for card_id, count, rect in self._stack_layout():
            if rect.collidepoint(mouse_pos):
                self._hovered_card_id = card_id
                deferred_hover = (card_id, count, rect)
                continue
            self._draw_stack(screen, manager.load(card_id), count, rect, self.GRID_CARD_HEIGHT)

        # The hovered stack is drawn last (on top of its neighbors) and at
        # HOVER_SCALE, centered on its own slot -- see class docstring.
        if deferred_hover is not None:
            card_id, count, rect = deferred_hover
            self._draw_stack(screen, manager.load(card_id), count, rect, round(self.GRID_CARD_HEIGHT * self.HOVER_SCALE), center_on=rect.center)

        screen.set_clip(previous_clip)

        if self._max_scroll_rows() > 0:
            self.border.draw(screen, self._slider_track_rect())
            pygame.draw.rect(screen, (150, 150, 150), self._slider_thumb_rect())

        if self._focused_card_id is not None:
            focused_card = manager.load(self._focused_card_id)
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


# ---------------------------------------------------------------------
# Generator panel (procedural assembler)
# ---------------------------------------------------------------------


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
        self.title_font = pygame.font.SysFont("arial", 18)

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
        manager = CardManager()

        previous_clip = screen.get_clip()
        screen.set_clip(area)
        for index, room_name in enumerate(room_names):
            row, col = divmod(index, columns)
            pos = (area.x + 8 + col * slot_w, area.y + 8 + row * slot_h)
            card = manager.load(room_card_id(room_name))
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

        title = self.title_font.render("Generation procedurale", True, (255, 255, 255))
        screen.blit(title, (self.x, self.y))

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


class RolePanelUI:
    """Opened by right-clicking a placed E/S object's indicator dot (see
    Creator's event loop -- ObjectManager.is_es_type; left-click on the
    same dot keeps its existing meaning, either a chest's ChestPanelUI or
    gate/wall's link-drag, unchanged). Lets the room designer pick this
    object's role -- "connector" (today's default, an ordinary inter-room
    link), "dungeon_entrance" (only ever meaningful in home -- see
    ObjectManager.ES_ROLES/set_role), or "dungeon_exit" (a new win
    condition). "Entree de donjon" is greyed out unless the caller says
    the current room allows it (Creator._is_home_room()) -- the room
    restriction lives in Creator, this widget just renders whatever it's
    told. Same modal-while-open shape as ChestPanelUI."""

    ROW_HEIGHT = 34
    ROW_SPACING = 8
    PANEL_WIDTH = 260

    ROLES = (
        ("connector", "Classique"),
        ("dungeon_entrance", "Entree de donjon"),
        ("dungeon_exit", "Sortie de donjon"),
    )

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 16)
        self.title_font = pygame.font.SysFont("arial", 18)
        self.obj = None  # the placed object dict currently being edited, or None if closed
        self.allow_dungeon_entrance = False

    @property
    def is_open(self):
        return self.obj is not None

    def open(self, obj, allow_dungeon_entrance):
        self.obj = obj
        self.allow_dungeon_entrance = allow_dungeon_entrance

    def close(self):
        self.obj = None

    def _row_rect(self, index):
        y = self.y + 30 + index * (self.ROW_HEIGHT + self.ROW_SPACING)
        return pygame.Rect(self.x, y, self.PANEL_WIDTH, self.ROW_HEIGHT)

    def _close_rect(self):
        return self._row_rect(len(self.ROLES))

    def _row_enabled(self, role):
        return role != "dungeon_entrance" or self.allow_dungeon_entrance

    def contains(self, pos):
        if not self.is_open:
            return False
        panel_rect = pygame.Rect(self.x, self.y, self.PANEL_WIDTH, self._close_rect().bottom - self.y + 10)
        return panel_rect.collidepoint(pos)

    def handle_event(self, event):
        """Returns the chosen role once a row is clicked, else None -- the
        caller (Creator) applies it via ObjectManager.set_role, same
        "widget returns a value, caller applies it" shape as
        GeneratorPanelUI/RoomPanelUI."""
        if not self.is_open or event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        for index, (role, _label) in enumerate(self.ROLES):
            if self._row_enabled(role) and self._row_rect(index).collidepoint(event.pos):
                return role

        if self._close_rect().collidepoint(event.pos):
            self.close()

        return None

    def render(self, screen):
        if not self.is_open:
            return

        title = self.title_font.render("Role de l'entree/sortie", True, (255, 255, 255))
        screen.blit(title, (self.x, self.y))

        for index, (role, label) in enumerate(self.ROLES):
            rect = self._row_rect(index)
            enabled = self._row_enabled(role)
            selected = self.obj.get("role", "connector") == role
            text = f"> {label}" if selected else label
            color = (255, 220, 120) if selected else None
            if enabled:
                self.border.draw_centered_label(screen, rect, self.font, text, color or (255, 255, 255))
            else:
                self.border.draw_enabled_label(screen, rect, self.font, text, False)

        self.border.draw_centered_label(screen, self._close_rect(), self.font, "Fermer")


# ---------------------------------------------------------------------
# Chest panel (loot editor for a placed chest, e.g. lilchest)
# ---------------------------------------------------------------------


class ChestPanelUI:
    """Opened by clicking a placed chest's indicator dot (see Creator's
    indicator-click handler, which checks ObjectManager.is_chest first) --
    lets the room designer customize how much of each currency type, and how
    many of the one item type, the chest drops once opened, instead of
    always using ObjectManager.add_object's hardcoded defaults. Acts as a
    modal while open: Creator suspends every other tool/panel so painting
    can't happen "underneath" an open chest's loot editor."""

    STEP_BUTTON_SIZE = 28
    COUNT_DISPLAY_WIDTH = 50
    ROW_HEIGHT = 30
    ROW_SPACING = 10
    PANEL_WIDTH = 260
    MIN_COUNT = 0
    MAX_COUNT = 99

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 16)
        self.title_font = pygame.font.SysFont("arial", 18)
        self.chest = None  # the placed object dict currently being edited, or None if closed

    @property
    def is_open(self):
        return self.chest is not None

    def open(self, chest_obj):
        self.chest = chest_obj

    def close(self):
        self.chest = None

    def _rows(self):
        """(label, loot_dict, key) for every adjustable row -- one per
        currency type (self.chest["loot"]), then one per existing item type
        (self.chest["item_loot"]) -- currently just dynamite, i.e. exactly
        the "1 slot d'item" this was specified with; a second item type
        later would just add a second row here for free."""
        rows = [(f"Pieces ({currency})", self.chest["loot"], currency) for currency in CURRENCY_FILES]
        rows += [
            (f"Objet ({definition['name']})", self.chest["item_loot"], item_id)
            for item_id, definition in ITEM_DEFINITIONS.items()
        ]
        return rows

    def _row_stepper(self, index):
        y = self.y + 34 + index * (self.ROW_HEIGHT + self.ROW_SPACING)
        return Stepper(self.x, y, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, self.MIN_COUNT, self.MAX_COUNT)

    def _role_rect(self):
        """Loot/Sortie-de-donjon toggle -- ObjectManager.CHEST_ROLES. A
        plain click-to-cycle row rather than the Stepper machinery the
        rows above use (only 2 states, no numeric value), so it mutates
        self.chest["role"] directly in handle_event the same way the
        stepper rows already mutate self.chest["loot"]/["item_loot"] in
        place -- both bypass ObjectManager.set_role's validation since
        this widget only ever writes one of the two valid chest role
        strings itself."""
        stepper = self._row_stepper(len(self._rows()) - 1)
        return pygame.Rect(self.x, stepper.bottom + 12, self.PANEL_WIDTH, 32)

    def _close_rect(self):
        return pygame.Rect(self.x, self._role_rect().bottom + 12, self.PANEL_WIDTH, 32)

    def contains(self, pos):
        if not self.is_open:
            return False
        panel_rect = pygame.Rect(self.x, self.y, self.PANEL_WIDTH, self._close_rect().bottom - self.y + 10)
        return panel_rect.collidepoint(pos)

    def handle_event(self, event):
        if not self.is_open or event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return

        for index, (_, loot, key) in enumerate(self._rows()):
            new_value = self._row_stepper(index).handle_click(event.pos, loot.get(key, 0))
            if new_value is not None:
                loot[key] = new_value
                return

        if self._role_rect().collidepoint(event.pos):
            self.chest["role"] = "dungeon_exit" if self.chest.get("role", "loot") == "loot" else "loot"
            return

        if self._close_rect().collidepoint(event.pos):
            self.close()

    def render(self, screen):
        if not self.is_open:
            return

        title = self.title_font.render("Contenu du coffre", True, (255, 255, 255))
        screen.blit(title, (self.x, self.y))

        for index, (label, loot, key) in enumerate(self._rows()):
            stepper = self._row_stepper(index)

            label_text = self.font.render(label, True, (220, 220, 220))
            screen.blit(label_text, (self.x, stepper.minus_rect.y - label_text.get_height() - 2))

            stepper.render(screen, self.border, self.font, loot.get(key, 0))

        role = self.chest.get("role", "loot")
        role_label = "Role : Sortie de donjon" if role == "dungeon_exit" else "Role : Loot"
        self.border.draw_centered_label(screen, self._role_rect(), self.font, role_label)

        self.border.draw_centered_label(screen, self._close_rect(), self.font, "Fermer")
