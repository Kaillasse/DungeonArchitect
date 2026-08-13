"""PeindreMixin -- mode "Peindre" (ex-"pixel") of SpriteEditorPanelUI, split
out of the old monolithic sprite_editor.py (see core/editor/ui/sprite_editor/
panel.py's own docstring for why). A rudimentary Paint-style raster editor:
brush (color wheel + size), eyedropper, free pixel-precise rectangular
selection, copy/cut/paste, undo, save-in-place, blank-canvas creation.
Fully self-contained -- confirmed during the split audit to touch no
decouper/bitmap state at all, only the generic base infra (self.camera,
self.image, self.name_box, self.file_browser, etc.) shared by every mode.
"""

import math

import pygame

from core.data.ressources import PROJECT_ROOT, save_tileset_png
from core.ui.widgets import Stepper


class PeindreMixin:
    PX_TOOLS = (("brush", "Pinceau"), ("eyedropper", "Pipette"), ("select", "Selection"))
    PX_MAX_BRUSH_SIZE = 16
    PX_UNDO_LIMIT = 20
    PX_WHEEL_SIZE = 120
    PX_VALUE_SLIDER_HEIGHT = 120
    PX_NEW_CANVAS_DIR = "tiles/custom_sprites"
    PX_NEW_CANVAS_MIN = 8
    PX_NEW_CANVAS_MAX = 256

    def _px_params_origin(self):
        return self._confirm_rect.x, self.y + 100
    def _px_image_pos(self, screen_pos, clamp=False):
        """Screen -> image-pixel coordinates, floored to an int index --
        same conversion _move_selection_to uses (_local_pos +
        camera.screen_to_world) but WITHOUT its round(.../tile_size)*
        tile_size snap, since painting needs the exact pixel under the
        cursor, not a tile-aligned crop origin. clamp=False (click-to-START
        an action -- a brush stroke, an eyedropper pick, a selection
        anchor) requires the position to actually be inside both
        viewer_rect and the image's own bounds, else None. clamp=True
        (continuing an already-started drag, or a paste-at-cursor) instead
        clamps to the image's own edges, so a fast mouse movement past the
        viewer's border doesn't just stop painting/selecting -- same
        "keeps going, doesn't drop out" feel as a real paint tool."""
        if self.image is None:
            return None
        if not clamp and not self.viewer_rect.collidepoint(screen_pos):
            return None
        img_x, img_y = self.camera.screen_to_world(*self._local_pos(screen_pos))
        img_x, img_y = int(math.floor(img_x)), int(math.floor(img_y))
        w, h = self.image.get_size()
        if clamp:
            return max(0, min(img_x, w - 1)), max(0, min(img_y, h - 1))
        if not (0 <= img_x < w and 0 <= img_y < h):
            return None
        return img_x, img_y
    def _px_paint_at(self, img_x, img_y):
        size = self.brush_size
        half = size // 2
        pygame.draw.rect(self.image, self.brush_color, pygame.Rect(img_x - half, img_y - half, size, size))
    def _px_paint_line(self, from_pos, to_pos):
        """Steps pixel-by-pixel from from_pos to to_pos, painting each --
        without this, a fast mouse drag (more image-pixels crossed between
        two consecutive MOUSEMOTION events than a single _px_paint_at call
        would cover, easy at any real zoom level) leaves visible gaps in
        the stroke instead of a continuous line."""
        x0, y0 = from_pos
        x1, y1 = to_pos
        steps = max(abs(x1 - x0), abs(y1 - y0))
        if steps == 0:
            self._px_paint_at(x1, y1)
            return
        for step in range(steps + 1):
            t = step / steps
            self._px_paint_at(round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t))
    def _px_eyedrop_at(self, img_x, img_y):
        color = self.image.get_at((img_x, img_y))
        hue, sat, value, _alpha = pygame.Color(color.r, color.g, color.b, 255).hsva
        self._px_hue, self._px_sat, self._px_value = hue, sat, value
        self._px_recompute_brush_color()
        self.status_text = f"Couleur piochee : #{color.r:02x}{color.g:02x}{color.b:02x}."
    def _px_recompute_brush_color(self):
        """brush_color is always fully opaque (alpha 100%, no alpha
        control exists in this rudimentary pass) -- teinte/saturation come
        from the wheel, luminosite from the separate slider (see
        _px_pick_wheel/_px_pick_value_slider), recombined here on every
        change instead of baking luminosite into the cached wheel Surface
        (see _px_wheel_surface)."""
        color = pygame.Color(0)
        color.hsva = (
            self._px_hue % 360,
            max(0.0, min(100.0, self._px_sat)),
            max(0.0, min(100.0, self._px_value)),
            100,
        )
        self.brush_color = color
    def _px_wheel_surface(self):
        """Roue teinte/saturation (angle -> teinte, distance au centre ->
        saturation), construite une seule fois et mise en cache
        (self._px_wheel_cache) -- valeur fixee a 100 ici deliberement, le
        curseur de luminosite separe (_px_value_rect) la combine a la
        volee dans _px_recompute_brush_color plutot que de forcer une
        reconstruction pixel-par-pixel de cette Surface a chaque
        ajustement de luminosite."""
        if self._px_wheel_cache is not None:
            return self._px_wheel_cache
        size = self.PX_WHEEL_SIZE
        surface = pygame.Surface((size, size), pygame.SRCALPHA)
        radius = size / 2
        for y in range(size):
            for x in range(size):
                dx = x - radius + 0.5
                dy = y - radius + 0.5
                dist = math.hypot(dx, dy)
                if dist <= radius:
                    hue = (math.degrees(math.atan2(dy, dx)) + 360) % 360
                    sat = min(dist / radius, 1.0) * 100
                    color = pygame.Color(0)
                    color.hsva = (hue, sat, 100, 100)
                    surface.set_at((x, y), color)
        self._px_wheel_cache = surface
        return surface
    def _px_pick_wheel(self, pos):
        rect = self._px_wheel_rect
        radius = rect.width / 2
        dx = pos[0] - rect.centerx
        dy = pos[1] - rect.centery
        dist = min(math.hypot(dx, dy), radius)
        hue = (math.degrees(math.atan2(dy, dx)) + 360) % 360
        sat = (dist / radius) * 100 if radius else 0.0
        self._px_hue, self._px_sat = hue, sat
        self._px_recompute_brush_color()
    def _px_pick_value_slider(self, pos):
        rect = self._px_value_rect
        ratio = 1.0 - (pos[1] - rect.y) / rect.height
        self._px_value = max(0.0, min(100.0, ratio * 100))
        self._px_recompute_brush_color()
    def _px_update_selection(self, pos):
        if self._px_select_anchor is None:
            return
        ax, ay = self._px_select_anchor
        bx, by = pos
        x0, x1 = sorted((ax, bx))
        y0, y1 = sorted((ay, by))
        self.px_selection = pygame.Rect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    def _px_push_undo(self):
        """Snapshots the whole image before a destructive edit (a brush
        stroke, a cut, a paste) -- never for a merely navigational action
        (panning/zooming/selecting/picking a color), same "only a real
        edit dirties/snapshots" discipline bm_dirty already established
        for mode bitmap (see its own docstring for the data-corruption bug
        that taught that lesson)."""
        if self.image is None:
            return
        self._px_undo_stack.append(self.image.copy())
        if len(self._px_undo_stack) > self.PX_UNDO_LIMIT:
            del self._px_undo_stack[0]
    def _px_undo(self):
        if not self._px_undo_stack:
            self.status_text = "Rien a annuler."
            return
        self.image = self._px_undo_stack.pop()
        self.px_dirty = True
        self.status_text = "Annule."
    def _px_copy_selection(self):
        if self.image is None or self.px_selection is None:
            return
        clipped = self.px_selection.clip(self.image.get_rect())
        if clipped.width <= 0 or clipped.height <= 0:
            self.status_text = "Selection vide."
            return
        self.px_clipboard = self.image.subsurface(clipped).copy()
        self.status_text = f"Copie ({clipped.width}x{clipped.height})."
    def _px_cut_selection(self):
        if self.image is None or self.px_selection is None:
            return
        clipped = self.px_selection.clip(self.image.get_rect())
        if clipped.width <= 0 or clipped.height <= 0:
            self.status_text = "Selection vide."
            return
        self._px_push_undo()
        self.px_clipboard = self.image.subsurface(clipped).copy()
        self.image.fill((0, 0, 0, 0), clipped)
        self.px_dirty = True
        self.status_text = f"Coupe ({clipped.width}x{clipped.height})."
    def _px_paste_at_cursor(self):
        """Colle immediatement au point image sous le curseur -- pas de
        "collage flottant" qu'on drag avant de valider (simplification
        deliberee, coherente avec la demande "outils rudimentaires")."""
        if self.image is None or self.px_clipboard is None:
            return
        pos = self._px_image_pos(pygame.mouse.get_pos(), clamp=True)
        if pos is None:
            return
        self._px_push_undo()
        self.image.blit(self.px_clipboard, pos)
        self.px_dirty = True
        self.status_text = "Colle."
    def _px_handle_keydown(self, event):
        """Ctrl+C/X/V/Z only -- the sole KEYDOWN branch in this whole file
        (see handle_event's own comment) has no existing modifier handling
        to collide with. Gated to mode "pixel" with no text field visible
        by the caller (see handle_event) -- the new-canvas sub-form's
        name_box gets KEYDOWN routed to it directly instead, never here."""
        if not (pygame.key.get_mods() & pygame.KMOD_CTRL):
            return
        if event.key == pygame.K_c:
            self._px_copy_selection()
        elif event.key == pygame.K_x:
            self._px_cut_selection()
        elif event.key == pygame.K_v:
            self._px_paste_at_cursor()
        elif event.key == pygame.K_z:
            self._px_undo()
    def _px_new_canvas_create(self):
        """Cree une toile vierge, entierement transparente, et l'ecrit
        IMMEDIATEMENT sur disque (contrairement a tuile/pack/bitmap, rien
        n'attend "Enregistrer" ici) -- ainsi le fichier existe reellement
        des ce point, unifiant tout de suite avec le flux "ouvrir un PNG
        existant" (memes _px_save/dirty-tracking ensuite pour les deux)."""
        raw_name = self.name_box.value.strip()
        if not raw_name:
            self.status_text = "Donne un nom a la nouvelle image."
            return
        target_dir = PROJECT_ROOT / "assets" / self.PX_NEW_CANVAS_DIR
        existing = {p.stem for p in target_dir.glob("*.png")} if target_dir.exists() else set()
        slug = self._sanitize_id(raw_name, existing, fallback="sprite")
        width = max(self.PX_NEW_CANVAS_MIN, min(self._px_new_w, self.PX_NEW_CANVAS_MAX))
        height = max(self.PX_NEW_CANVAS_MIN, min(self._px_new_h, self.PX_NEW_CANVAS_MAX))
        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        surface.fill((0, 0, 0, 0))
        relative_path = f"{self.PX_NEW_CANVAS_DIR}/{slug}.png"
        save_tileset_png(surface, relative_path)

        self.image = surface
        self.image_name = relative_path
        fit_scale = min(self.VIEWER_WIDTH / width, self.VIEWER_HEIGHT / height)
        self.camera.zoom = max(self.VIEWER_MIN_SCALE, min(self.VIEWER_MAX_SCALE, fit_scale))
        self.camera.x = 0.0
        self.camera.y = 0.0
        self.px_selection = None
        self._px_undo_stack = []
        self.px_dirty = False
        self._px_new_canvas_open = False
        self.name_box.value = ""
        self._refresh_file_list()
        self.status_text = f"'{slug}.png' cree ({width}x{height})."
    def _px_save(self):
        if self.image is None or self.image_name is None:
            self.status_text = "Aucune image chargee."
            return
        save_tileset_png(self.image, self.image_name)
        self.px_dirty = False
        self.status_text = f"'{self.image_name}' enregistre."
    def _handle_pixel_event(self, event):
        """Mode "pixel"'s own event handling -- entirely separate from
        every other mode's chain (see MODES' own docstring for what this
        mode does), dispatched before any tuile/pack/bitmap rect is ever
        tested, same self-contained-mode precedent as
        _handle_bitmap_event. Never returns a value Creator would credit a
        card for (see handle_event's own docstring) -- this mode only ever
        produces/edits a PNG file, never an OBJECT_TYPES entry."""
        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.file_browser.handle_event(event)
                self._px_painting = False
                self._px_last_paint_pos = None
                self._px_select_anchor = None
                self._px_dragging_wheel = False
                self._px_dragging_value = False
            elif event.button == 2:
                self._panning = False
                self._pan_last_pos = None
            return None

        if event.type == pygame.MOUSEMOTION:
            if self._panning and self._pan_last_pos is not None:
                dx = event.pos[0] - self._pan_last_pos[0]
                dy = event.pos[1] - self._pan_last_pos[1]
                self.camera.x -= dx / self.camera.zoom
                self.camera.y -= dy / self.camera.zoom
                self._pan_last_pos = event.pos
                return None
            if self._px_dragging_wheel:
                self._px_pick_wheel(event.pos)
                return None
            if self._px_dragging_value:
                self._px_pick_value_slider(event.pos)
                return None
            if self._px_painting and self.px_tool == "brush":
                pos = self._px_image_pos(event.pos, clamp=True)
                if pos is not None:
                    if self._px_last_paint_pos is not None:
                        self._px_paint_line(self._px_last_paint_pos, pos)
                    else:
                        self._px_paint_at(*pos)
                    self._px_last_paint_pos = pos
                    self.px_dirty = True
                return None
            if self._px_select_anchor is not None and self.px_tool == "select":
                pos = self._px_image_pos(event.pos, clamp=True)
                if pos is not None:
                    self._px_update_selection(pos)
                return None
            self.file_browser.handle_event(event)
            return None

        # MOUSEBUTTONDOWN from here.
        if self.file_browser.is_modal:
            self.file_browser.handle_event(event)
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

        if self._handle_mode_switch(event.pos):
            return None

        if self.file_browser.contains(event.pos):
            self.file_browser.handle_event(event)
            selected = self.file_browser.selected_name
            if selected is not None and self._full_image_name(selected) != self.image_name:
                self._load_image(selected)
                self.px_selection = None
                self.px_clipboard = None
                self._px_undo_stack = []
                self.px_dirty = False
            return None

        if self._px_new_canvas_open:
            params_x, px_top_y = self._px_params_origin()
            self.name_box.rect.topleft = (params_x, px_top_y + 80)

            new_width = self._px_new_width_stepper.handle_click(event.pos, self._px_new_w)
            if new_width is not None:
                self._px_new_w = new_width
                return None
            new_height = self._px_new_height_stepper.handle_click(event.pos, self._px_new_h)
            if new_height is not None:
                self._px_new_h = new_height
                return None
            if self._px_create_rect.collidepoint(event.pos):
                self._px_new_canvas_create()
                return None
            if self._px_cancel_new_rect.collidepoint(event.pos):
                self._px_new_canvas_open = False
                self.status_text = ""
                return None
            return None

        for tool_id, rect in self._px_tool_rects.items():
            if rect.collidepoint(event.pos):
                self.px_tool = tool_id
                return None

        if self._px_new_rect.collidepoint(event.pos):
            self._px_new_canvas_open = True
            self.name_box.value = ""
            self.status_text = ""
            return None

        if self._px_save_rect.collidepoint(event.pos):
            self._px_save()
            return None
        if self._px_undo_rect.collidepoint(event.pos):
            self._px_undo()
            return None

        if self.px_tool == "brush":
            new_size = self._px_brush_stepper.handle_click(event.pos, self.brush_size)
            if new_size is not None:
                self.brush_size = new_size
                return None
            if self._px_wheel_rect.collidepoint(event.pos):
                self._px_dragging_wheel = True
                self._px_pick_wheel(event.pos)
                return None
            if self._px_value_rect.collidepoint(event.pos):
                self._px_dragging_value = True
                self._px_pick_value_slider(event.pos)
                return None

        pos = self._px_image_pos(event.pos)
        if pos is not None:
            if self.px_tool == "brush":
                self._px_push_undo()
                self._px_painting = True
                self._px_paint_at(*pos)
                self._px_last_paint_pos = pos
                self.px_dirty = True
            elif self.px_tool == "eyedropper":
                self._px_eyedrop_at(*pos)
            elif self.px_tool == "select":
                self._px_select_anchor = pos
                self.px_selection = pygame.Rect(pos[0], pos[1], 1, 1)
        return None
    def _render_pixel(self, screen):
        """Mode "pixel"'s own rendering -- file browser (root "", tout
        assets/, voir _set_mode) + outils/roue de couleur a gauche, image
        chargee (ou indice si aucune) dans viewer_rect avec le meme pan/
        zoom Camera que tous les autres modes."""
        params_x, px_top_y = self._px_params_origin()

        self.file_browser.render(screen)

        for tool_id, rect in self._px_tool_rects.items():
            label = dict(self.PX_TOOLS)[tool_id]
            selected = tool_id == self.px_tool
            text = f"> {label}" if selected else label
            self.border.draw_centered_label(
                screen, rect, self.small_font, text, (255, 220, 120) if selected else (255, 255, 255),
            )

        self.border.draw_centered_label(screen, self._px_new_rect, self.font, "Nouveau")

        if self._px_new_canvas_open:
            self.name_box.rect.topleft = (params_x, px_top_y + 80)
            self.name_box.render(screen)
            name_label = self.small_font.render("Nom du fichier", True, (200, 200, 200))
            screen.blit(name_label, (self.name_box.rect.x, self.name_box.rect.y - 18))

            self._px_new_width_stepper.render(screen, self.border, self.font, self._px_new_w)
            w_label = self.small_font.render("Largeur (px)", True, (200, 200, 200))
            screen.blit(w_label, (
                self._px_new_width_stepper.minus_rect.x,
                self._px_new_width_stepper.minus_rect.y - w_label.get_height() - 2,
            ))

            self._px_new_height_stepper.render(screen, self.border, self.font, self._px_new_h)
            h_label = self.small_font.render("Hauteur (px)", True, (200, 200, 200))
            screen.blit(h_label, (
                self._px_new_height_stepper.minus_rect.x,
                self._px_new_height_stepper.minus_rect.y - h_label.get_height() - 2,
            ))

            self.border.draw_centered_label(screen, self._px_create_rect, self.font, "Creer")
            self.border.draw_centered_label(screen, self._px_cancel_new_rect, self.font, "Annuler")
        elif self.px_tool == "brush":
            self._px_brush_stepper.render(screen, self.border, self.font, self.brush_size)
            size_label = self.small_font.render("Taille du pinceau", True, (200, 200, 200))
            screen.blit(size_label, (
                self._px_brush_stepper.minus_rect.x,
                self._px_brush_stepper.minus_rect.y - size_label.get_height() - 2,
            ))

            screen.blit(self._px_wheel_surface(), self._px_wheel_rect.topleft)
            radius = self._px_wheel_rect.width / 2
            angle = math.radians(self._px_hue)
            dist = (self._px_sat / 100) * radius
            cursor_pos = (
                round(self._px_wheel_rect.centerx + math.cos(angle) * dist),
                round(self._px_wheel_rect.centery + math.sin(angle) * dist),
            )
            pygame.draw.circle(screen, (255, 255, 255), cursor_pos, 4, 1)

            pygame.draw.rect(screen, (60, 60, 60), self._px_value_rect)
            value_y = self._px_value_rect.bottom - (self._px_value / 100) * self._px_value_rect.height
            pygame.draw.rect(screen, (230, 230, 230), (self._px_value_rect.x, value_y - 2, self._px_value_rect.width, 4))
            pygame.draw.rect(screen, (255, 255, 255), self._px_value_rect, 1)

            pygame.draw.rect(screen, self.brush_color, self._px_swatch_rect)
            pygame.draw.rect(screen, (255, 255, 255), self._px_swatch_rect, 1)
        elif self.px_tool == "select" and self.px_selection is not None:
            hint = self.small_font.render(
                f"Selection : {self.px_selection.width}x{self.px_selection.height}", True, (200, 200, 200),
            )
            screen.blit(hint, (params_x, px_top_y + 84))

        save_label = "Enregistrer *" if self.px_dirty else "Enregistrer"
        self.border.draw_centered_label(screen, self._px_save_rect, self.font, save_label)
        self.border.draw_centered_label(screen, self._px_undo_rect, self.font, "Annuler (Ctrl+Z)")

        self.border.draw(screen, self.viewer_rect)
        if self.image is not None:
            zoom = self.camera.zoom
            scaled_size = (round(self.image.get_width() * zoom), round(self.image.get_height() * zoom))
            scaled_image = pygame.transform.scale(self.image, scaled_size)
            image_screen_x, image_screen_y = self.camera.world_to_screen(0, 0)
            clip = screen.get_clip()
            screen.set_clip(self.viewer_rect)
            screen.blit(scaled_image, (self.viewer_rect.x + image_screen_x, self.viewer_rect.y + image_screen_y))
            if self.px_selection is not None:
                sx, sy = self.camera.world_to_screen(self.px_selection.x, self.px_selection.y)
                sel_rect = pygame.Rect(
                    self.viewer_rect.x + sx, self.viewer_rect.y + sy,
                    self.px_selection.width * zoom, self.px_selection.height * zoom,
                )
                pygame.draw.rect(screen, (255, 220, 120), sel_rect, 2)
            screen.set_clip(clip)
        else:
            hint = self.small_font.render("Choisis un fichier a gauche, ou cree une image", True, (180, 180, 180))
            screen.blit(hint, (self.viewer_rect.centerx - hint.get_width() / 2, self.viewer_rect.centery))

        if self.status_text:
            status_surface = self.small_font.render(self.status_text, True, (255, 220, 120))
            screen.blit(status_surface, (self._px_undo_rect.x, self._px_undo_rect.bottom + 8))

    def _layout_peindre(self, column):
        """Lays out mode "peindre"'s own params column -- called from
        SpriteEditorPanelUI._layout() with a LayoutColumn already
        positioned at (params_x, self.y + 100, step_w). Numerically
        identical to the offsets this mode used before the LayoutColumn
        split (verified by the split's own scripted checks comparing
        every produced rect against the pre-split values) -- the tools
        row/new-button/save/undo flow through the shared cursor linearly,
        but the middle section is genuinely two parallel, mutually
        exclusive sub-layouts (brush controls vs. new-canvas sub-form)
        that happen to share their starting y -- modeled as two small
        local offset chains anchored on that one shared snapshot point
        (`branch_y`) rather than forced through one cursor, since they
        don't actually share a rhythm past that point (see PX_TOOLS/
        _px_new_canvas_open's own docstrings for what each branch is)."""
        tool_rects = column.row(len(self.PX_TOOLS), 32, gap=5)
        self._px_tool_rects = {tool_id: rect for (tool_id, _label), rect in zip(self.PX_TOOLS, tool_rects)}
        column.gap(8)
        self._px_new_rect = column.rect(32)
        column.gap(8)
        branch_y = column.y

        # Branch A -- brush tool controls. name_box (branch B's filename
        # field) is intentionally NOT laid out here -- it's repositioned
        # dynamically inside _render_pixel/_handle_pixel_event instead,
        # same as before the split.
        self._px_brush_stepper = Stepper(column.x, branch_y, 28, 50, 1, self.PX_MAX_BRUSH_SIZE)
        wheel_top = branch_y + 44
        wheel_x = column.x + (column.width - self.PX_WHEEL_SIZE) // 2
        self._px_wheel_rect = pygame.Rect(wheel_x, wheel_top, self.PX_WHEEL_SIZE, self.PX_WHEEL_SIZE)
        self._px_value_rect = pygame.Rect(self._px_wheel_rect.right + 8, wheel_top, 24, self.PX_VALUE_SLIDER_HEIGHT)
        self._px_swatch_rect = pygame.Rect(column.x, self._px_wheel_rect.bottom + 8, 48, 28)

        # Branch B -- new-canvas sub-form (name_box, then width/height
        # steppers, then Creer/Annuler) -- own +44px rhythm from branch_y.
        self._px_new_width_stepper = Stepper(column.x, wheel_top, 28, 50, self.PX_NEW_CANVAS_MIN, self.PX_NEW_CANVAS_MAX)
        self._px_new_height_stepper = Stepper(column.x, wheel_top + 44, 28, 50, self.PX_NEW_CANVAS_MIN, self.PX_NEW_CANVAS_MAX)
        px_half = (column.width - 8) // 2
        create_y = wheel_top + 84
        self._px_create_rect = pygame.Rect(column.x, create_y, px_half, 32)
        self._px_cancel_new_rect = pygame.Rect(self._px_create_rect.right + 8, create_y, px_half, 32)

        # Both branches done -- resync the shared cursor past the taller
        # of the two (branch A's swatch ends furthest down) before
        # continuing the linear save/undo tail.
        column.y = branch_y + 250
        self._px_save_rect = column.rect(40)
        column.gap(8)
        self._px_undo_rect = column.rect(32)
