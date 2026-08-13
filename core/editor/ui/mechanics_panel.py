"""MechanicsPanelUI -- the "mechanical" counterpart to SpriteEditorPanelUI.

Where SpriteEditorPanelUI owns a custom type's visual/identity data (asset/
name/size/frames), this panel owns its gameplay flags (blocks_movement/
cell_modes/interactable/lockable), capacites (throwable/explosive), effets
(heal today), and -- for an enemy mob -- its stats (PV/vitesse/aggro/portee/
loot). Confirmed split with the user, framed as the long-term "Artiste"
(sprite editor) vs "Forgeron" (this panel) divide, though no NPC/dialogue
gating exists yet: reachable today by dragging an owned card from
CardPanelUI directly onto this panel's own body (wrapped in a PanelFrame
titled "Forge" -- see Creator.__init__/the drop handling in Creator.run()).

Docked/draggable/resizable exactly like CardPanelUI/GeneratorPanelUI, NOT
modal -- a dropped card stays loaded and editable at leisure, without
blocking the rest of the editor. "Empty" (nothing dropped yet) vs "populated"
is read directly off self.type_id/self.item_id (mutually exclusive -- a
dropped card is either an OBJECT_TYPES entry or an ITEM_DEFINITIONS entry,
never both), no separate open/active flag.

Built-in OBJECT_TYPES entries are fully in scope for the gameplay-flag half
(see object_manager.update_type_mechanics -- the dict-asset guard only
applies to the VISUAL half, SpriteEditorPanelUI's domain): open() only
refuses a room card or an unknown id. Persists through update_type_mechanics
(OBJECT_TYPES entries), or -- for an ITEM_DEFINITIONS entry -- either
update_item_overrides (a builtin item like dynamite: mechanics-only, same
split as OBJECT_TYPES) or update_item (a custom item like a Potion de soin:
full entry, the item equivalent of update_custom_type). Never touches
asset/name/size/frames/archetype/icon, which stay whatever SpriteEditorPanelUI
(or, for a builtin, the Python source) already set.

Capacites/Effets are shown for item, mob, AND pnj cards (not a plain
decorative/special object -- nothing reads a world object's "capabilities"/
"effects" yet, so a control there would silently do nothing). Enregistrer
is available for every card kind now that mob/pnj have something real to
save too.

**Unified preview** (_render_preview/_preview_current_frames/
_preview_state_options): a single animated preview area replaces what used
to be a permanently-static 48x48 icon shown regardless of card kind.
- PNJ: tabs for whichever wander_actions role is configured, a looping
  animation of that role's tagged sprite for the selected direction (see
  object_manager.load_npc_frames/NPC_DIRECTIONS), and click-drag directly
  on the preview to cycle through directions (_pnj_dragging_direction/
  _update_pnj_drag) -- the only card kind with a direction concept at all.
- Mob: tabs for its fixed animation set (ENEMY_ANIMATIONS for an enemy,
  idle/move for an animal), looping through object_manager.load_enemy_frames/
  load_animal_frames.
- Plain object with more than one frame (torch, lilchest...): no tabs, just
  an automatic loop through object_manager.load_object_frames.
- Item: a single static frame (its own icon) -- nothing to loop.
update(dt) advances preview_frame whenever the current selection has more
than one frame, called every frame from Creator.run() regardless of what's
loaded (a no-op otherwise) -- the one thing in this panel that needs real
elapsed time rather than just reacting to a click.

Mob stats editing (_render_mob_stats_editing) is enemy-only -- animals
carry no stats at all. active_attack_frames (the attack swing's damage
window) is never exposed to editing, passed through unchanged on save so a
stats edit can't silently break combat timing. No write API exists for a
PNJ's entity_pack/wander_actions, or for creating a new mob type -- those
stay SpriteEditorPanelUI's job / unbuilt, respectively.
"""

import pygame

from core.editor.ui.mixins import _ResizableCornerMixin
from core.ui.widgets import BorderManager, Stepper
from core.world.object_manager import (
    OBJECT_TYPES, ITEM_DEFINITIONS, ARCHETYPES, CELL_MODES, ENEMY_ANIMATIONS, CURRENCY_FILES,
    NPC_DIRECTIONS, load_npc_frames, load_enemy_frames, load_animal_frames, load_object_frames,
    action_direction_coverage,
    update_type_mechanics, update_item_overrides, update_item, is_builtin_item,
)
from core.data.cards import resolve_card_sprite

CELL_MODES_ARCHETYPES = ("sol", "mur", "porte")


class MechanicsPanelUI(_ResizableCornerMixin):
    STANDARD_WIDTH = 420
    STANDARD_HEIGHT = 920
    MAX_WIDTH = 900
    MAX_HEIGHT = 1050
    CELL_MODE_COLORS = {"block": (190, 90, 90), "behind": (110, 190, 110), "front": (100, 150, 220)}
    GRID_MAX_PX = 140
    STEP_BUTTON_SIZE = 24
    COUNT_DISPLAY_WIDTH = 50
    # Canonical role order for the PNJ preview's tabs -- only roles actually
    # present in a given PNJ's own wander_actions are shown (see
    # _pnj_available_roles), same "idle"/"move" mandatory + "sitting"/
    # "laying"/"run" independently optional split as core.world.entities.Npc
    # itself documents.
    PNJ_ROLES = ("idle", "move", "sitting", "laying", "run")
    PREVIEW_ANIMATION_SPEED = 0.2  # matches core.world.entities.Npc.ANIMATION_SPEED
    PNJ_DRAG_STEP_PX = 24  # horizontal pixels dragged per direction step

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.width = self.STANDARD_WIDTH
        self.height = self.STANDARD_HEIGHT
        self._resizing = False
        self._resize_last_pos = None

        self.type_id = None
        self.item_id = None
        self.name = ""
        self.icon = None

        # Reconstructed from the loaded config, passed straight through to
        # update_type_mechanics/update_item unchanged -- this panel never
        # edits any of these, only the mechanical flags/capacites/effets/
        # stats below. item_slot/icon_path/icon_rect only ever populated for
        # an item card (self.item_id set); tileset/rect/frame_rects/size/
        # archetype only for an object card (self.type_id set).
        self.tileset = None
        self.rect = None
        self.frame_rects = None
        self.size = (1, 1)
        self.archetype = "sol"
        self.item_slot = None
        self.icon_path = None
        self.icon_rect = None

        # The actual editable state -- plain (non-mob, non-pnj) OBJECT_TYPES
        # cards only (self.type_id).
        self.blocks_movement = False
        self.cell_modes_grid = None
        self.interactable = False
        self.lockable = False

        # Mob (animal/enemy) cards are OBJECT_TYPES entries too, but none of
        # the fields above apply to one (a mob was showing the exact same
        # "Bloque le mouvement"/"Interagible" checkboxes as a decorative
        # floor object, which made no sense) -- Type/Etats info instead
        # (_render_mob_info), plus real stats editing for an enemy (see
        # mob_health and friends below, _render_mob_stats_editing).
        self.is_mob = False
        self.mob_kind = None
        self.mob_states = ()
        self.mob_stats = {}
        self.mob_health = 1
        self.mob_move_speed = 10
        # aggro_range/attack_range are floats in the underlying data (e.g.
        # 6.0/1.2) but Stepper is integer-only -- mob_aggro_range/
        # mob_attack_range are the rounded, EDITABLE integers shown by the
        # steppers, while _mob_*_range_raw keeps the exact original value
        # so _try_save can pass it straight through UNCHANGED whenever the
        # user never actually touched that stepper (comparing the rounded
        # display value against round(raw)) -- without this, saving for any
        # OTHER reason (e.g. just toggling a capability) would silently
        # round-trip attack_range from 1.2 to 1 every single time.
        self.mob_aggro_range = 1
        self._mob_aggro_range_raw = 1
        self.mob_attack_range = 1
        self._mob_attack_range_raw = 1
        self.mob_loot = {}
        self.mob_item_loot = {}

        # PNJ cards get their own info branch (is_pnj/open/_render_pnj_info)
        # -- entity-pack data (nested by action THEN direction, unlike the
        # flat per-state dict mob/object previews use, see
        # _preview_current_frames) plus the one interactive, non-editing
        # feature in this panel: click-drag on the preview to rotate
        # direction (_pnj_dragging_direction/_update_pnj_drag). No write API
        # exists here for entity_pack/wander_actions, that stays
        # SpriteEditorPanelUI's job.
        self.is_pnj = False
        self.pnj_entity_pack = None
        self.pnj_wander_actions = {}
        self.pnj_frames = {}
        self.pnj_direction = NPC_DIRECTIONS[0]
        self._pnj_dragging_direction = False
        self._pnj_drag_last_pos = None

        # Shared preview state -- see module docstring's "Unified preview"
        # section. preview_state is a role (PNJ)/animation name (mob)/None
        # (plain object or item, nothing to choose). _preview_frames is
        # {state: [Surface,...]} for a mob, a flat [Surface,...] for a
        # plain object or item -- PNJ keeps using pnj_frames/pnj_direction
        # instead (its own nested-by-direction shape), see
        # _preview_current_frames's dispatch.
        self.preview_state = None
        self._preview_frames = []
        self.preview_frame = 0
        self.preview_animation_timer = 0.0

        # Capacites/Effets -- item/mob/pnj cards, see module docstring.
        # "capabilities"/"effects" vocabulary is the same one
        # object_manager/cards.py already use.
        self.throwable_enabled = False
        self.throw_speed = 220
        self.explosive_enabled = False
        self.blast_radius_tiles = 2
        self.blast_damage = 1
        self.heal_enabled = False
        self.heal_amount = 1

        self.status_text = ""
        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 16)
        self.small_font = pygame.font.SysFont("arial", 13)

        self._blocks_rect = None
        self._interactable_rect = None
        self._lockable_rect = None
        self._throwable_rect = None
        self._explosive_rect = None
        self._heal_rect = None
        self._save_rect = None
        self._clear_rect = None
        self.preview_rect = None
        self._layout()

    def move(self, dx, dy):
        """See PanelFrame, which drives this via drag/restore -- _layout()
        is already a full re-derivation from self.x/self.y/self.width, so
        just updating the origin and re-running it is simpler and less
        error-prone than moving each cached rect individually."""
        self.x += dx
        self.y += dy
        self._layout()

    def contains(self, pos):
        return pygame.Rect(self.x, self.y, self.width, self.height).collidepoint(pos)

    def open(self, card_id):
        """Loads `card_id`'s current mechanical flags/capacites/stats for
        editing -- stays empty (self.type_id/self.item_id untouched) for a
        room card or an unknown id, the only two kinds this panel can't do
        anything with. An ITEM_DEFINITIONS id (self.item_id) and an
        OBJECT_TYPES id (self.type_id) are mutually exclusive and checked
        first/second respectively -- no id is ever both."""
        self.preview_frame = 0
        self.preview_animation_timer = 0.0

        item_def = ITEM_DEFINITIONS.get(card_id)
        if item_def is not None:
            self.item_id = card_id
            self.type_id = None
            self.name = item_def.get("name", card_id)
            self.icon = resolve_card_sprite(card_id)
            self.item_slot = item_def.get("slot", "interact")
            self.icon_path = item_def.get("icon_path")
            self.icon_rect = item_def.get("icon_rect")
            self.tileset = None
            self.rect = None
            self.frame_rects = None
            self.size = (1, 1)
            self.archetype = None
            self.blocks_movement = False
            self.cell_modes_grid = None
            self.interactable = False
            self.lockable = False
            self.is_mob = False
            self.is_pnj = False
            self.preview_state = None
            self._preview_frames = [self.icon] if self.icon else []
            self._load_capabilities(item_def.get("capabilities", {}))
            self._load_effects(item_def.get("effects", []))
            self.status_text = ""
            return

        config = OBJECT_TYPES.get(card_id)
        if config is None:
            return

        self.type_id = card_id
        self.item_id = None
        self.name = config.get("name", card_id)
        self.icon = resolve_card_sprite(card_id)

        self.is_mob = bool(config.get("animal") or config.get("enemy"))
        if self.is_mob:
            self.mob_kind = "enemy" if config.get("enemy") else "animal"
            # Fixed sets -- animal/enemy are always fully hand-authored
            # Python entries, never partially registered like a custom
            # PNJ, so there's no per-card variation to read here, unlike
            # config.get("stats") below (skeleton1 vs skeleton2 differ).
            self.mob_states = ENEMY_ANIMATIONS if self.mob_kind == "enemy" else ("idle", "move")
            self.mob_stats = config.get("stats", {})
            if self.mob_kind == "enemy":
                self.mob_health = self.mob_stats.get("health", 1)
                self.mob_move_speed = self.mob_stats.get("move_speed", 10)
                self._mob_aggro_range_raw = self.mob_stats.get("aggro_range", 1)
                self.mob_aggro_range = round(self._mob_aggro_range_raw)
                self._mob_attack_range_raw = self.mob_stats.get("attack_range", 1)
                self.mob_attack_range = round(self._mob_attack_range_raw)
                self.mob_loot = dict(self.mob_stats.get("loot", {}))
                self.mob_item_loot = dict(self.mob_stats.get("item_loot", {}))
                self._preview_frames = load_enemy_frames(card_id)
            else:
                self._preview_frames = load_animal_frames(card_id)
            self.preview_state = self.mob_states[0] if self.mob_states else None
        else:
            self.mob_kind = None
            self.mob_states = ()
            self.mob_stats = {}

        self.is_pnj = bool(config.get("npc"))
        if self.is_pnj:
            self.pnj_entity_pack = config.get("entity_pack")
            self.pnj_wander_actions = dict(config.get("wander_actions", {}))
            self.pnj_frames = load_npc_frames(self.pnj_entity_pack) if self.pnj_entity_pack else {}
            self.pnj_direction = NPC_DIRECTIONS[0]
            self._pnj_dragging_direction = False
            roles = self._pnj_available_roles()
            self.preview_state = roles[0] if roles else None
        else:
            self.pnj_entity_pack = None
            self.pnj_wander_actions = {}
            self.pnj_frames = {}

        if not self.is_mob and not self.is_pnj:
            self.preview_state = None
            self._preview_frames = load_object_frames(card_id)

        asset = config["asset"]
        if isinstance(asset, dict):
            if "rects" in asset:
                self.frame_rects = [list(r) for r in asset["rects"]]
                self.rect = self.frame_rects[0]
            else:
                self.frame_rects = None
                self.rect = asset["rect"]
            self.tileset = asset["tileset"]
        else:
            # A built-in's asset is its own dedicated sprite sheet path, not
            # a tileset crop -- this panel never edits it (that stays
            # SpriteEditorPanelUI's job, still gated to custom types only,
            # see update_type_visual), so these just stay at a harmless
            # default. _try_save only ever calls update_type_mechanics,
            # which ignores tileset/rect/frame_rects entirely.
            self.tileset = None
            self.rect = None
            self.frame_rects = None
        self.size = tuple(config.get("size", [1, 1]))
        self.archetype = next(
            (aid for aid, preset in ARCHETYPES.items() if preset["placement"] == config.get("placement")),
            "sol",
        )

        self.blocks_movement = config.get("blocks_movement", False)
        self.interactable = config.get("interactable", False)
        self.lockable = bool(config.get("blocks_until_open"))
        saved_cell_modes = config.get("cell_modes")
        width_tiles, height_tiles = self.size
        if saved_cell_modes is not None:
            self.cell_modes_grid = [list(row) for row in saved_cell_modes]
        elif width_tiles == 1 and height_tiles == 1:
            self.cell_modes_grid = None
        else:
            # Same fallback as SpriteEditorPanelUI._load_existing_card_for_
            # edit: a multi-cell card with no saved cell_modes at all (never
            # had blocks_movement/cell_modes set at creation) gets a fresh
            # all-"behind" grid rather than staying None forever.
            self.cell_modes_grid = [["behind"] * width_tiles for _ in range(height_tiles)]

        self._load_capabilities(config.get("capabilities", {}))
        self._load_effects(config.get("effects", []))
        self.status_text = ""

    def _load_capabilities(self, capabilities):
        throwable = capabilities.get("throwable")
        self.throwable_enabled = throwable is not None
        self.throw_speed = (throwable or {}).get("speed", 220)
        explosive = capabilities.get("explosive")
        self.explosive_enabled = explosive is not None
        self.blast_radius_tiles = (explosive or {}).get("radius_tiles", 2)
        self.blast_damage = (explosive or {}).get("damage", 1)

    def _load_effects(self, effects):
        heal = next((effect for effect in effects if effect.get("kind") == "heal"), None)
        self.heal_enabled = heal is not None
        self.heal_amount = (heal or {}).get("amount", 1)

    def _pnj_available_roles(self):
        """PNJ_ROLES filtered to the ones this PNJ's own wander_actions
        actually names (an optional role like "run" simply isn't in the
        dict if never configured) -- these are the only tabs shown, same
        "don't offer what isn't there" spirit as CELL_MODES_ARCHETYPES'
        own per-archetype gating above."""
        return [role for role in self.PNJ_ROLES if role in self.pnj_wander_actions]

    def _preview_state_options(self):
        """(state_id, label) pairs for the current card's selectable
        preview states -- empty if there's nothing to choose (a plain
        object's single automatic loop, or a static item icon)."""
        if self.is_pnj:
            return [(role, role) for role in self._pnj_available_roles()]
        if self.is_mob:
            return [(state, state) for state in self.mob_states]
        return []

    def _select_preview_state(self, state_id):
        self.preview_state = state_id
        self.preview_frame = 0
        self.preview_animation_timer = 0.0

    def _pnj_current_frames(self):
        """Frames for the selected role/direction, with the same cascading
        fallback core.world.entities.Npc._action_frames_for uses (exact
        direction -> any direction of the same action -> any direction of
        any action) -- simplified slightly (no need to search every OTHER
        action once the selected one has nothing, a preview can just say
        so) since this is a preview, not gameplay."""
        action_name = self.pnj_wander_actions.get(self.preview_state)
        action_frames = self.pnj_frames.get(action_name, {}) if action_name else {}
        if self.pnj_direction in action_frames:
            return action_frames[self.pnj_direction]
        if action_frames:
            return next(iter(action_frames.values()))
        return []

    def _preview_current_frames(self):
        """Dispatches by card kind -- PNJ's own frames are nested by
        (action, direction) so it keeps its dedicated lookup; a mob's
        _preview_frames is {state: [...]}; a plain object/item's is
        already the flat frame list to show."""
        if self.is_pnj:
            return self._pnj_current_frames()
        if self.is_mob:
            return self._preview_frames.get(self.preview_state, [])
        return self._preview_frames

    def _preview_state_rects(self):
        options = self._preview_state_options()
        if not options:
            return {}
        content_x = self.x + 20
        width = (self.width - 40 - 8 * (len(options) - 1)) / len(options)
        rects = {}
        for index, (state_id, _label) in enumerate(options):
            rects[state_id] = pygame.Rect(content_x + index * (width + 8), self.y + 48, width, 24)
        return rects

    def _update_pnj_drag(self, event):
        dx = event.pos[0] - self._pnj_drag_last_pos[0]
        if abs(dx) < self.PNJ_DRAG_STEP_PX:
            return
        steps = int(dx / self.PNJ_DRAG_STEP_PX)
        self._pnj_drag_last_pos = (
            self._pnj_drag_last_pos[0] + steps * self.PNJ_DRAG_STEP_PX, event.pos[1],
        )
        index = NPC_DIRECTIONS.index(self.pnj_direction)
        self.pnj_direction = NPC_DIRECTIONS[(index + steps) % len(NPC_DIRECTIONS)]
        self.preview_frame = 0
        self.preview_animation_timer = 0.0

    def update(self, dt):
        """Advances the preview's animation for ANY card kind with more
        than one frame to show -- a no-op for an item (always exactly one
        frame) or a single-frame object. Called every frame from
        Creator.run(), unlike every other piece of this panel's state,
        which only ever changes on a real event -- animation playback is
        the one thing here that needs real time to pass. Pure looping
        preview (always plays the selected state/direction forever) -- no
        state-machine transitions like the real core.world.entities.Npc/
        Enemy/Animal, this is a viewer, not a simulation."""
        frames = self._preview_current_frames()
        if len(frames) <= 1:
            return
        self.preview_animation_timer += dt
        if self.preview_animation_timer >= self.PREVIEW_ANIMATION_SPEED:
            self.preview_animation_timer -= self.PREVIEW_ANIMATION_SPEED
            self.preview_frame = (self.preview_frame + 1) % len(frames)

    def clear(self):
        """"Vider" -- returns to the empty placeholder state without
        touching disk, so the player can back out of a card they dropped by
        mistake without having to drop another one over it."""
        self.type_id = None
        self.item_id = None
        self.status_text = ""

    def _layout(self):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        self._clear_rect = pygame.Rect(panel_rect.right - 90, panel_rect.y + 12, 70, 28)
        content_x = self.x + 20
        # Shared preview -- state tabs (variable count, computed on demand
        # by _preview_state_rects) sit at y+48; the box itself is fixed.
        self.preview_rect = pygame.Rect(content_x, self.y + 76, 160, 160)
        # Plain-object mechanics rows (blocks/interactable/lockable) --
        # start right below the preview + a one-line info label.
        self._blocks_rect = pygame.Rect(content_x, self.y + 270, self.width - 40, 32)
        self._interactable_rect = pygame.Rect(content_x, self.y + 310, self.width - 40, 32)
        self._lockable_rect = pygame.Rect(content_x, self.y + 350, self.width - 40, 32)
        # Capacites/Effets -- item/mob/pnj cards (see module docstring),
        # fixed rows below anything mob/pnj/object might show above (worst
        # case, an enemy's Type+Etats info), each with its own Stepper row
        # (label drawn above it, same idiom as ChestPanelUI's loot rows)
        # directly beneath it, shown only while that row's own checkbox is
        # enabled -- same "always laid out, conditionally shown" style as
        # blocks/interactable/lockable.
        self._throwable_rect = pygame.Rect(content_x, self.y + 400, self.width - 40, 28)
        self._explosive_rect = pygame.Rect(content_x, self.y + 470, self.width - 40, 28)
        self._heal_rect = pygame.Rect(content_x, self.y + 540, self.width - 40, 28)
        self._save_rect = pygame.Rect(content_x, self.y + self.height - 56, self.width - 40, 40)

    def _throw_speed_stepper(self):
        return Stepper(self.x + 40, self.y + 432, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 20, 800)

    def _blast_radius_stepper(self):
        return Stepper(self.x + 40, self.y + 502, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 6)

    def _blast_damage_stepper(self):
        return Stepper(self.x + 260, self.y + 502, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 10)

    def _heal_amount_stepper(self):
        return Stepper(self.x + 40, self.y + 572, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 10)

    # -- mob stats editing (enemy only) -------------------------------

    def _mob_stat_steppers(self):
        """4 integer steppers -- aggro_range/attack_range are floats in the
        underlying data (e.g. 6.0/1.2) but Stepper is integer-only, rounded
        for editing (today's values are already effectively whole numbers
        for aggro_range; attack_range's sub-1 precision is a deliberately
        accepted loss for this first editing pass, see module docstring)."""
        return {
            "health": Stepper(self.x + 40, self.y + 620, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 20),
            "move_speed": Stepper(self.x + 260, self.y + 620, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 10, 200),
            "aggro_range": Stepper(self.x + 40, self.y + 654, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 15),
            "attack_range": Stepper(self.x + 260, self.y + 654, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 5),
        }

    def _mob_loot_rows(self):
        """(label, loot_dict, key) for every loot row -- mirrors
        core.editor.ui.chest_panel.ChestPanelUI._rows() exactly (one row
        per currency in CURRENCY_FILES, one per item in ITEM_DEFINITIONS),
        reused here so a mob's death-drop loot table is edited the same
        way a chest's is."""
        rows = [(f"Pieces ({currency})", self.mob_loot, currency) for currency in CURRENCY_FILES]
        rows += [
            (f"Objet ({definition['name']})", self.mob_item_loot, item_id)
            for item_id, definition in ITEM_DEFINITIONS.items()
        ]
        return rows

    def _mob_loot_row_stepper(self, index):
        y = self.y + 688 + index * 32
        return Stepper(self.x + 40, y, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 0, 99)

    def _cell_mode_grid_rects(self):
        width_tiles, height_tiles = self.size
        anchor = self._blocks_rect
        max_dim = max(width_tiles, height_tiles)
        gap = 2
        cell_px = max(16, min(32, (self.GRID_MAX_PX - gap * (max_dim - 1)) // max_dim))
        rects = {}
        for row in range(height_tiles):
            for col in range(width_tiles):
                rects[(row, col)] = pygame.Rect(
                    anchor.x + col * (cell_px + gap), anchor.y + row * (cell_px + gap), cell_px, cell_px,
                )
        return rects

    def _cycle_cell_mode(self, row, col, step):
        current = self.cell_modes_grid[row][col]
        index = CELL_MODES.index(current) if current in CELL_MODES else 0
        self.cell_modes_grid[row][col] = CELL_MODES[(index + step) % len(CELL_MODES)]

    def _is_multi_cell(self):
        return self.cell_modes_grid is not None

    def _current_cell_modes(self):
        return self.cell_modes_grid if self._is_multi_cell() else None

    def _try_save(self):
        """"Enregistrer" -- update_type_mechanics (OBJECT_TYPES cards --
        plain object, mob, or PNJ alike), or for an ITEM_DEFINITIONS card,
        update_item_overrides (a builtin item like dynamite -- mechanics-
        only, same split as update_type_mechanics) or update_item (a
        custom item like a Potion de soin -- full entry, passing name/slot/
        icon_path/icon_rect straight through unchanged, same "own the
        mechanics, pass the identity through" split SpriteEditorPanelUI/
        this panel already use for OBJECT_TYPES). Never touches visual/
        identity data. Returns the saved id on success (Creator credits
        nothing new -- the card already exists -- but does refresh
        CardPanelUI so a completeness badge/detail line picks up the
        change immediately), None on failure. Stays populated after saving
        (unlike the old modal version's auto-close) -- this is a docked
        panel now, closing would just mean re-dropping the same card."""
        capabilities = {}
        if self.throwable_enabled:
            capabilities["throwable"] = {"speed": self.throw_speed}
        if self.explosive_enabled:
            capabilities["explosive"] = {"radius_tiles": self.blast_radius_tiles, "damage": self.blast_damage}
        effects = []
        if self.heal_enabled:
            effects.append({"kind": "heal", "amount": self.heal_amount})

        try:
            if self.item_id is not None:
                if is_builtin_item(self.item_id):
                    update_item_overrides(self.item_id, capabilities, effects)
                else:
                    update_item(
                        self.item_id, self.name, self.item_slot, self.icon_path, self.icon_rect,
                        capabilities=capabilities, effects=effects,
                    )
            else:
                stats = None
                if self.is_mob and self.mob_kind == "enemy":
                    # Pass the exact original float through UNCHANGED
                    # whenever the user never actually moved that stepper
                    # (the rounded editable value still matches round(raw))
                    # -- see mob_aggro_range's own comment in __init__ for
                    # why: otherwise saving for any unrelated reason would
                    # silently truncate 1.2 to 1 every time.
                    aggro_range = (
                        self._mob_aggro_range_raw if self.mob_aggro_range == round(self._mob_aggro_range_raw)
                        else self.mob_aggro_range
                    )
                    attack_range = (
                        self._mob_attack_range_raw if self.mob_attack_range == round(self._mob_attack_range_raw)
                        else self.mob_attack_range
                    )
                    stats = {
                        "health": self.mob_health,
                        "move_speed": self.mob_move_speed,
                        "aggro_range": aggro_range,
                        "attack_range": attack_range,
                        "loot": dict(self.mob_loot),
                        "item_loot": dict(self.mob_item_loot),
                    }
                    active_attack_frames = self.mob_stats.get("active_attack_frames")
                    if active_attack_frames is not None:
                        stats["active_attack_frames"] = list(active_attack_frames)
                update_type_mechanics(
                    self.type_id,
                    blocks_movement=self.blocks_movement,
                    cell_modes=self._current_cell_modes(),
                    interactable=self.interactable,
                    lockable=self.lockable,
                    capabilities=capabilities,
                    stats=stats,
                    effects=effects,
                )
        except ValueError as exc:
            self.status_text = str(exc)
            return None
        self.status_text = f"'{self.name}' mise a jour."
        return self.item_id if self.item_id is not None else self.type_id

    def handle_event(self, event):
        if self._handle_resize_event(event):
            return None

        # The PNJ preview's click-drag-to-rotate gesture spans multiple
        # event types (unlike everything else in this panel, which only
        # ever reacts to a single MOUSEBUTTONDOWN) -- handled first, before
        # the MOUSEBUTTONDOWN-only gate below short-circuits every other
        # event type.
        if self.is_pnj and self._pnj_dragging_direction:
            if event.type == pygame.MOUSEMOTION:
                self._update_pnj_drag(event)
                return None
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._pnj_dragging_direction = False
                return None

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        if self.type_id is None and self.item_id is None:
            return None

        if self._clear_rect.collidepoint(event.pos):
            self.clear()
            return None

        # Preview state tabs -- generic, works for both PNJ (roles) and mob
        # (its fixed animation set). Empty for a plain object/item, see
        # _preview_state_options.
        for state_id, rect in self._preview_state_rects().items():
            if rect.collidepoint(event.pos):
                self._select_preview_state(state_id)
                return None

        # PNJ direction-drag start -- the only card kind with a direction
        # concept at all (see module docstring).
        if self.is_pnj and self.preview_rect.collidepoint(event.pos):
            self._pnj_dragging_direction = True
            self._pnj_drag_last_pos = event.pos
            return None

        if self.type_id is not None and not self.is_mob and not self.is_pnj:
            if self.archetype in CELL_MODES_ARCHETYPES:
                if not self._is_multi_cell():
                    if self.archetype == "sol" and self._blocks_rect.collidepoint(event.pos):
                        self.blocks_movement = not self.blocks_movement
                        return None
                else:
                    for (row, col), rect in self._cell_mode_grid_rects().items():
                        if rect.collidepoint(event.pos):
                            self._cycle_cell_mode(row, col, 1)
                            return None

            if self._interactable_rect.collidepoint(event.pos):
                self.interactable = not self.interactable
                return None

            if self.archetype == "porte" and self._lockable_rect.collidepoint(event.pos):
                self.lockable = not self.lockable
                return None

        if self.is_mob or self.is_pnj or self.item_id is not None:
            if self._throwable_rect.collidepoint(event.pos):
                self.throwable_enabled = not self.throwable_enabled
                return None
            if self.throwable_enabled:
                new_speed = self._throw_speed_stepper().handle_click(event.pos, self.throw_speed)
                if new_speed is not None:
                    self.throw_speed = new_speed
                    return None

            if self._explosive_rect.collidepoint(event.pos):
                self.explosive_enabled = not self.explosive_enabled
                return None
            if self.explosive_enabled:
                new_radius = self._blast_radius_stepper().handle_click(event.pos, self.blast_radius_tiles)
                if new_radius is not None:
                    self.blast_radius_tiles = new_radius
                    return None
                new_damage = self._blast_damage_stepper().handle_click(event.pos, self.blast_damage)
                if new_damage is not None:
                    self.blast_damage = new_damage
                    return None

            if self._heal_rect.collidepoint(event.pos):
                self.heal_enabled = not self.heal_enabled
                return None
            if self.heal_enabled:
                new_amount = self._heal_amount_stepper().handle_click(event.pos, self.heal_amount)
                if new_amount is not None:
                    self.heal_amount = new_amount
                    return None

        if self.is_mob and self.mob_kind == "enemy":
            steppers = self._mob_stat_steppers()
            values = {
                "health": self.mob_health, "move_speed": self.mob_move_speed,
                "aggro_range": self.mob_aggro_range, "attack_range": self.mob_attack_range,
            }
            for name, stepper in steppers.items():
                new_value = stepper.handle_click(event.pos, values[name])
                if new_value is not None:
                    setattr(self, f"mob_{name}", new_value)
                    return None

            for index, (_label, loot, key) in enumerate(self._mob_loot_rows()):
                new_value = self._mob_loot_row_stepper(index).handle_click(event.pos, loot.get(key, 0))
                if new_value is not None:
                    loot[key] = new_value
                    return None

        if self._save_rect.collidepoint(event.pos):
            return self._try_save()

        return None

    def render(self, screen):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        self.border.draw(screen, panel_rect)

        if self.type_id is None and self.item_id is None:
            hint = self.small_font.render("Glisse une carte ici pour l'editer", True, (150, 150, 150))
            screen.blit(hint, (self.x + 20, self.y + 16))
            self._draw_resize_handle(screen)
            return

        title = self.font.render(f"Mecaniques -- {self.name}", True, (255, 255, 255))
        screen.blit(title, (self.x + 20, self.y + 16))
        self.border.draw_centered_label(screen, self._clear_rect, self.small_font, "Vider")

        self._render_preview(screen)

        if self.type_id is not None:
            if self.is_mob:
                self._render_mob_info(screen)
            elif self.is_pnj:
                self._render_pnj_info(screen)
            else:
                type_label = self.small_font.render(f"Archetype : {ARCHETYPES.get(self.archetype, {}).get('label', self.archetype)}", True, (200, 200, 200))
                screen.blit(type_label, (self.x + 20, self.y + 244))

                if self.archetype in CELL_MODES_ARCHETYPES:
                    if not self._is_multi_cell():
                        if self.archetype == "sol":
                            check_label = "[x] Bloque le mouvement" if self.blocks_movement else "[ ] Bloque le mouvement"
                            self.border.draw_centered_label(screen, self._blocks_rect, self.font, check_label)
                    else:
                        self._render_cell_modes_grid(screen)

                interact_label = "[x] Interagible" if self.interactable else "[ ] Interagible"
                self.border.draw_centered_label(screen, self._interactable_rect, self.font, interact_label)

                if self.archetype == "porte":
                    lock_label = "[x] Porte verrouillable" if self.lockable else "[ ] Porte verrouillable"
                    self.border.draw_centered_label(screen, self._lockable_rect, self.font, lock_label)
        else:
            item_label = self.small_font.render("Item d'inventaire", True, (200, 200, 200))
            screen.blit(item_label, (self.x + 20, self.y + 244))

        if self.is_mob or self.is_pnj or self.item_id is not None:
            self._render_capabilities(screen)
            self._render_effects(screen)

        if self.is_mob and self.mob_kind == "enemy":
            self._render_mob_stats_editing(screen)

        self.border.draw_centered_label(screen, self._save_rect, self.font, "Enregistrer")

        if self.status_text:
            status = self.small_font.render(self.status_text, True, (220, 220, 120))
            screen.blit(status, (self.x + 20, self._save_rect.y - 22))

        self._draw_resize_handle(screen)

    def _render_preview(self, screen):
        """Shared preview area for EVERY card kind -- see module docstring's
        "Unified preview" section."""
        for state_id, rect in self._preview_state_rects().items():
            label = f"[{state_id}]" if state_id == self.preview_state else state_id
            self.border.draw_centered_label(screen, rect, self.small_font, label)

        pygame.draw.rect(screen, (28, 28, 32), self.preview_rect)
        pygame.draw.rect(screen, (70, 70, 78), self.preview_rect, 1)
        frames = self._preview_current_frames()
        if frames:
            sprite = frames[self.preview_frame % len(frames)]
            pad = 8
            box = self.preview_rect.inflate(-pad * 2, -pad * 2)
            scale = min(box.width / sprite.get_width(), box.height / sprite.get_height())
            sw = max(1, round(sprite.get_width() * scale))
            sh = max(1, round(sprite.get_height() * scale))
            scaled = pygame.transform.scale(sprite, (sw, sh))
            screen.blit(scaled, (box.centerx - sw / 2, box.centery - sh / 2))
        else:
            hint = self.small_font.render("Aucun sprite disponible", True, (150, 150, 150))
            screen.blit(hint, (self.preview_rect.x + 8, self.preview_rect.centery))

    def _render_capabilities(self, screen):
        """Capacites section -- "Lançable"/"Explosif" toggles, each backed
        by the loaded card's own "capabilities" dict (see
        _load_capabilities/_try_save). Item, mob, or PNJ cards (see module
        docstring) -- caller (render) only invokes this for those."""
        throw_label = "[x] Lancable" if self.throwable_enabled else "[ ] Lancable"
        self.border.draw_centered_label(screen, self._throwable_rect, self.font, throw_label)
        if self.throwable_enabled:
            stepper = self._throw_speed_stepper()
            speed_label = self.small_font.render("Vitesse", True, (200, 200, 200))
            screen.blit(speed_label, (stepper.minus_rect.x, stepper.minus_rect.y - speed_label.get_height() - 2))
            stepper.render(screen, self.border, self.small_font, self.throw_speed)

        explosive_label = "[x] Explosif" if self.explosive_enabled else "[ ] Explosif"
        self.border.draw_centered_label(screen, self._explosive_rect, self.font, explosive_label)
        if self.explosive_enabled:
            radius_stepper = self._blast_radius_stepper()
            radius_label = self.small_font.render("Rayon (cases)", True, (200, 200, 200))
            screen.blit(radius_label, (radius_stepper.minus_rect.x, radius_stepper.minus_rect.y - radius_label.get_height() - 2))
            radius_stepper.render(screen, self.border, self.small_font, self.blast_radius_tiles)

            damage_stepper = self._blast_damage_stepper()
            damage_label = self.small_font.render("Degats", True, (200, 200, 200))
            screen.blit(damage_label, (damage_stepper.minus_rect.x, damage_stepper.minus_rect.y - damage_label.get_height() - 2))
            damage_stepper.render(screen, self.border, self.small_font, self.blast_damage)

    def _render_effects(self, screen):
        """Effets section -- "Soin" toggle, backed by the loaded card's own
        "effects" list (see _load_effects/_try_save -- a list of
        {"kind": ..., ...params} dicts, "Soin" is the only kind built so
        far). Item, mob, or PNJ cards, same reasoning as
        _render_capabilities."""
        heal_label = "[x] Soin" if self.heal_enabled else "[ ] Soin"
        self.border.draw_centered_label(screen, self._heal_rect, self.font, heal_label)
        if self.heal_enabled:
            stepper = self._heal_amount_stepper()
            amount_label = self.small_font.render("Montant (PV)", True, (200, 200, 200))
            screen.blit(amount_label, (stepper.minus_rect.x, stepper.minus_rect.y - amount_label.get_height() - 2))
            stepper.render(screen, self.border, self.small_font, self.heal_amount)

    def _render_mob_info(self, screen):
        """Type + Etats -- always informational (a mob's animation set is
        a fixed constant, never partial like a custom PNJ's, so there's no
        completeness notion to check). Stats/loot editing for an enemy is
        rendered separately, see _render_mob_stats_editing -- not shown
        twice as both read-only text and editable steppers."""
        kind_label = "Ennemi" if self.mob_kind == "enemy" else "Animal"
        type_label = self.small_font.render(f"Type : Mob ({kind_label})", True, (200, 200, 200))
        screen.blit(type_label, (self.x + 20, self.y + 244))

        states_label = self.small_font.render(f"Etats : {', '.join(self.mob_states)}", True, (200, 200, 200))
        screen.blit(states_label, (self.x + 20, self.y + 266))

        if self.mob_kind != "enemy":
            note = self.small_font.render(
                "Aucune stat pour un animal -- seuls les ennemis en ont.", True, (150, 150, 150)
            )
            screen.blit(note, (self.x + 20, self.y + 288))

    def _render_mob_stats_editing(self, screen):
        """PV/Vitesse/Aggro/Portee steppers + loot rows (currency then
        item, mirroring ChestPanelUI) -- enemy mobs only, called
        separately from render() rather than folded into _render_mob_info,
        since it's the one part of a mob card that's genuinely editable."""
        steppers = self._mob_stat_steppers()
        labels = {
            "health": "PV", "move_speed": "Vitesse",
            "aggro_range": "Aggro (cases)", "attack_range": "Portee (cases)",
        }
        values = {
            "health": self.mob_health, "move_speed": self.mob_move_speed,
            "aggro_range": self.mob_aggro_range, "attack_range": self.mob_attack_range,
        }
        for name, stepper in steppers.items():
            label = self.small_font.render(labels[name], True, (200, 200, 200))
            screen.blit(label, (stepper.minus_rect.x, stepper.minus_rect.y - label.get_height() - 2))
            stepper.render(screen, self.border, self.small_font, values[name])

        for index, (label_text, loot, key) in enumerate(self._mob_loot_rows()):
            stepper = self._mob_loot_row_stepper(index)
            label_surface = self.small_font.render(label_text, True, (200, 200, 200))
            screen.blit(label_surface, (stepper.minus_rect.x, stepper.minus_rect.y - label_surface.get_height() - 2))
            stepper.render(screen, self.border, self.small_font, loot.get(key, 0))

    def _render_pnj_info(self, screen):
        """PNJ-specific info below the shared preview -- entity pack name
        and the currently-selected direction + how much of the current
        action is actually tagged (see object_manager.
        action_direction_coverage) -- the preview itself (tabs/box/frame)
        is drawn generically by _render_preview."""
        type_label = self.small_font.render("Type : PNJ", True, (200, 200, 200))
        screen.blit(type_label, (self.x + 20, self.y + 244))
        pack_label = self.small_font.render(f"Pack : {self.pnj_entity_pack}", True, (150, 150, 150))
        screen.blit(pack_label, (self.x + 20, self.y + 260))

        tagged, _missing = action_direction_coverage(self.pnj_entity_pack, self.pnj_wander_actions.get(self.preview_state))
        coverage = f"{len(tagged)}/{len(NPC_DIRECTIONS)} directions taguees"
        direction_label = self.small_font.render(
            f"Direction : {self.pnj_direction} ({coverage}) -- glisser sur le sprite pour tourner",
            True, (200, 200, 200),
        )
        screen.blit(direction_label, (self.x + 20, self.y + 276))

    def _render_cell_modes_grid(self, screen):
        """Same 3-state grid as SpriteEditorPanelUI's own (see that
        module's _render_cell_modes_grid docstring for the full B/D/F
        legend) -- duplicated rather than shared, same "each panel owns
        its own small rendering helpers" precedent already used across
        this editor's panels."""
        if self.cell_modes_grid is None:
            return
        rects = self._cell_mode_grid_rects()
        for (row, col), rect in rects.items():
            mode = self.cell_modes_grid[row][col]
            color = self.CELL_MODE_COLORS.get(mode, self.CELL_MODE_COLORS["behind"])
            pygame.draw.rect(screen, color, rect)
            pygame.draw.rect(screen, (20, 20, 20), rect, 1)
            letter = {"block": "B", "behind": "D", "front": "F"}.get(mode, "?")
            label = self.small_font.render(letter, True, (255, 255, 255))
            screen.blit(label, (rect.centerx - label.get_width() / 2, rect.centery - label.get_height() / 2))
        legend_y = max(r.bottom for r in rects.values()) + 6
        legend = self.small_font.render("B = bloquant | D = derriere | F = devant", True, (170, 170, 170))
        screen.blit(legend, (self._blocks_rect.x, legend_y))
