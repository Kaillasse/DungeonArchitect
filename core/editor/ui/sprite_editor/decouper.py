"""DecouperMixin -- NOT a live UI mode anymore (2026-08-20 cleanup). Used to
own mode "Decouper" (one selection on a loaded image -> one placable Card,
registered directly via register_custom_type/update_custom_type), but that
whole flow was superseded 2026-08-18 by "Extraire" (extraire.py, raw region
extraction into a pack) + "Assembler" (bitmap.py, actually turns a pack into
a card) -- see CLAUDE.md's editor-simplification plan. SpriteEditorPanelUI's
handle_event/render only ever dispatch to mode "extraire" or "assembler"
(panel.py's own "by elimination" comment), so nothing here ever received an
event or got rendered -- confirmed by tracing the actual call graph, not
assumed, before deleting the (very large) dead half of this file: several
methods that only ever called each other (_handle_decouper_event,
_render_decouper, _try_register, _try_update_existing,
_load_existing_card_for_edit, _reset_to_new_card, _move_selection_to,
_render_existing_card_markers, _current_frame_rects, _current_directions,
_ensure_door_frame_rects, _door_frame_thumb_rects, _door_frame_direction_rect,
_cycle_frame_direction, _render_door_frame_thumbs) are gone.

What's left is genuinely live: BitmapMixin's own "Carte"/Multitile checklist
(bitmap.py) reuses this mixin's cell_modes grid helpers
(_ensure_cell_modes_grid/_cell_mode_grid_rects/_current_cell_modes/
_cycle_cell_mode/_cell_mode_at/_render_cell_modes_grid) and its
existing-custom-card bookkeeping (_refresh_existing_cards, wired as
existing_cards_browser's own on_delete via _try_delete_card,
_find_custom_type_by_name) -- panel.py's shared _load_image also calls
_clamp_selection/_refresh_existing_cards directly. _layout_decouper survives
too, TRIMMED to just the two rects other modes actually still read
(self._blocks_rect, self._confirm_rect -- see its own docstring for exactly
who reads what) -- every OTHER rect/Stepper it used to build (archetype
buttons, width/height/door-frame steppers, the new-card button,
existing_cards_browser's own position here) had zero live reader once the
methods above were gone, so only the column.gap() arithmetic that feeds
those two survivors remains, not the dead objects themselves. Keep this
file's surface exactly as small as what bitmap.py/peindre.py actually use;
if a change here doesn't affect one of those, it isn't live."""

import pygame

from core.world.object_manager import OBJECT_TYPES, delete_custom_type, custom_types_for_tileset, CELL_MODES
from core.data.ressources import TILE_SIZE, type_references


class DecouperMixin:
    # BitmapMixin's own Multitile checklist reads these two directly
    # (self.MAX_TILES for its width/height Steppers' own max) -- still live
    # even though the methods that used to build UI around them here are
    # gone.
    MAX_TILES = 30
    # Cycling a door/multiframe thumbnail's direction tag through this
    # sequence used to be decouper-only -- BitmapMixin's own Carte
    # checklist (multiframe+multidirection) reads all three directly now
    # too (self.DIRECTION_CYCLE/DIRECTION_LABELS/DIRECTION_LABEL_STRIP),
    # same reasoning as MAX_TILES above. Only the 4 cardinals
    # ObjectManager._AUTO_DIRECTION_WALL_ADJACENCY actually uses for "auto"
    # placement, not the full 8 NPC_DIRECTIONS.
    DIRECTION_CYCLE = (None, "front", "back", "left", "right")
    DIRECTION_LABELS = {None: "-", "front": "F", "back": "B", "left": "G", "right": "D"}
    DIRECTION_LABEL_STRIP = 8

    # Cell-mode grid legend/colors -- CELL_MODES_ARCHETYPES ("sol"/"mur"/
    # "porte") existed here too but had zero live reader once the dead
    # methods above were removed (BitmapMixin always assembles under the
    # neutral "sol" archetype, see bitmap.py's own _try_register_carte),
    # so it's gone rather than kept as an unused constant.
    CELL_MODE_LABELS = {"block": "B", "behind": "D", "front": "F"}
    CELL_MODE_COLORS = {"block": (190, 90, 90), "behind": (110, 190, 110), "front": (100, 150, 220)}
    WALKABLE_GRID_MAX_PX = 140

    def _clamp_selection(self):
        if self.image is None:
            return
        img_w, img_h = self.image.get_size()
        sel_w = self.width_tiles * TILE_SIZE
        sel_h = self.height_tiles * TILE_SIZE
        self._sel_x = max(0, min(self._sel_x, max(0, img_w - sel_w)))
        self._sel_y = max(0, min(self._sel_y, max(0, img_h - sel_h)))

    def _ensure_cell_modes_grid(self):
        """Keeps cell_modes_grid's shape in sync with width_tiles/
        height_tiles -- called whenever either stepper changes. Every
        footprint size gets a full [height][width] grid, mono-tile included
        (2026-08-20: blocking is the grid's job for any size, no separate
        flat "blocks_movement" checkbox anywhere live anymore). Default cell
        is "behind" for "sol" (walkable), "block" for anything else (mirrors
        object_manager.is_cell_walkable's own terrain-based fallback: "sol"
        sits on already-walkable FLOOR, "mur"/"porte" sit on already-
        blocking WALL) -- BitmapMixin always assembles under "sol" today, so
        this only ever actually produces "behind" in practice, but stays
        correct if that ever changes. Resets on every resize rather than
        trying to preserve a smaller grid's values into a larger one,
        simplest correct behavior for what's expected to be a rare,
        deliberate resize."""
        default_cell = "behind" if self.archetype == "sol" else "block"
        self.cell_modes_grid = [[default_cell] * self.width_tiles for _ in range(self.height_tiles)]

    def _cell_mode_grid_rects(self):
        """(row, col) -> rect for the per-cell walkable toggle grid,
        anchored at _blocks_rect's position -- computed fresh every call
        (unlike a fixed-layout rect) since width_tiles/height_tiles change
        at runtime via the steppers. Cell size shrinks as the largest
        dimension grows so the grid's total footprint stays roughly
        WALKABLE_GRID_MAX_PX regardless of selection size."""
        anchor = self._blocks_rect
        max_dim = max(self.width_tiles, self.height_tiles)
        gap = 2
        cell_px = max(16, min(32, (self.WALKABLE_GRID_MAX_PX - gap * (max_dim - 1)) // max_dim))
        rects = {}
        for row in range(self.height_tiles):
            for col in range(self.width_tiles):
                rects[(row, col)] = pygame.Rect(
                    anchor.x + col * (cell_px + gap), anchor.y + row * (cell_px + gap), cell_px, cell_px,
                )
        return rects

    def _current_cell_modes(self):
        """The grid to persist -- the value register_custom_type/
        update_custom_type's own cell_modes param expects. Always real,
        any footprint size (see _ensure_cell_modes_grid)."""
        return self.cell_modes_grid

    def _cycle_cell_mode(self, row, col, step):
        """Advances (or reverses, step=-1) one cell's mode through
        CELL_MODES ("block"/"behind"/"front"), wrapping around -- shared by
        clicking a cell and hovering it while scrolling."""
        current = self.cell_modes_grid[row][col]
        index = CELL_MODES.index(current) if current in CELL_MODES else 0
        self.cell_modes_grid[row][col] = CELL_MODES[(index + step) % len(CELL_MODES)]

    def _cell_mode_at(self, pos):
        """(row, col) of the per-cell grid cell containing `pos`, or None."""
        if self.cell_modes_grid is None:
            return None
        for (row, col), rect in self._cell_mode_grid_rects().items():
            if rect.collidepoint(pos):
                return row, col
        return None

    def _render_cell_modes_grid(self, screen):
        """The per-cell mode grid (see _cell_mode_grid_rects/
        _ensure_cell_modes_grid) -- 3 states cycled by click or
        hover+scroll (_cycle_cell_mode): red "B" = bloquant (pour "porte"
        avec blocks_until_open : bloque tant que pas ouverte, voir
        ObjectManager.is_cell_walkable), green "D" = ne bloque pas /
        derriere le joueur, blue "F" = ne bloque pas / devant le joueur
        (torch-style), each a compact label since cells can be as small as
        16px (writing "Bloquant"/"Derriere"/"Devant" out in full inside a
        16px cell isn't legible, hence the legend line drawn below the grid
        instead)."""
        if self.cell_modes_grid is None:
            return
        rects = self._cell_mode_grid_rects()
        for (row, col), rect in rects.items():
            mode = self.cell_modes_grid[row][col]
            color = self.CELL_MODE_COLORS.get(mode, self.CELL_MODE_COLORS["behind"])
            pygame.draw.rect(screen, color, rect)
            pygame.draw.rect(screen, (20, 20, 20), rect, 1)
            label = self.small_font.render(self.CELL_MODE_LABELS.get(mode, "?"), True, (20, 20, 20))
            screen.blit(label, (rect.centerx - label.get_width() / 2, rect.centery - label.get_height() / 2))

        grid_left = min(r.left for r in rects.values())
        grid_bottom = max(r.bottom for r in rects.values())
        legend = self.small_font.render("B = Bloquant   D = Derriere   F = Devant", True, (200, 200, 200))
        screen.blit(legend, (grid_left, grid_bottom + 4))

    def _refresh_existing_cards(self):
        """Repopulates existing_cards_browser with every custom card
        already sourced from the currently loaded file -- called on load
        and again after a successful register/update so a freshly (re)named
        card shows up immediately. Empty (no file loaded) is a valid,
        harmless state."""
        if self.image_name is None:
            self.existing_cards_browser.set_rooms([])
            return
        cards = custom_types_for_tileset(self.image_name)
        entries = [(config.get("name", type_id), type_id) for type_id, config in cards]
        entries.sort(key=lambda entry: entry[0].lower())
        self.existing_cards_browser.set_rooms(entries)

    def _try_delete_card(self, type_id):
        """on_delete callback for existing_cards_browser -- shared by
        BitmapMixin's Carte screen (see _refresh_carte_existing_cards) and
        this mixin's own _refresh_existing_cards, which both point the SAME
        browser instance's on_delete here. Refuses with an explanation in
        status_text instead of deleting outright when the type is still
        placed somewhere (ressources.type_references scans every
        room/dungeon), same protective spirit as Creator._can_rename_room
        blocking a home room -- without this, a room that still placed it
        would hit a bare OBJECT_TYPES lookup KeyError the next time it's
        loaded, not a graceful degradation.

        The post-delete refresh has to pick the right of the two
        populating methods for whichever mode is actually driving this
        browser right now (Assembler's is keyed off the loaded pack's
        tileset, this mixin's own off self.image_name, which is always None
        while in Assembler) -- calling the wrong one would silently wipe
        the browser back to empty instead of just dropping the one row."""
        used_in = type_references(type_id)
        if used_in:
            self.status_text = f"Impossible de supprimer : encore utilisee dans {', '.join(used_in)}."
            return
        try:
            delete_custom_type(type_id)
        except ValueError as exc:
            self.status_text = str(exc)
            return
        self.status_text = f"'{type_id}' supprimee."
        if self.mode == "assembler":
            self._refresh_carte_existing_cards()
        else:
            self._refresh_existing_cards()

    @staticmethod
    def _find_custom_type_by_name(raw_name):
        """The id of an existing custom card whose name matches `raw_name`
        (case-insensitive), or None -- the direct fix for the "stone"/
        "stone_2" case: two cards sharing a display name are indistinguishable
        in the collection panel no matter how their ids differ, so a fresh
        registration under an already-used name is refused instead of
        silently creating a confusing duplicate."""
        target = raw_name.strip().lower()
        for candidate_id, config in OBJECT_TYPES.items():
            if isinstance(config.get("asset"), dict) and config.get("name", "").strip().lower() == target:
                return candidate_id
        return None

    def _layout_decouper(self, column):
        """Called from SpriteEditorPanelUI._layout() with a LayoutColumn
        already positioned at (params_x, self.y + 100, step_w) -- computes
        ONLY self._blocks_rect (the cell_modes grid's own anchor, see
        _cell_mode_grid_rects -- BitmapMixin also sets this itself right
        before reading it, line ~1579 of bitmap.py, so this copy mostly
        exists as a defensive fallback) and self._confirm_rect (read for
        its .width by BitmapMixin's entity-kind layout and for its .x by
        PeindreMixin's new-canvas dialog position -- neither sets it
        themselves, so this genuinely is the only place it's computed).
        The column.gap() calls in between reproduce the exact cumulative
        offset the old, much longer version of this method used to advance
        through (width/height steppers, archetype buttons, door-frames
        stepper) -- those widgets themselves are gone (2026-08-20, no live
        reader once mode "decouper" was confirmed dead), but the SPACING
        between _blocks_rect and _confirm_rect has to stay numerically
        identical or both would land in the wrong place for the modes that
        still read them."""
        column.gap(32 + 14)  # name_box row
        column.gap(28 + 16)  # width stepper row
        column.gap(28 + 16)  # height stepper row
        column.gap(32 + 12)  # archetype buttons row
        self._blocks_rect = column.rect(32)
        column.gap(120)
        column.gap(28 + 76)  # door-frames stepper row
        self._confirm_rect = column.rect(40)
