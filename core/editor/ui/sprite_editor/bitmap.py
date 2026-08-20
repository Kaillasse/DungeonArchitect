"""BitmapMixin -- mode "Bitmap" of SpriteEditorPanelUI, split out of the old
monolithic sprite_editor.py (see core/editor/ui/sprite_editor/panel.py's own
docstring for why). Autotile neighbor-bitmask/variant tagging on an already-
extracted pack, AND NPC/entity-pack action/direction/order tagging together
-- confirmed during the split audit that these two are NOT a clean seam
(shared state: pack_browser, bm_pack_name, _bm_pack_payload/_bm_tile_at/
_select_bitmap_pack/_try_delete_pack/_try_rename_pack all straddle both),
so they stay in one file rather than forcing an artificial split that would
just relocate the coupling. Stays independent from "decouper"/the Forge for
now -- its possible future split between them is explicitly undecided, not
part of this refactor (see CLAUDE.md)."""

import pygame

from core.world.object_manager import (
    OBJECT_TYPES, delete_custom_type,
    NPC_DIRECTIONS, npc_types_for_pack,
    rename_entity_pack_references, action_direction_coverage,
    register_custom_type, update_custom_type, update_type_visual, update_type_mechanics, custom_types_for_tileset,
)
from core.data.ressources import (
    load_tileset_region,
    list_autotile_packs, load_autotile_pack, update_autotile_pack_tile, update_autotile_pack_tiles,
    get_autotile_pack_path, delete_autotile_pack, rename_autotile_pack, pack_references, type_references,
    update_autotile_pack_meta,
)
from core.editor.autotile import EMPTY, FLOOR, WALL, DEFAULT_VARIANT_KEY
from core.ui.widgets import Stepper


class BitmapMixin:
    FLOOR_REFERENCE_SHAPES = (
        "1111", "1112", "1121", "1122", "1211", "1221", "2111", "2112", "2211",
    )
    WALL_REFERENCE_SHAPES = (
        "0022", "0212", "0220", "1122", "1202", "1221", "2002", "2021", "2120", "2200",
    )

    # Libelles courts -- ces boutons partagent la largeur de la colonne de
    # parametres a 3, une chaine longue deborderait de son propre rect
    # (draw_centered_label ne tronque/wrap pas). Le titre du panneau +
    # status_text donnent le contexte complet.
    #
    # "decouper" regroupe les anciens modes "tuile" et "pack" (voir
    # crop_kind, le sous-toggle qui choisit lequel des deux comportements
    # est actif -- tuile/pack ne sont plus des self.mode possibles depuis
    # ce regroupement, seulement des self.crop_kind). "peindre" est un pur
    # renommage de l'ancien mode "pixel" -- aucun changement de
    # comportement, seuls les identifiants internes _px_*/_handle_pixel_
    # event/_render_pixel restent tels quels (identifiants Python internes,
    # non visibles, les renommer serait du churn sans benefice).
    NEIGHBOR_KEYS = ("up", "right", "down", "left")
    NEIGHBOR_VALUE_LABELS = {EMPTY: "Vide", FLOOR: "Sol", WALL: "Mur"}
    NEIGHBOR_VALUE_COLORS = {EMPTY: (50, 50, 55), FLOOR: (214, 186, 138), WALL: (92, 78, 66)}
    NEIGHBOR_CYCLE = (EMPTY, FLOOR, WALL)

    # Per-cell mode for a multi-cell "sol"/"mur"/"porte" tile
    # (core.world.object_manager.CELL_MODES) -- "block" solide/non walkable
    # (pour "porte" verrouillable : bloque tant qu'elle n'est pas ouverte,
    # voir ObjectManager.is_cell_walkable), "behind" walkable dessine dans
    # l'ordre normal (ex: fleurs, tapis), "front" walkable dessine devant le
    # joueur (ex: torche). Purement une question de rendu/blocage -- n'a
    # aucune influence sur quelle case valide le PLACEMENT (voir
    # object_manager.ObjectManager._anchor_cell, toujours automatique : le
    # bas-centre du footprint, meme case marquee ici ou non). Meme cycle
    # click-ou-scroll que le mode bitmap (voir _cycle_cell_mode/
    # _handle_cell_mode_wheel).
    NEIGHBOR_GRID_POSITIONS = {
        "nw": (0, 0), "up": (0, 1), "ne": (0, 2),
        "left": (1, 0), "center": (1, 1), "right": (1, 2),
        "sw": (2, 0), "down": (2, 1), "se": (2, 2),
    }
    CORNER_KEYS = ("nw", "ne", "sw", "se")

    BM_TILE_CELL = 56
    BM_TILE_GAP = 6
    # Height reserved for a single hint/label line above a control row --
    # used by the "choisis une vocation" screen (_bm_vocation_rects) so its
    # own hint text has somewhere to render WITHOUT going above the
    # column's anchor y (see that method's own docstring for why that
    # used to overlap the mode-tab row).
    HINT_ROW_HEIGHT = 20
    def _bm_columns(self):
        return max(1, (self.viewer_rect.width - 8) // (self.BM_TILE_CELL + self.BM_TILE_GAP))
    def _bm_visible_rows(self):
        return max(1, (self.viewer_rect.height - 8) // (self.BM_TILE_CELL + self.BM_TILE_GAP))
    def _bm_clamp_scroll(self, tile_count):
        """Keeps bm_scroll_rows within [0, last row that still has content
        at the top of the viewer] for a pack of `tile_count` tiles -- called
        after every wheel nudge and whenever the loaded pack changes size,
        so scrolling can never run past either end."""
        columns = self._bm_grid_columns()
        total_rows = -(-tile_count // columns) if tile_count else 0  # ceil div
        max_scroll = max(0, total_rows - self._bm_visible_rows())
        self.bm_scroll_rows = max(0, min(self.bm_scroll_rows, max_scroll))
    def _bm_tile_rect(self, index):
        columns = self._bm_grid_columns()
        row, col = divmod(index, columns)
        row -= self.bm_scroll_rows
        return pygame.Rect(
            self.viewer_rect.x + 4 + col * (self.BM_TILE_CELL + self.BM_TILE_GAP),
            self.viewer_rect.y + 4 + row * (self.BM_TILE_CELL + self.BM_TILE_GAP),
            self.BM_TILE_CELL, self.BM_TILE_CELL,
        )
    def _bm_pack_payload(self):
        """Cached by (pack_name, file mtime) -- this was a fresh disk read
        + full JSON reparse on EVERY call with no caching at all, and
        bitmap mode calls it well over a dozen times per single frame
        (render, tile-grid hit-testing, wheel/motion handlers). Mirrors
        the exact mtime-keyed caching autotile.build_pack_lookup/
        object_manager.build_entity_pack_lookup already use on the
        in-game consumption side: a stat() call, not a reparse, on every
        call after the first, and it reloads automatically the instant a
        tag/save actually changes the file (its mtime advances)."""
        if self.bm_pack_name is None:
            return None
        try:
            mtime = get_autotile_pack_path(self.bm_pack_name).stat().st_mtime
        except OSError:
            mtime = None

        cached = self._bm_pack_payload_cache.get(self.bm_pack_name)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        payload = load_autotile_pack(self.bm_pack_name)
        self._bm_pack_payload_cache[self.bm_pack_name] = (mtime, payload)
        return payload
    def _bm_pack_kind(self):
        """"entity" or "autotile" (the back-compat default, matching
        ressources.list_autotile_packs' own convention) -- which of the two
        very different bitmap-mode editors applies to whatever pack is
        currently loaded: _handle_bitmap_event's bitmask/variant chain, or
        _handle_entity_bitmap_event's action/direction/order tagging.

        Only meaningful once a pack actually HAS a vocation -- a pack
        fresh out of Extraire always saves "kind": null on purpose (see
        ressources.save_autotile_pack's own docstring), so dict.get's
        default here never actually fires for one (the key IS present,
        just None -- .get only falls back to its default for a MISSING
        key). Callers must check _bm_pack_needs_vocation FIRST and route
        to the "choose vocation" screen instead of ever reaching this for
        that case (found 2026-08-19: without that check, an unassigned
        pack silently fell through to the autotile Motif/Variante screen,
        useless for e.g. a freshly-extracted character sheet)."""
        kind = (self._bm_pack_payload() or {}).get("kind")
        return kind if kind else "autotile"

    def _bm_pack_needs_vocation(self):
        """True for a pack that has never been assigned a vocation at all
        (kind=None/absent, e.g. straight out of Extraire) -- gates the
        "choose vocation" screen (_render_pack_vocation/_handle_pack_
        vocation_event), checked BEFORE any _bm_pack_kind()-based
        dispatch so an unassigned pack is never silently treated as
        autotile just because that's _bm_pack_kind()'s own fallback."""
        payload = self._bm_pack_payload()
        return payload is not None and not payload.get("kind")

    def _bm_vocation_rects(self):
        """Anchored BELOW the Carte checklist's own 3 rows (_bm_carte_
        checklist_bottom), not at _bm_carte_toggle_rect directly -- the
        checklist itself always renders/handles clicks regardless of
        vocation (Carte works on ANY pack, assigned or not, see its own
        docstring), so it occupies that top-of-column space unconditionally.
        Sharing that same space with this screen's own buttons (found
        2026-08-19) made them not just visually overlap the (invisible
        here, but still click-checked FIRST) checklist boxes, but actually
        UNREACHABLE by click -- clicking "Personnage / Entite" was really
        toggling the "animation" checkbox underneath it instead."""
        anchor = self._bm_carte_toggle_rect
        top = self._bm_carte_checklist_bottom() + self.HINT_ROW_HEIGHT + 8
        return {
            "autotile": pygame.Rect(anchor.x, top, anchor.width, 40),
            "entity": pygame.Rect(anchor.x, top + 40 + 12, anchor.width, 40),
        }

    def _assign_pack_vocation(self, kind):
        """Writes `kind` ("autotile" or "entity") onto the currently loaded
        pack via ressources.update_autotile_pack_meta -- the very next
        _bm_pack_payload() read (mtime-keyed cache) picks it up
        automatically, no manual cache invalidation needed. Refreshes
        both browsers that key off pack kind so whichever screen this
        pack now routes to is immediately populated correctly."""
        update_autotile_pack_meta(self.bm_pack_name, kind=kind)
        self.bm_scroll_rows = 0
        self._refresh_shape_browser()
        self._refresh_npc_existing()
        label = "Tuiles (autotile)" if kind == "autotile" else "Personnage / Entite"
        self.status_text = f"'{self.bm_pack_name}' assigne comme {label}."

    def _render_pack_vocation(self, screen):
        """"Ce pack n'a pas encore de vocation" screen -- every other
        bitmap-mode editor (Motif/Variante, entity tagging) needs one to
        make any sense at all, and a pack straight out of Extraire always
        starts with kind=None on purpose (see ressources.
        save_autotile_pack's own docstring: extraction itself never
        commits to a vocation). Shows the pack's own tile grid so the
        player can confirm it's the right one before choosing, plus the
        2 buttons themselves."""
        self.border.draw(screen, self.viewer_rect)
        payload = self._bm_pack_payload()
        if payload is None:
            return
        clip = screen.get_clip()
        screen.set_clip(self.viewer_rect)
        for index, tile in enumerate(payload.get("tiles", [])):
            rect = self._bm_tile_rect(index)
            region = load_tileset_region(payload["tileset"], tile["rect"])
            scaled = pygame.transform.scale(region, (rect.width, rect.height))
            screen.blit(scaled, rect.topleft)
        screen.set_clip(clip)

        rects = self._bm_vocation_rects()
        hint = self.small_font.render(
            f"'{self.bm_pack_name}' n'a pas encore de vocation -- choisis-en une :",
            True, (220, 190, 90),
        )
        screen.blit(hint, (self._bm_carte_toggle_rect.x, self._bm_carte_checklist_bottom() + 8))
        self.border.draw_centered_label(screen, rects["autotile"], self.font, "Tuiles (autotile)")
        self.border.draw_centered_label(screen, rects["entity"], self.font, "Personnage / Entite")

        detail = self.small_font.render(
            "Tuiles : motif de voisinage + variantes (sol/mur).", True, (170, 170, 170),
        )
        screen.blit(detail, (rects["autotile"].x, rects["entity"].bottom + 10))
        detail2 = self.small_font.render(
            "Personnage/Entite : actions taguees par direction, jusqu'a 8 directions, autant d'actions que voulu.",
            True, (170, 170, 170),
        )
        screen.blit(detail2, (rects["autotile"].x, rects["entity"].bottom + 10 + detail.get_height() + 4))

        if self.status_text:
            status_surface = self.small_font.render(self.status_text, True, (255, 220, 120))
            screen.blit(status_surface, (
                rects["autotile"].x, rects["entity"].bottom + 10 + detail.get_height() * 2 + 12,
            ))

    def _handle_pack_vocation_event(self, event):
        """"Choisis une vocation" screen's own event handling -- delegated
        to from _handle_bitmap_event while _bm_pack_needs_vocation() is
        true."""
        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.pack_browser.handle_event(event)
            return None

        if event.type == pygame.MOUSEMOTION:
            self.pack_browser.handle_event(event)
            return None

        if self.pack_browser.is_modal:
            self.pack_browser.handle_event(event)
            return None

        if event.button == 3:
            if self.pack_browser.contains(event.pos):
                self.pack_browser.handle_event(event)
            return None

        if event.button != 1:
            return None

        if self._close_rect.collidepoint(event.pos):
            self.close()
            return None

        if self._handle_mode_switch(event.pos):
            return None

        if self.pack_browser.contains(event.pos):
            self.pack_browser.handle_event(event)
            selected = self.pack_browser.selected_name
            if selected is not None and selected != self.bm_pack_name:
                self._select_bitmap_pack(selected)
            return None

        rects = self._bm_vocation_rects()
        if rects["autotile"].collidepoint(event.pos):
            self._assign_pack_vocation("autotile")
            return None
        if rects["entity"].collidepoint(event.pos):
            self._assign_pack_vocation("entity")
            return None

        return None
    def _bm_grid_columns(self):
        """Columns to lay the tile grid out with. An entity-kind pack that
        was sliced with a known width (see save_autotile_pack's own
        "columns" field) uses THAT, so one displayed row is exactly one
        real row of the source sheet (e.g. one direction) -- not the
        unrelated, viewer-pixel-width-driven wrap _bm_columns() computes,
        which visually interleaved rows from a sheet wider than the
        viewer and made rectangular multi-select fastidious. Autotile
        packs (and any entity pack saved before this field existed) keep
        _bm_columns() -- display order never mattered functionally for
        them, each tile is tagged individually regardless of screen
        position."""
        payload = self._bm_pack_payload()
        if payload is not None and payload.get("kind") == "entity":
            native = payload.get("columns")
            if native:
                return native
        return self._bm_columns()
    def _npc_pack_actions(self):
        """Sorted distinct action strings already tagged anywhere in the
        loaded entity pack -- populates the idle/move action cyclers
        (_cycle_npc_action) and the icon-frame lookup (_npc_icon_rect)."""
        payload = self._bm_pack_payload() or {}
        return sorted({tile["action"] for tile in payload.get("tiles", []) if tile.get("action")})
    def _bm_tile_at(self, pos):
        payload = self._bm_pack_payload()
        if payload is None:
            return None
        for index in range(len(payload.get("tiles", []))):
            if self._bm_tile_rect(index).collidepoint(pos):
                return index
        return None
    def _bm_auto_save_current(self):
        """Persists whatever tile is currently being edited before the
        selection moves on -- the "click a tile, tweak it, click another
        tile" flow the user asked for shouldn't need an explicit
        Enregistrer between each one. Gated on bm_dirty: merely clicking
        through tiles to LOOK at them, with no actual neighbor edit made,
        must never silently write a bitmask onto a tile the player never
        touched (confirmed root cause of real data corruption -- see
        bm_dirty's own docstring). A no-op with nothing selected/dirty.
        Also called before switching pack, leaving bitmap mode, or closing
        the panel entirely, so a genuine tweak is never silently lost."""
        if self.bm_pack_name is not None and self.bm_tile_index is not None and self.bm_dirty:
            self._try_save_bitmap_tile()
    def _select_bitmap_pack(self, pack_name):
        self._bm_auto_save_current()
        self.bm_pack_name = pack_name
        self.bm_tile_index = None
        self.bm_picking_variant_family = None
        self.bm_scroll_rows = 0
        self.bm_carte_multitile = False
        self.bm_carte_multidirection = False
        self.bm_carte_animation = False
        self.bm_carte_selection = []
        self.bm_carte_directions = []
        self.width_tiles = 1
        self.height_tiles = 1
        self.cell_modes_grid = None
        self._bm_entity_selection = set()
        self._bm_entity_drag_start = None
        self._bm_entity_exclude = set()
        self._npc_editing_type_id = None
        self._npc_idle_action = None
        self._npc_move_action = None
        self._npc_sitting_action = None
        self._npc_laying_action = None
        self._npc_run_action = None
        self.name_box.value = ""
        self._refresh_shape_browser()
        self._refresh_npc_existing()
        self._refresh_carte_existing_cards()
    def _try_delete_pack(self, pack_name):
        """on_delete callback for pack_browser (see __init__), also the
        target of the dedicated "Supprimer" button (see _handle_bitmap_
        event/RoomBrowser.arm_delete_confirm). Reserved for admingod (see
        self.is_admingod, set by Creator from Profile.admingod) -- a
        definitive deletion tool is deliberately not something an ordinary
        playthrough can reach. Refuses with an explanation instead of
        deleting outright when the pack is still used as a room/dungeon's
        terrain theme (ressources.pack_references) or by a registered PNJ's
        entity_pack (npc_types_for_pack) -- same protective spirit as
        _try_delete_card/_try_delete_npc, just two kinds of reference
        instead of one."""
        if not self.is_admingod():
            self.status_text = "Suppression de pack reservee au mode admingod."
            return
        used_in = pack_references(pack_name)
        used_by_npcs = [type_id for type_id, _config in npc_types_for_pack(pack_name)]
        if used_in or used_by_npcs:
            parts = []
            if used_in:
                parts.append(", ".join(used_in))
            if used_by_npcs:
                parts.append("Cartes : " + ", ".join(used_by_npcs))
            self.status_text = f"Impossible de supprimer : encore utilise dans {' | '.join(parts)}."
            return
        delete_autotile_pack(pack_name)
        if self.bm_pack_name == pack_name:
            self.bm_pack_name = None
            self.bm_tile_index = None
            self._refresh_shape_browser()
            self._refresh_npc_existing()
        self.status_text = f"Pack '{pack_name}' supprime."
        self.pack_browser.set_rooms(list_autotile_packs())
    def _try_rename_pack(self, old_name, new_name):
        """on_rename callback for pack_browser (see __init__). Delegates
        the file rename + room/dungeon floor_theme/wall_theme cascade to
        ressources.rename_autotile_pack, then keeps every registered
        PNJ's own entity_pack field in sync (rename_entity_pack_
        references) -- a pack rename is only complete once both have run.
        Updates bm_pack_name if the renamed pack was the one currently
        open, so the bitmap-mode screen doesn't silently keep pointing at
        a filename that no longer exists."""
        actual_new_name = rename_autotile_pack(old_name, new_name)
        if actual_new_name is None:
            self.status_text = f"Renommage refuse (nom invalide ou '{new_name}' deja pris)."
            return
        rename_entity_pack_references(old_name, actual_new_name)
        if self.bm_pack_name == old_name:
            self.bm_pack_name = actual_new_name
        self.status_text = f"Pack renomme en '{actual_new_name}'."
        self.pack_browser.set_rooms(list_autotile_packs())
        self._refresh_npc_existing()
    def _select_bitmap_tile(self, index):
        """Clicking a pack tile means something different depending on
        which mode is active (Motif vs Variante, set explicitly via
        _bm_toggle_rects -- the mode itself no longer auto-switches based on
        what's clicked, only the user's own Motif/Variante button does).

        Motif mode: pre-fills bm_neighbors from this tile's own saved
        bitmask (if any), so re-opening an assigned tile shows what it
        currently has instead of resetting to a blank slate.

        Variante mode: clicking an already-assigned tile (its own bitmask,
        a variant_of another one, or simply marked default -- no bitmask
        required, see _bm_family_bitmask) switches bm_tile_index to it,
        which is what _bm_family_bitmask derives the browsed family from --
        the family's own variants then render as sprites in the params
        column (see _bm_variant_layout). Clicking a still-blank tile instead
        either does nothing (no "+" armed yet, just a hint) or, if the "+"
        cell WAS just clicked (bm_picking_variant_family set), turns THIS
        blank tile into the new variant (_bm_add_variant_from_pick) -- the
        player picks which tile, nothing is auto-grabbed."""
        payload = self._bm_pack_payload() or {}
        tiles = payload.get("tiles", [])
        if not (0 <= index < len(tiles)):
            return
        tile = tiles[index]

        if self.bm_variant_mode:
            if tile.get("bitmask") or tile.get("variant_of") or tile.get("default"):
                self.bm_picking_variant_family = None
                self.bm_tile_index = index
            elif self.bm_picking_variant_family is not None:
                self._bm_add_variant_from_pick(index, self.bm_picking_variant_family)
                self.bm_picking_variant_family = None
            else:
                self.status_text = (
                    "Tuile vierge -- marque une tuile par defaut (mode Motif) "
                    "ou assigne-lui un motif pour pouvoir lui ajouter des variantes."
                )
            return

        if self.bm_tile_index is not None and self.bm_tile_index != index:
            self._bm_auto_save_current()
        self.bm_tile_index = index
        self._bm_load_neighbors_from_tile(tile)
    def _bm_load_neighbors_from_tile(self, tile):
        """Loads bm_neighbors from `tile`'s own saved bitmask, or resets to
        Vide if it has none (e.g. a variant tile, which carries no bitmask
        of its own) -- shared by _select_bitmap_tile's Motif branch and the
        Motif/Variante toggle switching back to Motif (see
        _bm_toggle_rects's click handling below), so bm_neighbors never sits
        stale relative to whatever tile is actually selected. Also clears
        bm_dirty -- this is the clean, just-loaded baseline for THIS tile,
        not an edit."""
        bitmask = tile.get("bitmask")
        if bitmask and len(bitmask) == 4:
            for key, digit in zip(self.NEIGHBOR_KEYS, bitmask):
                self.bm_neighbors[key] = int(digit)
        else:
            for key in self.NEIGHBOR_KEYS:
                self.bm_neighbors[key] = EMPTY
        self.bm_dirty = False
    def _bm_current_bitmask(self):
        return "".join(str(self.bm_neighbors[key]) for key in self.NEIGHBOR_KEYS)
    def _cycle_neighbor(self, key, step):
        """Advances (or reverses, step=-1) one cardinal neighbor's value
        through Vide->Sol->Mur, wrapping around -- shared by clicking a
        cardinal cell in the 3x3 preview and scrolling the wheel over it
        (see _handle_bitmap_wheel), same underlying state either way. Marks
        bm_dirty so _bm_auto_save_current knows this tile actually got
        edited (see bm_dirty's own docstring)."""
        cycle_index = self.NEIGHBOR_CYCLE.index(self.bm_neighbors[key])
        self.bm_neighbors[key] = self.NEIGHBOR_CYCLE[(cycle_index + step) % len(self.NEIGHBOR_CYCLE)]
        self.bm_dirty = True
    def _bm_neighbor_at(self, pos):
        """The cardinal key (never a corner -- see CORNER_KEYS) whose grid
        cell contains `pos`, or None."""
        for key in self.NEIGHBOR_KEYS:
            rect = self._bm_grid_rects.get(key)
            if rect is not None and rect.collidepoint(pos):
                return key
        return None
    def _bm_existing_bitmasks(self):
        """Every bitmask some OTHER tile in the current pack already claims
        as its own -- the candidates a variant can meaningfully target
        (varying a shape nothing has claimed yet would never be picked, see
        autotile.build_pack_lookup's lookup.get(value, default_index))."""
        payload = self._bm_pack_payload() or {}
        return sorted({
            tile["bitmask"] for tile in payload.get("tiles", [])
            if tile.get("bitmask")
        })
    def _refresh_shape_browser(self):
        """Populates shape_browser with FLOOR_REFERENCE_SHAPES or
        WALL_REFERENCE_SHAPES (whichever matches the selected pack's role),
        each row tagged "deja assignee" if some tile in this pack already
        claims that bitmask (see _bm_existing_bitmasks) -- called on pack
        selection and again after every save, so the tags never go stale.
        A no-op (empty list) with no pack selected, or with an entity-kind
        pack selected (no role, no bitmask -- see _refresh_npc_existing for
        what that case shows in this same screen slot instead)."""
        payload = self._bm_pack_payload()
        if payload is None or payload.get("kind") == "entity":
            self.shape_browser.set_rooms([])
            return
        shapes = self.WALL_REFERENCE_SHAPES if payload.get("role") == "wall" else self.FLOOR_REFERENCE_SHAPES
        assigned = self._bm_existing_bitmasks()
        entries = [
            (f"{shape} (deja assignee)" if shape in assigned else shape, shape)
            for shape in shapes
        ]
        self.shape_browser.set_rooms(entries)
    def _refresh_carte_existing_cards(self):
        """Repopulates existing_cards_browser (the same instance
        DecouperMixin's own dead "decouper" tab used to own -- reused here
        rather than duplicated, see panel.py's __init__ comment on it)
        with every FLAT custom card already sourced from the CURRENT
        pack's own tileset -- the Carte screen's answer to "what have I
        already built from this pack", requested after the checklist
        redesign left no way to review/clean up prior work.

        Two exclusions (2026-08-18, confirmed with the user -- "il faut
        que ca corresponde a la seule carte en vigueur... pas a toutes les
        versions qui l'ont eu"): a fusion-derived card (config["fused_from"]
        set, see object_manager.fuse_card) is a player-facing collection
        outcome, not something the editor manages -- tearing/fusing
        properties onto a base card is meant to spawn independent
        collectible variants, not clutter this "what did I build" list
        with every combination anyone's ever fused. An entity_pack-backed
        card belongs to _refresh_npc_existing's own browser instead (same
        pack, different screen, different editing model) -- listing it
        here too would just be confusing duplication."""
        payload = self._bm_pack_payload()
        if payload is None:
            self.existing_cards_browser.set_rooms([])
            return
        cards = custom_types_for_tileset(payload["tileset"])
        entries = [
            (config.get("name", type_id), type_id) for type_id, config in cards
            if not config.get("fused_from") and not config.get("entity_pack")
        ]
        entries.sort(key=lambda entry: entry[0].lower())
        self.existing_cards_browser.set_rooms(entries)

    def _refresh_npc_existing(self):
        """Repopulates _npc_existing_browser with every entity-pack-backed
        type already registered from the current pack -- entity-kind
        counterpart of _refresh_carte_existing_cards, called on pack
        selection and again after a successful register/update. Empty (no
        pack, or an autotile pack) is a valid, harmless state.

        UNLIKE _refresh_carte_existing_cards, a fusion-derived card is NOT
        excluded here (reversed 2026-08-20, confirmed with the user --
        wanted the opposite of the 2026-08-18 decision this used to match:
        "l'assembleur [doit] reconnaitre dynamiquement les cartes qui
        utilisent un pack"). Adding a new tagged action/frame to a pack
        (e.g. an "attack" animation) is meaningless if the card actually
        placed in-game -- typically already fused with "Comportement"/
        capabilities via the Forge -- never shows up here to pick back up;
        the old behavior forced recreating a disconnected duplicate card
        instead of continuing to edit the real one. _try_update_npc was
        fixed alongside this to re-pass the loaded card's existing
        capabilities/stats/etc through unchanged (see its own docstring),
        since without that, editing a fused card here would have silently
        wiped whatever was fused onto it."""
        if self.bm_pack_name is None:
            self._npc_existing_browser.set_rooms([])
            return
        npcs = npc_types_for_pack(self.bm_pack_name)
        entries = [(config.get("name", type_id), type_id) for type_id, config in npcs]
        entries.sort(key=lambda entry: entry[0].lower())
        self._npc_existing_browser.set_rooms(entries)
    def _try_delete_npc(self, type_id):
        """on_delete callback for _npc_existing_browser (see __init__) --
        same protective refusal as _try_delete_card (ressources.
        type_references, since a PNJ type is stored/placed exactly like a
        custom card, see delete_custom_type). Resets the "Enregistrer
        comme PNJ" sub-form if the deleted type was the one being edited."""
        used_in = type_references(type_id)
        if used_in:
            self.status_text = f"Impossible de supprimer : encore utilise dans {', '.join(used_in)}."
            return
        try:
            delete_custom_type(type_id)
        except ValueError as exc:
            self.status_text = str(exc)
            return
        if self._npc_editing_type_id == type_id:
            self._npc_editing_type_id = None
            self.name_box.value = ""
            self._npc_idle_action = None
            self._npc_move_action = None
            self._npc_sitting_action = None
            self._npc_laying_action = None
            self._npc_run_action = None
        self.status_text = f"'{type_id}' supprime."
        self._refresh_npc_existing()
    def _load_npc_for_edit(self, type_id):
        """Loads an existing PNJ type's saved name/wander actions into the
        editing state and marks self._npc_editing_type_id so the register
        button calls _try_update_npc instead of _try_register_npc -- entity-
        kind counterpart of _load_existing_card_for_edit. The icon rect/size
        aren't editable here (they're re-derived from idle action + current
        direction on save, see _npc_icon_rect) -- only name and wander
        actions are, since those are the only fields this screen exposes."""
        config = OBJECT_TYPES.get(type_id)
        if config is None or not config.get("entity_pack"):
            return
        self._npc_editing_type_id = type_id
        self.name_box.value = config.get("name", type_id)
        wander = config.get("wander_actions", {})
        self._npc_idle_action = wander.get("idle")
        self._npc_move_action = wander.get("move")
        self._npc_sitting_action = wander.get("sitting")
        self._npc_laying_action = wander.get("laying")
        self._npc_run_action = wander.get("run")
        self.status_text = f"Edition de '{self.name_box.value}' ({type_id})."
    def _entity_tile_rect_range(self, start_index, end_index):
        """Every valid tile index in the rectangular block spanning
        start_index/end_index (inclusive), read as (row, col) positions in
        the pack's own grid (_bm_grid_columns) -- the shift-drag rectangular
        multi-select _handle_entity_bitmap_event builds up as the mouse
        moves, mirroring how a spreadsheet-style drag-select works rather
        than a simple index range (rows can wrap at different widths)."""
        columns = self._bm_grid_columns()
        row0, col0 = divmod(start_index, columns)
        row1, col1 = divmod(end_index, columns)
        row_lo, row_hi = min(row0, row1), max(row0, row1)
        col_lo, col_hi = min(col0, col1), max(col0, col1)
        total = len(self._bm_pack_payload().get("tiles", []))
        selection = set()
        for row in range(row_lo, row_hi + 1):
            for col in range(col_lo, col_hi + 1):
                index = row * columns + col
                if index < total:
                    selection.add(index)
        return selection
    def _cycle_entity_direction(self, step):
        index = NPC_DIRECTIONS.index(self._bm_entity_direction)
        self._bm_entity_direction = NPC_DIRECTIONS[(index + step) % len(NPC_DIRECTIONS)]
    def _cycle_npc_action(self, which, step, allow_none=False):
        """which is "idle"/"move"/"sitting"/"laying"/"run" -- all 5 roles
        are optional now (2026-08-18: a combat-only mob built purely from
        attack/damaged/death tags has no use for any of them, see
        entities.Mob's aggro-capable-entity-pack support), each
        independently enabling its own bit of behavior (wander/rest chain
        for idle/move/sitting/laying/run -- see core.world.entities.Mob's
        own class docstring). allow_none=True (sitting/laying/run only,
        for now) lets the cycle land back on "no action"; idle/move never
        offered that before they became optional and still don't here --
        simply never touching either cycler leaves them at their initial
        None, no need to cycle back to it. Cycles through the pack's own
        distinct tagged action names (a closed choice, unlike the
        free-text action box used for tagging itself). Starts at the
        first available option the first time either is touched, since
        every one of these starts at None."""
        actions = self._npc_pack_actions()
        if not actions:
            return
        attr = f"_npc_{which}_action"
        current = getattr(self, attr)
        options = ([None] + actions) if allow_none else actions
        if current not in options:
            setattr(self, attr, options[0])
            return
        setattr(self, attr, options[(options.index(current) + step) % len(options)])
    def _npc_icon_rect(self):
        """The (rect, tileset) of whichever tile has order==0 for the idle
        action + currently-selected direction -- becomes the PNJ's static
        icon in the palette/placed-on-grid view (asset {"tileset","rect"},
        completely unrelated to load_npc_frames' own live-animation path).
        (None, None) if no such tile has been tagged yet.

        Idle is no longer a required role (2026-08-18 -- a combat-only
        mob built purely from attack/damaged/death tags, no wander/rest
        concept at all, is a legitimate card too, see entities.Mob's own
        aggro-capable-entity-pack support) -- with no idle action chosen
        at all, falls back to ANY order-0 tile at the current direction,
        so there's still SOME icon to show rather than refusing to
        register entirely just because "idle" specifically isn't tagged."""
        payload = self._bm_pack_payload() or {}
        for tile in payload.get("tiles", []):
            if (
                tile.get("action") == self._npc_idle_action
                and tile.get("direction") == self._bm_entity_direction
                and tile.get("order") == 0
            ):
                return tile["rect"], payload["tileset"]
        if self._npc_idle_action is None:
            for tile in payload.get("tiles", []):
                if tile.get("direction") == self._bm_entity_direction and tile.get("order") == 0:
                    return tile["rect"], payload["tileset"]
        return None, None
    def _tag_entity_selection(self):
        """"Tagger la selection" -- one update_autotile_pack_tiles call for
        every selected, non-excluded tile: the free-text action, the
        currently-cycled direction, and a row-major order derived from
        position WITHIN the selection's own bounding box (excluded tiles
        don't consume an order slot, so a 3-frame walk cycle selected
        alongside a blank 4th column still numbers its real frames 0/1/2,
        not 0/1/3 -- see load_npc_frames, which plays frames in order)."""
        if self.bm_pack_name is None or not self._bm_entity_selection:
            self.status_text = "Selectionne au moins une tuile."
            return
        action = self.entity_action_box.value.strip()
        if not action:
            self.status_text = "Donne un nom a l'action."
            return

        columns = self._bm_grid_columns()
        ordered = sorted(
            self._bm_entity_selection - self._bm_entity_exclude,
            key=lambda index: divmod(index, columns),
        )
        if not ordered:
            self.status_text = "Toutes les tuiles selectionnees sont exclues."
            return
        updates = {
            index: {"action": action, "direction": self._bm_entity_direction, "order": order}
            for order, index in enumerate(ordered)
        }
        try:
            update_autotile_pack_tiles(self.bm_pack_name, updates)
        except ValueError as exc:
            self.status_text = str(exc)
            return

        self.status_text = f"{len(updates)} tuile(s) taguee(s) : {action} / {self._bm_entity_direction}."
        self._bm_entity_selection = set()
        self._bm_entity_exclude = set()
    def _npc_wander_actions(self):
        """The wander_actions dict register_custom_type/update_custom_type's
        own `wander_actions` param expects -- every role ("idle"/"move"/
        "sitting"/"laying"/"run") only included when actually chosen,
        "not used" rather than an empty string when unset (core.world.
        entities.Mob._has_action treats a missing key exactly like one
        that names an untagged action). Purely a naming convenience now
        (2026-08-19) -- each role already falls back to its own literal
        name when nothing's mapped here at all (see Mob.
        _current_action_name), so a card can be built with this dict
        entirely empty, no role ever explicitly picked."""
        wander = {}
        if self._npc_idle_action is not None:
            wander["idle"] = self._npc_idle_action
        if self._npc_move_action is not None:
            wander["move"] = self._npc_move_action
        if self._npc_sitting_action is not None:
            wander["sitting"] = self._npc_sitting_action
        if self._npc_laying_action is not None:
            wander["laying"] = self._npc_laying_action
        if self._npc_run_action is not None:
            wander["run"] = self._npc_run_action
        return wander
    def _role_coverage_suffix(self, action_name):
        """" (n/8)" appended to a wander-role label while filling in the
        "Enregistrer comme PNJ" form -- live direction-coverage feedback
        using the exact same primitive (object_manager.
        action_direction_coverage) core.data.cards.npc_completeness uses
        later for the persisted card's own "incomplete" badge, so the two
        can never disagree. "" for an unset role (nothing to preview yet)
        or with no pack loaded."""
        if not action_name or self.bm_pack_name is None:
            return ""
        tagged, _missing = action_direction_coverage(self.bm_pack_name, action_name)
        return f" ({len(tagged)}/{len(NPC_DIRECTIONS)})"
    def _try_register_npc(self):
        """"Enregistrer la carte" -- same return contract as _try_register
        (the new type_id, so Creator credits a card for it) or None+
        status_text on failure. Reuses self.name_box for the card's own
        display name (bitmap mode never otherwise shows it).

        Goes through register_custom_type (archetype "sol", same neutral
        default the Carte checklist already uses), NOT register_npc_type
        (2026-08-19, confirmed with the user -- "il faut arreter avec
        enregistrer comme PNJ, meme comme mob") -- entity_pack/
        wander_actions are attached as purely structural fields, "mob" is
        never set here at all. This card carries as many states as are
        tagged on the pack (see entities.Mob._stationary_state_options)
        without being alive; tearing "Comportement" off any existing mob
        and gluing it here (see object_manager.extract_property_payload's
        "behavior" category) is what makes it one, in the Forge, never at
        this registration step."""
        if self.bm_pack_name is None:
            self.status_text = "Choisis d'abord un pack."
            return None
        raw_name = self.name_box.value.strip()
        if not raw_name:
            self.status_text = "Donne un nom a la carte."
            return None

        duplicate_id = self._find_custom_type_by_name(raw_name)
        if duplicate_id is not None:
            self.status_text = f"'{raw_name}' existe deja ({duplicate_id})."
            return None

        icon_rect, icon_tileset = self._npc_icon_rect()
        if icon_rect is None:
            self.status_text = "Tague au moins une tuile d'ordre 0 pour la direction courante (icone)."
            return None

        type_id = self._sanitize_id(raw_name, OBJECT_TYPES, fallback="carte")
        try:
            register_custom_type(
                type_id, raw_name, icon_tileset, icon_rect, (1, 1), "sol",
                entity_pack=self.bm_pack_name, wander_actions=self._npc_wander_actions() or None,
            )
        except ValueError as exc:
            self.status_text = str(exc)
            return None

        self.status_text = f"'{raw_name}' enregistree ({type_id})."
        self.name_box.value = ""
        self._npc_editing_type_id = None
        self._refresh_npc_existing()
        return type_id
    def _try_update_npc(self):
        """Register button's action while self._npc_editing_type_id is set --
        rewrites that card's definition in place. Never returns a value for
        Creator to grant a card for (the type already exists, presumably
        already owned). See _try_register_npc's own docstring for why this
        goes through the generic, type-less registration path rather than
        register_npc_type/update_npc_type.

        Calls update_type_visual + update_type_mechanics directly (NOT the
        update_custom_type alias _try_register_npc's sibling used to use)
        so capabilities/stats/effects/sounds/sound_pitch/loot_cards can be
        explicitly re-passed from the live entry -- update_type_mechanics
        always clears every mechanics key first (see its own docstring),
        so calling it with none of those would silently wipe e.g. a torn/
        glued "errance" capability or a fused-on "Comportement"'s stats the
        moment this card (now that _refresh_npc_existing shows fused cards
        too, 2026-08-20) is ever re-saved here. Same lesson
        _try_register_carte's own directions/cell_modes follow-up call
        already had to learn."""
        raw_name = self.name_box.value.strip()
        if not raw_name:
            self.status_text = "Donne un nom a la carte."
            return None

        duplicate_id = self._find_custom_type_by_name(raw_name)
        if duplicate_id is not None and duplicate_id != self._npc_editing_type_id:
            self.status_text = f"'{raw_name}' est deja pris par {duplicate_id}."
            return None

        icon_rect, icon_tileset = self._npc_icon_rect()
        if icon_rect is None:
            self.status_text = "Tague au moins une tuile d'ordre 0 pour la direction courante (icone)."
            return None

        existing = OBJECT_TYPES.get(self._npc_editing_type_id, {})
        try:
            update_type_visual(
                self._npc_editing_type_id, raw_name, icon_tileset, icon_rect, (1, 1), "sol",
                entity_pack=self.bm_pack_name, wander_actions=self._npc_wander_actions() or None,
            )
            update_type_mechanics(
                self._npc_editing_type_id,
                capabilities=existing.get("capabilities"),
                stats=existing.get("stats"),
                effects=existing.get("effects"),
                sounds=existing.get("sounds"),
                sound_pitch=existing.get("sound_pitch"),
                loot_cards=existing.get("loot_cards"),
            )
        except ValueError as exc:
            self.status_text = str(exc)
            return None

        self.status_text = f"'{raw_name}' mise a jour ({self._npc_editing_type_id})."
        self._refresh_npc_existing()
        return None
    def _entity_bm_layout(self):
        """Every rect entity-kind bitmap mode's own params column needs,
        positioning entity_action_box/name_box in place as a side effect
        (both TextInputBox instances render/hit-test against their own
        .rect, unlike every other control here which is a fresh throwaway
        pygame.Rect) -- recomputed on every call (cheap, only ever read
        while this exact mode/kind is active), same reasoning as
        _cell_mode_grid_rects. Reuses _bm_toggle_rects["assign"]'s x as the
        shared params column anchor every other mode/kind already uses.

        top_y starts BELOW the Carte checklist's own 3 rows (2026-08-19,
        same fix as _bm_carte_layout_rects already applies) -- the
        checklist always renders/handles clicks whenever a pack is loaded
        regardless of which screen ends up shown (Carte works on any pack,
        see its own docstring), so this screen's own controls used to sit
        at the exact same y and visually/click-wise collide with it."""
        params_x = self._bm_toggle_rects["assign"].x
        step_w = self._confirm_rect.width
        top_y = self._bm_carte_checklist_bottom() + self.HINT_ROW_HEIGHT
        half = (step_w - 8) // 2

        self.entity_action_box.rect.topleft = (params_x, top_y)
        self.name_box.rect.topleft = (params_x, top_y + 160)

        return {
            "direction_prev": pygame.Rect(params_x, top_y + 44, half, 32),
            "direction_next": pygame.Rect(params_x + half + 8, top_y + 44, half, 32),
            "tag_button": pygame.Rect(params_x, top_y + 88, step_w, 40),
            "idle_prev": pygame.Rect(params_x, top_y + 204, half, 32),
            "idle_next": pygame.Rect(params_x + half + 8, top_y + 204, half, 32),
            "move_prev": pygame.Rect(params_x, top_y + 248, half, 32),
            "move_next": pygame.Rect(params_x + half + 8, top_y + 248, half, 32),
            # Optional -- each independently enables its own portion of
            # Npc's move <-> [sitting] <-> sit <-> [laying] <-> lie chain
            # (see core.world.entities.Npc). Cycled with allow_none=True,
            # unlike idle/move above.
            "sitting_prev": pygame.Rect(params_x, top_y + 292, half, 32),
            "sitting_next": pygame.Rect(params_x + half + 8, top_y + 292, half, 32),
            "laying_prev": pygame.Rect(params_x, top_y + 336, half, 32),
            "laying_next": pygame.Rect(params_x + half + 8, top_y + 336, half, 32),
            "run_prev": pygame.Rect(params_x, top_y + 380, half, 32),
            "run_next": pygame.Rect(params_x + half + 8, top_y + 380, half, 32),
            "register_button": pygame.Rect(params_x, top_y + 424, step_w, 40),
        }
    def _handle_entity_bitmap_event(self, event):
        """Mode "bitmap"'s own event handling for an entity-kind pack --
        entirely separate from _handle_bitmap_event's autotile-specific
        chain (bitmask cycling/variants have no equivalent here). A
        rectangular multi-select (shift-drag, or a single click) over the
        same tile grid instead of _select_bitmap_tile's one-tile-at-a-time
        Motif/Variante dispatch, plus the free-text action + 8-way
        direction pickers and the "register as PNJ" sub-form."""
        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.pack_browser.handle_event(event)
                self._bm_entity_drag_start = None
            return None

        if event.type == pygame.MOUSEMOTION:
            self.pack_browser.handle_event(event)
            if self._bm_entity_drag_start is not None:
                current = self._bm_tile_at(event.pos)
                if current is not None:
                    self._bm_entity_selection = self._entity_tile_rect_range(self._bm_entity_drag_start, current)
                    self._bm_entity_exclude &= self._bm_entity_selection
            return None

        # MOUSEBUTTONDOWN from here.
        # pack_browser/_npc_existing_browser's own rename-box/delete-
        # confirm/context-menu popups can render outside their normal
        # row-list bounds (RoomBrowser.is_modal) -- route every event
        # there unconditionally while one is open, or the popup renders
        # but never actually receives input.
        if self.pack_browser.is_modal:
            self.pack_browser.handle_event(event)
            return None
        if self._npc_existing_browser.is_modal:
            self._npc_existing_browser.handle_event(event)
            return None

        if event.button == 3:
            # Right-click only ever means "open one of these two
            # browsers' own Renommer/Supprimer menu" in this mode --
            # everything else here only responds to left-click.
            if self.pack_browser.contains(event.pos):
                self.pack_browser.handle_event(event)
            elif self._npc_existing_browser.contains(event.pos):
                self._npc_existing_browser.handle_event(event)
            return None

        if event.button != 1:
            return None

        if self._close_rect.collidepoint(event.pos):
            self.close()
            return None

        if self._handle_mode_switch(event.pos):
            return None

        if self.pack_browser.contains(event.pos):
            self.pack_browser.handle_event(event)
            selected = self.pack_browser.selected_name
            if selected is not None and selected != self.bm_pack_name:
                self._select_bitmap_pack(selected)
            return None

        if self._npc_existing_browser.contains(event.pos):
            self._npc_existing_browser.handle_event(event)
            selected_id = self._npc_existing_browser.selected_name
            if selected_id is not None:
                self._load_npc_for_edit(selected_id)
            return None

        if self.bm_pack_name is not None:
            tile_index = self._bm_tile_at(event.pos)
            if tile_index is not None:
                if tile_index in self._bm_entity_selection:
                    # Clicking an already-selected tile again toggles its
                    # exclusion instead of restarting the selection -- the
                    # "some rows have fewer real frames" escape hatch.
                    if tile_index in self._bm_entity_exclude:
                        self._bm_entity_exclude.discard(tile_index)
                    else:
                        self._bm_entity_exclude.add(tile_index)
                else:
                    self._bm_entity_drag_start = tile_index
                    self._bm_entity_selection = {tile_index}
                    self._bm_entity_exclude = set()
                return None

        # _entity_bm_layout repositions entity_action_box/name_box as a
        # side effect -- must run before testing their .rect below.
        rects = self._entity_bm_layout()

        if self.entity_action_box.rect.collidepoint(event.pos):
            self._entity_bm_focus = "action"
            return None
        if rects["direction_prev"].collidepoint(event.pos):
            self._cycle_entity_direction(-1)
            return None
        if rects["direction_next"].collidepoint(event.pos):
            self._cycle_entity_direction(1)
            return None
        if rects["tag_button"].collidepoint(event.pos):
            self._tag_entity_selection()
            return None
        if self.name_box.rect.collidepoint(event.pos):
            self._entity_bm_focus = "npc_name"
            return None
        if rects["idle_prev"].collidepoint(event.pos):
            self._cycle_npc_action("idle", -1)
            return None
        if rects["idle_next"].collidepoint(event.pos):
            self._cycle_npc_action("idle", 1)
            return None
        if rects["move_prev"].collidepoint(event.pos):
            self._cycle_npc_action("move", -1)
            return None
        if rects["move_next"].collidepoint(event.pos):
            self._cycle_npc_action("move", 1)
            return None
        if rects["sitting_prev"].collidepoint(event.pos):
            self._cycle_npc_action("sitting", -1, allow_none=True)
            return None
        if rects["sitting_next"].collidepoint(event.pos):
            self._cycle_npc_action("sitting", 1, allow_none=True)
            return None
        if rects["laying_prev"].collidepoint(event.pos):
            self._cycle_npc_action("laying", -1, allow_none=True)
            return None
        if rects["laying_next"].collidepoint(event.pos):
            self._cycle_npc_action("laying", 1, allow_none=True)
            return None
        if rects["run_prev"].collidepoint(event.pos):
            self._cycle_npc_action("run", -1, allow_none=True)
            return None
        if rects["run_next"].collidepoint(event.pos):
            self._cycle_npc_action("run", 1, allow_none=True)
            return None
        if rects["register_button"].collidepoint(event.pos):
            if self._npc_editing_type_id is not None:
                return self._try_update_npc()
            return self._try_register_npc()

        return None
    def _apply_shape_selection(self, bitmask):
        """A shape_browser row was clicked -- sets bm_neighbors directly
        from it, instead of composing the same bitmask by hand via the 4
        neighbor-cycling buttons. Motif mode only -- inert in Variante mode,
        where the family being browsed comes from clicking an actual
        assigned pack tile instead (see _bm_family_bitmask), not an
        arbitrary reference shape that might not even have a tile yet."""
        if self.bm_variant_mode:
            return
        for key, digit in zip(self.NEIGHBOR_KEYS, bitmask):
            self.bm_neighbors[key] = int(digit)
        self.bm_dirty = True
    def _bm_family_bitmask(self):
        """The family key whose registered variants Variante mode should
        list -- the currently selected pack tile's OWN bitmask if it's a
        base tile, its variant_of target if it's itself a variant, OR
        DEFAULT_VARIANT_KEY if it's simply marked as the pack's default
        tile (no bitmask required at all -- see autotile.DEFAULT_VARIANT_KEY
        for why: a player who never bothers autotiling shape-by-shape can
        still get cosmetic variety on every cell that falls through to the
        default tile). None if nothing useful is selected yet (a still-
        blank, non-default tile, or nothing at all). Selecting ANY member of
        a family (base, variant, or the default tile itself) always
        resolves to the same family key, so browsing doesn't depend on
        which particular tile happened to be clicked."""
        payload = self._bm_pack_payload() or {}
        tiles = payload.get("tiles", [])
        if self.bm_tile_index is None or not (0 <= self.bm_tile_index < len(tiles)):
            return None
        tile = tiles[self.bm_tile_index]
        if tile.get("bitmask"):
            return tile["bitmask"]
        if tile.get("variant_of"):
            return tile["variant_of"]
        if tile.get("default"):
            return DEFAULT_VARIANT_KEY
        return None
    def _bm_variants_of_family(self, family_bitmask):
        """[(tile_index, percent_int), ...] for every pack tile registered
        as a variant of `family_bitmask`, sorted by tile index -- percent
        converted from the stored 0..1 probability for display/editing."""
        if not family_bitmask:
            return []
        payload = self._bm_pack_payload() or {}
        tiles = payload.get("tiles", [])
        return sorted(
            (index, round(float(tile.get("probability", 0.0)) * 100))
            for index, tile in enumerate(tiles)
            if tile.get("variant_of") == family_bitmask
        )
    def _bm_variant_total_pct(self, family_bitmask, exclude_index=None):
        """Sum of every variant's percentage in `family_bitmask`'s family,
        excluding `exclude_index` (the row being edited, so its OWN current
        value doesn't eat into its own headroom -- see _bm_set_variant_pct's
        allowed_max)."""
        return sum(
            pct for index, pct in self._bm_variants_of_family(family_bitmask)
            if index != exclude_index
        )
    VARIANT_CELL = 48
    VARIANT_GAP = 6
    VARIANT_PCT_STEP = 5
    def _bm_variant_layout(self):
        """(family_bitmask_or_None, [(tile_index, percent, rect), ...],
        add_rect_or_None) for Variante mode's sprite grid -- each existing
        variant of the family currently being browsed (_bm_family_bitmask)
        as a hoverable/clickable thumbnail cell, wrapping within the params
        column width, followed by one more "+" cell (add_rect) to add a new
        variant (_bm_add_new_variant). Rebuilt fresh on every call (render
        AND click/scroll all call this) since the variant count changes at
        runtime, same "recomputed on demand" shape as _cell_mode_grid_rects.
        add_rect is None only when there's no family to add to yet."""
        family = self._bm_family_bitmask()
        if family is None or not self._bm_toggle_rects:
            return family, [], None
        params_x = self._bm_toggle_rects["assign"].x
        top_y = self._bm_toggle_rects["assign"].bottom + 34
        step_w = 190
        columns = max(1, (step_w + self.VARIANT_GAP) // (self.VARIANT_CELL + self.VARIANT_GAP))

        def cell_rect(i):
            row, col = divmod(i, columns)
            return pygame.Rect(
                params_x + col * (self.VARIANT_CELL + self.VARIANT_GAP),
                top_y + row * (self.VARIANT_CELL + self.VARIANT_GAP),
                self.VARIANT_CELL, self.VARIANT_CELL,
            )

        variants = self._bm_variants_of_family(family)
        rows = [(tile_index, pct, cell_rect(i)) for i, (tile_index, pct) in enumerate(variants)]
        add_rect = cell_rect(len(variants))
        return family, rows, add_rect
    def _bm_set_variant_pct(self, tile_index, requested_pct, family_bitmask):
        """Applies a variant's new percentage, clamped to whatever headroom
        is left under the family's 100% ceiling (confirmed with the user:
        raising a variant past what's available caps at the remaining
        amount instead of refusing the scroll/click outright). 0% fully
        removes the variant (pops variant_of/probability via
        ressources.update_autotile_pack_tile's None-means-pop convention),
        turning the tile back into a blank, addable-again one."""
        other_total = self._bm_variant_total_pct(family_bitmask, exclude_index=tile_index)
        new_pct = max(0, min(requested_pct, 100 - other_total))
        if new_pct <= 0:
            update_autotile_pack_tile(self.bm_pack_name, tile_index, variant_of=None, probability=None)
            self.status_text = f"Tuile {tile_index} : variante retiree."
        else:
            update_autotile_pack_tile(
                self.bm_pack_name, tile_index, variant_of=family_bitmask, probability=new_pct / 100.0,
            )
            self.status_text = f"Tuile {tile_index} : variante de {self._bm_family_label(family_bitmask)} a {new_pct}%."
        self._refresh_shape_browser()
    def _bm_family_label(self, family_bitmask):
        return "la tuile par defaut" if family_bitmask == DEFAULT_VARIANT_KEY else f"motif {family_bitmask}"
    def _bm_add_variant_from_pick(self, tile_index, family_bitmask):
        """Turns the tile the player just clicked (while a "+" cell was
        armed -- see _select_bitmap_tile/bm_picking_variant_family) into a
        new variant of `family_bitmask`, defaulting to whatever's smaller of
        20% or the family's remaining headroom. Refuses (status hint) if the
        family is already at 100% -- the picking arms regardless, but
        landing on a tile at that point still can't create an over-100%
        family."""
        remaining = 100 - self._bm_variant_total_pct(family_bitmask)
        if remaining <= 0:
            self.status_text = f"{self._bm_family_label(family_bitmask).capitalize()} : deja 100% de variantes -- reduis-en une d'abord."
            return
        default_pct = min(20, remaining)
        update_autotile_pack_tile(
            self.bm_pack_name, tile_index, variant_of=family_bitmask, probability=default_pct / 100.0,
        )
        self.status_text = f"Tuile {tile_index} : nouvelle variante de {self._bm_family_label(family_bitmask)} ({default_pct}%)."
        self._refresh_shape_browser()
    def _try_save_bitmap_tile(self):
        """Persists the in-progress bitmask edit (Motif mode only --
        Variante mode has nothing to batch-save, every variant writes
        straight through to the pack file immediately on click/scroll via
        _bm_set_variant_pct/_bm_add_variant_from_pick). Callable both from
        the explicit "Enregistrer" click (always runs) and from
        _bm_auto_save_current (gated on bm_dirty there, not here)."""
        if self.bm_variant_mode:
            return
        if self.bm_pack_name is None or self.bm_tile_index is None:
            self.status_text = "Choisis un pack et une tuile."
            return

        bitmask = self._bm_current_bitmask()
        update_autotile_pack_tile(self.bm_pack_name, self.bm_tile_index, bitmask=bitmask)
        self.status_text = f"Tuile {self.bm_tile_index} : motif {bitmask}."
        self.bm_dirty = False
        self._refresh_shape_browser()
    def _bm_mark_default(self):
        if self.bm_pack_name is None or self.bm_tile_index is None:
            self.status_text = "Choisis un pack et une tuile."
            return
        update_autotile_pack_tile(self.bm_pack_name, self.bm_tile_index, default=True)
        self.status_text = f"Tuile {self.bm_tile_index} marquee par defaut."
    def _bm_clear_bitmask(self):
        """Un-assigns the selected tile's own bitmask (confirmed with the
        user: needed after they got a pack's shapes tangled composing an
        unreachable motif by hand) -- pops the field via ressources.
        update_autotile_pack_tile's None-means-pop convention, and resets
        bm_neighbors locally so the 3x3 preview doesn't keep showing the
        just-removed pattern. Leaves `default`/variants of OTHER shapes
        untouched; any variant still pointing at this exact bitmask string
        simply becomes orphaned (falls through to the pack's default tile
        like any other unassigned shape) rather than being cascade-deleted."""
        if self.bm_pack_name is None or self.bm_tile_index is None:
            self.status_text = "Choisis un pack et une tuile."
            return
        update_autotile_pack_tile(self.bm_pack_name, self.bm_tile_index, bitmask=None)
        for key in self.NEIGHBOR_KEYS:
            self.bm_neighbors[key] = EMPTY
        self.bm_dirty = False
        self.status_text = f"Tuile {self.bm_tile_index} : motif retire."
        self._refresh_shape_browser()

    def _handle_bitmap_event(self, event):
        """Mode "bitmap"'s own event handling -- entirely separate from
        tuile/pack's chain below (their width/height stepper, archetype,
        and blocks-movement rects occupy overlapping screen positions with
        this mode's own controls, since all 3 modes share one params
        column -- dispatching here first, before any of those, is what
        keeps a bitmap-mode click from being misread as one of them).

        Delegates entirely to _handle_entity_bitmap_event once a loaded
        pack is entity-kind -- its return value (a freshly registered PNJ
        type_id, or None) propagates all the way up through handle_event,
        same "Creator credits a card for it" contract as _try_register's
        return value in tuile mode. Same delegation, to _handle_carte_
        bitmap_event, once any Carte checklist box is on -- checked FIRST
        (and the checklist's own click handling caught even earlier, right
        here) so it's reachable from either the autotile or entity screen,
        and toggling a box back off works the same way from inside Carte
        mode. Also delegates to _handle_pack_vocation_event for a pack
        that has no vocation at all yet (kind=None, e.g. straight out of
        Extraire) -- checked AFTER the Carte checklist (Carte works on any
        pack regardless of vocation, unaffected) but BEFORE the "entity"
        check, since an unassigned pack must never silently fall through
        to the autotile Motif/Variante screen below (found 2026-08-19:
        that's exactly what used to happen -- a fresh character-sheet
        pack showed the bitmask/variant editor, completely unusable for
        it, with no way to fix it from here at all)."""
        if (
            event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
            and self.bm_pack_name is not None
        ):
            for key, rect in self._bm_carte_checklist_rects().items():
                if rect.collidepoint(event.pos):
                    self._toggle_bm_carte_checkbox(key)
                    return None

        if self.bm_pack_name is not None and self._bm_carte_active():
            return self._handle_carte_bitmap_event(event)

        if self.bm_pack_name is not None and self._bm_pack_needs_vocation():
            return self._handle_pack_vocation_event(event)

        if self.bm_pack_name is not None and self._bm_pack_kind() == "entity":
            return self._handle_entity_bitmap_event(event)

        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.pack_browser.handle_event(event)
                self.shape_browser.handle_event(event)
            return None

        if event.type == pygame.MOUSEMOTION:
            self.pack_browser.handle_event(event)
            self.shape_browser.handle_event(event)
            return None

        # MOUSEBUTTONDOWN from here.
        # pack_browser's own rename-box/delete-confirm/context-menu
        # popup can render outside its normal row-list bounds
        # (RoomBrowser.is_modal) -- route every event there
        # unconditionally while one is open, or the popup renders but
        # never actually receives input.
        if self.pack_browser.is_modal:
            self.pack_browser.handle_event(event)
            return None

        if event.button == 3:
            # Right-click only ever means "open pack_browser's own
            # Renommer/Supprimer menu" here -- shape_browser has neither
            # wired (see __init__), everything else only responds to
            # left-click.
            if self.pack_browser.contains(event.pos):
                self.pack_browser.handle_event(event)
            return None

        if event.button != 1:
            return None

        if self._close_rect.collidepoint(event.pos):
            self.close()
            return None

        if self.is_admingod() and self._delete_pack_rect.collidepoint(event.pos):
            selected = self.pack_browser.selected_name
            if selected is None:
                self.status_text = "Selectionnez un pack a supprimer."
            else:
                self.pack_browser.arm_delete_confirm(selected, self._delete_pack_rect.topleft)
            return None

        if self._handle_mode_switch(event.pos):
            return None

        if self.pack_browser.contains(event.pos):
            self.pack_browser.handle_event(event)
            selected = self.pack_browser.selected_name
            if selected is not None and selected != self.bm_pack_name:
                self._select_bitmap_pack(selected)
            return None

        if self.shape_browser.contains(event.pos):
            self.shape_browser.handle_event(event)
            bitmask = self.shape_browser.selected_name
            if bitmask is not None:
                self._apply_shape_selection(bitmask)
            return None

        if self.bm_pack_name is not None:
            tile_index = self._bm_tile_at(event.pos)
            if tile_index is not None:
                self._select_bitmap_tile(tile_index)
                return None

        for key, rect in self._bm_toggle_rects.items():
            if rect.collidepoint(event.pos):
                was_variant = self.bm_variant_mode
                self.bm_variant_mode = (key == "variant")
                self.bm_picking_variant_family = None
                if was_variant and not self.bm_variant_mode:
                    # Coming back from Variante -- bm_neighbors may be stale
                    # relative to whatever's currently selected (a variant
                    # tile has no bitmask of its own), refresh it now rather
                    # than showing a leftover Motif selection from before.
                    payload = self._bm_pack_payload() or {}
                    tiles = payload.get("tiles", [])
                    if self.bm_tile_index is not None and 0 <= self.bm_tile_index < len(tiles):
                        self._bm_load_neighbors_from_tile(tiles[self.bm_tile_index])
                return None

        if self.bm_variant_mode:
            family, rows, add_rect = self._bm_variant_layout()
            for tile_index, pct, rect in rows:
                if rect.collidepoint(event.pos):
                    # Click also nudges the percentage forward one step (in
                    # addition to hover+scroll) -- same "more permissive"
                    # precedent as every other hover+scroll control here.
                    self._bm_set_variant_pct(tile_index, pct + self.VARIANT_PCT_STEP, family)
                    return None
            if add_rect is not None and add_rect.collidepoint(event.pos):
                if self.bm_picking_variant_family == family:
                    # Clicking "+" again while already armed cancels it --
                    # a quick way out without having to click a tile.
                    self.bm_picking_variant_family = None
                    self.status_text = "Ajout de variante annule."
                else:
                    self.bm_picking_variant_family = family
                    self.status_text = "Clique une tuile vierge (grise) dans la grille pour l'ajouter comme variante."
                return None
        else:
            neighbor_key = self._bm_neighbor_at(event.pos)
            if neighbor_key is not None:
                # Click still cycles too (in addition to hover+scroll) --
                # "plus permissive", more than one way to do the same thing.
                self._cycle_neighbor(neighbor_key, 1)
                return None
            if self._bm_clear_rect.collidepoint(event.pos):
                self._bm_clear_bitmask()
                return None
            if self._bm_default_rect.collidepoint(event.pos):
                self._bm_mark_default()
                return None

            if self._bm_save_rect.collidepoint(event.pos):
                self._try_save_bitmap_tile()
                return None

        return None
    def _render_bitmap(self, screen):
        """Mode "bitmap"'s own rendering -- pack picker + shape check-list
        on the left, the pack's tiles as a grid inside viewer_rect's bounds
        (instead of a loaded image), and either the 4 neighbor-cycling
        buttons (Motif) or the selected tile's variant family list
        (Variante), whichever self.bm_variant_mode currently selects.

        Delegates to _render_entity_bitmap once a loaded pack is entity-
        kind -- entirely different screen (action/direction tagging + PNJ
        registration instead of bitmask/variant editing). Same delegation,
        to _render_carte_bitmap, once any Carte checklist box is on -- the
        checklist itself renders first, unconditionally, so it's reachable
        (and shows its own state) from either screen. Same delegation, to
        _render_pack_vocation, for a pack with no vocation at all yet --
        see _handle_bitmap_event's own docstring for why this has to be
        checked before the "entity" branch, not folded into its fallback."""
        self.pack_browser.render(screen)

        if self.is_admingod():
            label = "Supprimer pack" if self.pack_browser.selected_name else "Supprimer pack (aucun)"
            self.border.draw_centered_label(screen, self._delete_pack_rect, self.font, label, color=(255, 150, 150))

        if self.bm_pack_name is not None:
            self._render_bm_carte_checklist(screen)
            if self._bm_carte_active():
                self.existing_cards_browser.render(screen)
                if not self.existing_cards_browser.rooms:
                    hint = self.small_font.render(
                        "Aucune carte sur ce pack.", True, (150, 150, 150),
                    )
                    screen.blit(hint, (
                        self.existing_cards_browser.x,
                        self.existing_cards_browser.y + self.existing_cards_browser.height + 8,
                    ))
                self._render_carte_bitmap(screen)
                return

        if self.bm_pack_name is not None and self._bm_pack_needs_vocation():
            self._render_pack_vocation(screen)
            return

        if self.bm_pack_name is not None and self._bm_pack_kind() == "entity":
            self._render_entity_bitmap(screen)
            return

        self.shape_browser.render(screen)
        if self.bm_pack_name is None:
            hint = self.small_font.render("Choisis un pack pour voir ses motifs", True, (180, 180, 180))
            screen.blit(hint, (self.shape_browser.x, self.shape_browser.y + self.shape_browser.height + 8))

        self.border.draw(screen, self.viewer_rect)
        payload = self._bm_pack_payload()
        if payload is None:
            hint = self.small_font.render("Choisis un pack a gauche", True, (180, 180, 180))
            screen.blit(hint, (self.viewer_rect.centerx - hint.get_width() / 2, self.viewer_rect.centery))
        else:
            clip = screen.get_clip()
            screen.set_clip(self.viewer_rect)
            for index, tile in enumerate(payload.get("tiles", [])):
                rect = self._bm_tile_rect(index)
                region = load_tileset_region(payload["tileset"], tile["rect"])
                scaled = pygame.transform.scale(region, (rect.width, rect.height))
                screen.blit(scaled, rect.topleft)
                if tile.get("default"):
                    pygame.draw.rect(screen, (120, 200, 255), rect, 2)
                elif tile.get("bitmask") or tile.get("variant_of"):
                    pygame.draw.rect(screen, (120, 220, 120), rect, 2)
                elif self.bm_picking_variant_family is not None:
                    # Armed via the "+" cell -- every still-pickable (blank)
                    # tile gets its own visible affordance so the player
                    # knows exactly where a click will land.
                    pygame.draw.rect(screen, (220, 190, 90), rect, 2)
                if index == self.bm_tile_index:
                    pygame.draw.rect(screen, (255, 220, 120), rect, 3)
            screen.set_clip(clip)

            legend_y = self.viewer_rect.bottom + 6
            legend = self.small_font.render(
                "Jaune = selection actuelle  |  Bleu = tuile par defaut  |  "
                "Vert = motif/variante assigne(e)  |  Gris = vierge  |  molette = defiler",
                True, (170, 170, 170),
            )
            screen.blit(legend, (self.viewer_rect.x, legend_y))

        params_x = self._bm_toggle_rects["assign"].x if self._bm_toggle_rects else self.viewer_rect.right + 20

        for key, rect in self._bm_toggle_rects.items():
            label = "Bitmask" if key == "assign" else "Variante"
            selected = (key == "variant") == self.bm_variant_mode
            text = f"> {label}" if selected else label
            self.border.draw_centered_label(screen, rect, self.small_font, text, (255, 220, 120) if selected else (255, 255, 255))

        if self.bm_tile_index is None:
            hint = self.small_font.render("Clique une tuile ci-dessus", True, (180, 180, 180))
            screen.blit(hint, (params_x, self._bm_toggle_rects["assign"].bottom + 12))
            return

        if self.bm_variant_mode:
            self._render_bm_variant_list(screen, params_x)
        else:
            self._render_bm_neighbor_grid(screen)
            mask_label = self.small_font.render(f"Motif : {self._bm_current_bitmask()}", True, (200, 200, 200))
            screen.blit(mask_label, (params_x, self._bm_default_rect.y - mask_label.get_height() - 4))
            self.border.draw_centered_label(screen, self._bm_clear_rect, self.small_font, "Retirer")
            self.border.draw_centered_label(screen, self._bm_default_rect, self.small_font, "Par defaut")
            self.border.draw_centered_label(screen, self._bm_save_rect, self.font, "Enregistrer la tuile")

    def _bm_carte_checklist_rects(self):
        """3 checkbox rows (Multitile/Multidirection/Animation), stacked
        below the pack picker -- any combination can be on at once (see
        _bm_carte_active). Anchored at self._bm_carte_toggle_rect (kept as
        the fixed layout anchor set by _layout_bitmap, even though it's no
        longer a single toggle itself)."""
        anchor = self._bm_carte_toggle_rect
        rects = {}
        y = anchor.y
        for key in ("multitile", "multidirection", "animation"):
            rects[key] = pygame.Rect(anchor.x, y, anchor.width, 32)
            y += 32 + 6
        return rects

    def _bm_carte_checklist_bottom(self):
        return max(r.bottom for r in self._bm_carte_checklist_rects().values())

    def _bm_carte_active(self):
        """True once any Carte checklist box is checked -- the gate
        _handle_bitmap_event/_render_bitmap use to delegate to the whole
        Carte-building screen instead of the autotile/entity one."""
        return self.bm_carte_multitile or self.bm_carte_multidirection or self.bm_carte_animation

    def _toggle_bm_carte_checkbox(self, key):
        attr = f"bm_carte_{key}"
        setattr(self, attr, not getattr(self, attr))

    def _render_bm_carte_checklist(self, screen):
        labels = {"multitile": "Multitile", "multidirection": "Multidirection", "animation": "Animation"}
        for key, rect in self._bm_carte_checklist_rects().items():
            checked = getattr(self, f"bm_carte_{key}")
            text = f"[x] {labels[key]}" if checked else f"[ ] {labels[key]}"
            self.border.draw_centered_label(screen, rect, self.font, text)

    def _bm_carte_selection_rects(self):
        """index-in-selection -> small thumbnail rect, wrapped onto
        multiple rows -- same idiom as DecouperMixin._door_frame_thumb_
        rects, anchored below the checklist instead of a frame-count
        stepper (Carte mode has no such stepper -- the tile grid itself,
        via bm_carte_selection, is the count)."""
        size, gap = 26, 4
        origin_x = self._bm_carte_toggle_rect.x
        origin_y = self._bm_carte_checklist_bottom() + 12
        per_row = max(1, (self._bm_carte_toggle_rect.width + gap) // (size + gap))
        rects = {}
        for i in range(len(self.bm_carte_selection)):
            row, col = divmod(i, per_row)
            rects[i] = pygame.Rect(origin_x + col * (size + gap), origin_y + row * (size + gap), size, size)
        return rects

    def _bm_carte_selection_direction_rect(self, thumb_rect):
        return pygame.Rect(
            thumb_rect.x, thumb_rect.bottom - self.DIRECTION_LABEL_STRIP,
            thumb_rect.width, self.DIRECTION_LABEL_STRIP,
        )

    def _bm_carte_controls_top(self):
        """y just below the selection strip (empty selection still reserves
        one row's worth of space, so the controls below never jump around
        as the selection count changes)."""
        size, gap = 26, 4
        origin_y = self._bm_carte_checklist_bottom() + 12
        rects = self._bm_carte_selection_rects()
        rows = 1 + max((r.y - origin_y) // (size + gap) for r in rects.values()) if rects else 1
        return origin_y + rows * (size + gap) + 12

    def _bm_carte_layout_rects(self):
        """Every rect/widget the currently-active Carte tools need, stacked
        top to bottom below the selection strip: the Multitile footprint
        tool (width/height steppers + DecouperMixin's shared cell_modes
        grid editor, only while bm_carte_multitile is on), the
        Multidirection placement-mode toggle (only while bm_carte_
        multidirection is on), the name box, and the confirm button.
        Recomputed fresh every call (like _bm_carte_selection_rects) since
        which sections are even present depends on the checklist -- shared
        by render and event handling so neither can drift from the other.

        Positions self._blocks_rect as a side effect when Multitile is on
        -- DecouperMixin's _cell_mode_grid_rects/_render_cell_modes_grid/
        _cell_mode_at all anchor off it, reused here rather than
        duplicating that geometry since Decouper's own tab is unreachable
        (see decouper.py's own docstring). Deliberately no archetype
        picker here at all -- see panel.py's own bm_carte_multitile/
        _try_register_carte's docstring for why."""
        params_x = self._bm_carte_toggle_rect.x
        width = self._bm_carte_toggle_rect.width
        top = self._bm_carte_controls_top()

        width_stepper = None
        height_stepper = None
        if self.bm_carte_multitile:
            width_stepper = Stepper(params_x, top + 16, 28, 50, 1, self.MAX_TILES)
            top = width_stepper.bottom + 16
            height_stepper = Stepper(params_x, top, 28, 50, 1, self.MAX_TILES)
            top = height_stepper.bottom + 16
            self._blocks_rect = pygame.Rect(params_x, top, 32, 32)
            if self.cell_modes_grid is not None:
                grid_rects = self._cell_mode_grid_rects()
                top = max(r.bottom for r in grid_rects.values()) + 24
            else:
                top += 24

        direction_mode_rect = None
        if self.bm_carte_multidirection:
            direction_mode_rect = pygame.Rect(params_x, top, width, 32)
            top = direction_mode_rect.bottom + 14

        name_box_pos = (params_x, top)
        top += 32 + 14
        confirm_rect = pygame.Rect(params_x, top, width, 40)
        return {
            "width_stepper": width_stepper,
            "height_stepper": height_stepper,
            "direction_mode_rect": direction_mode_rect,
            "name_box_pos": name_box_pos,
            "confirm_rect": confirm_rect,
        }

    def _render_carte_bitmap(self, screen):
        """"Carte" screen -- pick one or more of the loaded pack's regions
        (click a tile in the grid to toggle it in/out of bm_carte_
        selection, order = click order = frame/animation order), then use
        whichever checklist tools are on to shape it further. Reuses the
        exact same tile grid as the autotile screen (see _render_bitmap)
        for picking, just with selection-order highlighting instead of a
        single bm_tile_index. No archetype/type is ever shown or chosen
        here -- see _try_register_carte."""
        self.border.draw(screen, self.viewer_rect)
        payload = self._bm_pack_payload()
        if payload is None:
            hint = self.small_font.render("Choisis un pack a gauche", True, (180, 180, 180))
            screen.blit(hint, (self.viewer_rect.centerx - hint.get_width() / 2, self.viewer_rect.centery))
            return

        clip = screen.get_clip()
        screen.set_clip(self.viewer_rect)
        for index, tile in enumerate(payload.get("tiles", [])):
            rect = self._bm_tile_rect(index)
            region = load_tileset_region(payload["tileset"], tile["rect"])
            scaled = pygame.transform.scale(region, (rect.width, rect.height))
            screen.blit(scaled, rect.topleft)
            if index in self.bm_carte_selection:
                order = self.bm_carte_selection.index(index)
                pygame.draw.rect(screen, (255, 220, 120), rect, 3)
                order_label = self.small_font.render(str(order), True, (255, 255, 255))
                screen.blit(order_label, (rect.x + 1, rect.y + 1))
        screen.set_clip(clip)

        legend_text = "Clique une tuile pour l'ajouter/retirer -- le chiffre est son ordre"
        if self.bm_carte_animation:
            legend_text += " (= ordre de lecture de l'animation)"
        legend = self.small_font.render(legend_text, True, (170, 170, 170))
        screen.blit(legend, (self.viewer_rect.x, self.viewer_rect.bottom + 6))

        params_x = self._bm_carte_toggle_rect.x
        strip_rects = self._bm_carte_selection_rects()
        for i, rect in strip_rects.items():
            pygame.draw.rect(screen, (40, 40, 45), rect)
            index = self.bm_carte_selection[i]
            tile = payload["tiles"][index] if index < len(payload.get("tiles", [])) else None
            if tile is not None:
                region = load_tileset_region(payload["tileset"], tile["rect"])
                screen.blit(pygame.transform.scale(region, rect.size), rect.topleft)
            pygame.draw.rect(screen, (120, 120, 120), rect, 2)
            if self.bm_carte_multidirection:
                direction_rect = self._bm_carte_selection_direction_rect(rect)
                direction = self.bm_carte_directions[i] if i < len(self.bm_carte_directions) else None
                pygame.draw.rect(screen, (70, 70, 100), direction_rect)
                direction_label = self.small_font.render(self.DIRECTION_LABELS[direction], True, (255, 255, 255))
                screen.blit(direction_label, (
                    direction_rect.centerx - direction_label.get_width() // 2,
                    direction_rect.centery - direction_label.get_height() // 2,
                ))
        if not strip_rects:
            hint = self.small_font.render("Aucune region choisie", True, (150, 150, 150))
            screen.blit(hint, (params_x, self._bm_carte_checklist_bottom() + 12))

        layout = self._bm_carte_layout_rects()

        if self.bm_carte_multitile:
            w_label = self.small_font.render("Largeur (tuiles)", True, (200, 200, 200))
            screen.blit(w_label, (
                layout["width_stepper"].minus_rect.x,
                layout["width_stepper"].minus_rect.y - w_label.get_height() - 2,
            ))
            layout["width_stepper"].render(screen, self.border, self.font, self.width_tiles)
            h_label = self.small_font.render("Hauteur (tuiles)", True, (200, 200, 200))
            screen.blit(h_label, (
                layout["height_stepper"].minus_rect.x,
                layout["height_stepper"].minus_rect.y - h_label.get_height() - 2,
            ))
            layout["height_stepper"].render(screen, self.border, self.font, self.height_tiles)
            if self.cell_modes_grid is not None:
                self._render_cell_modes_grid(screen)

        if self.bm_carte_multidirection and layout["direction_mode_rect"] is not None:
            direction_mode_label = "Placement : Auto" if self.bm_carte_direction_mode == "auto" else "Placement : Manuel"
            self.border.draw_centered_label(screen, layout["direction_mode_rect"], self.font, direction_mode_label)

        self.name_box.rect.topleft = layout["name_box_pos"]
        self.name_box.render(screen)

        self.border.draw_centered_label(screen, layout["confirm_rect"], self.font, "Enregistrer comme Carte")

        if self.status_text:
            status_surface = self.small_font.render(self.status_text, True, (255, 220, 120))
            screen.blit(status_surface, (layout["confirm_rect"].x, layout["confirm_rect"].bottom + 8))

    def _cycle_bm_carte_direction(self, index, step=1):
        """Advances selection-slot `index`'s direction tag through
        DIRECTION_CYCLE -- same constant/cycle DecouperMixin's own
        _cycle_frame_direction uses, just indexing bm_carte_directions
        instead of frame_directions (both mixins live on the same final
        class, see this module's own docstring)."""
        current = self.bm_carte_directions[index]
        cycle_index = self.DIRECTION_CYCLE.index(current) if current in self.DIRECTION_CYCLE else 0
        self.bm_carte_directions[index] = self.DIRECTION_CYCLE[(cycle_index + step) % len(self.DIRECTION_CYCLE)]

    def _toggle_bm_carte_tile(self, index):
        """Adds `index` to the end of bm_carte_selection (a fresh, untagged
        slot), or removes it (and its matching direction slot) if already
        selected -- click order IS frame order, so removing from the
        middle naturally shifts every later frame's index down, exactly
        like DecouperMixin's own door_frame_rects shrinking."""
        if index in self.bm_carte_selection:
            position = self.bm_carte_selection.index(index)
            del self.bm_carte_selection[position]
            del self.bm_carte_directions[position]
        else:
            self.bm_carte_selection.append(index)
            self.bm_carte_directions.append(None)

    def _try_register_carte(self):
        """"Enregistrer comme Carte" -- builds ONLY the structural/visual
        fields the active checklist tools produced (region(s)/frame order,
        footprint size + per-cell modes if Multitile is on, direction tags
        if Multidirection is on) and calls register_custom_type. Never sets
        an archetype/placement, nor blocks_movement/interactable/lockable
        -- always registered under the neutral "sol" archetype with every
        other flag left at its False/None default. A freshly-assembled
        card is deliberately typeless/property-less at creation: it's the
        player's job to tear/fuse those from other existing cards in-game
        afterward (extract_property_payload in object_manager.py), never
        the Assembleur's to decide. A follow-up update_type_mechanics call
        sets direction_mode if any direction was actually tagged --
        register_custom_type itself has no such param (Forge-only field,
        see _build_mechanics_fields' own docstring)."""
        payload = self._bm_pack_payload()
        if payload is None or not self.bm_carte_selection:
            self.status_text = "Choisis au moins une region dans la grille."
            return None

        raw_name = self.name_box.value.strip()
        if not raw_name:
            self.status_text = "Donne un nom a la carte."
            return None

        target = raw_name.strip().lower()
        for candidate_id, config in OBJECT_TYPES.items():
            if isinstance(config.get("asset"), dict) and config.get("name", "").strip().lower() == target:
                self.status_text = f"'{raw_name}' existe deja ({candidate_id})."
                return None

        type_id = self._sanitize_id(raw_name, OBJECT_TYPES, fallback="carte")
        tiles = payload.get("tiles", [])
        rects = [tiles[index]["rect"] for index in self.bm_carte_selection]
        directions = {}
        if self.bm_carte_multidirection:
            directions = {
                direction: i for i, direction in enumerate(self.bm_carte_directions) if direction
            }
        size = (self.width_tiles, self.height_tiles) if self.bm_carte_multitile else (1, 1)
        cell_modes = self._current_cell_modes() if self.bm_carte_multitile else None

        try:
            register_custom_type(
                type_id, raw_name, payload["tileset"], rects[0], size, "sol",
                cell_modes=cell_modes,
                frame_rects=rects if len(rects) > 1 else None,
                directions=directions,
            )
            if directions:
                # update_type_mechanics REPLACES every mechanics field, it
                # doesn't merge (see its own docstring) -- cell_modes must
                # be re-passed here too, or this call would silently wipe
                # out what register_custom_type just set above.
                update_type_mechanics(type_id, cell_modes=cell_modes, direction_mode=self.bm_carte_direction_mode)
        except ValueError as exc:
            self.status_text = str(exc)
            return None

        self.status_text = f"'{raw_name}' enregistre ({type_id})."
        self.name_box.value = ""
        self.bm_carte_selection = []
        self.bm_carte_directions = []
        self._refresh_carte_existing_cards()
        return type_id

    def _handle_carte_bitmap_event(self, event):
        """"Carte" screen's own event handling -- delegated to from
        _handle_bitmap_event once _bm_carte_active() is true. The
        checklist's own click handling is caught one level up, before this
        is ever reached, so toggling a box on/off works the same from any
        screen."""
        if event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.pack_browser.handle_event(event)
                self.existing_cards_browser.handle_event(event)
            return None

        if event.type == pygame.MOUSEMOTION:
            self.pack_browser.handle_event(event)
            self.existing_cards_browser.handle_event(event)
            return None

        # MOUSEBUTTONDOWN from here.
        # existing_cards_browser's own delete-confirm/context-menu popup
        # can render outside its normal row-list bounds (RoomBrowser.
        # is_modal) -- route every event there unconditionally while one
        # is open, same precedent as DecouperMixin's own handling of it.
        if self.existing_cards_browser.is_modal:
            self.existing_cards_browser.handle_event(event)
            return None
        if self.pack_browser.is_modal:
            self.pack_browser.handle_event(event)
            return None

        if event.button == 3:
            # Right-click opens Supprimer on whichever of the two this hit
            # -- pack_browser (delete the whole pack) or existing_cards_
            # browser (delete one already-built card), see _try_delete_pack/
            # _try_delete_card.
            if self.pack_browser.contains(event.pos):
                self.pack_browser.handle_event(event)
            elif self.existing_cards_browser.contains(event.pos):
                self.existing_cards_browser.handle_event(event)
            return None

        if event.button != 1:
            return None

        if self._close_rect.collidepoint(event.pos):
            self.close()
            return None

        if self._handle_mode_switch(event.pos):
            return None

        if self.existing_cards_browser.contains(event.pos):
            self.existing_cards_browser.handle_event(event)
            return None

        if self.pack_browser.contains(event.pos):
            self.pack_browser.handle_event(event)
            selected = self.pack_browser.selected_name
            if selected is not None and selected != self.bm_pack_name:
                # _select_bitmap_pack resets the whole checklist -- switching
                # packs mid-Carte-session should stay in Carte mode with the
                # same tools active, just against the new pack's regions.
                was_multitile = self.bm_carte_multitile
                was_multidirection = self.bm_carte_multidirection
                was_animation = self.bm_carte_animation
                self._select_bitmap_pack(selected)
                self.bm_carte_multitile = was_multitile
                self.bm_carte_multidirection = was_multidirection
                self.bm_carte_animation = was_animation
            return None

        if self.bm_pack_name is not None:
            tile_index = self._bm_tile_at(event.pos)
            if tile_index is not None:
                self._toggle_bm_carte_tile(tile_index)
                return None

        if self.bm_carte_multidirection:
            for i, rect in self._bm_carte_selection_rects().items():
                if self._bm_carte_selection_direction_rect(rect).collidepoint(event.pos):
                    self._cycle_bm_carte_direction(i)
                    return None

        layout = self._bm_carte_layout_rects()

        if self.bm_carte_multitile:
            new_width = layout["width_stepper"].handle_click(event.pos, self.width_tiles)
            if new_width is not None:
                self.width_tiles = new_width
                self._ensure_cell_modes_grid()
                return None
            new_height = layout["height_stepper"].handle_click(event.pos, self.height_tiles)
            if new_height is not None:
                self.height_tiles = new_height
                self._ensure_cell_modes_grid()
                return None
            if self.cell_modes_grid is not None:
                cell = self._cell_mode_at(event.pos)
                if cell is not None:
                    row, col = cell
                    self._cycle_cell_mode(row, col, 1)
                    return None

        if self.bm_carte_multidirection and layout["direction_mode_rect"] is not None:
            if layout["direction_mode_rect"].collidepoint(event.pos):
                self.bm_carte_direction_mode = "manual" if self.bm_carte_direction_mode == "auto" else "auto"
                return None

        if layout["confirm_rect"].collidepoint(event.pos):
            return self._try_register_carte()

        return None

    def _render_entity_bitmap(self, screen):
        """The whole bitmap-mode screen once an entity-kind pack is loaded --
        replaces shape_browser (autotile-only reference shapes) with
        _npc_existing_browser, and the tile grid's own coloring/selection
        with the action/direction/order tagging flow (see
        _handle_entity_bitmap_event)."""
        self._npc_existing_browser.render(screen)
        if not self._npc_existing_browser.rooms:
            hint = self.small_font.render(
                "Aucune carte enregistree depuis ce pack.", True, (180, 180, 180),
            )
            screen.blit(hint, (self._npc_existing_browser.x, self._npc_existing_browser.y + self._npc_existing_browser.height + 8))

        self.border.draw(screen, self.viewer_rect)
        payload = self._bm_pack_payload()
        clip = screen.get_clip()
        screen.set_clip(self.viewer_rect)
        for index, tile in enumerate(payload.get("tiles", [])):
            rect = self._bm_tile_rect(index)
            region = load_tileset_region(payload["tileset"], tile["rect"])
            scaled = pygame.transform.scale(region, (rect.width, rect.height))
            screen.blit(scaled, rect.topleft)
            if tile.get("action"):
                pygame.draw.rect(screen, (120, 220, 120), rect, 2)
            if index in self._bm_entity_selection:
                color = (200, 90, 90) if index in self._bm_entity_exclude else (255, 220, 120)
                pygame.draw.rect(screen, color, rect, 3)
        screen.set_clip(clip)

        legend_y = self.viewer_rect.bottom + 6
        legend = self.small_font.render(
            "Jaune = selection  |  Rouge = exclu de la selection  |  Vert = deja tague  |  "
            "clic-glisser = selection rectangulaire, re-cliquer = exclure/inclure  |  molette = defiler",
            True, (170, 170, 170),
        )
        screen.blit(legend, (self.viewer_rect.x, legend_y))

        self._render_entity_bitmap_params(screen)
    def _render_entity_bitmap_params(self, screen):
        """The params column for an entity-kind pack: the action/direction
        tagging controls on top, the "Enregistrer/Mettre a jour comme PNJ"
        sub-form below -- positions come from _entity_bm_layout, the single
        source of truth shared with _handle_entity_bitmap_event."""
        rects = self._entity_bm_layout()

        action_label = self.small_font.render("Action (texte libre)", True, (200, 200, 200))
        screen.blit(action_label, (self.entity_action_box.rect.x, self.entity_action_box.rect.y - 18))
        self.entity_action_box.render(screen)

        direction_label = self.small_font.render(f"Direction : {self._bm_entity_direction}", True, (200, 200, 200))
        screen.blit(direction_label, (rects["direction_prev"].x, rects["direction_prev"].y - 18))
        self.border.draw_centered_label(screen, rects["direction_prev"], self.small_font, "<")
        self.border.draw_centered_label(screen, rects["direction_next"], self.small_font, ">")

        tag_count = len(self._bm_entity_selection - self._bm_entity_exclude)
        self.border.draw_centered_label(screen, rects["tag_button"], self.font, f"Tagger la selection ({tag_count})")

        name_label = self.small_font.render("Nom de la carte", True, (200, 200, 200))
        screen.blit(name_label, (self.name_box.rect.x, self.name_box.rect.y - 18))
        self.name_box.render(screen)

        idle_label = self.small_font.render(
            f"Idle : {self._npc_idle_action or '--'}{self._role_coverage_suffix(self._npc_idle_action)}",
            True, (200, 200, 200),
        )
        screen.blit(idle_label, (rects["idle_prev"].x, rects["idle_prev"].y - 18))
        self.border.draw_centered_label(screen, rects["idle_prev"], self.small_font, "<")
        self.border.draw_centered_label(screen, rects["idle_next"], self.small_font, ">")

        move_label = self.small_font.render(
            f"Move : {self._npc_move_action or '--'}{self._role_coverage_suffix(self._npc_move_action)}",
            True, (200, 200, 200),
        )
        screen.blit(move_label, (rects["move_prev"].x, rects["move_prev"].y - 18))
        self.border.draw_centered_label(screen, rects["move_prev"], self.small_font, "<")
        self.border.draw_centered_label(screen, rects["move_next"], self.small_font, ">")

        sitting_label = self.small_font.render(
            f"Sitting (optionnel) : {self._npc_sitting_action or '(aucune)'}"
            f"{self._role_coverage_suffix(self._npc_sitting_action)}",
            True, (200, 200, 200),
        )
        screen.blit(sitting_label, (rects["sitting_prev"].x, rects["sitting_prev"].y - 18))
        self.border.draw_centered_label(screen, rects["sitting_prev"], self.small_font, "<")
        self.border.draw_centered_label(screen, rects["sitting_next"], self.small_font, ">")

        laying_label = self.small_font.render(
            f"Laying (optionnel) : {self._npc_laying_action or '(aucune)'}"
            f"{self._role_coverage_suffix(self._npc_laying_action)}",
            True, (200, 200, 200),
        )
        screen.blit(laying_label, (rects["laying_prev"].x, rects["laying_prev"].y - 18))
        self.border.draw_centered_label(screen, rects["laying_prev"], self.small_font, "<")
        self.border.draw_centered_label(screen, rects["laying_next"], self.small_font, ">")

        run_label = self.small_font.render(
            f"Running (optionnel) : {self._npc_run_action or '(aucune)'}"
            f"{self._role_coverage_suffix(self._npc_run_action)}",
            True, (200, 200, 200),
        )
        screen.blit(run_label, (rects["run_prev"].x, rects["run_prev"].y - 18))
        self.border.draw_centered_label(screen, rects["run_prev"], self.small_font, "<")
        self.border.draw_centered_label(screen, rects["run_next"], self.small_font, ">")

        register_label = "Mettre a jour la carte" if self._npc_editing_type_id is not None else "Enregistrer la carte"
        self.border.draw_centered_label(screen, rects["register_button"], self.font, register_label)
    def _render_bm_variant_list(self, screen, params_x):
        """Variante mode's own rendering -- the family of variants for
        whichever pack tile is currently selected (_bm_family_bitmask), each
        shown as its own actual sprite thumbnail (not a text row) with its
        percentage overlaid on top -- hover it and scroll to adjust
        (_bm_variant_layout/_bm_set_variant_pct), click also nudges it
        forward. The trailing "+" cell arms tile-picking (a follow-up click
        on a blank pack tile above turns IT into the new variant -- see
        _select_bitmap_tile/_bm_add_variant_from_pick, confirmed with the
        user: the player picks the tile, nothing is auto-grabbed) -- no
        save button here, every change writes through to the pack file
        immediately, matching the user's own "drag it down to 0 removes it"
        request."""
        top_y = self._bm_toggle_rects["assign"].bottom + 12
        family, rows, add_rect = self._bm_variant_layout()
        if family is None:
            hint = self.small_font.render(
                "Clique une tuile assignee (verte/bleue) pour voir ses variantes.", True, (180, 180, 180),
            )
            screen.blit(hint, (params_x, top_y))
            return

        total = self._bm_variant_total_pct(family)
        header = self.small_font.render(f"Variantes de {self._bm_family_label(family)} (total {total}%)", True, (200, 200, 200))
        screen.blit(header, (params_x, top_y))

        payload = self._bm_pack_payload()
        tiles = payload.get("tiles", []) if payload else []
        for tile_index, pct, rect in rows:
            if 0 <= tile_index < len(tiles):
                region = load_tileset_region(payload["tileset"], tiles[tile_index]["rect"])
                scaled = pygame.transform.scale(region, (rect.width, rect.height))
                screen.blit(scaled, rect.topleft)
            pygame.draw.rect(screen, (120, 220, 120), rect, 2)
            pct_label = self.small_font.render(f"{pct}%", True, (255, 255, 255))
            label_bg = pygame.Rect(rect.x, rect.bottom - pct_label.get_height() - 2, rect.width, pct_label.get_height() + 2)
            pygame.draw.rect(screen, (0, 0, 0), label_bg)
            screen.blit(pct_label, (rect.centerx - pct_label.get_width() / 2, label_bg.y + 1))

        if add_rect is not None:
            armed = self.bm_picking_variant_family == family
            self.border.draw(screen, add_rect)
            label = "x" if armed else "+"
            color = (255, 220, 120) if armed else (255, 255, 255)
            self.border.draw_centered_label(screen, add_rect, self.title_font, label, color)
            if armed:
                hint = self.small_font.render("Clique une tuile grise ci-dessus", True, (220, 190, 90))
                screen.blit(hint, (add_rect.x, add_rect.bottom + 4))
    def _render_bm_neighbor_grid(self, screen):
        """The 3x3 spatial preview: center = the selected tile's own
        thumbnail, cardinal cells = each neighbor's Vide/Sol/Mur value as a
        color swatch + label (hover here and scroll the wheel, or click, to
        cycle it -- see _handle_bitmap_wheel/_cycle_neighbor), corners =
        decorative filler only (confirmed with the user: the bitmask stays
        4-directional, this is purely a visual "real neighborhood" layout)."""
        payload = self._bm_pack_payload()
        tile = payload["tiles"][self.bm_tile_index] if payload else None
        hover_key = self._bm_neighbor_at(pygame.mouse.get_pos())

        for key, rect in self._bm_grid_rects.items():
            if key == "center":
                if tile is not None:
                    region = load_tileset_region(payload["tileset"], tile["rect"])
                    scaled = pygame.transform.scale(region, (rect.width, rect.height))
                    screen.blit(scaled, rect.topleft)
                pygame.draw.rect(screen, (200, 200, 200), rect, 1)
            elif key in self.CORNER_KEYS:
                pygame.draw.rect(screen, (35, 35, 38), rect)
            else:
                value = self.bm_neighbors[key]
                pygame.draw.rect(screen, self.NEIGHBOR_VALUE_COLORS[value], rect)
                label = self.small_font.render(self.NEIGHBOR_VALUE_LABELS[value], True, (20, 20, 20))
                screen.blit(label, (rect.centerx - label.get_width() / 2, rect.centery - label.get_height() / 2))
                border_color = (255, 220, 120) if key == hover_key else (200, 200, 200)
                pygame.draw.rect(screen, border_color, rect, 3 if key == hover_key else 1)

        if self.status_text:
            status_surface = self.small_font.render(self.status_text, True, (255, 220, 120))
            screen.blit(status_surface, (self._bm_save_rect.x, self._bm_save_rect.bottom + 8))

    def _layout_bitmap(self, column):
        """Lays out mode "bitmap"'s own UI -- called from
        SpriteEditorPanelUI._layout(). pack_browser/shape_browser/
        _npc_existing_browser live in the LEFT column (like file_browser),
        not the params column `column` represents -- positioned directly,
        same as before the split. Numerically identical to the pre-split
        offsets (verified by the split's own scripted rect comparison)."""
        self.pack_browser.x = self.x + 16
        self.pack_browser.y = self.y + 60

        # Check-list of reference shapes -- directly below pack_browser in
        # the same left column, same width.
        self.shape_browser.x = self.x + 16
        self.shape_browser.y = self.pack_browser.y + self.pack_browser.height + 16

        # Entity-kind packs show this instead of shape_browser -- same
        # slot, never both visible at once.
        self._npc_existing_browser.x = self.x + 16
        self._npc_existing_browser.y = self.pack_browser.y + self.pack_browser.height + 16

        # Carte mode shows this instead of either of the above -- same slot
        # again, reusing DecouperMixin's own existing_cards_browser (see
        # _refresh_carte_existing_cards). Repositioned here since this
        # runs AFTER _layout_decouper (see panel.py's own _layout, which
        # calls every mode's _layout_xxx in a fixed order) -- Decouper's
        # own tab is unreachable, so its position assignment there is dead
        # and this one wins for good.
        self.existing_cards_browser.x = self.x + 16
        self.existing_cards_browser.y = self.pack_browser.y + self.pack_browser.height + 16

        # "Carte" checklist anchor -- own 3-row block (Multitile/
        # Multidirection/Animation, see _bm_carte_checklist_rects), above
        # everything else, ALWAYS shown once a pack is loaded regardless of
        # its kind (see bm_carte_multitile's own docstring in panel.py's
        # __init__). Deliberately not part of _bm_toggle_rects (Motif/
        # Variante) below -- checking any box delegates to a wholly
        # separate screen, same "own screen entirely" shape as the
        # entity-kind delegation. Kept as a single anchor rect (not 3
        # separately laid-out ones) since _bm_carte_checklist_rects derives
        # all 3 rows from just its position/width.
        self._bm_carte_toggle_rect = pygame.Rect(column.x, column.y, column.width, 32)
        column.gap(3 * (32 + 6) + 6)

        # Fixed 93px width (not column.row()'s auto-computed width) --
        # matches the pre-split rect exactly (93*2+8=194, a few px past
        # step_w, same as it always was).
        toggle_y = column.y
        row_x = column.x
        self._bm_toggle_rects = {}
        for key in ("assign", "variant"):
            rect = pygame.Rect(row_x, toggle_y, 93, 32)
            self._bm_toggle_rects[key] = rect
            row_x = rect.right + 8
        column.gap(46)  # 32 (row height) + 14 (gap to the neighbor grid)

        # Spatial 3x3 preview -- center cell is the selected tile's own
        # thumbnail, the 4 cardinal cells are hover+scroll-editable, the 4
        # corners are decorative filler only (bitmask stays 4-directional
        # everywhere, including the interior tileset).
        neighbor_y = column.y
        grid_cell = 44
        grid_gap = 4
        grid_size = grid_cell * 3 + grid_gap * 2
        grid_x = column.x + (column.width - grid_size) // 2
        self._bm_grid_rects = {
            key: pygame.Rect(
                grid_x + col * (grid_cell + grid_gap), neighbor_y + row * (grid_cell + grid_gap),
                grid_cell, grid_cell,
            )
            for key, (row, col) in self.NEIGHBOR_GRID_POSITIONS.items()
        }
        column.y += grid_size
        column.gap(28)

        self._bm_clear_rect, self._bm_default_rect = column.row(2, 32, gap=8)
        column.gap(12)
        self._bm_save_rect = column.rect(40)
