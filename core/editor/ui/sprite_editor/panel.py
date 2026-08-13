"""SpriteEditorPanelUI -- split into a package (see the other files in
this directory) once the single monolithic sprite_editor.py grew to 3689
lines mixing 5 largely-independent concerns. This module holds only the
generic infrastructure shared by every mode: construction, open/close,
the file browser, image loading, camera<->screen conversion, mode
switching, and the top-level handle_event/render dispatch -- each mode's
own UI/behavior lives in its own mixin file (decouper.py/bitmap.py/
peindre.py), combined here via multiple inheritance so every mode's
methods still operate on ONE shared `self` (same camera, image, name_box,
status_text, etc.) exactly as they did before the split -- a mechanical
move, not a redesign, verified by comparing every produced rect and by
replaying real handle_event()-driven scenarios per mode.
"""

import pygame

from core.ui.widgets import BorderManager, RoomBrowser, TextInputBox, LayoutColumn
from core.data.ressources import PROJECT_ROOT, load_tileset_by_name, list_autotile_packs
from core.world.object_manager import NPC_DIRECTIONS
from core.engine.camera import Camera
from core.editor.autotile import EMPTY

from .decouper import DecouperMixin
from .bitmap import BitmapMixin
from .peindre import PeindreMixin


class SpriteEditorPanelUI(DecouperMixin, BitmapMixin, PeindreMixin):
    """Grand panneau modal (meme famille que core.exploration.inventory_ui.
    InventoryPanel -- assez de place pour afficher une image chargee a une
    echelle utilisable, contrairement aux petits panneaux dockes de coin
    comme CardPanelUI) : on choisit un fichier PNG, on deplace une
    selection dimensionnee selon les steppers largeur/hauteur (alignee sur
    la grille source 16px, pas de redimensionnement libre au pixel pres).

    Trois modes (self.mode, boutons _mode_rects) -- voir le docstring de
    chaque mixin pour le detail complet de ce que fait chacun :
    - "decouper" (DecouperMixin) : recadrage/extraction -- sous-toggle
      crop_kind "tuile" (une carte placable) / "pack" (grille de tuiles
      extraites).
    - "bitmap" (BitmapMixin) : tagging bitmask/variante autotile + tagging
      action/direction/ordre NPC/entite, sur un pack deja extrait. Reste
      independant de "decouper" pour l'instant -- sa possible repartition
      future (avec la Forge) n'est pas encore tranchee.
    - "peindre" (PeindreMixin, ex-"pixel") : editeur pixel type Paint
      rudimentaire (pinceau/roue de couleur, pipette, selection, copier/
      couper/coller, annuler, sauvegarde en place).

    Camera de la visionneuse (self.camera, core.engine.camera.Camera) :
    clic molette maintenu = pan, molette = zoom ancre sur le curseur --
    meme mecanique que la vue de room de Creator, appliquee a une image
    statique plutot qu'a une grille de Dungeon. Non utilisee par le mode
    "bitmap" (grille de tuiles scrollee, pas d'image chargee)."""

    PANEL_WIDTH = 1000
    # +44 par rapport a l'original (700) -- meme delta que le nouveau toggle
    # crop_kind ajoute en tete de la colonne de parametres du mode
    # "decouper" (voir _layout), pour que confirm_rect/le texte de statut en
    # dessous restent visibles au lieu de toucher tout juste le bord bas.
    PANEL_HEIGHT = 744
    OVERLAY_ALPHA = 150
    VIEWER_WIDTH = 520
    VIEWER_HEIGHT = 520
    VIEWER_MIN_SCALE = 1.0
    VIEWER_MAX_SCALE = 4.0
    MODES = (("decouper", "Decouper"), ("peindre", "Peindre"), ("bitmap", "Bitmap"))

    # Mode "decouper" -- sous-toggle entre les deux anciens comportements
    # "tuile" (une seule carte placable) et "pack" (grille de tuiles
    # individuelles extraites) qu'il regroupe desormais. Reprend
    # exactement le vocabulaire des anciens ids de mode -- toute la chaine
    # partagee tuile/pack plus bas teste self.crop_kind au lieu de
    # self.mode, sans autre changement de comportement.

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 15)
        self.title_font = pygame.font.SysFont("arial", 20)
        self.small_font = pygame.font.SysFont("arial", 13)

        self.active = False
        self.image_name = None
        self.image = None
        # world = image pixel space, origin (0, 0) at the image's own
        # top-left -- same Camera class Creator's own room view uses for
        # its world<->screen transform, just applied to a static image
        # instead of a Dungeon grid. Viewer-local screen coords (subtract
        # viewer_rect.topleft first) are what world_to_screen/screen_to_world
        # actually operate in -- see render()/_move_selection_to.
        self.camera = Camera(zoom=1.0, min_zoom=0.5, max_zoom=8.0)
        self._panning = False
        self._pan_last_pos = None

        self.mode = "decouper"
        # Sous-toggle du mode "decouper" (voir CROP_KINDS) -- "tuile" : une
        # seule region devient une nouvelle Carte placable (comportement
        # d'origine). "pack" : la zone de selection devient une grille de
        # tuiles 1x1 INDIVIDUELLES (width_tiles x height_tiles cases
        # separees, pas un seul sprite combine) extraites et numerotees
        # dans un nouveau pack autotile (voir _try_register_pack /
        # ressources.save_autotile_pack) -- l'association bitmask reste une
        # etape manuelle separee, ce sous-mode ne fait qu'automatiser le
        # recadrage.
        self.crop_kind = "tuile"
        self.width_tiles = 1
        self.height_tiles = 1
        # crop_kind "pack" only -- "autotile" (comportement d'origine, ci-dessus)
        # ou "entite" : la feuille chargee vient d'une feuille de
        # personnage/PNJ (assets/characters/, voir _file_browser_root) et le
        # decoupage en grille utilise entity_tile_size (32 par defaut pour
        # coller aux feuilles deja existantes) au lieu du TILE_SIZE de 16 du
        # tileset interieur. Voir _try_register_pack/mode "bitmap" (l'ecran
        # de tagging action/direction qui suit branche sur le "kind" du pack
        # charge, pas sur cet attribut -- celui-ci ne pilote que la capture).
        self.pack_kind = "autotile"
        self.entity_tile_size = 32
        # Racine sous assets/ que file_browser liste -- "tiles" (defaut,
        # inchange) ou "characters" une fois pack_kind="entite" choisi (voir
        # _refresh_file_list/_load_image). Toujours remis a "tiles" en
        # quittant le mode pack ou en repassant en Autotile.
        self._file_browser_root = "tiles"
        self.archetype = "sol"
        self.blocks_movement = False
        # Per-cell walkable override for a multi-cell "sol" tile (see
        # object_manager._build_custom_type_entry's walkable_cells) --
        # [row][col] booleans, resized by _ensure_cell_modes_grid whenever
        # width_tiles/height_tiles changes. None whenever the tile is 1x1,
        # where the single blocks_movement checkbox above is used instead
        # (see _current_cell_modes/render/handle_event).
        self.cell_modes_grid = None
        # Generic flag, no behavior yet (see object_manager's "interactable"
        # field) -- confirmed with the user, just reserved for a future PNJ/
        # interaction system.
        self.interactable = False
        self._sel_x = 0
        self._sel_y = 0
        self._dragging_selection = False

        # Archetype "porte" only -- opt-in (default False so an existing
        # "porte" card, or one saved without ever touching this checkbox,
        # keeps today's always-walkable behavior). See
        # object_manager._build_custom_type_entry's `lockable` param.
        self.lockable = False
        # Opening-animation frame count + one source rect per frame, picked
        # INDIVIDUALLY on the viewer rather than a single contiguous strip
        # auto-sliced -- see _ensure_door_frame_rects/object_manager.
        # _build_custom_type_entry's `frame_rects` param. A fresh frame
        # starts out equal to the current selection (_sel_x/_sel_y sized
        # width_tiles x height_tiles), so an untouched frame is still a
        # well-defined region, not an empty/invalid one.
        self.door_frame_count = 1
        self.door_frame_rects = []
        # Index of the frame the viewer's drag-select currently edits, or
        # None while the plain selection (frame 0's own slot) is what
        # dragging moves -- set by clicking a frame thumbnail (see
        # _door_frame_thumb_rects/handle_event).
        self.editing_door_frame = None

        # Set once the player clicks an entry in existing_cards_browser --
        # Confirmer then calls object_manager.update_custom_type on this id
        # instead of register_custom_type (see _try_update_existing/
        # handle_event's confirm dispatch). Cleared by _load_image (loading
        # a different file) and by the "Nouvelle carte" button.
        self.editing_type_id = None

        self.status_text = ""

        self.file_browser = RoomBrowser(0, 0, width=200)
        # Cartes custom deja sourcees depuis le fichier actuellement charge
        # (object_manager.custom_types_for_tileset) -- repopulee par
        # _load_image, cliquer une entree charge ses parametres pour
        # edition (voir _load_existing_card_for_edit). C'est le correctif
        # direct du cas "stone"/"stone_2" : le joueur voit ce qui existe
        # deja avant d'en recreer une carte ambigue. on_delete only (no
        # on_rename) -- renaming a card already works via the existing
        # edit-and-reconfirm flow (update_custom_type lets raw_name
        # change), and RoomBrowser's generic rename box would pre-fill
        # with the row's VALUE (type_id, see _room_name_for_context) not
        # its display label, which would be confusing here even though
        # the callback itself would still work fine.
        self.existing_cards_browser = RoomBrowser(0, 0, width=200, on_delete=self._try_delete_card)
        self.name_box = TextInputBox(0, 0, 190, 32)

        # Bitmap-mode state -- which pack/tile is selected, and the
        # 4-neighbor values being assembled into a bitmask (Motif mode --
        # see _select_bitmap_tile). Variante mode has no state of its own
        # here: the family being browsed is derived on demand from whichever
        # tile is selected (_bm_family_bitmask) and every row writes
        # straight through to the pack file on click/scroll
        # (_bm_set_variant_pct/_bm_add_variant_from_pick), so there's
        # nothing to stage in memory.
        # Both on_rename and on_delete (unlike the two browsers above) --
        # a pack's id IS its whole identity (no separate display name, see
        # ressources.rename_autotile_pack's own docstring), so this is the
        # ONLY place either operation is reachable at all.
        self.pack_browser = RoomBrowser(
            0, 0, width=200, on_rename=self._try_rename_pack, on_delete=self._try_delete_pack,
        )
        # Check-list of FLOOR_REFERENCE_SHAPES/WALL_REFERENCE_SHAPES (whichever
        # matches the selected pack's role) -- clicking a row sets
        # bm_neighbors directly from that shape's digits (Motif mode only,
        # see _apply_shape_selection), instead of composing it by hand via
        # the 4 neighbor-cycling buttons every time. Repopulated by
        # _refresh_shape_browser (pack selection, and after every save so
        # its "deja assignee" tags stay current).
        self.shape_browser = RoomBrowser(0, 0, width=200)
        self.bm_pack_name = None
        # {pack_name: (mtime, payload)} -- see _bm_pack_payload. Never
        # needs clearing on open()/pack-switch: correctness comes from the
        # mtime comparison each call, not from resetting this dict, so a
        # stale entry for a pack we're not even looking at anymore is
        # harmless dead weight, not a bug.
        self._bm_pack_payload_cache = {}
        self.bm_tile_index = None
        self.bm_neighbors = {"up": EMPTY, "right": EMPTY, "down": EMPTY, "left": EMPTY}
        self.bm_variant_mode = False
        # True only once bm_neighbors has actually been EDITED since the
        # current tile was selected (_cycle_neighbor/_apply_shape_selection
        # set it) -- _bm_auto_save_current only persists when this is set,
        # so merely clicking through tiles to look at them (no edit made)
        # can never silently write a bitmask onto a tile the player never
        # touched. Confirmed root cause of a real data bug: without this
        # gate, browsing tiles in Motif mode was auto-saving whatever
        # bm_neighbors happened to still hold (often a stale "0000") onto
        # every tile clicked past, not just ones actually edited.
        self.bm_dirty = False
        # Set while a "+" cell in Variante mode is armed, waiting for the
        # player to click which still-blank pack tile becomes the new
        # variant (see _select_bitmap_tile/_bm_add_variant_from_pick) --
        # confirmed with the user: the "+" should let them CHOOSE the tile,
        # not silently grab whichever blank one happens to be first.
        self.bm_picking_variant_family = None
        # Row offset (in whole tile rows) the tile grid is scrolled down by
        # -- BM_TILE_CELL's fixed grid has no built-in pagination, so a pack
        # with more tiles than fit in viewer_rect at once (routine for an
        # entity pack sliced across many rows of a character sheet) had NO
        # way to reach anything past the fold before this. See
        # _bm_tile_rect/_bm_clamp_scroll and handle_event's MOUSEWHEEL
        # branch -- scrolling while hovering the grid itself, in EITHER
        # pack kind.
        self.bm_scroll_rows = 0

        # Bitmap-mode state, ENTITY-kind packs only (see _bm_pack_kind) --
        # completely separate from the autotile Motif/Variante state above,
        # since tagging a region with (action, direction, ordre) has
        # nothing in common with a neighbor bitmask. A rectangular
        # multi-select (shift-drag across the tile grid, see
        # _handle_entity_bitmap_event) instead of one tile at a time --
        # tagging a whole action/direction block (up to MAX_TILES tiles) in
        # one "Tagger la selection" click is the entire point, a real
        # character sheet has hundreds of individual frames.
        self._bm_entity_selection = set()
        self._bm_entity_drag_start = None
        # Indices WITHIN the current selection the player has excluded from
        # the next tag (see _handle_entity_bitmap_event) -- for a pose with
        # fewer real frames than the selection's own rectangle (e.g. a
        # 3-frame walk cycle leaving a 4th, transparent column selected
        # along with it).
        self._bm_entity_exclude = set()
        self.entity_action_box = TextInputBox(0, 0, 150, 28)
        self._bm_entity_direction = NPC_DIRECTIONS[0]
        # Which of entity_action_box/name_box a KEYDOWN routes to (see
        # handle_event) -- both are visible on screen at once in this mode,
        # unlike tuile/pack where name_box is the only text field, so a
        # click-to-focus concept is needed here specifically.
        self._entity_bm_focus = "action"

        # "Enregistrer comme PNJ" sub-form, entity-kind bitmap mode only --
        # reuses self.name_box for the PNJ's own name (bitmap mode never
        # otherwise uses it, unlike tuile/pack). idle/move actions cycle
        # through whichever distinct action strings are already tagged in
        # the current pack (see _npc_pack_actions) rather than free text --
        # unlike an action NAME (arbitrary per pack), "which of this pack's
        # own actions plays while idling/moving" is a closed choice.
        self._npc_idle_action = None
        self._npc_move_action = None
        # Optional -- each independently enables its own portion of Npc's
        # move <-> [sitting] <-> sit <-> [laying] <-> lie posture chain
        # (see core.world.entities.Npc's own class docstring). None means
        # "not used", cycled with allow_none=True (see _cycle_npc_action)
        # since leaving any of these unset is a deliberate, valid choice.
        self._npc_sitting_action = None
        self._npc_laying_action = None
        self._npc_run_action = None
        # Set once the player clicks an entry in _npc_existing_browser (the
        # entity-pack analogue of existing_cards_browser) -- Confirmer then
        # calls update_npc_type instead of register_npc_type, same
        # editing_type_id shape as tuile mode. on_delete only, same
        # reasoning as existing_cards_browser above (renaming a PNJ
        # already works via edit-and-reconfirm).
        self._npc_editing_type_id = None
        self._npc_existing_browser = RoomBrowser(0, 0, width=200, on_delete=self._try_delete_npc)

        # Pixel-mode state -- the only mode that touches actual pixel
        # content (see MODES/mode "pixel"'s own docstring above). Reuses
        # file_browser (root "", see _refresh_file_list/_set_mode) rather
        # than a second browser instance.
        self.px_tool = "brush"  # "brush" | "eyedropper" | "select"
        self.brush_color = pygame.Color(0, 0, 0, 255)
        self.brush_size = 1  # carre NxN -- pas de brosse ronde, outil rudimentaire comme demande
        # Alimentent brush_color (teinte/saturation choisies sur la roue,
        # luminosite sur le curseur separe -- voir _px_render_wheel/
        # _px_recompute_brush_color). Valeur (100) par defaut = couleur
        # pleine, pas assombrie.
        self._px_hue = 0.0
        self._px_sat = 0.0
        self._px_value = 100.0
        self._px_wheel_cache = None  # Surface radiale construite une seule fois (lazy, voir _px_wheel_surface)
        self.px_selection = None  # pygame.Rect en coordonnees image (mode "select"), ou None
        self._px_select_anchor = None  # coin de depart du cliqué-glissé de selection, ou None
        self._px_painting = False
        self._px_last_paint_pos = None  # dernier pixel peint (coords image), pour interpoler le trait
        self._px_dragging_wheel = False
        self._px_dragging_value = False
        self.px_clipboard = None  # pygame.Surface (copie independante) ou None
        self._px_undo_stack = []  # snapshots pygame.Surface, plafonne (voir _PX_UNDO_LIMIT)
        self.px_dirty = False
        self._px_new_canvas_open = False
        self._px_new_w = 16
        self._px_new_h = 16

        self._mode_rects = {}
        self._crop_kind_rects = {}
        self._width_stepper = None
        self._height_stepper = None
        self._archetype_rects = {}
        self._blocks_rect = None
        self._interactable_rect = None
        self._lockable_rect = None
        self._door_frames_stepper = None
        # NOTE: no self._door_frame_thumb_rects placeholder here on purpose
        # -- a method of that exact name is defined below (computed fresh
        # per call, same idiom as _cell_mode_grid_rects). An instance
        # attribute of the same name used to be pre-declared here, which
        # SHADOWED the method (Python resolves `self.attr` to the instance
        # dict before the class), making every `self._door_frame_thumb_
        # rects().items()` call site raise `TypeError: 'dict' object is
        # not callable` the moment a "porte" with door_frame_count > 1 was
        # ever rendered or clicked. Found during the sprite_editor.py
        # architecture audit -- fixed by simply not shadowing it.
        self._new_card_rect = None
        self._confirm_rect = None
        self._close_rect = None
        self._bm_toggle_rects = {}
        self._bm_grid_rects = {}
        self._bm_clear_rect = None
        self._bm_default_rect = None
        self._bm_save_rect = None
        self._layout()

    @property
    def is_open(self):
        return self.active
    def open(self):
        self.active = True
        self.mode = "decouper"
        self.crop_kind = "tuile"
        self.pack_kind = "autotile"
        self._file_browser_root = "tiles"
        self.status_text = ""
        self.name_box.value = ""
        self._refresh_file_list()
        self.pack_browser.set_rooms(list_autotile_packs())
        self.bm_pack_name = None
        self.bm_tile_index = None
        self.bm_dirty = False
        self.bm_picking_variant_family = None
        self.bm_scroll_rows = 0
        self._bm_entity_selection = set()
        self._bm_entity_drag_start = None
        self._bm_entity_exclude = set()
        self.entity_action_box.value = ""
        self._entity_bm_focus = "action"
        self._npc_idle_action = None
        self._npc_move_action = None
        self._npc_sitting_action = None
        self._npc_laying_action = None
        self._npc_run_action = None
        self._npc_editing_type_id = None
        self._npc_existing_browser.set_rooms([])
        self.shape_browser.set_rooms([])
        self.existing_cards_browser.set_rooms([])
        self.editing_type_id = None
        self.interactable = False
        self.cell_modes_grid = None
        self.lockable = False
        self.door_frame_count = 1
        self.door_frame_rects = []
        self.editing_door_frame = None

        self.px_tool = "brush"
        self.px_selection = None
        self._px_select_anchor = None
        self._px_painting = False
        self._px_last_paint_pos = None
        self._px_dragging_wheel = False
        self._px_dragging_value = False
        self.px_clipboard = None
        self._px_undo_stack = []
        self.px_dirty = False
        self._px_new_canvas_open = False
    def close(self):
        if self.mode == "bitmap":
            self._bm_auto_save_current()
        self.active = False
    def _refresh_file_list(self):
        """Lists every PNG under self._file_browser_root (relative to
        assets/) -- "tiles" (default, flat, exactly today's behavior: bare
        filenames like "tileset2.png") or "characters" (nested per-
        character folders, see _load_image for why the browser shows a
        path relative to THIS root while self.image_name still ends up
        assets-relative overall)."""
        root_dir = PROJECT_ROOT / "assets" / self._file_browser_root
        if self._file_browser_root == "tiles":
            names = sorted(p.name for p in root_dir.glob("*.png"))
        else:
            names = sorted(
                str(p.relative_to(root_dir)).replace("\\", "/") for p in root_dir.rglob("*.png")
            )
        self.file_browser.set_rooms(names)
    def _layout(self):
        """Every child rect, computed once from self.x/self.y (this panel
        is centered at construction time and never dragged, unlike
        Creator's docked PanelFrame-wrapped panels). Generic pieces
        (viewer, mode buttons, close button, file browser) are laid out
        directly here; each mode's own params-column content is delegated
        to its own mixin's `_layout_xxx(column)`, each given a fresh
        LayoutColumn positioned at the same (params_x, self.y + 100,
        step_w) origin -- safe since only one mode's rects are ever
        rendered/hit-tested at a time (see handle_event/render's own
        3-way dispatch)."""
        self.file_browser.x = self.x + 16
        self.file_browser.y = self.y + 60

        self.viewer_rect = pygame.Rect(self.x + 236, self.y + 60, self.VIEWER_WIDTH, self.VIEWER_HEIGHT)
        params_x = self.viewer_rect.right + 20
        step_w = 190

        # 3 boutons (Decouper/Peindre/Bitmap, voir MODES) -- 70px chacun
        # (3*70+2*4=218 tient dans les ~224px disponibles entre params_x
        # et le bord droit du panneau).
        self._mode_rects = {}
        row_x = params_x
        for mode_id, _label in self.MODES:
            rect = pygame.Rect(row_x, self.y + 60, 70, 32)
            self._mode_rects[mode_id] = rect
            row_x = rect.right + 4

        self._close_rect = pygame.Rect(self.x + self.PANEL_WIDTH - 90, self.y + 12, 70, 28)

        self._layout_decouper(LayoutColumn(params_x, self.y + 100, step_w))
        self._layout_bitmap(LayoutColumn(params_x, self.y + 100, step_w))
        self._layout_peindre(LayoutColumn(params_x, self.y + 100, step_w))

    def _full_image_name(self, filename):
        """`filename` (whatever file_browser is currently showing) joined
        back onto self._file_browser_root into a path relative to assets/
        itself -- see _refresh_file_list for why the browser only shows a
        root-relative name. Shared by _load_image and its own caller's
        "did the selection actually change" check, so the two can't drift
        on what "the same file" means once root != "tiles". Root "" (mode
        "pixel", see _refresh_file_list's rglob branch scanning assets/
        itself) is the other bare-passthrough case -- `filename` there is
        already assets-relative (e.g. "tiles/vase.png"), same as "tiles"."""
        if self._file_browser_root in ("tiles", ""):
            return filename
        return f"{self._file_browser_root}/{filename}"
    def _load_image(self, filename):
        """`filename` is whatever file_browser is currently showing --
        relative to self._file_browser_root, not necessarily to assets/
        itself (see _full_image_name). self.image_name always ends up
        assets-relative either way -- what save_autotile_pack/
        register_custom_type persist as "tileset", and what
        load_tileset_by_name expects."""
        full_name = self._full_image_name(filename)
        try:
            self.image = load_tileset_by_name(full_name)
        except (pygame.error, FileNotFoundError):
            self.image = None
            self.status_text = f"Impossible de charger {filename}"
            return
        self.image_name = full_name
        img_w, img_h = self.image.get_size()
        fit_scale = min(self.VIEWER_WIDTH / img_w, self.VIEWER_HEIGHT / img_h)
        self.camera.zoom = max(self.VIEWER_MIN_SCALE, min(self.VIEWER_MAX_SCALE, fit_scale))
        self.camera.x = 0.0
        self.camera.y = 0.0
        self._sel_x = 0
        self._sel_y = 0
        self._clamp_selection()
        self.status_text = ""
        self.editing_type_id = None
        self._refresh_existing_cards()
    def _local_pos(self, screen_pos):
        """screen_pos, made relative to the viewer's own top-left -- the
        coordinate space Camera.screen_to_world/world_to_screen actually
        operate in here (see self.camera's own comment)."""
        return screen_pos[0] - self.viewer_rect.x, screen_pos[1] - self.viewer_rect.y

    @staticmethod
    def _sanitize_id(raw_name, taken, fallback="carte"):
        """A filesystem/id-safe slug from `raw_name`, deduped against
        `taken` (any container supporting `in`) by appending _2/_3/... --
        shared by _try_register (against OBJECT_TYPES) and
        _try_register_pack (against list_autotile_packs()), same
        auto-dedupe spirit as core.data.profile_manager's name sanitizing."""
        slug = "".join(c if c.isalnum() else "_" for c in raw_name.lower()).strip("_") or fallback
        candidate = slug
        suffix = 2
        while candidate in taken:
            candidate = f"{slug}_{suffix}"
            suffix += 1
        return candidate

    def _set_mode(self, mode_id):
        """Switches self.mode, resetting "decouper"'s own crop_kind/pack_kind/
        file-browser-root back to their defaults whenever leaving it entirely
        -- otherwise file_browser could keep showing assets/characters/**
        content while in "peindre"/"bitmap", which mean something else
        entirely (see _full_image_name/_refresh_file_list). A no-op reset if
        pack_kind was already "autotile" (see _set_crop_kind for the
        equivalent reset when switching crop_kind WITHIN "decouper" instead
        of leaving it).

        Also refreshes pack_browser whenever entering "bitmap" -- open()
        populates it once, so without this a pack registered moments ago
        under crop_kind "pack" (e.g. straight after slicing blackcat.png)
        would never show up here until the whole panel is closed and
        reopened.

        "peindre" gets the same file_browser_root treatment as "decouper"
        above, just with its own root ("", assets/ entier -- see
        _refresh_file_list) instead of "characters". Deliberately no
        autosave-on-leave here (unlike bitmap's _bm_auto_save_current) -- a
        PNG write is heavier/more destructive than bitmap's per-tile JSON
        merge, confirmed with the user as an explicit "Enregistrer" button
        only (see _px_save)."""
        if self.mode == "decouper" and mode_id != "decouper" and self._file_browser_root != "tiles":
            self.pack_kind = "autotile"
            self._file_browser_root = "tiles"
            self._refresh_file_list()
        if self.mode == "peindre" and mode_id != "peindre" and self._file_browser_root != "tiles":
            self._file_browser_root = "tiles"
            self._px_painting = False
            self._px_new_canvas_open = False
            self._px_dragging_wheel = False
            self._px_dragging_value = False
            self._px_select_anchor = None
            self._refresh_file_list()
        if mode_id == "bitmap" and self.mode != "bitmap":
            self.pack_browser.set_rooms(list_autotile_packs())
        if mode_id == "peindre" and self.mode != "peindre":
            self._file_browser_root = ""
            self._refresh_file_list()
        self.mode = mode_id
    def _handle_mode_switch(self, pos):
        """True (and switches self.mode) if `pos` hit a mode button --
        checked first by every mode's own event handling, since switching
        away must always be reachable no matter which mode is active."""
        for mode_id, rect in self._mode_rects.items():
            if rect.collidepoint(pos):
                if self.mode == "bitmap" and mode_id != "bitmap":
                    self._bm_auto_save_current()
                    self.bm_picking_variant_family = None
                self._set_mode(mode_id)
                return True
        return False

    def handle_event(self, event):
        """Returns the newly-registered type_id once Confirmer succeeds
        (Creator credits the card and refreshes CardPanelUI, same "widget
        returns a value, caller applies it" shape as RolePanelUI/
        GeneratorPanelUI), else None -- whether or not the event was
        otherwise consumed, since Creator already routes every event here
        unconditionally while this panel is open."""
        if not self.active:
            return None

        if event.type == pygame.KEYDOWN:
            # A right-click-triggered rename box (pack_browser is the only
            # one of the 3 browsers with on_rename wired, see __init__)
            # needs to receive typed characters -- without this, KEYDOWN
            # always fell through to name_box/entity_action_box below
            # instead, so the rename box rendered but could never actually
            # be typed into. Harmless to route here even mid context-menu/
            # delete-confirm (RoomBrowser.handle_event no-ops on a KEYDOWN
            # in those states) -- see RoomBrowser.is_modal.
            for browser in (self.pack_browser, self.existing_cards_browser, self._npc_existing_browser):
                if browser.is_modal:
                    browser.handle_event(event)
                    return None
            if self.mode == "peindre":
                # New-canvas sub-form reuses name_box for the filename --
                # typed characters go there. Otherwise (no text field
                # visible in this mode) KEYDOWN only ever means a
                # Ctrl+C/X/V/Z clipboard/undo shortcut -- see
                # _px_handle_keydown, gated here instead of falling through
                # to name_box.handle_event below (which would otherwise
                # type the literal character from a Ctrl-combo into a text
                # box that isn't even shown).
                if self._px_new_canvas_open:
                    self.name_box.handle_event(event)
                else:
                    self._px_handle_keydown(event)
                return None
            if (
                self.mode == "bitmap" and self.bm_pack_name is not None
                and self._bm_pack_kind() == "entity" and self._entity_bm_focus == "action"
            ):
                # Entity-bitmap mode has TWO visible text fields at once
                # (the action-tag box and the PNJ-name box) -- unlike every
                # other mode, where name_box is the only one, so which box
                # a keystroke reaches depends on which was last clicked
                # (see _entity_bm_focus/_handle_entity_bitmap_event).
                self.entity_action_box.handle_event(event)
            else:
                self.name_box.handle_event(event)
            return None

        if event.type == pygame.MOUSEWHEEL:
            if self.mode == "bitmap":
                mouse_pos = pygame.mouse.get_pos()
                if self.bm_pack_name is not None and self.viewer_rect.collidepoint(mouse_pos):
                    # Scrolling over the tile grid itself pages through it --
                    # BM_TILE_CELL's fixed grid has no other way to reach
                    # anything past the fold once a pack has more tiles than
                    # fit at once (routine for an entity pack sliced across
                    # many rows of a character sheet). Takes priority over
                    # the kind-specific controls below since those all live
                    # outside viewer_rect's bounds -- no real overlap.
                    payload = self._bm_pack_payload() or {}
                    tile_count = len(payload.get("tiles", []))
                    self.bm_scroll_rows += -1 if event.y > 0 else 1
                    self._bm_clamp_scroll(tile_count)
                    return None
                if self.bm_pack_name is not None and self._bm_pack_kind() == "entity":
                    # Same hover+scroll idiom as the autotile neighbor grid
                    # below, generalized to this screen's own cyclers
                    # (direction / idle / move / sitting / laying / running)
                    # -- click (see the MOUSEBUTTONDOWN handling below)
                    # still works too, scroll is just the faster path.
                    mouse_pos = pygame.mouse.get_pos()
                    rects = self._entity_bm_layout()
                    step = 1 if event.y > 0 else -1
                    if rects["direction_prev"].collidepoint(mouse_pos) or rects["direction_next"].collidepoint(mouse_pos):
                        self._cycle_entity_direction(step)
                    elif rects["idle_prev"].collidepoint(mouse_pos) or rects["idle_next"].collidepoint(mouse_pos):
                        self._cycle_npc_action("idle", step)
                    elif rects["move_prev"].collidepoint(mouse_pos) or rects["move_next"].collidepoint(mouse_pos):
                        self._cycle_npc_action("move", step)
                    elif rects["sitting_prev"].collidepoint(mouse_pos) or rects["sitting_next"].collidepoint(mouse_pos):
                        self._cycle_npc_action("sitting", step, allow_none=True)
                    elif rects["laying_prev"].collidepoint(mouse_pos) or rects["laying_next"].collidepoint(mouse_pos):
                        self._cycle_npc_action("laying", step, allow_none=True)
                    elif rects["run_prev"].collidepoint(mouse_pos) or rects["run_next"].collidepoint(mouse_pos):
                        self._cycle_npc_action("run", step, allow_none=True)
                    return None
                # Hovering a cardinal cell of the 3x3 preview cycles its
                # value -- the primary way to edit a neighbor per the
                # user's own request, click (see the MOUSEBUTTONDOWN
                # handling below) is the extra, more-permissive path.
                if self.bm_variant_mode:
                    # Same hover+scroll pattern, this time over a variant's
                    # own sprite thumbnail -- the primary way to adjust its
                    # percentage now, click there also nudges it forward.
                    family, rows, _add_rect = self._bm_variant_layout()
                    mouse_pos = pygame.mouse.get_pos()
                    for tile_index, pct, rect in rows:
                        if rect.collidepoint(mouse_pos):
                            step = self.VARIANT_PCT_STEP if event.y > 0 else -self.VARIANT_PCT_STEP
                            self._bm_set_variant_pct(tile_index, pct + step, family)
                            break
                elif self.bm_tile_index is not None:
                    neighbor_key = self._bm_neighbor_at(pygame.mouse.get_pos())
                    if neighbor_key is not None:
                        self._cycle_neighbor(neighbor_key, 1 if event.y > 0 else -1)
                return None
            if (
                self.crop_kind == "tuile"
                and self.archetype in self.CELL_MODES_ARCHETYPES
                and self.cell_modes_grid is not None
                and not (self.width_tiles == 1 and self.height_tiles == 1)
            ):
                # Same hover+scroll pattern as the bitmap 3x3 preview above --
                # click (see the MOUSEBUTTONDOWN handling below) still cycles
                # too, scroll is just the faster path across many cells.
                cell = self._cell_mode_at(pygame.mouse.get_pos())
                if cell is not None:
                    row, col = cell
                    self._cycle_cell_mode(row, col, 1 if event.y > 0 else -1)
                return None
            # Same feel as Creator's own room view (Camera.zoom_at, anchored
            # on the cursor) -- only while hovering the viewer itself, per
            # the user's "sur le visualizer".
            mouse_pos = pygame.mouse.get_pos()
            if self.image is not None and self.viewer_rect.collidepoint(mouse_pos):
                local_x, local_y = self._local_pos(mouse_pos)
                self.camera.zoom_at(local_x, local_y, event.y, self.viewer_rect.width, self.viewer_rect.height)
            return None

        if event.type not in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            return None

        if self.mode == "bitmap":
            return self._handle_bitmap_event(event)

        if self.mode == "peindre":
            return self._handle_pixel_event(event)

        # By elimination, everything below is mode "decouper" -- bitmap and
        # peindre already dispatched away above, same precedent as those
        # two's own _handle_bitmap_event/_handle_pixel_event.
        return self._handle_decouper_event(event)
    def render(self, screen):
        if not self.active:
            return

        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, self.OVERLAY_ALPHA))
        screen.blit(overlay, (0, 0))

        panel_rect = pygame.Rect(self.x, self.y, self.PANEL_WIDTH, self.PANEL_HEIGHT)
        self.border.draw(screen, panel_rect)

        title = self.title_font.render("Editeur de sprite", True, (255, 255, 255))
        screen.blit(title, (self.x + 16, self.y + 14))
        self.border.draw_centered_label(screen, self._close_rect, self.font, "Fermer")

        for mode_id, rect in self._mode_rects.items():
            label = dict(self.MODES)[mode_id]
            selected = mode_id == self.mode
            text = f"> {label}" if selected else label
            self.border.draw_centered_label(screen, rect, self.small_font, text, (255, 220, 120) if selected else (255, 255, 255))

        if self.mode == "bitmap":
            self._render_bitmap(screen)
            return

        if self.mode == "peindre":
            self._render_pixel(screen)
            return

        # By elimination, everything below is mode "decouper" -- same
        # precedent as _handle_decouper_event.
        self._render_decouper(screen)
