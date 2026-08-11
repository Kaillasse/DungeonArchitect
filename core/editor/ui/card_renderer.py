"""CardRenderer -- split out of the old monolithic core/editor/ui.py."""

from pathlib import Path

import pygame

from core.data.cards import CardManager, resolve_card_sprite, room_card_properties

PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
        # card_id -> Card, and room_name -> room_card_properties() result --
        # every caller that needs a Card object to hand to get_surface (or a
        # room card's dimensions/E-S/entity counts for the standard-mode
        # detail readout) used to call CardManager().load(card_id)/
        # room_card_properties(room_name) fresh -- a JSON-or-disk-scan read,
        # for a room card even a full Dungeon reload -- every single frame
        # a card is visible, even though only the already-cached composited
        # Surface actually needed the result. Both invalidate together with
        # clear_cache() below, same as _cache/_sprite_cache.
        self._card_cache = {}
        self._properties_cache = {}

    def clear_cache(self):
        """Called by CardPanelUI.refresh() -- a freshly reloaded card's
        name/type/effects (or, later, a card-editing UI's changes) must not
        keep showing a stale composited image."""
        self._cache.clear()
        self._sprite_cache.clear()
        self._card_cache.clear()
        self._properties_cache.clear()

    def get_surface(self, card, pixel_height):
        key = (card.card_id, pixel_height)
        surface = self._cache.get(key)
        if surface is None:
            surface = self._compose(card, pixel_height)
            self._cache[key] = surface
        return surface

    def get_card(self, card_id):
        """The Card for card_id, loaded via CardManager().load() at most
        once per clear_cache() cycle instead of once per frame per visible
        card -- callers that used to do their own `CardManager().load(...)`
        right before handing the result to get_surface (CardPanelUI's grid/
        list, GeneratorPanelUI's room-card grid, Creator's drag-follow
        sprite) should call this instead. Not cached if load() returns None
        (an id that doesn't currently resolve to anything) -- retried next
        call rather than permanently remembered as missing, in case the
        underlying data reappears (e.g. a deleted-then-recreated room)."""
        card = self._card_cache.get(card_id)
        if card is None:
            card = CardManager().load(card_id)
            if card is not None:
                self._card_cache[card_id] = card
        return card

    def get_room_properties(self, room_name):
        """room_card_properties(room_name), cached -- it reloads a whole
        Dungeon from the room's JSON and re-walks every placed object, the
        exact same work _sprite_for's own render_room_thumbnail (see
        core.data.cards.resolve_card_sprite) does right next to it for the
        room's thumbnail, which IS already cached via _sprite_cache. Used by
        CardPanelUI's standard-mode detail readout, recomputed every frame
        while a room card is selected."""
        properties = self._properties_cache.get(room_name)
        if properties is None:
            properties = room_card_properties(room_name)
            self._properties_cache[room_name] = properties
        return properties

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
