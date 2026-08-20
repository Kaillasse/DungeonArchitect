"""ExtraireMixin -- mode "Extraire" of SpriteEditorPanelUI (added 2026-08-18,
Plan A / Phase 2 of the editor simplification -- see CLAUDE.md). Replaces
DecouperMixin's old crop_kind="pack" sub-mode: load an image, draw a
selection (1x1 or a WxH grid of `extract_tile_size`-px cells), "Ajouter au
pack" crops it into that image's own region library (one
core.data.ressources autotile_pack JSON per source image, kind=None until
something later gives it a vocation -- see ressources.add_pack_regions'
own docstring) and keeps going: repeat with a new selection (same or a
different pack name) to keep growing the same library across a whole
editing session, instead of committing to one crop-and-register-everything
call the way "tuile" mode still does.

Deliberately does NOT choose "autotile" vs "entite" vs any card archetype
here at all -- that's Assembler's job (Phase 3, not built yet). Browses
every PNG under assets/ in one flat list (self._file_browser_root = "",
the same mechanism PeindreMixin already uses) rather than a Tuiles/
Personnages folder toggle -- confirmed with the user that splitting this
NEW panel by source folder felt like exactly the kind of category
fragmentation the whole refactor is meant to remove: the editor doesn't
need to know or care where a PNG lives to crop a region out of it."""

import pygame

from core.data.ressources import TILE_SIZE, add_pack_regions, list_autotile_packs, load_autotile_pack
from core.ui.widgets import Stepper


class ExtraireMixin:
    EXTRACT_MAX_GRID = 30

    def _extract_active_pack_name(self):
        """The sanitized pack name the current name_box text would target --
        just a slug, deliberately NOT deduped against list_autotile_packs()
        the way _sanitize_id is (see _try_extract's own docstring for why:
        typing an EXISTING pack's name here means "keep adding to it", not
        "make a new one with a numeric suffix")."""
        raw = self.name_box.value.strip()
        return "".join(c if c.isalnum() else "_" for c in raw.lower()).strip("_") or None

    def _extract_target_pack_info(self):
        """(pack_name, existing_tile_count) for whatever the name box
        currently spells, or (None, 0) if it's empty -- purely informational,
        rendered next to the name box so it's obvious whether Confirmer is
        about to create a brand-new pack or grow an existing one."""
        pack_name = self._extract_active_pack_name()
        if pack_name is None:
            return None, 0
        payload = load_autotile_pack(pack_name)
        if payload is None:
            return pack_name, 0
        return pack_name, len(payload.get("tiles", []))

    def _extract_clamp_selection(self):
        if self.image is None:
            return
        img_w, img_h = self.image.get_size()
        sel_w = self.extract_width * self.extract_tile_size
        sel_h = self.extract_height * self.extract_tile_size
        self.extract_sel_x = max(0, min(self.extract_sel_x, max(0, img_w - sel_w)))
        self.extract_sel_y = max(0, min(self.extract_sel_y, max(0, img_h - sel_h)))

    def _extract_move_selection_to(self, screen_pos):
        img_x, img_y = self.camera.screen_to_world(*self._local_pos(screen_pos))
        self.extract_sel_x = round(img_x / self.extract_tile_size) * self.extract_tile_size
        self.extract_sel_y = round(img_y / self.extract_tile_size) * self.extract_tile_size
        self._extract_clamp_selection()

    def _try_extract(self):
        """"Ajouter au pack" -- crops the current WxH-at-extract_tile_size
        selection into extract_width*extract_height individual regions and
        appends them (see ressources.add_pack_regions) to whatever pack the
        name box spells. No dedup-by-suffix here (contrast Decouper's own
        _try_register/_sanitize_id): the whole point of this mode is that
        typing the SAME name again keeps growing that pack instead of
        spawning pack_2 -- see _extract_active_pack_name."""
        if self.image is None:
            self.status_text = "Choisis d'abord un fichier."
            return
        pack_name = self._extract_active_pack_name()
        if pack_name is None:
            self.status_text = "Donne un nom au pack (nouveau, ou existant pour continuer a y ajouter)."
            return

        rects = [
            (
                self.extract_sel_x + col * self.extract_tile_size,
                self.extract_sel_y + row * self.extract_tile_size,
                self.extract_tile_size, self.extract_tile_size,
            )
            for row in range(self.extract_height)
            for col in range(self.extract_width)
        ]

        try:
            new_indices = add_pack_regions(pack_name, self.image_name, rects)
        except ValueError as exc:
            self.status_text = str(exc)
            return

        self.status_text = f"'{pack_name}' : {len(new_indices)} region(s) ajoutee(s) (total {new_indices[-1] + 1})."

    def _layout_extraire(self, column):
        # "Peindre" toggle -- LEFT column, directly below file_browser (same
        # slot Decouper's own existing_cards_browser/_new_card_rect used to
        # occupy there) -- confirmed with the user: Peindre belongs on the
        # left side of Extraire, not a top-level mode of its own anymore.
        self._extract_peindre_toggle_rect = pygame.Rect(
            self.x + 16, self.file_browser.y + self.file_browser.height + 16, 200, 32,
        )

        # name_box itself is a SHARED single TextInputBox (Decouper/Bitmap/
        # Peindre each reposition it too, for their own field) -- since
        # SpriteEditorPanelUI._layout() calls every mode's _layout_xxx ONCE
        # at construction, whichever runs LAST silently wins the actual
        # `.rect` position for everyone. Bitmap already works around this
        # (see _entity_bm_layout's own docstring: "recomputed on every
        # call") by repositioning it fresh at USE time instead of relying
        # on this one-time pass -- _extract_name_box_pos is that same fix
        # for Extraire: the real position gets (re)applied in
        # _render_extraire/_handle_extraire_event, every time this mode is
        # actually active, undoing whatever another mode's own layout call
        # left it at.
        self._extract_name_box_pos = (column.x, column.y)
        # name_box's own 32px height, then room for the pack-info line
        # rendered just below it (see _render_extraire), then clearance
        # before the next stepper's own label (drawn ABOVE it, intruding
        # into the tail of this gap -- same convention every stepper label
        # in this file uses).
        column.gap(32 + 34)

        self._extract_tile_size_stepper = Stepper(column.x, column.y, 28, 50, 8, 128)
        column.gap(28 + 16)
        self._extract_width_stepper = Stepper(column.x, column.y, 28, 50, 1, self.EXTRACT_MAX_GRID)
        column.gap(28 + 16)
        self._extract_height_stepper = Stepper(column.x, column.y, 28, 50, 1, self.EXTRACT_MAX_GRID)
        column.gap(28 + 24)

        self._extract_confirm_rect = column.rect(40)

    def _toggle_extract_peindre(self):
        """Flips extract_peindre_mode. file_browser_root itself no longer
        needs touching here either way (2026-08-20: plain "Extraire"
        already browses all of assets/ -- root "" -- same as this
        sub-toggle always did, so entering/leaving it is a no-op for the
        browser now, not a root switch)."""
        self.extract_peindre_mode = not self.extract_peindre_mode
        if not self.extract_peindre_mode:
            self._px_painting = False
            self._px_new_canvas_open = False
            self._px_dragging_wheel = False
            self._px_dragging_value = False
            self._px_select_anchor = None

    def _handle_extraire_event(self, event):
        if (
            event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
            and self._extract_peindre_toggle_rect.collidepoint(event.pos)
        ):
            self._toggle_extract_peindre()
            return None

        if self.extract_peindre_mode:
            return self._handle_pixel_event(event)

        self.name_box.rect.topleft = self._extract_name_box_pos
        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 2:
                self._panning = False
                self._pan_last_pos = None
                return None
            self._dragging_selection = False
            if event.button == 1:
                self.file_browser.handle_event(event)
            return None

        if event.type == pygame.MOUSEMOTION:
            if self._panning and self._pan_last_pos is not None:
                dx = event.pos[0] - self._pan_last_pos[0]
                dy = event.pos[1] - self._pan_last_pos[1]
                self.camera.x -= dx / self.camera.zoom
                self.camera.y -= dy / self.camera.zoom
                self._pan_last_pos = event.pos
                return None
            if self._dragging_selection:
                self._extract_move_selection_to(event.pos)
                return None
            self.file_browser.handle_event(event)
            return None

        # MOUSEBUTTONDOWN from here on.
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

        for mode_id, rect in self._mode_rects.items():
            if rect.collidepoint(event.pos):
                self._set_mode(mode_id)
                return None

        if self.file_browser.contains(event.pos):
            self.file_browser.handle_event(event)
            selected = self.file_browser.selected_name
            if selected is not None and self._full_image_name(selected) != self.image_name:
                self._load_image(selected)
                self.extract_sel_x = 0
                self.extract_sel_y = 0
                self._extract_clamp_selection()
            return None

        if self.viewer_rect.collidepoint(event.pos) and self.image is not None:
            self._dragging_selection = True
            self._extract_move_selection_to(event.pos)
            return None

        new_size = self._extract_tile_size_stepper.handle_click(event.pos, self.extract_tile_size)
        if new_size is not None:
            self.extract_tile_size = new_size
            self._extract_clamp_selection()
            return None

        new_width = self._extract_width_stepper.handle_click(event.pos, self.extract_width)
        if new_width is not None:
            self.extract_width = new_width
            self._extract_clamp_selection()
            return None

        new_height = self._extract_height_stepper.handle_click(event.pos, self.extract_height)
        if new_height is not None:
            self.extract_height = new_height
            self._extract_clamp_selection()
            return None

        if self._extract_confirm_rect.collidepoint(event.pos):
            self._try_extract()
            return None

        return None

    def _render_pack_region_markers(self, screen):
        """Light outlines over every region already extracted into an
        existing pack from the currently loaded file -- read-only (no
        click-to-edit for packs), just visibility before re-selecting over
        the same spot. Moved here from DecouperMixin 2026-08-18 once Pack
        mode was retired -- region extraction is entirely this mode's own
        concern now."""
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

    def _render_extraire(self, screen):
        peindre_label = "[x] Peindre" if self.extract_peindre_mode else "[ ] Peindre"
        self.border.draw_centered_label(screen, self._extract_peindre_toggle_rect, self.font, peindre_label)
        if self.extract_peindre_mode:
            self._render_pixel(screen)
            return

        self.name_box.rect.topleft = self._extract_name_box_pos
        self.file_browser.render(screen)

        self.border.draw(screen, self.viewer_rect)
        if self.image is not None:
            zoom = self.camera.zoom
            scaled_size = (round(self.image.get_width() * zoom), round(self.image.get_height() * zoom))
            scaled_image = pygame.transform.scale(self.image, scaled_size)
            image_screen_x, image_screen_y = self.camera.world_to_screen(0, 0)
            clip = screen.get_clip()
            screen.set_clip(self.viewer_rect)
            screen.blit(scaled_image, (self.viewer_rect.x + image_screen_x, self.viewer_rect.y + image_screen_y))

            self._render_pack_region_markers(screen)

            sel_screen_x, sel_screen_y = self.camera.world_to_screen(self.extract_sel_x, self.extract_sel_y)
            sel_rect = pygame.Rect(
                self.viewer_rect.x + sel_screen_x,
                self.viewer_rect.y + sel_screen_y,
                self.extract_width * self.extract_tile_size * zoom,
                self.extract_height * self.extract_tile_size * zoom,
            )
            pygame.draw.rect(screen, (255, 220, 120), sel_rect, 2)
            tile_px = self.extract_tile_size * zoom
            for col in range(1, self.extract_width):
                lx = sel_rect.x + col * tile_px
                pygame.draw.line(screen, (255, 220, 120), (lx, sel_rect.y), (lx, sel_rect.bottom), 1)
            for row in range(1, self.extract_height):
                ly = sel_rect.y + row * tile_px
                pygame.draw.line(screen, (255, 220, 120), (sel_rect.x, ly), (sel_rect.right, ly), 1)
            screen.set_clip(clip)
        else:
            hint = self.small_font.render("Choisis un fichier a gauche", True, (180, 180, 180))
            screen.blit(hint, (self.viewer_rect.centerx - hint.get_width() / 2, self.viewer_rect.centery))

        self.name_box.render(screen)
        pack_name, existing_count = self._extract_target_pack_info()
        if pack_name is not None:
            info = f"'{pack_name}' -- {existing_count} region(s) deja extraite(s)" if existing_count else f"'{pack_name}' -- nouveau pack"
        else:
            info = "Nom du pack (nouveau ou existant)"
        info_label = self.small_font.render(info, True, (200, 200, 200))
        screen.blit(info_label, (self.name_box.rect.x, self.name_box.rect.bottom + 4))

        for stepper, value, label_text in (
            (self._extract_tile_size_stepper, self.extract_tile_size, "Taille de tuile (px)"),
            (self._extract_width_stepper, self.extract_width, "Largeur (tuiles)"),
            (self._extract_height_stepper, self.extract_height, "Hauteur (tuiles)"),
        ):
            stepper.render(screen, self.border, self.font, value)
            label = self.small_font.render(label_text, True, (200, 200, 200))
            screen.blit(label, (stepper.minus_rect.x, stepper.minus_rect.y - label.get_height() - 2))

        self.border.draw_centered_label(screen, self._extract_confirm_rect, self.font, "Ajouter au pack")

        if self.status_text:
            status_surface = self.small_font.render(self.status_text, True, (255, 220, 120))
            screen.blit(status_surface, (self._extract_confirm_rect.x, self._extract_confirm_rect.bottom + 8))
