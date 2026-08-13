"""MechanicsPanelUI -- the "mechanical" counterpart to SpriteEditorPanelUI.

Where SpriteEditorPanelUI owns a custom type's visual/identity data (asset/
name/size/frames), this panel owns its gameplay flags (blocks_movement/
cell_modes/interactable/lockable), capacites (throwable/explosive), and
effets (heal today) -- confirmed split with the user, framed as the
long-term "Artiste" (sprite editor) vs "Forgeron" (this panel) divide,
though no NPC/dialogue gating exists yet: reachable today by dragging an
owned card from CardPanelUI directly onto this panel's own body (wrapped in
a PanelFrame titled "Forge" -- see Creator.__init__/the drop handling in
Creator.run()).

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

Capacites/Effets are ITEM cards only (self.item_id) -- no OBJECT_TYPES-side
consumer reads a world object's "capabilities"/"effects" yet, so showing
either section for an object card would be a control that silently does
nothing. The data model stays symmetric (object_manager still lets
"capabilities" be set on any type, cards.py still bridges "effects" for
OBJECT_TYPES cards too) for when a consumer eventually exists -- just no UI
for it here yet.

A mob (animal/enemy) OBJECT_TYPES card gets its own read-only branch
(is_mob/_render_mob_info) instead of the ordinary blocks_movement/
cell_modes/interactable/lockable rows -- those don't apply to a mob at all
(a mob was showing the exact same checkboxes as a decorative floor object
before this branch existed). Shows Etats (its fixed animation set) and, for
an enemy, its stats/loot -- nothing editable yet, since no register_mob_type
write API exists.

A PNJ (config["npc"]) OBJECT_TYPES card gets its own read-only branch too
(is_pnj/_render_pnj_info): tabs for whichever wander_actions role is
configured, a LIVE looping preview of that role's tagged sprite (see
object_manager.load_npc_frames/NPC_DIRECTIONS), and click-drag directly on
the preview to cycle through directions (_pnj_dragging_direction/
_update_pnj_drag) -- the one interactive, non-editing feature in this
panel. This needs real elapsed time to animate, unlike everything else
here (state only ever changes on a discrete click): see update(dt), called
every frame from Creator.run() regardless of what's loaded (a no-op unless
is_pnj). No write API exists for entity_pack/wander_actions here either --
still SpriteEditorPanelUI's job.
"""

import pygame

from core.editor.ui.mixins import _ResizableCornerMixin
from core.ui.widgets import BorderManager, Stepper
from core.world.object_manager import (
    OBJECT_TYPES, ITEM_DEFINITIONS, ARCHETYPES, CELL_MODES, ENEMY_ANIMATIONS,
    NPC_DIRECTIONS, load_npc_frames, action_direction_coverage,
    update_type_mechanics, update_item_overrides, update_item, is_builtin_item,
)
from core.data.cards import resolve_card_sprite

CELL_MODES_ARCHETYPES = ("sol", "mur", "porte")


class MechanicsPanelUI(_ResizableCornerMixin):
    STANDARD_WIDTH = 420
    STANDARD_HEIGHT = 600
    MAX_WIDTH = 900
    MAX_HEIGHT = 700
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
    PNJ_ANIMATION_SPEED = 0.2  # matches core.world.entities.Npc.ANIMATION_SPEED
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
        # edits any of these, only the mechanical flags/capacites/effets
        # below. item_slot/icon_path/icon_rect only ever populated for an
        # item card (self.item_id set); tileset/rect/frame_rects/size/
        # archetype only for an object card (self.type_id set).
        self.tileset = None
        self.rect = None
        self.frame_rects = None
        self.size = (1, 1)
        self.archetype = "sol"
        self.item_slot = None
        self.icon_path = None
        self.icon_rect = None

        # The actual editable state -- OBJECT_TYPES cards only (self.type_id).
        self.blocks_movement = False
        self.cell_modes_grid = None
        self.interactable = False
        self.lockable = False

        # Mob (animal/enemy) cards are OBJECT_TYPES entries too, but none of
        # the fields above apply to one (a mob was showing the exact same
        # "Bloque le mouvement"/"Interagible" checkboxes as a decorative
        # floor object, which made no sense) -- read-only summary instead,
        # see open()/_render_mob_info. No write API for mob stats exists
        # (no register_mob_type), so there is nothing to save here yet.
        self.is_mob = False
        self.mob_kind = None
        self.mob_states = ()
        self.mob_stats = {}

        # PNJ cards get their own live-preview branch (see is_pnj/open/
        # _render_pnj_info) -- animation playback (pnj_frame/
        # pnj_animation_timer, advanced by update(dt), see Creator.run())
        # of whichever wander_actions role is selected (pnj_action_role),
        # for whichever NPC_DIRECTIONS entry is selected (pnj_direction) --
        # changed by click-dragging on the preview itself, see
        # _pnj_dragging_direction/handle_event. Read-only, like mob info:
        # no write API exists here for entity_pack/wander_actions, that
        # stays SpriteEditorPanelUI's job.
        self.is_pnj = False
        self.pnj_entity_pack = None
        self.pnj_wander_actions = {}
        self.pnj_frames = {}
        self.pnj_action_role = None
        self.pnj_direction = NPC_DIRECTIONS[0]
        self.pnj_frame = 0
        self.pnj_animation_timer = 0.0
        self._pnj_dragging_direction = False
        self._pnj_drag_last_pos = None

        # Capacites/Effets -- ITEM cards only (self.item_id), see module
        # docstring for why. "capabilities"/"effects" vocabulary is the
        # same one object_manager/cards.py already use.
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
        """Loads `card_id`'s current mechanical flags/capacites for editing
        -- stays empty (self.type_id/self.item_id untouched) for a room
        card or an unknown id, the only two kinds this panel can't do
        anything with. An ITEM_DEFINITIONS id (self.item_id) and an
        OBJECT_TYPES id (self.type_id) are mutually exclusive and checked
        first/second respectively -- no id is ever both."""
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
        else:
            self.mob_kind = None
            self.mob_states = ()
            self.mob_stats = {}

        self.is_pnj = bool(config.get("npc"))
        if self.is_pnj:
            self.pnj_entity_pack = config.get("entity_pack")
            self.pnj_wander_actions = dict(config.get("wander_actions", {}))
            self.pnj_frames = load_npc_frames(self.pnj_entity_pack) if self.pnj_entity_pack else {}
            self.pnj_action_role = self._pnj_available_roles()[0] if self._pnj_available_roles() else None
            self.pnj_direction = NPC_DIRECTIONS[0]
            self.pnj_frame = 0
            self.pnj_animation_timer = 0.0
            self._pnj_dragging_direction = False
        else:
            self.pnj_entity_pack = None
            self.pnj_wander_actions = {}
            self.pnj_frames = {}
            self.pnj_action_role = None

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

    def _pnj_current_frames(self):
        """Frames for the selected role/direction, with the same cascading
        fallback core.world.entities.Npc._action_frames_for uses (exact
        direction -> any direction of the same action -> any direction of
        any action) -- simplified slightly (no need to search every OTHER
        action once the selected one has nothing, a preview can just say
        so) since this is a preview, not gameplay."""
        action_name = self.pnj_wander_actions.get(self.pnj_action_role)
        action_frames = self.pnj_frames.get(action_name, {}) if action_name else {}
        if self.pnj_direction in action_frames:
            return action_frames[self.pnj_direction]
        if action_frames:
            return next(iter(action_frames.values()))
        return []

    def _pnj_role_rects(self):
        roles = self._pnj_available_roles()
        content_x = self.x + 20
        width = (self.width - 40 - 8 * (len(roles) - 1)) / len(roles) if roles else 0
        rects = {}
        for index, role in enumerate(roles):
            rects[role] = pygame.Rect(content_x + index * (width + 8), self.y + 88, width, 28)
        return rects

    def _select_pnj_role(self, role):
        self.pnj_action_role = role
        self.pnj_frame = 0
        self.pnj_animation_timer = 0.0

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
        self.pnj_frame = 0
        self.pnj_animation_timer = 0.0

    def update(self, dt):
        """Advances the PNJ preview's animation -- a no-op for every other
        card kind. Called every frame from Creator.run(), unlike every
        other piece of this panel's state, which only ever changes on a
        real event -- animation playback is the one thing here that needs
        real time to pass. Pure looping preview (always plays the selected
        action/direction forever) -- no state-machine transitions like the
        real core.world.entities.Npc, this is a viewer, not a simulation."""
        if not self.is_pnj:
            return
        frames = self._pnj_current_frames()
        if not frames:
            return
        self.pnj_animation_timer += dt
        if self.pnj_animation_timer >= self.PNJ_ANIMATION_SPEED:
            self.pnj_animation_timer -= self.PNJ_ANIMATION_SPEED
            self.pnj_frame = (self.pnj_frame + 1) % len(frames)

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
        self._blocks_rect = pygame.Rect(content_x, self.y + 140, self.width - 40, 32)
        self._interactable_rect = pygame.Rect(content_x, self.y + 180, self.width - 40, 32)
        self._lockable_rect = pygame.Rect(content_x, self.y + 220, self.width - 40, 32)
        # Capacites/Effets -- ITEM cards only (see module docstring), fixed
        # rows below the OBJECT_TYPES-only ones above (unused/not
        # hit-tested for an item card, and vice versa), each with its own
        # Stepper row (label drawn above it, same idiom as ChestPanelUI's
        # loot rows) directly beneath it, shown only while that row's own
        # checkbox is enabled -- same "always laid out, conditionally
        # shown" style as blocks/interactable/lockable.
        self._throwable_rect = pygame.Rect(content_x, self.y + 256, self.width - 40, 28)
        self._explosive_rect = pygame.Rect(content_x, self.y + 344, self.width - 40, 28)
        self._heal_rect = pygame.Rect(content_x, self.y + 432, self.width - 40, 28)
        self._save_rect = pygame.Rect(content_x, self.y + self.height - 56, self.width - 40, 40)
        # PNJ preview -- role tabs computed on demand (_pnj_role_rects,
        # variable count) sit just above this at y+88; click-drag on the
        # square below rotates pnj_direction (see _update_pnj_drag).
        self._pnj_preview_rect = pygame.Rect(content_x, self.y + 130, 160, 160)

    def _throw_speed_stepper(self):
        return Stepper(self.x + 40, self.y + 308, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 20, 800)

    def _blast_radius_stepper(self):
        return Stepper(self.x + 40, self.y + 398, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 6)

    def _blast_damage_stepper(self):
        return Stepper(self.x + 260, self.y + 398, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 10)

    def _heal_amount_stepper(self):
        return Stepper(self.x + 40, self.y + 464, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 10)

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
        """"Enregistrer" -- update_type_mechanics (OBJECT_TYPES cards), or
        for an ITEM_DEFINITIONS card, update_item_overrides (a builtin item
        like dynamite -- mechanics-only, same split as update_type_mechanics)
        or update_item (a custom item like a Potion de soin -- full entry,
        passing name/slot/icon_path/icon_rect straight through unchanged,
        same "own the mechanics, pass the identity through" split
        SpriteEditorPanelUI/this panel already use for OBJECT_TYPES).
        Never touches visual/identity data. Returns the saved id on success
        (Creator credits nothing new -- the card already exists -- but does
        refresh CardPanelUI so a completeness badge/detail line picks up
        the change immediately), None on failure. Stays populated after
        saving (unlike the old modal version's auto-close) -- this is a
        docked panel now, closing would just mean re-dropping the same
        card."""
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
                update_type_mechanics(
                    self.type_id,
                    blocks_movement=self.blocks_movement,
                    cell_modes=self._current_cell_modes(),
                    interactable=self.interactable,
                    lockable=self.lockable,
                    capabilities=capabilities,
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

        if self.is_pnj:
            for role, rect in self._pnj_role_rects().items():
                if rect.collidepoint(event.pos):
                    self._select_pnj_role(role)
                    return None
            if self._pnj_preview_rect.collidepoint(event.pos):
                self._pnj_dragging_direction = True
                self._pnj_drag_last_pos = event.pos
                return None
            return None

        if self.type_id is not None and not self.is_mob:
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

        if self.item_id is not None:
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

        if not self.is_mob and not self.is_pnj and self._save_rect.collidepoint(event.pos):
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

        if self.icon is not None:
            icon_rect = pygame.Rect(self.x + 20, self.y + 48, 48, 48)
            scaled = pygame.transform.scale(self.icon, icon_rect.size)
            screen.blit(scaled, icon_rect.topleft)

        if self.type_id is not None:
            if self.is_mob:
                self._render_mob_info(screen)
            elif self.is_pnj:
                self._render_pnj_info(screen)
            else:
                type_label = self.small_font.render(f"Archetype : {ARCHETYPES.get(self.archetype, {}).get('label', self.archetype)}", True, (200, 200, 200))
                screen.blit(type_label, (self.x + 80, self.y + 60))

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
            screen.blit(item_label, (self.x + 80, self.y + 60))
            self._render_capabilities(screen)
            self._render_effects(screen)

        if not self.is_mob and not self.is_pnj:
            self.border.draw_centered_label(screen, self._save_rect, self.font, "Enregistrer")

        if self.status_text:
            status = self.small_font.render(self.status_text, True, (220, 220, 120))
            screen.blit(status, (self.x + 20, self._save_rect.y - 22))

        self._draw_resize_handle(screen)

    def _render_capabilities(self, screen):
        """Capacites section -- "Lançable"/"Explosif" toggles, each backed
        by ITEM_DEFINITIONS' own "capabilities" dict (see
        _load_capabilities/_try_save). Item cards only (see module
        docstring for why) -- caller (render) only invokes this in the
        item branch."""
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
        """Effets section -- "Soin" toggle, backed by ITEM_DEFINITIONS' own
        "effects" list (see _load_effects/_try_save -- a list of
        {"kind": ..., ...params} dicts, "Soin" is the only kind built so
        far). Item cards only, same reasoning as _render_capabilities."""
        heal_label = "[x] Soin" if self.heal_enabled else "[ ] Soin"
        self.border.draw_centered_label(screen, self._heal_rect, self.font, heal_label)
        if self.heal_enabled:
            stepper = self._heal_amount_stepper()
            amount_label = self.small_font.render("Montant (PV)", True, (200, 200, 200))
            screen.blit(amount_label, (stepper.minus_rect.x, stepper.minus_rect.y - amount_label.get_height() - 2))
            stepper.render(screen, self.border, self.small_font, self.heal_amount)

    def _render_mob_info(self, screen):
        """Read-only mob (animal/enemy) summary -- see is_mob's own comment
        in __init__ for why this exists instead of falling through to the
        object-mechanics rows above (they don't apply to a mob at all)."""
        kind_label = "Ennemi" if self.mob_kind == "enemy" else "Animal"
        type_label = self.small_font.render(f"Type : Mob ({kind_label})", True, (200, 200, 200))
        screen.blit(type_label, (self.x + 80, self.y + 60))

        states_label = self.small_font.render(f"Etats : {', '.join(self.mob_states)}", True, (200, 200, 200))
        screen.blit(states_label, (self.x + 20, self.y + 110))

        next_y = self.y + 136
        if self.mob_stats:
            stats_line = (
                f"PV {self.mob_stats.get('health', '?')} | "
                f"Vitesse {self.mob_stats.get('move_speed', '?')} | "
                f"Aggro {self.mob_stats.get('aggro_range', '?')} | "
                f"Portee {self.mob_stats.get('attack_range', '?')}"
            )
            stats_label = self.small_font.render(stats_line, True, (200, 200, 200))
            screen.blit(stats_label, (self.x + 20, next_y))
            next_y += 22

            loot = self.mob_stats.get("loot")
            if loot:
                loot_line = "Loot : " + ", ".join(f"{currency} x{count}" for currency, count in loot.items())
                loot_label = self.small_font.render(loot_line, True, (200, 200, 200))
                screen.blit(loot_label, (self.x + 20, next_y))
                next_y += 22

            item_loot = self.mob_stats.get("item_loot")
            if item_loot:
                item_loot_line = "Loot objet : " + ", ".join(f"{item_id} x{count}" for item_id, count in item_loot.items())
                item_loot_label = self.small_font.render(item_loot_line, True, (200, 200, 200))
                screen.blit(item_loot_label, (self.x + 20, next_y))
                next_y += 22

        no_edit = self.small_font.render(
            "Lecture seule -- pas encore de creation/edition de mob custom.", True, (150, 150, 150)
        )
        screen.blit(no_edit, (self.x + 20, next_y + 8))

    def _render_pnj_info(self, screen):
        """Live PNJ preview -- role tabs (only the ones actually configured
        in wander_actions), a looping animation of the selected role's
        sprite for the selected direction (advanced by update(dt), see its
        own docstring), and click-drag-to-rotate on the sprite itself. Read
        only, same reasoning as _render_mob_info -- no write API exists
        here for entity_pack/wander_actions."""
        type_label = self.small_font.render("Type : PNJ", True, (200, 200, 200))
        screen.blit(type_label, (self.x + 80, self.y + 60))
        pack_label = self.small_font.render(f"Pack : {self.pnj_entity_pack}", True, (150, 150, 150))
        screen.blit(pack_label, (self.x + 80, self.y + 76))

        for role, rect in self._pnj_role_rects().items():
            label = f"[{role}]" if role == self.pnj_action_role else role
            self.border.draw_centered_label(screen, rect, self.small_font, label)

        pygame.draw.rect(screen, (28, 28, 32), self._pnj_preview_rect)
        pygame.draw.rect(screen, (70, 70, 78), self._pnj_preview_rect, 1)
        frames = self._pnj_current_frames()
        if frames:
            sprite = frames[self.pnj_frame % len(frames)]
            pad = 8
            box = self._pnj_preview_rect.inflate(-pad * 2, -pad * 2)
            scale = min(box.width / sprite.get_width(), box.height / sprite.get_height())
            sw = max(1, round(sprite.get_width() * scale))
            sh = max(1, round(sprite.get_height() * scale))
            scaled = pygame.transform.scale(sprite, (sw, sh))
            screen.blit(scaled, (box.centerx - sw / 2, box.centery - sh / 2))
        else:
            hint = self.small_font.render("Aucun sprite tague pour cette action", True, (150, 150, 150))
            screen.blit(hint, (self._pnj_preview_rect.x + 8, self._pnj_preview_rect.centery))

        tagged, _missing = action_direction_coverage(self.pnj_entity_pack, self.pnj_wander_actions.get(self.pnj_action_role))
        coverage = f"{len(tagged)}/{len(NPC_DIRECTIONS)} directions taguees"
        direction_label = self.small_font.render(
            f"Direction : {self.pnj_direction} ({coverage}) -- glisser sur le sprite pour tourner",
            True, (200, 200, 200),
        )
        screen.blit(direction_label, (self.x + 20, self._pnj_preview_rect.bottom + 8))

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
