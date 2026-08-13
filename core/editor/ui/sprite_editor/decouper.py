"""DecouperMixin -- mode "Decouper" of SpriteEditorPanelUI, split out of the
old monolithic sprite_editor.py (see core/editor/ui/sprite_editor/panel.py's
own docstring for why). Regroups the two former top-level modes "tuile"
(a selection becomes ONE placable Card) and "pack" (a selection becomes a
grid of individually-extracted tiles) behind a crop_kind sub-toggle --
they were never really separate handlers even before that regroup (see
CROP_KINDS' own history), sharing almost this entire params column and
event/render chain, so this single mixin covers both."""

import pygame

from core.world.object_manager import (
    OBJECT_TYPES, ARCHETYPES, register_custom_type, update_custom_type, delete_custom_type,
    custom_types_for_tileset, CELL_MODES,
)
from core.data.ressources import TILE_SIZE, save_autotile_pack, list_autotile_packs, load_autotile_pack, type_references
from core.ui.widgets import Stepper


class DecouperMixin:
    MAX_TILES = 30
    # Opening-animation frame count cap for a lockable "porte" -- gate/wall's
    # own built-in sheets top out at 8/7 frames, this leaves headroom without
    # inviting an unreasonably long per-frame manual capture session.
    MAX_DOOR_FRAMES = 12
    DOOR_FRAME_THUMB_SIZE = 26
    DOOR_FRAME_THUMB_GAP = 4

    # Motifs de voisinage qui se produisent reellement dans une salle valide
    # -- extraits de assets/tiles/tile_categories.json (les valeurs "floor"/
    # "wall" distinctes qu'il utilise deja pour le tileset interieur), pas
    # les 3**4=81 combinaisons theoriquement possibles dont la plupart ne
    # peuvent jamais apparaitre. C'est la check-list que le mode bitmap
    # propose une fois un pack charge, pour assigner un motif connu d'un
    # clic plutot que de le composer a la main a chaque tuile.
    CROP_KINDS = (("tuile", "Tuile"), ("pack", "Pack"))

    # Mode "peindre" (ex-"pixel") -- outils/roue de couleur.
    CELL_MODE_LABELS = {"block": "B", "behind": "D", "front": "F"}
    CELL_MODE_COLORS = {"block": (190, 90, 90), "behind": (110, 190, 110), "front": (100, 150, 220)}

    # Archetypes whose multi-cell selection gets the cell_modes grid editor
    # instead of just the plain blocks_movement checkbox -- lets a
    # multi-cell "sol"/"mur"/"porte" object mix blocking/walkable/
    # front-drawn cells instead of one flag applying uniformly (see
    # ObjectManager.is_cell_walkable/cell_mode). Independent of placement
    # validation, which is always anchor-only (see _anchor_cell) regardless
    # of archetype or cell_modes.
    CELL_MODES_ARCHETYPES = ("sol", "mur", "porte")

    # (row, col) of every cell in the 3x3 spatial preview (see _layout's
    # _bm_grid_rects) -- the 4 corners are decorative-only, never included
    # in NEIGHBOR_KEYS so hover/scroll/click logic can just check "is this
    # key in NEIGHBOR_KEYS" to know whether a grid cell is interactive.

    def _active_tile_size(self):
        """The pixel grid the current selection snaps to and is sized in --
        TILE_SIZE (16, the interior tileset's own grid) everywhere except
        pack mode with pack_kind="entite", which uses entity_tile_size
        (32 by default) instead: a character sheet's own cells are rarely
        16px (blackcat.png's are 32x32) and vary per sheet, unlike the
        fixed built-in tileset every other mode crops from."""
        if self.crop_kind == "pack" and self.pack_kind == "entite":
            return self.entity_tile_size
        return TILE_SIZE
    def _set_pack_kind(self, kind_id):
        """Switches pack_kind, refreshing file_browser to the matching root
        (assets/tiles/ for "autotile", assets/characters/ for "entite" --
        see _refresh_file_list) and resetting the loaded image/selection,
        since a file picked under one root is meaningless once the browser
        no longer even lists it."""
        if kind_id == self.pack_kind:
            return
        self.pack_kind = kind_id
        self._file_browser_root = "characters" if kind_id == "entite" else "tiles"
        self.image = None
        self.image_name = None
        self._sel_x = 0
        self._sel_y = 0
        self._refresh_file_list()
    def _set_crop_kind(self, kind_id):
        """Tuile <-> Pack sub-toggle within mode "decouper" (see CROP_KINDS)
        -- mirrors _set_pack_kind's own reset, just triggered by switching
        crop_kind INSTEAD of leaving mode "decouper" entirely (see
        _set_mode's own equivalent reset, gated on the outer mode instead).
        Without this, switching from crop_kind "pack"+pack_kind "entite"
        (file_browser pointed at assets/characters/) back to "tuile" would
        leave file_browser stuck showing character sheets instead of
        assets/tiles/."""
        if kind_id == self.crop_kind:
            return
        if self.crop_kind == "pack" and self._file_browser_root != "tiles":
            self.pack_kind = "autotile"
            self._file_browser_root = "tiles"
            self._refresh_file_list()
        self.crop_kind = kind_id
    def _clamp_selection(self):
        if self.image is None:
            return
        img_w, img_h = self.image.get_size()
        tile_size = self._active_tile_size()
        sel_w = self.width_tiles * tile_size
        sel_h = self.height_tiles * tile_size
        self._sel_x = max(0, min(self._sel_x, max(0, img_w - sel_w)))
        self._sel_y = max(0, min(self._sel_y, max(0, img_h - sel_h)))
    WALKABLE_GRID_MAX_PX = 140
    def _ensure_cell_modes_grid(self):
        """Keeps cell_modes_grid's shape in sync with width_tiles/
        height_tiles -- called whenever either stepper changes. 1x1 has no
        grid at all (None -- the single blocks_movement checkbox is used
        instead, see _current_cell_modes); a genuinely multi-cell
        selection always gets a full [height][width] grid, defaulting every
        cell to "behind" (walkable, normal draw order -- closest match to
        the single checkbox's own unchecked-by-default state) -- resetting
        on every resize rather than trying to preserve a smaller grid's
        values into a larger one, simplest correct behavior for what's
        expected to be a rare, deliberate resize."""
        if self.width_tiles == 1 and self.height_tiles == 1:
            self.cell_modes_grid = None
            return
        self.cell_modes_grid = [["behind"] * self.width_tiles for _ in range(self.height_tiles)]
    def _ensure_door_frame_rects(self):
        """Keeps door_frame_rects in sync with door_frame_count/width_tiles/
        height_tiles -- called whenever any of the three changes. A new slot
        starts equal to the current selection (_sel_x/_sel_y, sized to
        width_tiles/height_tiles), so an untouched frame is still a
        well-defined region instead of an empty one; shrinking the count
        drops the extra tail entries. Every entry's own width/height is kept
        in sync with the current footprint size too, so resizing width_tiles/
        height_tiles after picking frames doesn't leave stale-sized rects
        behind. Also arms editing_door_frame at a valid index whenever more
        than 1 frame exists (see _move_selection_to), or clears it back to
        None for a plain 1-frame selection."""
        sel_w = self.width_tiles * TILE_SIZE
        sel_h = self.height_tiles * TILE_SIZE
        while len(self.door_frame_rects) < self.door_frame_count:
            self.door_frame_rects.append([self._sel_x, self._sel_y, sel_w, sel_h])
        del self.door_frame_rects[self.door_frame_count:]
        for frame_rect in self.door_frame_rects:
            frame_rect[2], frame_rect[3] = sel_w, sel_h

        if self.door_frame_count > 1:
            current = self.editing_door_frame if self.editing_door_frame is not None else 0
            self.editing_door_frame = min(current, self.door_frame_count - 1)
        else:
            self.editing_door_frame = None
    def _door_frame_thumb_rects(self):
        """index -> rect for each configured door frame's thumbnail, wrapped
        onto multiple rows if door_frame_count exceeds one row's worth --
        same dynamic-per-call approach as _cell_mode_grid_rects, anchored
        just below _door_frames_stepper."""
        size = self.DOOR_FRAME_THUMB_SIZE
        gap = self.DOOR_FRAME_THUMB_GAP
        origin_x = self._door_frames_stepper.minus_rect.x
        origin_y = self._door_frames_stepper.bottom + 8
        step_w = self._confirm_rect.width
        per_row = max(1, (step_w + gap) // (size + gap))
        rects = {}
        for index in range(self.door_frame_count):
            row, col = divmod(index, per_row)
            rects[index] = pygame.Rect(
                origin_x + col * (size + gap), origin_y + row * (size + gap), size, size,
            )
        return rects
    def _cell_mode_grid_rects(self):
        """(row, col) -> rect for the per-cell walkable toggle grid,
        anchored at _blocks_rect's position -- computed fresh every call
        (unlike _layout's fixed rects) since width_tiles/height_tiles
        change at runtime via the steppers. Cell size shrinks as the
        largest dimension grows so the grid's total footprint stays
        roughly WALKABLE_GRID_MAX_PX regardless of selection size."""
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
        """None for a 1x1 selection (the plain blocks_movement bool applies
        instead) -- the value register_custom_type/update_custom_type's own
        cell_modes param expects."""
        if self.width_tiles == 1 and self.height_tiles == 1:
            return None
        return self.cell_modes_grid
    def _current_frame_rects(self):
        """None unless archetype is "porte" with more than 1 opening-
        animation frame configured -- a 1-frame (or non-"porte") selection
        stays on the plain single "rect" path (see _build_custom_type_
        entry), same reasoning as _current_cell_modes above."""
        if self.archetype == "porte" and self.door_frame_count > 1:
            return self.door_frame_rects
        return None
    def _cycle_cell_mode(self, row, col, step):
        """Advances (or reverses, step=-1) one cell's mode through
        CELL_MODES ("block"/"behind"/"front"), wrapping around -- shared by
        clicking a cell and hovering it while scrolling (see
        handle_event's MOUSEBUTTONDOWN chain and its MOUSEWHEEL branch)."""
        current = self.cell_modes_grid[row][col]
        index = CELL_MODES.index(current) if current in CELL_MODES else 0
        self.cell_modes_grid[row][col] = CELL_MODES[(index + step) % len(CELL_MODES)]
    def _cell_mode_at(self, pos):
        """(row, col) of the per-cell grid cell containing `pos`, or None --
        only meaningful while a multi-cell "sol" tile is being configured
        (cell_modes_grid is not None), mirrors _bm_neighbor_at's shape for
        the bitmap editor's own 3x3 preview."""
        if self.cell_modes_grid is None:
            return None
        for (row, col), rect in self._cell_mode_grid_rects().items():
            if rect.collidepoint(pos):
                return row, col
        return None
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
        """on_delete callback for existing_cards_browser (see __init__) --
        refuses with an explanation in status_text instead of deleting
        outright when the type is still placed somewhere (ressources.
        type_references scans every room/dungeon), same protective spirit
        as Creator._can_rename_room blocking a home room -- without this,
        a room that still placed it would hit a bare OBJECT_TYPES lookup
        KeyError the next time it's loaded, not a graceful degradation.
        Clears editing_type_id if the deleted card was the one being
        edited, so Confirmer doesn't try to update a type that no longer
        exists."""
        used_in = type_references(type_id)
        if used_in:
            self.status_text = f"Impossible de supprimer : encore utilisee dans {', '.join(used_in)}."
            return
        try:
            delete_custom_type(type_id)
        except ValueError as exc:
            self.status_text = str(exc)
            return
        if self.editing_type_id == type_id:
            self._reset_to_new_card()
        self.status_text = f"'{type_id}' supprimee."
        self._refresh_existing_cards()
    def _load_existing_card_for_edit(self, type_id):
        """Loads an existing custom card's saved parameters into the
        editing state (selection, size, archetype, flags, name) and marks
        self.editing_type_id so Confirmer calls update_custom_type instead
        of register_custom_type -- see handle_event's confirm dispatch.
        Triggered by clicking a row in existing_cards_browser."""
        config = OBJECT_TYPES.get(type_id)
        if config is None or not isinstance(config.get("asset"), dict):
            return
        self.editing_type_id = type_id
        asset = config["asset"]
        # A lockable "porte" with 2+ opening frames saves "rects" (plural)
        # instead of a single "rect" -- see _build_custom_type_entry/
        # object_manager.load_object_frames. door_frame_rects/frame_count
        # restore from it; a plain single-region card (everything else,
        # including a 1-frame "porte") has no "rects" at all.
        if "rects" in asset:
            frame_rects = [list(r) for r in asset["rects"]]
        else:
            frame_rects = []
        rect = frame_rects[0] if frame_rects else asset["rect"]
        self._sel_x, self._sel_y = rect[0], rect[1]
        self.width_tiles, self.height_tiles = config.get("size", [1, 1])
        self.archetype = next(
            (aid for aid, preset in ARCHETYPES.items() if preset["placement"] == config.get("placement")),
            "sol",
        )
        saved_cell_modes = config.get("cell_modes")
        if saved_cell_modes is not None:
            self.cell_modes_grid = [list(row) for row in saved_cell_modes]
        elif self.width_tiles == 1 and self.height_tiles == 1:
            self.cell_modes_grid = None
        else:
            # A multi-cell card with no saved cell_modes at all (either
            # saved before this feature existed, or -- like "bigstone" --
            # simply never had blocks_movement/cell_modes set at creation
            # time) has nothing to restore here. Without this fallback,
            # cell_modes_grid stayed None forever once loaded back for
            # editing (only the width/height steppers' own change handler,
            # _ensure_cell_modes_grid, ever built a fresh grid, and neither
            # stepper needs touching if the loaded size is already
            # correct) -- so the grid editor silently never appeared and a
            # multi-cell card's hitbox could never actually be set. Default
            # every cell to "behind" (walkable, normal draw order), same as
            # _ensure_cell_modes_grid's own default for a brand-new resize
            # -- the closest match to this card's current in-game
            # behavior (no blocks_movement/cell_modes at all falls through
            # to plain terrain walkability, see ObjectManager.
            # is_cell_walkable).
            self.cell_modes_grid = [["behind"] * self.width_tiles for _ in range(self.height_tiles)]
        self.blocks_movement = config.get("blocks_movement", False)
        self.interactable = config.get("interactable", False)
        # blocks_until_open is only ever set on a custom type by this same
        # editor's own lockable checkbox (see _build_custom_type_entry) --
        # a reliable proxy for "was this porte saved as lockable".
        self.lockable = bool(config.get("blocks_until_open"))
        self.door_frame_rects = frame_rects
        self.door_frame_count = len(frame_rects) if frame_rects else 1
        self.editing_door_frame = 0 if len(frame_rects) > 1 else None
        self.name_box.value = config.get("name", type_id)
        self._clamp_selection()
        self.status_text = f"Edition de '{self.name_box.value}' ({type_id})."
    def _reset_to_new_card(self):
        """The "Nouvelle carte" button -- drops out of edit mode back to a
        blank creation state, without discarding the currently loaded file/
        selection position (only the identity/flags reset)."""
        self.editing_type_id = None
        self.name_box.value = ""
        self.archetype = "sol"
        self.blocks_movement = False
        self.cell_modes_grid = None
        self.interactable = False
        self.lockable = False
        self.door_frame_count = 1
        self.door_frame_rects = []
        self.editing_door_frame = None
        self.status_text = ""
    def _move_selection_to(self, screen_pos):
        img_x, img_y = self.camera.screen_to_world(*self._local_pos(screen_pos))
        tile_size = self._active_tile_size()
        self._sel_x = round(img_x / tile_size) * tile_size
        self._sel_y = round(img_y / tile_size) * tile_size
        self._clamp_selection()
        # A door frame is currently armed for editing (see
        # _door_frame_thumb_rects' click handling) -- the drag captures
        # THAT frame's own rect, in lockstep with the visible selection
        # rectangle, instead of the plain single-selection slot.
        if self.editing_door_frame is not None and self.editing_door_frame < len(self.door_frame_rects):
            self.door_frame_rects[self.editing_door_frame][0] = self._sel_x
            self.door_frame_rects[self.editing_door_frame][1] = self._sel_y

    @staticmethod
    def _find_custom_type_by_name(raw_name):
        """The id of an existing custom card whose name matches `raw_name`
        (case-insensitive), or None -- the direct fix for the "stone"/
        "stone_2" case: two cards sharing a display name are indistinguishable
        in the collection panel no matter how their ids differ, so a fresh
        registration under an already-used name is refused (see _try_register)
        instead of silently creating a confusing duplicate."""
        target = raw_name.strip().lower()
        for candidate_id, config in OBJECT_TYPES.items():
            if isinstance(config.get("asset"), dict) and config.get("name", "").strip().lower() == target:
                return candidate_id
        return None
    def _try_register(self):
        if self.image is None:
            self.status_text = "Choisis d'abord un fichier."
            return None

        raw_name = self.name_box.value.strip()
        if not raw_name:
            self.status_text = "Donne un nom a la carte."
            return None

        duplicate_id = self._find_custom_type_by_name(raw_name)
        if duplicate_id is not None:
            self.status_text = f"'{raw_name}' existe deja ({duplicate_id}) -- clique-la dans la liste pour la modifier."
            return None

        type_id = self._sanitize_id(raw_name, OBJECT_TYPES, fallback="carte")

        sel_w = self.width_tiles * TILE_SIZE
        sel_h = self.height_tiles * TILE_SIZE
        rect = [self._sel_x, self._sel_y, sel_w, sel_h]

        try:
            register_custom_type(
                type_id, raw_name, self.image_name, rect,
                (self.width_tiles, self.height_tiles), self.archetype,
                blocks_movement=self.blocks_movement,
                cell_modes=self._current_cell_modes(),
                interactable=self.interactable,
                lockable=self.lockable,
                frame_rects=self._current_frame_rects(),
            )
        except ValueError as exc:
            self.status_text = str(exc)
            return None

        self.status_text = f"'{raw_name}' enregistre ({type_id})."
        self.name_box.value = ""
        self._refresh_existing_cards()
        return type_id
    def _try_update_existing(self):
        """Confirmer's action while self.editing_type_id is set -- rewrites
        that card's definition in place via update_custom_type instead of
        creating a new one. Never returns a value for Creator to grant a
        card for (the card already exists, presumably already owned) --
        see handle_event's confirm dispatch."""
        raw_name = self.name_box.value.strip()
        if not raw_name:
            self.status_text = "Donne un nom a la carte."
            return None

        duplicate_id = self._find_custom_type_by_name(raw_name)
        if duplicate_id is not None and duplicate_id != self.editing_type_id:
            self.status_text = f"'{raw_name}' est deja pris par {duplicate_id}."
            return None

        sel_w = self.width_tiles * TILE_SIZE
        sel_h = self.height_tiles * TILE_SIZE
        rect = [self._sel_x, self._sel_y, sel_w, sel_h]

        try:
            update_custom_type(
                self.editing_type_id, raw_name, self.image_name, rect,
                (self.width_tiles, self.height_tiles), self.archetype,
                blocks_movement=self.blocks_movement,
                cell_modes=self._current_cell_modes(),
                interactable=self.interactable,
                lockable=self.lockable,
                frame_rects=self._current_frame_rects(),
            )
        except ValueError as exc:
            self.status_text = str(exc)
            return None

        self.status_text = f"'{raw_name}' mise a jour ({self.editing_type_id})."
        self._refresh_existing_cards()
        return None
    def _try_register_pack(self):
        """Pack mode: the current selection is a width_tiles x height_tiles
        GRID of separate 1x1 (or, for pack_kind="entite", tile_size x
        tile_size -- see _active_tile_size) tiles -- each cell is cropped
        and numbered independently. Autotile: never touches OBJECT_TYPES/
        the Card system (raw terrain tiles aren't placeable objects) --
        deliberately just extraction, no bitmask assignment (see
        ressources.save_autotile_pack's own docstring). Entite: same
        "just extraction" split -- action/direction/order tagging is mode
        "bitmap"'s own job (see _handle_entity_bitmap_event), not this
        one. Neither branch ever returns a value Creator would act on --
        see handle_event's confirm dispatch."""
        if self.image is None:
            self.status_text = "Choisis d'abord un fichier."
            return None

        raw_name = self.name_box.value.strip()
        if not raw_name:
            self.status_text = "Donne un nom au pack."
            return None

        pack_name = self._sanitize_id(raw_name, set(list_autotile_packs()), fallback="pack")
        tile_size = self._active_tile_size()
        rects = [
            (self._sel_x + col * tile_size, self._sel_y + row * tile_size, tile_size, tile_size)
            for row in range(self.height_tiles)
            for col in range(self.width_tiles)
        ]

        if self.pack_kind == "entite":
            save_autotile_pack(pack_name, None, self.image_name, rects, kind="entity", columns=self.width_tiles)
        else:
            role = ARCHETYPES[self.archetype]["placement"]
            save_autotile_pack(pack_name, role, self.image_name, rects)

        self.status_text = f"Pack '{raw_name}' enregistre ({len(rects)} tuiles, {pack_name})."
        self.name_box.value = ""
        return None
    def _handle_decouper_event(self, event):
        """Mode "decouper"'s own event handling (crop_kind "tuile"/"pack"
        both live here, already merged into one shared chain before this
        method existed -- see CROP_KINDS' own docstring). Extracted from
        what used to be handle_event's own unconditional tail, mirroring
        the _handle_bitmap_event/_handle_pixel_event precedent so all 3
        modes now have a dedicated handler instead of only 2 of them."""
        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 2:
                self._panning = False
                self._pan_last_pos = None
                return None
            self._dragging_selection = False
            if event.button == 1:
                # Also lets the file/existing-cards browsers' own
                # slider-drag release clear their _dragging_slider state.
                self.file_browser.handle_event(event)
                self.existing_cards_browser.handle_event(event)
            return None

        if event.type == pygame.MOUSEMOTION:
            if self._panning and self._pan_last_pos is not None:
                # Same math as Creator's own middle-click pan (see run()) --
                # panning moves the camera opposite the drag, scaled by zoom.
                dx = event.pos[0] - self._pan_last_pos[0]
                dy = event.pos[1] - self._pan_last_pos[1]
                self.camera.x -= dx / self.camera.zoom
                self.camera.y -= dy / self.camera.zoom
                self._pan_last_pos = event.pos
                return None
            if self._dragging_selection:
                self._move_selection_to(event.pos)
                return None
            # Not dragging our own selection or panning -- forward in case
            # the file/existing-cards browsers' own sliders are being
            # dragged (RoomBrowser tracks that via its own _dragging_slider
            # flag, not the event's position, so this is safe to call
            # unconditionally on every motion).
            self.file_browser.handle_event(event)
            self.existing_cards_browser.handle_event(event)
            return None

        # MOUSEBUTTONDOWN from here on.
        # existing_cards_browser's own rename-box/delete-confirm/context-
        # menu popup can render outside its normal row-list bounds
        # (RoomBrowser.is_modal) -- route every event there
        # unconditionally while one is open, or the popup renders but
        # never actually receives input.
        if self.crop_kind == "tuile" and self.existing_cards_browser.is_modal:
            self.existing_cards_browser.handle_event(event)
            return None

        if event.button == 3:
            # Right-click only ever means "open existing_cards_browser's
            # own Supprimer menu" here -- everything else only responds
            # to left-click/middle-click (pan).
            if self.crop_kind == "tuile" and self.existing_cards_browser.contains(event.pos):
                self.existing_cards_browser.handle_event(event)
            return None

        if event.button == 2:
            if self.viewer_rect.collidepoint(event.pos) and self.image is not None:
                self._panning = True
                self._pan_last_pos = event.pos
            return None

        if event.button != 1:
            return None

        if self._close_rect.collidepoint(event.pos):
            self.close()
            return None

        if self.file_browser.contains(event.pos):
            self.file_browser.handle_event(event)
            selected = self.file_browser.selected_name
            if selected is not None and self._full_image_name(selected) != self.image_name:
                self._load_image(selected)
            return None

        if self.crop_kind == "tuile" and self.existing_cards_browser.contains(event.pos):
            self.existing_cards_browser.handle_event(event)
            selected_id = self.existing_cards_browser.selected_name
            if selected_id is not None:
                self._load_existing_card_for_edit(selected_id)
            return None

        if self.crop_kind == "tuile" and self.editing_type_id is not None and self._new_card_rect.collidepoint(event.pos):
            self._reset_to_new_card()
            return None

        for mode_id, rect in self._mode_rects.items():
            if rect.collidepoint(event.pos):
                self._set_mode(mode_id)
                return None

        for kind_id, rect in self._crop_kind_rects.items():
            if rect.collidepoint(event.pos):
                self._set_crop_kind(kind_id)
                return None

        if self.viewer_rect.collidepoint(event.pos) and self.image is not None:
            self._dragging_selection = True
            self._move_selection_to(event.pos)
            return None

        new_width = self._width_stepper.handle_click(event.pos, self.width_tiles)
        if new_width is not None:
            self.width_tiles = new_width
            self._clamp_selection()
            self._ensure_cell_modes_grid()
            self._ensure_door_frame_rects()
            return None

        new_height = self._height_stepper.handle_click(event.pos, self.height_tiles)
        if new_height is not None:
            self.height_tiles = new_height
            self._clamp_selection()
            self._ensure_cell_modes_grid()
            self._ensure_door_frame_rects()
            return None

        if self.crop_kind == "pack":
            for kind_id, rect in self._pack_kind_rects.items():
                if rect.collidepoint(event.pos):
                    self._set_pack_kind(kind_id)
                    return None

            if self.pack_kind == "entite":
                new_size = self._entity_tile_size_stepper.handle_click(event.pos, self.entity_tile_size)
                if new_size is not None:
                    self.entity_tile_size = new_size
                    self._clamp_selection()
                    return None

        if not (self.crop_kind == "pack" and self.pack_kind == "entite"):
            for archetype_id, rect in self._archetype_rects.items():
                if rect.collidepoint(event.pos):
                    self.archetype = archetype_id
                    return None

        if self.crop_kind == "tuile" and self.archetype == "porte":
            if self._lockable_rect.collidepoint(event.pos):
                self.lockable = not self.lockable
                return None

            new_frames = self._door_frames_stepper.handle_click(event.pos, self.door_frame_count)
            if new_frames is not None:
                self.door_frame_count = new_frames
                self._ensure_door_frame_rects()
                return None

            for index, rect in self._door_frame_thumb_rects().items():
                if rect.collidepoint(event.pos):
                    # Arms this frame for the next drag AND jumps the visible
                    # selection to whatever's already captured there, so the
                    # player sees (and can nudge) the existing region instead
                    # of blindly dragging from wherever it last was.
                    self.editing_door_frame = index
                    if index < len(self.door_frame_rects):
                        self._sel_x, self._sel_y = self.door_frame_rects[index][0], self.door_frame_rects[index][1]
                    return None

        if self.crop_kind == "tuile" and self.archetype in self.CELL_MODES_ARCHETYPES:
            if self.width_tiles == 1 and self.height_tiles == 1:
                # The plain blocks_movement checkbox only ever makes sense
                # for "sol" -- "mur" is already solid by sitting on a WALL
                # cell (same fallback the built-in plain "torch" relies on,
                # no flag needed), and "porte" needs its own walkable/
                # blocks_until_open flags (see ARCHETYPES/_build_custom_type_
                # entry) to actually WIN in ObjectManager.is_cell_walkable's
                # precedence -- blocks_movement would short-circuit ahead of
                # them and make the door permanently solid.
                if self.archetype == "sol" and self._blocks_rect.collidepoint(event.pos):
                    self.blocks_movement = not self.blocks_movement
                    return None
            else:
                for (row, col), rect in self._cell_mode_grid_rects().items():
                    if rect.collidepoint(event.pos):
                        self._cycle_cell_mode(row, col, 1)
                        return None

        if self.crop_kind == "tuile" and self._interactable_rect.collidepoint(event.pos):
            self.interactable = not self.interactable
            return None

        if self._confirm_rect.collidepoint(event.pos):
            if self.crop_kind == "pack":
                self._try_register_pack()
                return None
            if self.editing_type_id is not None:
                self._try_update_existing()
                return None
            return self._try_register()

        return None
    def _render_decouper(self, screen):
        """Mode "decouper"'s own rendering (crop_kind "tuile"/"pack" both
        live here) -- extracted from what used to be render's own
        unconditional tail, mirroring _render_bitmap/_render_pixel."""
        for kind_id, rect in self._crop_kind_rects.items():
            label = dict(self.CROP_KINDS)[kind_id]
            selected = kind_id == self.crop_kind
            text = f"> {label}" if selected else label
            self.border.draw_centered_label(screen, rect, self.font, text, (255, 220, 120) if selected else (255, 255, 255))

        self.file_browser.render(screen)
        if self.crop_kind == "tuile":
            self.existing_cards_browser.render(screen)
            if self.editing_type_id is not None:
                self.border.draw_centered_label(screen, self._new_card_rect, self.small_font, "Nouvelle carte")
            elif self.image_name is not None and not self.existing_cards_browser.rooms:
                hint = self.small_font.render("Aucune carte sur ce fichier", True, (150, 150, 150))
                screen.blit(hint, (self.existing_cards_browser.x, self.existing_cards_browser.y + 4))

        self.border.draw(screen, self.viewer_rect)
        if self.image is not None:
            zoom = self.camera.zoom
            scaled_size = (round(self.image.get_width() * zoom), round(self.image.get_height() * zoom))
            scaled_image = pygame.transform.scale(self.image, scaled_size)
            image_screen_x, image_screen_y = self.camera.world_to_screen(0, 0)
            clip = screen.get_clip()
            screen.set_clip(self.viewer_rect)
            screen.blit(scaled_image, (self.viewer_rect.x + image_screen_x, self.viewer_rect.y + image_screen_y))

            if self.crop_kind == "tuile":
                self._render_existing_card_markers(screen)
            elif self.crop_kind == "pack":
                self._render_pack_region_markers(screen)

            active_tile_size = self._active_tile_size()
            sel_screen_x, sel_screen_y = self.camera.world_to_screen(self._sel_x, self._sel_y)
            sel_rect = pygame.Rect(
                self.viewer_rect.x + sel_screen_x,
                self.viewer_rect.y + sel_screen_y,
                self.width_tiles * active_tile_size * zoom,
                self.height_tiles * active_tile_size * zoom,
            )
            pygame.draw.rect(screen, (255, 220, 120), sel_rect, 2)
            if self.crop_kind == "pack":
                # Internal grid lines -- makes "this is N separate 1x1 (or
                # tile_size x tile_size) tiles, not one combined sprite"
                # visible at a glance.
                tile_px = active_tile_size * zoom
                for col in range(1, self.width_tiles):
                    lx = sel_rect.x + col * tile_px
                    pygame.draw.line(screen, (255, 220, 120), (lx, sel_rect.y), (lx, sel_rect.bottom), 1)
                for row in range(1, self.height_tiles):
                    ly = sel_rect.y + row * tile_px
                    pygame.draw.line(screen, (255, 220, 120), (sel_rect.x, ly), (sel_rect.right, ly), 1)
            screen.set_clip(clip)
        else:
            hint = self.small_font.render("Choisis un fichier a gauche", True, (180, 180, 180))
            screen.blit(hint, (self.viewer_rect.centerx - hint.get_width() / 2, self.viewer_rect.centery))

        self.name_box.render(screen)
        self._width_stepper.render(screen, self.border, self.font, self.width_tiles)
        self._height_stepper.render(screen, self.border, self.font, self.height_tiles)
        w_label = self.small_font.render("Largeur (tuiles)", True, (200, 200, 200))
        screen.blit(w_label, (self._width_stepper.minus_rect.x, self._width_stepper.minus_rect.y - w_label.get_height() - 2))
        h_label = self.small_font.render("Hauteur (tuiles)", True, (200, 200, 200))
        screen.blit(h_label, (self._height_stepper.minus_rect.x, self._height_stepper.minus_rect.y - h_label.get_height() - 2))

        if self.crop_kind == "pack":
            for kind_id, rect in self._pack_kind_rects.items():
                label = "Autotile" if kind_id == "autotile" else "Entite"
                selected = kind_id == self.pack_kind
                text = f"> {label}" if selected else label
                self.border.draw_centered_label(
                    screen, rect, self.small_font, text, (255, 220, 120) if selected else (255, 255, 255),
                )
            if self.pack_kind == "entite":
                self._entity_tile_size_stepper.render(screen, self.border, self.font, self.entity_tile_size)
                size_label = self.small_font.render("Taille de cellule (px)", True, (200, 200, 200))
                screen.blit(size_label, (
                    self._entity_tile_size_stepper.minus_rect.x,
                    self._entity_tile_size_stepper.minus_rect.y - size_label.get_height() - 2,
                ))

        if not (self.crop_kind == "pack" and self.pack_kind == "entite"):
            for archetype_id, rect in self._archetype_rects.items():
                label = ARCHETYPES[archetype_id]["label"]
                selected = archetype_id == self.archetype
                text = f"> {label}" if selected else label
                self.border.draw_centered_label(screen, rect, self.font, text, (255, 220, 120) if selected else (255, 255, 255))

        if self.crop_kind == "tuile" and self.archetype in self.CELL_MODES_ARCHETYPES:
            if self.width_tiles == 1 and self.height_tiles == 1:
                if self.archetype == "sol":
                    check_label = "[x] Bloque le mouvement" if self.blocks_movement else "[ ] Bloque le mouvement"
                    self.border.draw_centered_label(screen, self._blocks_rect, self.font, check_label)
            else:
                self._render_cell_modes_grid(screen)

        if self.crop_kind == "tuile":
            interact_label = "[x] Interagible" if self.interactable else "[ ] Interagible"
            self.border.draw_centered_label(screen, self._interactable_rect, self.font, interact_label)

        if self.crop_kind == "tuile" and self.archetype == "porte":
            lock_label = "[x] Porte verrouillable" if self.lockable else "[ ] Porte verrouillable"
            self.border.draw_centered_label(screen, self._lockable_rect, self.font, lock_label)

            self._door_frames_stepper.render(screen, self.border, self.font, self.door_frame_count)
            frames_label = self.small_font.render("Frames d'ouverture", True, (200, 200, 200))
            screen.blit(frames_label, (
                self._door_frames_stepper.minus_rect.x,
                self._door_frames_stepper.minus_rect.y - frames_label.get_height() - 2,
            ))

            self._render_door_frame_thumbs(screen)

        confirm_label = "Mettre a jour" if (self.crop_kind == "tuile" and self.editing_type_id is not None) else "Enregistrer"
        self.border.draw_centered_label(screen, self._confirm_rect, self.font, confirm_label)

        if self.status_text:
            status_surface = self.small_font.render(self.status_text, True, (255, 220, 120))
            screen.blit(status_surface, (self._confirm_rect.x, self._confirm_rect.bottom + 8))
    def _render_existing_card_markers(self, screen):
        """Outlines every custom card already sourced from the currently
        loaded file directly on the visionneuse, in a color distinct from
        the live selection (yellow) -- lets the player see what's already
        claimed before recadring over it, the visual half of the
        "cartes existantes" fix (see _refresh_existing_cards/
        _load_existing_card_for_edit)."""
        zoom = self.camera.zoom
        for type_id, config in custom_types_for_tileset(self.image_name):
            asset = config["asset"]
            # A multi-frame "porte" (see _build_custom_type_entry) has
            # "rects" (plural) instead of one "rect" -- outline every frame
            # of it, not just a first/only region.
            rects = asset["rects"] if "rects" in asset else [asset["rect"]]
            color = (255, 220, 120) if type_id == self.editing_type_id else (100, 180, 255)
            for rx, ry, rw, rh in rects:
                sx, sy = self.camera.world_to_screen(rx, ry)
                marker_rect = pygame.Rect(self.viewer_rect.x + sx, self.viewer_rect.y + sy, rw * zoom, rh * zoom)
                pygame.draw.rect(screen, color, marker_rect, 2)
    def _render_pack_region_markers(self, screen):
        """Light outlines over every region already extracted into an
        existing autotile pack from the currently loaded file -- read-only
        (no click-to-edit for packs this round, see the plan's own scope
        note), just visibility before re-selecting over the same spot."""
        zoom = self.camera.zoom
        for pack_name in list_autotile_packs():
            payload = load_autotile_pack(pack_name)
            if payload is None or payload.get("tileset") != self.image_name:
                continue
            for tile in payload.get("tiles", []):
                rx, ry, rw, rh = tile["rect"]
                sx, sy = self.camera.world_to_screen(rx, ry)
                marker_rect = pygame.Rect(self.viewer_rect.x + sx, self.viewer_rect.y + sy, rw * zoom, rh * zoom)
                pygame.draw.rect(screen, (150, 150, 150), marker_rect, 1)
    def _render_cell_modes_grid(self, screen):
        """The per-cell mode grid for a multi-cell "sol"/"mur"/"porte"
        selection (see _cell_mode_grid_rects/_ensure_cell_modes_grid) -- 3
        states cycled by click or hover+scroll (_cycle_cell_mode): red "B" =
        bloquant (pour "porte" avec blocks_until_open : bloque tant que pas
        ouverte, voir ObjectManager.is_cell_walkable), green "D" = ne bloque
        pas / derriere le joueur, blue "F" = ne bloque pas / devant le
        joueur (torch-style), each a compact label since cells can be as
        small as 16px (writing "Bloquant"/"Derriere"/"Devant" out in full
        inside a 16px cell isn't legible, hence the legend line drawn
        below the grid instead -- same three words, just not squeezed
        into the cell itself). Purement une question de rendu/blocage --
        quelle case valide le PLACEMENT (le mur pour une porte, le sol
        pour un objet sol/mur) est decide automatiquement ailleurs (voir
        ObjectManager._anchor_cell), independamment de ce marquage."""
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
    def _render_door_frame_thumbs(self, screen):
        """One small thumbnail per configured door_frame_rects entry,
        cropped straight from the currently loaded image -- click arms that
        frame for the next drag (see handle_event), highlighted with a
        yellow border same as the main selection. A frame beyond
        door_frame_rects' current length (shouldn't happen outside a
        mid-frame _ensure_door_frame_rects resize) or with no image loaded
        just shows its index on a blank tile instead of erroring."""
        for index, rect in self._door_frame_thumb_rects().items():
            pygame.draw.rect(screen, (40, 40, 45), rect)
            if self.image is not None and index < len(self.door_frame_rects):
                fx, fy, fw, fh = self.door_frame_rects[index]
                fx = max(0, min(fx, self.image.get_width() - 1))
                fy = max(0, min(fy, self.image.get_height() - 1))
                fw = max(1, min(fw, self.image.get_width() - fx))
                fh = max(1, min(fh, self.image.get_height() - fy))
                crop = self.image.subsurface(pygame.Rect(fx, fy, fw, fh))
                thumb = pygame.transform.scale(crop, rect.size)
                screen.blit(thumb, rect)
            border_color = (255, 220, 120) if index == self.editing_door_frame else (120, 120, 120)
            pygame.draw.rect(screen, border_color, rect, 2)
            label = self.small_font.render(str(index), True, (255, 255, 255))
            screen.blit(label, (rect.x + 1, rect.y + 1))

    def _layout_decouper(self, column):
        """Lays out mode "decouper"'s own UI -- called from
        SpriteEditorPanelUI._layout() with a LayoutColumn already
        positioned at (params_x, self.y + 100, step_w). Numerically
        identical to the pre-split offsets (verified by the split's own
        scripted rect comparison). existing_cards_browser/_new_card_rect
        live in the LEFT column (like file_browser), not `column`."""
        self.existing_cards_browser.x = self.x + 16
        self.existing_cards_browser.y = self.file_browser.y + self.file_browser.height + 16
        self._new_card_rect = pygame.Rect(
            self.existing_cards_browser.x, self.existing_cards_browser.y + self.existing_cards_browser.height + 8,
            200, 32,
        )

        crop_kind_rects = column.row(len(self.CROP_KINDS), 32, gap=4)
        self._crop_kind_rects = {kind_id: rect for (kind_id, _label), rect in zip(self.CROP_KINDS, crop_kind_rects)}
        column.gap(12)

        self.name_box.rect.topleft = (column.x, column.y)
        column.gap(32 + 14)

        self._width_stepper = Stepper(column.x, column.y, 28, 50, 1, self.MAX_TILES)
        column.gap(28 + 16)
        self._height_stepper = Stepper(column.x, column.y, 28, 50, 1, self.MAX_TILES)
        column.gap(28 + 16)

        # Fixed 60px width (not column.row()'s auto-computed width) --
        # matches the pre-split rect exactly (60*3+8*2=196, a few px past
        # step_w, same as it always was).
        self._archetype_rects = {}
        row_x = column.x
        for archetype_id, _preset in ARCHETYPES.items():
            rect = pygame.Rect(row_x, column.y, 60, 32)
            self._archetype_rects[archetype_id] = rect
            row_x = rect.right + 8
        column.gap(32 + 12)

        # _blocks_rect doubles as the per-cell walkable grid's anchor once
        # the tile is multi-cell -- crop_kind "pack"'s own pack_kind_rects/
        # entity_tile_size_stepper anchor off its .y directly rather than
        # through the shared cursor (same slot, never shown at once, same
        # "no real overlap" precedent as bitmap's own bm_toggle_rects)
        # since the cursor itself needs to keep moving toward
        # _interactable_rect regardless of which (if either) renders.
        self._blocks_rect = column.rect(32)
        self._pack_kind_rects = {}
        row_x = self._blocks_rect.x
        for kind_id, _label in (("autotile", "Autotile"), ("entite", "Entite")):
            rect = pygame.Rect(row_x, self._blocks_rect.y, 93, 32)
            self._pack_kind_rects[kind_id] = rect
            row_x = rect.right + 4
        self._entity_tile_size_stepper = Stepper(self._blocks_rect.x, self._blocks_rect.y + 44, 28, 50, 8, 128)

        column.gap(120)
        self._interactable_rect = column.rect(32)
        column.gap(8)
        self._lockable_rect = column.rect(32)
        column.gap(10)
        self._door_frames_stepper = Stepper(column.x, column.y, 28, 50, 1, self.MAX_DOOR_FRAMES)
        column.gap(28 + 76)
        self._confirm_rect = column.rect(40)
