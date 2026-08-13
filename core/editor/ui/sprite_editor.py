"""SpriteEditorPanelUI -- split out of the old monolithic core/editor/ui.py."""

import math
from pathlib import Path

import pygame

from core.ui.widgets import BorderManager, RoomBrowser, Stepper, TextInputBox
from core.world.object_manager import (
    OBJECT_TYPES, ARCHETYPES, register_custom_type, update_custom_type, delete_custom_type,
    custom_types_for_tileset, CELL_MODES,
    NPC_DIRECTIONS, register_npc_type, update_npc_type, npc_types_for_pack,
    rename_entity_pack_references, action_direction_coverage,
)
from core.data.ressources import (
    TILE_SIZE, load_tileset_by_name, load_tileset_region, save_autotile_pack, save_tileset_png,
    list_autotile_packs, load_autotile_pack, update_autotile_pack_tile, update_autotile_pack_tiles,
    get_autotile_pack_path, delete_autotile_pack, rename_autotile_pack, pack_references, type_references,
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
    pixel pres). Trois modes (self.mode, boutons _mode_rects) :
    - "decouper" : regroupe les deux comportements de recadrage/extraction
      qui n'ont jamais ete des handlers vraiment separes (ils partagent deja
      toute leur colonne de parametres et leur chaine handle_event/render,
      voir plus bas) -- un sous-toggle self.crop_kind (CROP_KINDS,
      _crop_kind_rects) choisit lequel est actif :
        - "tuile" : la selection est UN sprite (une carte) -- on regle nom/
          archetype/blocage, "Enregistrer" appelle object_manager.
          register_custom_type puis rend l'id du type nouvellement cree --
          Creator (le seul appelant) s'en sert pour crediter 1 exemplaire de
          la carte au profil actif et rafraichir CardPanelUI, meme geste que
          --give-card. Volontairement limite aux archetypes a une seule
          region (voir ARCHETYPES) -- torche/pilier restent hors scope, voir
          leur commentaire dans object_manager.py.
        - "pack" : la selection devient une grille de width_tiles x
          height_tiles tuiles 1x1 INDIVIDUELLES -- "Enregistrer" les extrait
          et numerote chacune separement dans un nouveau pack autotile
          (ressources.save_autotile_pack), sans les brancher sur
          AUTOTILE_LOOKUP : associer chaque tuile a son motif de voisins
          reste une etape manuelle separee, ce sous-mode automatise
          seulement le recadrage. Ne touche jamais OBJECT_TYPES/le systeme
          de Cartes (des tuiles de terrain brutes ne sont pas des objets
          placables) -- handle_event retourne toujours None pour ce
          sous-mode, Creator n'a rien a crediter.
    - "bitmap" : remplace la visionneuse de fichier par un choix de pack
      (self.pack_browser) + une grille de ses tuiles deja extraites. La
      tuile selectionnee gagne soit un bitmask (4 boutons Haut/Droite/Bas/
      Gauche, cycle Vide/Sol/Mur -- meme vocabulaire EMPTY/FLOOR/WALL que
      core.editor.autotile) soit un statut de variante (probabilite d'un
      bitmask deja assigne ailleurs dans le pack), via ressources.
      update_autotile_pack_tile. handle_event retourne toujours None ici
      aussi -- Creator resynchronise juste le donjon ouvert si le pack
      modifie est son theme actif (voir _try_save_bitmap_tile). Reste
      independant de "decouper" pour l'instant -- pourrait un jour s'y
      repartir (avec la Forge), pas encore tranche.
    - "peindre" (ex-"pixel", pur renommage -- identifiants internes
      _handle_pixel_event/_render_pixel/_px_* inchanges) : le seul mode qui
      touche vraiment aux pixels -- un outil type Paint rudimentaire
      (pinceau avec roue de couleur + taille, pipette, selection
      rectangulaire au clique-glisse, copier/couper/coller au clavier,
      annuler) sur le fichier PNG charge (n'importe lequel sous assets/, pas
      seulement assets/tiles/ -- voir _file_browser_root == ""), ou sur une
      toile vierge nouvellement creee (voir _px_new_canvas_create, ecrite
      sous assets/tiles/custom_sprites/). "Enregistrer" ecrase le fichier
      source en place (pygame.image.save via ressources.save_tileset_png)
      -- confirme avec l'utilisateur : pas de sauvegarde automatique par
      trait, contrairement au mode bitmap, une ecriture PNG est plus
      couteuse et plus destructive qu'une simple fusion JSON. handle_event
      retourne toujours None -- ce mode ne credite jamais de nouvelle
      Carte, il ne fait que produire/modifier le PNG source qu'un passage
      en mode "decouper" saura ensuite recadrer/tagger.

    Camera de la visionneuse (self.camera, core.engine.camera.Camera) :
    clic molette maintenu = pan, molette = zoom ancre sur le curseur --
    meme mecanique que la vue de room de Creator, appliquee a une image
    statique plutot qu'a une grille de Dungeon.
    """

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
    MODES = (("decouper", "Decouper"), ("peindre", "Peindre"), ("bitmap", "Bitmap"))

    # Mode "decouper" -- sous-toggle entre les deux anciens comportements
    # "tuile" (une seule carte placable) et "pack" (grille de tuiles
    # individuelles extraites) qu'il regroupe desormais. Reprend
    # exactement le vocabulaire des anciens ids de mode -- toute la chaine
    # partagee tuile/pack plus bas teste self.crop_kind au lieu de
    # self.mode, sans autre changement de comportement.
    CROP_KINDS = (("tuile", "Tuile"), ("pack", "Pack"))

    # Mode "peindre" (ex-"pixel") -- outils/roue de couleur.
    PX_TOOLS = (("brush", "Pinceau"), ("eyedropper", "Pipette"), ("select", "Selection"))
    PX_MAX_BRUSH_SIZE = 16
    PX_UNDO_LIMIT = 20
    PX_WHEEL_SIZE = 120
    PX_VALUE_SLIDER_HEIGHT = 120
    PX_NEW_CANVAS_DIR = "tiles/custom_sprites"
    PX_NEW_CANVAS_MIN = 8
    PX_NEW_CANVAS_MAX = 256

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
        self._door_frame_thumb_rects = {}
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

        # 3 boutons (Decouper/Peindre/Bitmap, voir MODES) -- largeur
        # d'origine 70px (3*70+2*4=218 tient dans les ~224px disponibles
        # entre params_x et le bord droit du panneau).
        self._mode_rects = {}
        row_x = params_x
        for mode_id, _label in self.MODES:
            rect = pygame.Rect(row_x, self.y + 60, 70, 32)
            self._mode_rects[mode_id] = rect
            row_x = rect.right + 4

        # Sous-toggle Tuile/Pack du mode "decouper" (voir CROP_KINDS) --
        # meme gabarit que _pack_kind_rects plus bas (93px chacun). En tete
        # de la colonne de parametres partagee tuile/pack, ce qui decale
        # tout le reste (name_box et en dessous) de +44px par rapport a
        # avant ce regroupement -- meme delta ajoute a PANEL_HEIGHT.
        self._crop_kind_rects = {}
        row_x = params_x
        for kind_id, _label in self.CROP_KINDS:
            rect = pygame.Rect(row_x, self.y + 100, 93, 32)
            self._crop_kind_rects[kind_id] = rect
            row_x = rect.right + 4

        self.name_box.rect.x = params_x
        self.name_box.rect.y = self.y + 144

        self._width_stepper = Stepper(params_x, self.y + 190, 28, 50, 1, self.MAX_TILES)
        self._height_stepper = Stepper(params_x, self.y + 234, 28, 50, 1, self.MAX_TILES)

        # 3 archetypes now (Sol/Mur/Porte) share the same column width as
        # the 3 mode buttons above -- same narrow-width treatment (60px vs
        # the original 90px, "Porte" itself is a short label -- see
        # object_manager.ARCHETYPES).
        archetype_y = self.y + 278
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
        self._blocks_rect = pygame.Rect(params_x, self.y + 322, step_w, 32)
        self._interactable_rect = pygame.Rect(params_x, self.y + 474, step_w, 32)

        # crop_kind "pack" only -- Autotile (comportement d'origine, utilise
        # archetype_rects ci-dessus pour le role Sol/Mur) vs Entite (feuille
        # de personnage/PNJ, voir pack_kind) -- meme emplacement que
        # _blocks_rect ci-dessus, jamais utilise par crop_kind "pack"
        # lui-meme, donc aucun chevauchement reel malgre le meme y.
        self._pack_kind_rects = {}
        row_x = params_x
        for kind_id, _label in (("autotile", "Autotile"), ("entite", "Entite")):
            rect = pygame.Rect(row_x, self.y + 322, 93, 32)
            self._pack_kind_rects[kind_id] = rect
            row_x = rect.right + 4
        # Taille de cellule (px, feuille source) pour le decoupage en grille
        # d'un pack Entite -- 32 par defaut (voir entity_tile_size), une
        # feuille de personnage n'est quasiment jamais gridee sur 16px comme
        # le tileset interieur (TILE_SIZE) que le mode Autotile utilise.
        self._entity_tile_size_stepper = Stepper(params_x, self.y + 366, 28, 50, 8, 128)

        # Archetype "porte" only, below _interactable_rect -- see
        # _try_register/handle_event/render's own archetype gates. Frame
        # thumbnails (see _door_frame_thumb_rects) start right below the
        # stepper and can wrap onto a 2nd row up to MAX_DOOR_FRAMES -- the
        # gap to _confirm_rect below leaves room for that.
        self._lockable_rect = pygame.Rect(params_x, self.y + 514, step_w, 32)
        self._door_frames_stepper = Stepper(params_x, self.y + 556, 28, 50, 1, self.MAX_DOOR_FRAMES)

        self._confirm_rect = pygame.Rect(params_x, self.y + 660, step_w, 40)
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

        # Entity-kind packs show this instead of shape_browser (see
        # _render_entity_bitmap) -- same slot, never both visible at once,
        # same "no real overlap" precedent as _pack_kind_rects sharing
        # _blocks_rect's position.
        self._npc_existing_browser.x = self.x + 16
        self._npc_existing_browser.y = self.pack_browser.y + self.pack_browser.height + 16

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

        # Mode "pixel" -- own params column, entirely self-contained
        # (_handle_pixel_event/_render_pixel both early-return before ever
        # reaching tuile/pack/bitmap's own rect chains, same precedent as
        # mode "bitmap" -- see handle_event/render's top dispatch), so
        # sharing y-offsets with tuile/pack/bitmap's own rects below is
        # safe: never rendered/hit-tested at the same time. Two sub-states
        # that ARE mutually exclusive WITHIN this mode (see
        # _px_new_canvas_open) deliberately share slots too, same "no real
        # overlap" precedent _pack_kind_rects already established.
        px_top_y = self.y + 100
        tool_gap = 5
        tool_w = (step_w - tool_gap * (len(self.PX_TOOLS) - 1)) // len(self.PX_TOOLS)
        self._px_tool_rects = {}
        row_x = params_x
        for tool_id, _label in self.PX_TOOLS:
            self._px_tool_rects[tool_id] = pygame.Rect(row_x, px_top_y, tool_w, 32)
            row_x += tool_w + tool_gap
        self._px_new_rect = pygame.Rect(params_x, px_top_y + 40, step_w, 32)

        # Brush size (tool "brush") and the new-canvas name/width slot
        # (_px_new_canvas_open) never show at once -- same rect.
        self._px_brush_stepper = Stepper(params_x, px_top_y + 80, 28, 50, 1, self.PX_MAX_BRUSH_SIZE)
        self._px_new_width_stepper = Stepper(
            params_x, px_top_y + 124, 28, 50, self.PX_NEW_CANVAS_MIN, self.PX_NEW_CANVAS_MAX,
        )
        self._px_new_height_stepper = Stepper(
            params_x, px_top_y + 168, 28, 50, self.PX_NEW_CANVAS_MIN, self.PX_NEW_CANVAS_MAX,
        )
        px_half = (step_w - 8) // 2
        self._px_create_rect = pygame.Rect(params_x, px_top_y + 208, px_half, 32)
        self._px_cancel_new_rect = pygame.Rect(self._px_create_rect.right + 8, px_top_y + 208, px_half, 32)

        wheel_x = params_x + (step_w - self.PX_WHEEL_SIZE) // 2
        self._px_wheel_rect = pygame.Rect(wheel_x, px_top_y + 124, self.PX_WHEEL_SIZE, self.PX_WHEEL_SIZE)
        self._px_value_rect = pygame.Rect(
            self._px_wheel_rect.right + 8, self._px_wheel_rect.y, 24, self.PX_VALUE_SLIDER_HEIGHT,
        )
        self._px_swatch_rect = pygame.Rect(params_x, self._px_wheel_rect.bottom + 8, 48, 28)

        self._px_save_rect = pygame.Rect(params_x, px_top_y + 330, step_w, 40)
        self._px_undo_rect = pygame.Rect(params_x, px_top_y + 378, step_w, 32)

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

    def _local_pos(self, screen_pos):
        """screen_pos, made relative to the viewer's own top-left -- the
        coordinate space Camera.screen_to_world/world_to_screen actually
        operate in here (see self.camera's own comment)."""
        return screen_pos[0] - self.viewer_rect.x, screen_pos[1] - self.viewer_rect.y

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

    # -- Mode "bitmap" --------------------------------------------------

    BM_TILE_CELL = 56
    BM_TILE_GAP = 6

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
        _handle_entity_bitmap_event's action/direction/order tagging."""
        return (self._bm_pack_payload() or {}).get("kind", "autotile")

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

    def _try_delete_pack(self, pack_name):
        """on_delete callback for pack_browser (see __init__). Refuses
        with an explanation instead of deleting outright when the pack is
        still used as a room/dungeon's terrain theme (ressources.
        pack_references) or by a registered PNJ's entity_pack
        (npc_types_for_pack) -- same protective spirit as
        _try_delete_card/_try_delete_npc, just two kinds of reference
        instead of one."""
        used_in = pack_references(pack_name)
        used_by_npcs = [type_id for type_id, _config in npc_types_for_pack(pack_name)]
        if used_in or used_by_npcs:
            parts = []
            if used_in:
                parts.append(", ".join(used_in))
            if used_by_npcs:
                parts.append("PNJ : " + ", ".join(used_by_npcs))
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

    def _refresh_npc_existing(self):
        """Repopulates _npc_existing_browser with every PNJ type already
        registered from the current pack -- entity-kind counterpart of
        _refresh_existing_cards, called on pack selection and again after a
        successful register/update. Empty (no pack, or an autotile pack) is
        a valid, harmless state."""
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
        if config is None or not config.get("npc"):
            return
        self._npc_editing_type_id = type_id
        self.name_box.value = config.get("name", type_id)
        wander = config.get("wander_actions", {})
        self._npc_idle_action = wander.get("idle")
        self._npc_move_action = wander.get("move")
        self._npc_sitting_action = wander.get("sitting")
        self._npc_laying_action = wander.get("laying")
        self._npc_run_action = wander.get("run")
        self.status_text = f"Edition du PNJ '{self.name_box.value}' ({type_id})."

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
        """which is "idle"/"move" (required -- Npc's minimal fallback
        behavior needs both) or "sitting"/"laying"/"run" (optional --
        each independently enables its own portion of the move <->
        [sitting] <-> sit <-> [laying] <-> lie chain, see core.world.
        entities.Npc's own class docstring; pass allow_none=True so the
        cycle can land on "no action" for a PNJ that doesn't use it).
        Cycles through the pack's own distinct tagged action names (a
        closed choice, unlike the free-text action box used for tagging
        itself). Starts at the first available option the first time
        either is touched, since every one of these starts at None."""
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
        (None, None) if no such tile has been tagged yet."""
        payload = self._bm_pack_payload() or {}
        for tile in payload.get("tiles", []):
            if (
                tile.get("action") == self._npc_idle_action
                and tile.get("direction") == self._bm_entity_direction
                and tile.get("order") == 0
            ):
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
        """The wander_actions dict register_npc_type/update_npc_type expect
        -- "idle"/"move" always present (required, see Npc's own class
        docstring for why), "sitting"/"laying"/"run" only included when
        actually chosen (each independently optional, left unset means
        "not used" rather than an empty string -- core.world.entities.Npc.
        _has_action treats a missing key exactly like one that names an
        untagged action)."""
        wander = {"idle": self._npc_idle_action, "move": self._npc_move_action}
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
        """"Enregistrer comme PNJ" -- same return contract as _try_register
        (the new type_id, so Creator credits a card for it) or None+
        status_text on failure. Reuses self.name_box for the PNJ's own
        display name (bitmap mode never otherwise shows it)."""
        if self.bm_pack_name is None:
            self.status_text = "Choisis d'abord un pack."
            return None
        raw_name = self.name_box.value.strip()
        if not raw_name:
            self.status_text = "Donne un nom au PNJ."
            return None
        if self._npc_idle_action is None or self._npc_move_action is None:
            self.status_text = "Choisis une action idle et une action move (tague au moins une action d'abord)."
            return None

        duplicate_id = self._find_custom_type_by_name(raw_name)
        if duplicate_id is not None:
            self.status_text = f"'{raw_name}' existe deja ({duplicate_id})."
            return None

        icon_rect, icon_tileset = self._npc_icon_rect()
        if icon_rect is None:
            self.status_text = "Tague une tuile d'ordre 0 pour l'action idle et la direction courante (icone)."
            return None

        type_id = self._sanitize_id(raw_name, OBJECT_TYPES, fallback="pnj")
        try:
            register_npc_type(
                type_id, raw_name, self.bm_pack_name, icon_tileset, icon_rect,
                (1, 1), self._npc_wander_actions(),
            )
        except ValueError as exc:
            self.status_text = str(exc)
            return None

        self.status_text = f"'{raw_name}' enregistre comme PNJ ({type_id})."
        self.name_box.value = ""
        self._npc_editing_type_id = None
        self._refresh_npc_existing()
        return type_id

    def _try_update_npc(self):
        """Register button's action while self._npc_editing_type_id is set --
        rewrites that PNJ's definition in place via update_npc_type instead
        of creating a new one. Never returns a value for Creator to grant a
        card for (the type already exists, presumably already owned)."""
        raw_name = self.name_box.value.strip()
        if not raw_name:
            self.status_text = "Donne un nom au PNJ."
            return None
        if self._npc_idle_action is None or self._npc_move_action is None:
            self.status_text = "Choisis une action idle et une action move."
            return None

        duplicate_id = self._find_custom_type_by_name(raw_name)
        if duplicate_id is not None and duplicate_id != self._npc_editing_type_id:
            self.status_text = f"'{raw_name}' est deja pris par {duplicate_id}."
            return None

        icon_rect, icon_tileset = self._npc_icon_rect()
        if icon_rect is None:
            self.status_text = "Tague une tuile d'ordre 0 pour l'action idle et la direction courante (icone)."
            return None

        try:
            update_npc_type(
                self._npc_editing_type_id, raw_name, self.bm_pack_name, icon_tileset, icon_rect,
                (1, 1), self._npc_wander_actions(),
            )
        except ValueError as exc:
            self.status_text = str(exc)
            return None

        self.status_text = f"'{raw_name}' mis a jour ({self._npc_editing_type_id})."
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
        shared params column anchor every other mode/kind already uses."""
        params_x = self._bm_toggle_rects["assign"].x
        step_w = self._confirm_rect.width
        top_y = self.y + 100
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

    # -- Mode "pixel" -----------------------------------------------------

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
        return value in tuile mode."""
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

    def _render_bitmap(self, screen):
        """Mode "bitmap"'s own rendering -- pack picker + shape check-list
        on the left, the pack's tiles as a grid inside viewer_rect's bounds
        (instead of a loaded image), and either the 4 neighbor-cycling
        buttons (Motif) or the selected tile's variant family list
        (Variante), whichever self.bm_variant_mode currently selects.

        Delegates to _render_entity_bitmap once a loaded pack is entity-
        kind -- entirely different screen (action/direction tagging + PNJ
        registration instead of bitmask/variant editing)."""
        self.pack_browser.render(screen)
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

    def _render_entity_bitmap(self, screen):
        """The whole bitmap-mode screen once an entity-kind pack is loaded --
        replaces shape_browser (autotile-only reference shapes) with
        _npc_existing_browser, and the tile grid's own coloring/selection
        with the action/direction/order tagging flow (see
        _handle_entity_bitmap_event)."""
        self._npc_existing_browser.render(screen)
        if not self._npc_existing_browser.rooms:
            hint = self.small_font.render(
                "Aucun PNJ enregistre depuis ce pack.", True, (180, 180, 180),
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

        name_label = self.small_font.render("Nom du PNJ", True, (200, 200, 200))
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

        register_label = "Mettre a jour le PNJ" if self._npc_editing_type_id is not None else "Enregistrer comme PNJ"
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
