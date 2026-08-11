"""SpriteEditorPanelUI -- split out of the old monolithic core/editor/ui.py."""

from pathlib import Path

import pygame

from core.ui.widgets import BorderManager, RoomBrowser, Stepper, TextInputBox
from core.world.object_manager import (
    OBJECT_TYPES, ARCHETYPES, register_custom_type, update_custom_type,
    custom_types_for_tileset, CELL_MODES,
)
from core.data.ressources import (
    TILE_SIZE, load_tileset_by_name, load_tileset_region, save_autotile_pack,
    list_autotile_packs, load_autotile_pack, update_autotile_pack_tile,
)
from core.engine.camera import Camera
from core.editor.autotile import EMPTY, FLOOR, WALL, DEFAULT_VARIANT_KEY

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class SpriteEditorPanelUI:
    """Grand panneau modal (meme famille que core.exploration.inventory_ui.
    InventoryPanel -- assez de place pour afficher une image chargee a une
    echelle utilisable, contrairement aux petits panneaux dockes de coin
    comme CardPanelUI) : on choisit un fichier PNG sous assets/tiles/, on
    deplace une selection dimensionnee selon les steppers largeur/hauteur
    (alignee sur la grille source 16px, pas de redimensionnement libre au
    pixel pres). Deux modes (self.mode, boutons _mode_rects) :
    - "tuile" : la selection est UN sprite (une carte) -- on regle nom/
      archetype/blocage, "Enregistrer" appelle object_manager.
      register_custom_type puis rend l'id du type nouvellement cree --
      Creator (le seul appelant) s'en sert pour crediter 1 exemplaire de la
      carte au profil actif et rafraichir CardPanelUI, meme geste que
      --give-card. Volontairement limite aux archetypes a une seule region
      (voir ARCHETYPES) -- torche/pilier restent hors scope, voir leur
      commentaire dans object_manager.py.
    - "pack" : la selection devient une grille de width_tiles x height_tiles
      tuiles 1x1 INDIVIDUELLES -- "Enregistrer" les extrait et numerote
      chacune separement dans un nouveau pack autotile (ressources.
      save_autotile_pack), sans les brancher sur AUTOTILE_LOOKUP : associer
      chaque tuile a son motif de voisins reste une etape manuelle
      separee, ce mode automatise seulement le recadrage. Ne touche jamais
      OBJECT_TYPES/le systeme de Cartes (des tuiles de terrain brutes ne
      sont pas des objets placables) -- handle_event retourne toujours
      None pour ce mode, Creator n'a rien a crediter.
    - "bitmap" : remplace la visionneuse de fichier par un choix de pack
      (self.pack_browser) + une grille de ses tuiles deja extraites. La
      tuile selectionnee gagne soit un bitmask (4 boutons Haut/Droite/Bas/
      Gauche, cycle Vide/Sol/Mur -- meme vocabulaire EMPTY/FLOOR/WALL que
      core.editor.autotile) soit un statut de variante (probabilite d'un
      bitmask deja assigne ailleurs dans le pack), via ressources.
      update_autotile_pack_tile. handle_event retourne toujours None ici
      aussi -- Creator resynchronise juste le donjon ouvert si le pack
      modifie est son theme actif (voir _try_save_bitmap_tile).

    Camera de la visionneuse (self.camera, core.engine.camera.Camera) :
    clic molette maintenu = pan, molette = zoom ancre sur le curseur --
    meme mecanique que la vue de room de Creator, appliquee a une image
    statique plutot qu'a une grille de Dungeon.
    """

    PANEL_WIDTH = 1000
    PANEL_HEIGHT = 620
    OVERLAY_ALPHA = 150

    VIEWER_WIDTH = 520
    VIEWER_HEIGHT = 520
    VIEWER_MIN_SCALE = 1.0
    VIEWER_MAX_SCALE = 4.0

    MAX_TILES = 30

    # Motifs de voisinage qui se produisent reellement dans une salle valide
    # -- extraits de assets/tiles/tile_categories.json (les valeurs "floor"/
    # "wall" distinctes qu'il utilise deja pour le tileset interieur), pas
    # les 3**4=81 combinaisons theoriquement possibles dont la plupart ne
    # peuvent jamais apparaitre. C'est la check-list que le mode bitmap
    # propose une fois un pack charge, pour assigner un motif connu d'un
    # clic plutot que de le composer a la main a chaque tuile.
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
    MODES = (("tuile", "Tuile"), ("pack", "Pack"), ("bitmap", "Bitmap"))

    NEIGHBOR_KEYS = ("up", "right", "down", "left")
    NEIGHBOR_LABELS = {"up": "Haut", "right": "Droite", "down": "Bas", "left": "Gauche"}
    NEIGHBOR_VALUE_LABELS = {EMPTY: "Vide", FLOOR: "Sol", WALL: "Mur"}
    NEIGHBOR_VALUE_COLORS = {EMPTY: (50, 50, 55), FLOOR: (214, 186, 138), WALL: (92, 78, 66)}
    NEIGHBOR_CYCLE = (EMPTY, FLOOR, WALL)

    # Per-cell mode for a multi-cell "sol" tile (core.world.object_manager.
    # CELL_MODES) -- "block" solide/non walkable, "behind" walkable dessine
    # dans l'ordre normal (ex: fleurs, tapis), "front" walkable dessine
    # devant le joueur (ex: torche). Meme cycle click-ou-scroll que le mode
    # bitmap (voir _cycle_cell_mode/_handle_cell_mode_wheel).
    CELL_MODE_LABELS = {"block": "B", "behind": "D", "front": "F"}
    CELL_MODE_COLORS = {"block": (190, 90, 90), "behind": (110, 190, 110), "front": (100, 150, 220)}

    # (row, col) of every cell in the 3x3 spatial preview (see _layout's
    # _bm_grid_rects) -- the 4 corners are decorative-only, never included
    # in NEIGHBOR_KEYS so hover/scroll/click logic can just check "is this
    # key in NEIGHBOR_KEYS" to know whether a grid cell is interactive.
    NEIGHBOR_GRID_POSITIONS = {
        "nw": (0, 0), "up": (0, 1), "ne": (0, 2),
        "left": (1, 0), "center": (1, 1), "right": (1, 2),
        "sw": (2, 0), "down": (2, 1), "se": (2, 2),
    }
    CORNER_KEYS = ("nw", "ne", "sw", "se")

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

        # "tuile" -- une seule region devient une nouvelle Carte placable
        # (comportement d'origine). "pack" -- la zone de selection devient
        # une grille de tuiles 1x1 INDIVIDUELLES (width_tiles x height_tiles
        # cases separees, pas un seul sprite combine) extraites et
        # numerotees dans un nouveau pack autotile (voir _try_register_pack
        # / ressources.save_autotile_pack) -- l'association bitmask reste
        # une etape manuelle separee, ce mode ne fait qu'automatiser le
        # recadrage.
        self.mode = "tuile"
        self.width_tiles = 1
        self.height_tiles = 1
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
        # deja avant d'en recreer une carte ambigue.
        self.existing_cards_browser = RoomBrowser(0, 0, width=200)
        self.name_box = TextInputBox(0, 0, 190, 32)

        # Bitmap-mode state -- which pack/tile is selected, and the
        # 4-neighbor values being assembled into a bitmask (Motif mode --
        # see _select_bitmap_tile). Variante mode has no state of its own
        # here: the family being browsed is derived on demand from whichever
        # tile is selected (_bm_family_bitmask) and every row writes
        # straight through to the pack file on click/scroll
        # (_bm_set_variant_pct/_bm_add_variant_from_pick), so there's
        # nothing to stage in memory.
        self.pack_browser = RoomBrowser(0, 0, width=200)
        # Check-list of FLOOR_REFERENCE_SHAPES/WALL_REFERENCE_SHAPES (whichever
        # matches the selected pack's role) -- clicking a row sets
        # bm_neighbors directly from that shape's digits (Motif mode only,
        # see _apply_shape_selection), instead of composing it by hand via
        # the 4 neighbor-cycling buttons every time. Repopulated by
        # _refresh_shape_browser (pack selection, and after every save so
        # its "deja assignee" tags stay current).
        self.shape_browser = RoomBrowser(0, 0, width=200)
        self.bm_pack_name = None
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

        self._mode_rects = {}
        self._width_stepper = None
        self._height_stepper = None
        self._archetype_rects = {}
        self._blocks_rect = None
        self._interactable_rect = None
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
        self.mode = "tuile"
        self.status_text = ""
        self.name_box.value = ""
        self._refresh_file_list()
        self.pack_browser.set_rooms(list_autotile_packs())
        self.bm_pack_name = None
        self.bm_tile_index = None
        self.bm_dirty = False
        self.bm_picking_variant_family = None
        self.shape_browser.set_rooms([])
        self.existing_cards_browser.set_rooms([])
        self.editing_type_id = None
        self.interactable = False
        self.cell_modes_grid = None

    def close(self):
        if self.mode == "bitmap":
            self._bm_auto_save_current()
        self.active = False

    def _refresh_file_list(self):
        tiles_dir = PROJECT_ROOT / "assets" / "tiles"
        names = sorted(p.name for p in tiles_dir.glob("*.png"))
        self.file_browser.set_rooms(names)

    def _layout(self):
        """Every child rect, computed once from self.x/self.y (this panel
        is centered at construction time and never dragged, unlike
        Creator's docked PanelFrame-wrapped panels -- see Creator.__init__,
        same fixed-position convention ChestPanelUI/RolePanelUI already
        use)."""
        self.file_browser.x = self.x + 16
        self.file_browser.y = self.y + 60

        # Cartes custom deja sourcees du fichier charge -- juste sous la
        # liste de fichiers, meme colonne gauche (voir _load_image/
        # _load_existing_card_for_edit).
        self.existing_cards_browser.x = self.x + 16
        self.existing_cards_browser.y = self.file_browser.y + self.file_browser.height + 16
        self._new_card_rect = pygame.Rect(
            self.existing_cards_browser.x, self.existing_cards_browser.y + self.existing_cards_browser.height + 8,
            200, 32,
        )

        self.viewer_rect = pygame.Rect(self.x + 236, self.y + 60, self.VIEWER_WIDTH, self.VIEWER_HEIGHT)

        params_x = self.viewer_rect.right + 20
        step_w = 190

        self._mode_rects = {}
        row_x = params_x
        for mode_id, _label in self.MODES:
            rect = pygame.Rect(row_x, self.y + 60, 70, 32)
            self._mode_rects[mode_id] = rect
            row_x = rect.right + 4

        self.name_box.rect.x = params_x
        self.name_box.rect.y = self.y + 100

        self._width_stepper = Stepper(params_x, self.y + 146, 28, 50, 1, self.MAX_TILES)
        self._height_stepper = Stepper(params_x, self.y + 190, 28, 50, 1, self.MAX_TILES)

        # 3 archetypes now (Sol/Mur/Porte) share the same column width as
        # the 3 mode buttons above -- same narrow-width treatment (60px vs
        # the original 90px, "Porte" itself is a short label -- see
        # object_manager.ARCHETYPES).
        archetype_y = self.y + 234
        self._archetype_rects = {}
        row_x = params_x
        for archetype_id, preset in ARCHETYPES.items():
            rect = pygame.Rect(row_x, archetype_y, 60, 32)
            self._archetype_rects[archetype_id] = rect
            row_x = rect.right + 8

        # _blocks_rect doubles as the per-cell walkable grid's anchor once
        # the tile is multi-cell (see _cell_mode_grid_rects) -- the grid's
        # rendered footprint is capped to roughly this same ~140px
        # regardless of width_tiles/height_tiles, so a fixed gap before
        # _interactable_rect below is safe for any selection size.
        self._blocks_rect = pygame.Rect(params_x, self.y + 278, step_w, 32)
        self._interactable_rect = pygame.Rect(params_x, self.y + 430, step_w, 32)
        self._confirm_rect = pygame.Rect(params_x, self.y + 470, step_w, 40)
        self._close_rect = pygame.Rect(self.x + self.PANEL_WIDTH - 90, self.y + 12, 70, 28)

        # Mode "bitmap" -- reuses the same viewer_rect bounds for a tile
        # grid instead of a loaded image (see _bm_tile_rect); its own
        # separate rect set in the params column, since tuile/pack's
        # name_box/steppers/archetype rects don't apply here at all.
        self.pack_browser.x = self.x + 16
        self.pack_browser.y = self.y + 60

        # Check-list of reference shapes (FLOOR_REFERENCE_SHAPES/
        # WALL_REFERENCE_SHAPES) for the selected pack's role -- directly
        # below pack_browser in the same left column, same width.
        self.shape_browser.x = self.x + 16
        self.shape_browser.y = self.pack_browser.y + self.pack_browser.height + 16

        bm_toggle_y = self.y + 100
        self._bm_toggle_rects = {}
        row_x = params_x
        for key in ("assign", "variant"):
            rect = pygame.Rect(row_x, bm_toggle_y, 93, 32)
            self._bm_toggle_rects[key] = rect
            row_x = rect.right + 8

        # Spatial 3x3 preview -- center cell is the selected tile's own
        # thumbnail, the 4 cardinal cells are hover+scroll-editable (see
        # NEIGHBOR_GRID_POSITIONS/_handle_bitmap_wheel), the 4 corners are
        # decorative filler only (confirmed with the user: the bitmask
        # stays 4-directional everywhere, including the interior tileset --
        # showing all 8 keeps the layout visually a real neighborhood
        # without forking the data format).
        neighbor_y = self.y + 146
        grid_cell = 44
        grid_gap = 4
        grid_size = grid_cell * 3 + grid_gap * 2
        grid_x = params_x + (step_w - grid_size) // 2
        self._bm_grid_rects = {
            key: pygame.Rect(
                grid_x + col * (grid_cell + grid_gap), neighbor_y + row * (grid_cell + grid_gap),
                grid_cell, grid_cell,
            )
            for key, (row, col) in self.NEIGHBOR_GRID_POSITIONS.items()
        }

        mask_label_y = neighbor_y + grid_size + 6
        half_w = (step_w - 8) // 2
        self._bm_clear_rect = pygame.Rect(params_x, mask_label_y + 22, half_w, 32)
        self._bm_default_rect = pygame.Rect(self._bm_clear_rect.right + 8, mask_label_y + 22, half_w, 32)

        self._bm_save_rect = pygame.Rect(params_x, self._bm_default_rect.bottom + 12, step_w, 40)

    def _clamp_selection(self):
        if self.image is None:
            return
        img_w, img_h = self.image.get_size()
        sel_w = self.width_tiles * TILE_SIZE
        sel_h = self.height_tiles * TILE_SIZE
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

    def _load_image(self, filename):
        try:
            self.image = load_tileset_by_name(filename)
        except (pygame.error, FileNotFoundError):
            self.image = None
            self.status_text = f"Impossible de charger {filename}"
            return
        self.image_name = filename
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
        rect = config["asset"]["rect"]
        self._sel_x, self._sel_y = rect[0], rect[1]
        self.width_tiles, self.height_tiles = config.get("size", [1, 1])
        self.archetype = next(
            (aid for aid, preset in ARCHETYPES.items() if preset["placement"] == config.get("placement")),
            "sol",
        )
        self.cell_modes_grid = config.get("cell_modes")
        self.blocks_movement = config.get("blocks_movement", False)
        self.interactable = config.get("interactable", False)
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
        self.status_text = ""

    def _local_pos(self, screen_pos):
        """screen_pos, made relative to the viewer's own top-left -- the
        coordinate space Camera.screen_to_world/world_to_screen actually
        operate in here (see self.camera's own comment)."""
        return screen_pos[0] - self.viewer_rect.x, screen_pos[1] - self.viewer_rect.y

    def _move_selection_to(self, screen_pos):
        img_x, img_y = self.camera.screen_to_world(*self._local_pos(screen_pos))
        self._sel_x = round(img_x / TILE_SIZE) * TILE_SIZE
        self._sel_y = round(img_y / TILE_SIZE) * TILE_SIZE
        self._clamp_selection()

    # -- Mode "bitmap" --------------------------------------------------

    BM_TILE_CELL = 56
    BM_TILE_GAP = 6

    def _bm_columns(self):
        return max(1, (self.viewer_rect.width - 8) // (self.BM_TILE_CELL + self.BM_TILE_GAP))

    def _bm_tile_rect(self, index):
        columns = self._bm_columns()
        row, col = divmod(index, columns)
        return pygame.Rect(
            self.viewer_rect.x + 4 + col * (self.BM_TILE_CELL + self.BM_TILE_GAP),
            self.viewer_rect.y + 4 + row * (self.BM_TILE_CELL + self.BM_TILE_GAP),
            self.BM_TILE_CELL, self.BM_TILE_CELL,
        )

    def _bm_pack_payload(self):
        return load_autotile_pack(self.bm_pack_name) if self.bm_pack_name else None

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
        self._refresh_shape_browser()

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
        A no-op (empty list) with no pack selected."""
        payload = self._bm_pack_payload()
        if payload is None:
            self.shape_browser.set_rooms([])
            return
        shapes = self.WALL_REFERENCE_SHAPES if payload.get("role") == "wall" else self.FLOOR_REFERENCE_SHAPES
        assigned = self._bm_existing_bitmasks()
        entries = [
            (f"{shape} (deja assignee)" if shape in assigned else shape, shape)
            for shape in shapes
        ]
        self.shape_browser.set_rooms(entries)

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
            )
        except ValueError as exc:
            self.status_text = str(exc)
            return None

        self.status_text = f"'{raw_name}' mise a jour ({self.editing_type_id})."
        self._refresh_existing_cards()
        return None

    def _try_register_pack(self):
        """Pack mode: the current selection is a width_tiles x height_tiles
        GRID of separate 1x1 tiles (not one combined sprite) -- each cell
        is cropped and numbered independently. Never touches OBJECT_TYPES/
        the Card system (raw terrain tiles aren't placeable objects) and
        never returns a value Creator would act on -- see handle_event's
        confirm dispatch and ressources.save_autotile_pack's own docstring
        for why this is deliberately just extraction, no bitmask
        assignment."""
        if self.image is None:
            self.status_text = "Choisis d'abord un fichier."
            return None

        raw_name = self.name_box.value.strip()
        if not raw_name:
            self.status_text = "Donne un nom au pack."
            return None

        pack_name = self._sanitize_id(raw_name, set(list_autotile_packs()), fallback="pack")

        role = ARCHETYPES[self.archetype]["placement"]
        rects = [
            (self._sel_x + col * TILE_SIZE, self._sel_y + row * TILE_SIZE, TILE_SIZE, TILE_SIZE)
            for row in range(self.height_tiles)
            for col in range(self.width_tiles)
        ]

        save_autotile_pack(pack_name, role, self.image_name, rects)

        self.status_text = f"Pack '{raw_name}' enregistre ({len(rects)} tuiles, {pack_name})."
        self.name_box.value = ""
        return None

    def _handle_mode_switch(self, pos):
        """True (and switches self.mode) if `pos` hit a mode button --
        checked first by every mode's own event handling, since switching
        away must always be reachable no matter which mode is active."""
        for mode_id, rect in self._mode_rects.items():
            if rect.collidepoint(pos):
                if self.mode == "bitmap" and mode_id != "bitmap":
                    self._bm_auto_save_current()
                    self.bm_picking_variant_family = None
                self.mode = mode_id
                return True
        return False

    def _handle_bitmap_event(self, event):
        """Mode "bitmap"'s own event handling -- entirely separate from
        tuile/pack's chain below (their width/height stepper, archetype,
        and blocks-movement rects occupy overlapping screen positions with
        this mode's own controls, since all 3 modes share one params
        column -- dispatching here first, before any of those, is what
        keeps a bitmap-mode click from being misread as one of them)."""
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
            self.name_box.handle_event(event)
            return None

        if event.type == pygame.MOUSEWHEEL:
            if self.mode == "bitmap":
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
                self.mode == "tuile"
                and self.archetype == "sol"
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
            if selected is not None and selected != self.image_name:
                self._load_image(selected)
            return None

        if self.mode == "tuile" and self.existing_cards_browser.contains(event.pos):
            self.existing_cards_browser.handle_event(event)
            selected_id = self.existing_cards_browser.selected_name
            if selected_id is not None:
                self._load_existing_card_for_edit(selected_id)
            return None

        if self.mode == "tuile" and self.editing_type_id is not None and self._new_card_rect.collidepoint(event.pos):
            self._reset_to_new_card()
            return None

        for mode_id, rect in self._mode_rects.items():
            if rect.collidepoint(event.pos):
                self.mode = mode_id
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
            return None

        new_height = self._height_stepper.handle_click(event.pos, self.height_tiles)
        if new_height is not None:
            self.height_tiles = new_height
            self._clamp_selection()
            self._ensure_cell_modes_grid()
            return None

        for archetype_id, rect in self._archetype_rects.items():
            if rect.collidepoint(event.pos):
                self.archetype = archetype_id
                return None

        if self.mode == "tuile" and self.archetype == "sol":
            if self.width_tiles == 1 and self.height_tiles == 1:
                if self._blocks_rect.collidepoint(event.pos):
                    self.blocks_movement = not self.blocks_movement
                    return None
            else:
                for (row, col), rect in self._cell_mode_grid_rects().items():
                    if rect.collidepoint(event.pos):
                        self._cycle_cell_mode(row, col, 1)
                        return None

        if self.mode == "tuile" and self._interactable_rect.collidepoint(event.pos):
            self.interactable = not self.interactable
            return None

        if self._confirm_rect.collidepoint(event.pos):
            if self.mode == "pack":
                self._try_register_pack()
                return None
            if self.editing_type_id is not None:
                self._try_update_existing()
                return None
            return self._try_register()

        return None

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

        self.file_browser.render(screen)
        if self.mode == "tuile":
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

            if self.mode == "tuile":
                self._render_existing_card_markers(screen)
            elif self.mode == "pack":
                self._render_pack_region_markers(screen)

            sel_screen_x, sel_screen_y = self.camera.world_to_screen(self._sel_x, self._sel_y)
            sel_rect = pygame.Rect(
                self.viewer_rect.x + sel_screen_x,
                self.viewer_rect.y + sel_screen_y,
                self.width_tiles * TILE_SIZE * zoom,
                self.height_tiles * TILE_SIZE * zoom,
            )
            pygame.draw.rect(screen, (255, 220, 120), sel_rect, 2)
            if self.mode == "pack":
                # Internal grid lines -- makes "this is N separate 1x1
                # tiles, not one combined sprite" visible at a glance.
                tile_px = TILE_SIZE * zoom
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

        for archetype_id, rect in self._archetype_rects.items():
            label = ARCHETYPES[archetype_id]["label"]
            selected = archetype_id == self.archetype
            text = f"> {label}" if selected else label
            self.border.draw_centered_label(screen, rect, self.font, text, (255, 220, 120) if selected else (255, 255, 255))

        if self.mode == "tuile" and self.archetype == "sol":
            if self.width_tiles == 1 and self.height_tiles == 1:
                check_label = "[x] Bloque le mouvement" if self.blocks_movement else "[ ] Bloque le mouvement"
                self.border.draw_centered_label(screen, self._blocks_rect, self.font, check_label)
            else:
                self._render_cell_modes_grid(screen)

        if self.mode == "tuile":
            interact_label = "[x] Interagible" if self.interactable else "[ ] Interagible"
            self.border.draw_centered_label(screen, self._interactable_rect, self.font, interact_label)

        confirm_label = "Mettre a jour" if (self.mode == "tuile" and self.editing_type_id is not None) else "Enregistrer"
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
            rx, ry, rw, rh = config["asset"]["rect"]
            sx, sy = self.camera.world_to_screen(rx, ry)
            marker_rect = pygame.Rect(self.viewer_rect.x + sx, self.viewer_rect.y + sy, rw * zoom, rh * zoom)
            color = (255, 220, 120) if type_id == self.editing_type_id else (100, 180, 255)
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
        """The per-cell mode grid for a multi-cell "sol" selection (see
        _cell_mode_grid_rects/_ensure_cell_modes_grid) -- 3 states cycled by
        click or hover+scroll (_cycle_cell_mode): red "B" = bloquant, green
        "D" = ne bloque pas / derriere le joueur, blue "F" = ne bloque pas /
        devant le joueur (torch-style), each a compact label since cells
        can be as small as 16px."""
        if self.cell_modes_grid is None:
            return
        for (row, col), rect in self._cell_mode_grid_rects().items():
            mode = self.cell_modes_grid[row][col]
            color = self.CELL_MODE_COLORS.get(mode, self.CELL_MODE_COLORS["behind"])
            pygame.draw.rect(screen, color, rect)
            pygame.draw.rect(screen, (20, 20, 20), rect, 1)
            label = self.small_font.render(self.CELL_MODE_LABELS.get(mode, "?"), True, (20, 20, 20))
            screen.blit(label, (rect.centerx - label.get_width() / 2, rect.centery - label.get_height() / 2))

    def _render_bitmap(self, screen):
        """Mode "bitmap"'s own rendering -- pack picker + shape check-list
        on the left, the pack's tiles as a grid inside viewer_rect's bounds
        (instead of a loaded image), and either the 4 neighbor-cycling
        buttons (Motif) or the selected tile's variant family list
        (Variante), whichever self.bm_variant_mode currently selects."""
        self.pack_browser.render(screen)
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
                "Vert = motif/variante assigne(e)  |  Gris = vierge",
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
