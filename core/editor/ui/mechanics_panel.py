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

self.card_kind ("object"/"item"/"mob"/"pnj") is the one thing that actually
decides how this panel behaves, set once by open() -- is_mob/is_pnj are
read-only properties derived from it (kept for readability at their many
existing call sites) rather than their own independently-tracked booleans,
so the two can never drift out of sync with each other or with card_kind.

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

import random

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
from core.data.sound_manager import SoundManager, list_available_sound_files

CELL_MODES_ARCHETYPES = ("sol", "mur", "porte")


class MechanicsPanelUI(_ResizableCornerMixin):
    STANDARD_WIDTH = 420
    STANDARD_HEIGHT = 560
    MAX_WIDTH = 900
    MAX_HEIGHT = 900
    SOUND_ROW_HEIGHT = 30
    # A sound row gains this much extra height when its pitch slider is
    # showing (see _sound_row_height) -- the slider draws on its own line
    # right below the file picker/Jouer row, not squeezed onto it (no room
    # left in STANDARD_WIDTH once the pitch toggle button is added too).
    PITCH_ROW_HEIGHT = 26
    # The draggable range's own bounds -- how far a slider's two handles can
    # travel, not the DEFAULT range a freshly-enabled slot starts at
    # (that's DEFAULT_PITCH_RANGE below). x2.0/x0.5 is already a drastic
    # register shift for a short SFX; wider would mostly just sound broken.
    PITCH_SLIDER_MIN = 0.5
    PITCH_SLIDER_MAX = 2.0
    DEFAULT_PITCH_RANGE = [0.85, 1.15]
    # Panel-relative y where the scrollable content area begins (right below
    # the shared preview + its state tabs) -- every row at or below this,
    # across every card_kind, goes through _cy() instead of `self.y + N`
    # directly, so self.scroll_offset shifts it uniformly. The preview
    # itself, the title, "Vider", and the Enregistrer button all stay
    # pinned (never scroll) by continuing to use `self.y`/`self.height`
    # directly, never _cy().
    CONTENT_TOP = 244
    SCROLLBAR_WIDTH = 10
    WHEEL_STEP_PX = 48
    _SOUND_LABEL_OVERRIDES = {
        "use": "Utilisation", "place": "Pose", "destroy": "Casse",
        "throw": "Lancer", "interact": "Interaction",
        "idle": "Repos", "movement": "Mouvement", "move": "Mouvement",
        "attack": "Attaque", "damaged": "Touche", "death": "Mort",
    }
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

        # The one thing that actually decides how this panel behaves --
        # "object" (plain decorative/special OBJECT_TYPES), "item"
        # (ITEM_DEFINITIONS), "mob" or "pnj" (both OBJECT_TYPES too). Set
        # once by open(), never written anywhere else -- is_mob/is_pnj
        # below are read-only properties derived from it instead of their
        # own independently-tracked booleans, so the two can't drift out
        # of sync with each other or with card_kind (they used to be 2
        # separate flags set at 5 different call sites across open()).
        self.card_kind = None

        # Mob (animal/enemy) cards are OBJECT_TYPES entries too, but none of
        # the fields above apply to one (a mob was showing the exact same
        # "Bloque le mouvement"/"Interagible" checkboxes as a decorative
        # floor object, which made no sense) -- Type/Etats info instead
        # (_render_mob_info), plus real stats editing for an enemy (see
        # mob_health and friends below, _render_mob_stats_editing).
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

        # Sons -- {"use"/"place"/"destroy": "filename.wav"|None}, same
        # generic vocabulary as capabilities/effects above (see
        # core.data.cards.Card.sounds/object_manager's "sounds" mechanics
        # field). Which of the 3 keys is actually shown/editable depends on
        # card_kind, see _sound_slot_keys. _available_sound_files is
        # scanned once per panel lifetime (a session doesn't drop new .wav
        # files into assets/sound/ mid-edit), not re-globbed per frame.
        self.card_sounds = {"use": None, "place": None, "destroy": None}
        self._available_sound_files = list_available_sound_files()
        self._sound_rects = {}

        # Pitch -- {key: True/False} whether random-pitch is on for that
        # sound slot, {key: [min, max]} its range when it is (see
        # core.data.cards.Card.sound_pitch/core.data.sound_manager.
        # play_card_sound). Only meaningful for a key that also has a real
        # sound assigned (self.card_sounds[key]) -- the toggle/slider
        # simply aren't drawn otherwise, see _render_sounds. A fresh toggle
        # (no saved range yet) seeds DEFAULT_PITCH_RANGE rather than
        # starting degenerate at [1.0, 1.0].
        self.pitch_enabled = {}
        self.pitch_range = {}
        self._pitch_rects = {}
        self._pitch_dragging = None  # (key, "lo"/"hi") or None

        # Scrollable-content viewport state (see CONTENT_TOP's own
        # docstring) -- pixel-based, not row-based, since rows here are
        # variable-height/variable-count depending on card_kind, unlike
        # core.ui.widgets.RoomBrowser's uniform row list.
        self.scroll_offset = 0
        self._scrollbar_dragging = False

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

    @property
    def is_mob(self):
        return self.card_kind == "mob"

    @property
    def is_pnj(self):
        return self.card_kind == "pnj"

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
        self.scroll_offset = 0

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
            self.card_kind = "item"
            self.preview_state = None
            self._preview_frames = [self.icon] if self.icon else []
            self._load_capabilities(item_def.get("capabilities", {}))
            self._load_effects(item_def.get("effects", []))
            self._load_sounds(item_def.get("sounds", {}))
            self._load_pitch(item_def.get("sound_pitch", {}))
            self.status_text = ""
            return

        config = OBJECT_TYPES.get(card_id)
        if config is None:
            return

        self.type_id = card_id
        self.item_id = None
        self.name = config.get("name", card_id)
        self.icon = resolve_card_sprite(card_id)

        is_mob = bool(config.get("animal") or config.get("enemy"))
        if is_mob:
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

        is_pnj = bool(config.get("npc"))
        if is_pnj:
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

        if is_mob:
            self.card_kind = "mob"
        elif is_pnj:
            self.card_kind = "pnj"
        else:
            self.card_kind = "object"
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
        self._load_sounds(config.get("sounds", {}))
        self._load_pitch(config.get("sound_pitch", {}))
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

    def _cy(self, offset):
        """Screen-space y for a scrollable-content row at panel-relative
        offset `offset` (e.g. 270 for _blocks_rect) -- see CONTENT_TOP's
        own docstring. Every row-building call below CONTENT_TOP goes
        through this instead of `self.y + offset` directly, so
        self.scroll_offset shifts every one of them together."""
        return self.y + offset - self.scroll_offset

    def _viewport_rect(self):
        """The clipped, scrollable middle band -- from right below the
        preview/tabs down to just above the pinned Enregistrer button.
        Both the render clip and the click-hit gate for every scrollable
        row go through this one rect, so "what's visible" and "what's
        clickable" can never drift apart."""
        top = self.y + self.CONTENT_TOP
        bottom = self.y + self.height - 66
        return pygame.Rect(self.x, top, self.width, max(0, bottom - top))

    def _sound_row_height(self, key):
        """SOUND_ROW_HEIGHT, plus PITCH_ROW_HEIGHT once a real sound is
        assigned to `key` AND its random-pitch slider is enabled -- a row
        with nothing assigned, or with pitch off, never grows, so toggling
        pitch on/off for one row shifts every row below it without
        otherwise disturbing the layout."""
        height = self.SOUND_ROW_HEIGHT
        if self.card_sounds.get(key) and self.pitch_enabled.get(key):
            height += self.PITCH_ROW_HEIGHT
        return height

    def _sound_section_height(self):
        return sum(self._sound_row_height(key) for key in self._sound_slot_keys())

    def _content_height(self):
        """Total scrollable content height (panel-relative, i.e. as if
        scroll_offset were 0) for the currently loaded card -- always ends
        with the Sons section, whatever it's preceded by per card_kind, see
        _sounds_top_offset. 0 while empty (nothing to scroll)."""
        if self.type_id is None and self.item_id is None:
            return 0
        bottom = self._sounds_top_offset() + self._sound_section_height() + 10
        return bottom - self.CONTENT_TOP

    def _max_scroll(self):
        return max(0, self._content_height() - self._viewport_rect().height)

    def _clamp_scroll(self):
        self.scroll_offset = max(0, min(self.scroll_offset, self._max_scroll()))

    def _scrollbar_track_rect(self):
        viewport = self._viewport_rect()
        return pygame.Rect(viewport.right - self.SCROLLBAR_WIDTH, viewport.y, self.SCROLLBAR_WIDTH, viewport.height)

    def _scrollbar_thumb_rect(self):
        track = self._scrollbar_track_rect()
        max_scroll = self._max_scroll()
        if max_scroll <= 0 or track.height <= 0:
            return track
        thumb_h = max(20, track.height * track.height / (self._content_height() or 1))
        thumb_y = track.y + (track.height - thumb_h) * (self.scroll_offset / max_scroll)
        return pygame.Rect(track.x, thumb_y, track.width, thumb_h)

    def handle_wheel(self, pos, direction):
        """Scrolls while `pos` is anywhere over this panel -- same
        "hovering is enough, not just grabbing the thin thumb" precedent as
        core.ui.widgets.RoomBrowser.handle_wheel/CardPanelUI.handle_wheel.
        Returns True if consumed, so Creator's own MOUSEWHEEL handler knows
        not to fall through to zooming the world camera instead."""
        if not self.contains(pos):
            return False
        max_scroll = self._max_scroll()
        if max_scroll <= 0:
            return False
        self.scroll_offset = max(0, min(max_scroll, self.scroll_offset - direction * self.WHEEL_STEP_PX))
        return True

    def _sounds_top_offset(self):
        """Panel-relative y where the Sons section starts -- always right
        after whatever kind-specific content precedes it (object mechanics/
        capacites+effets/mob stats+loot/pnj info), computed per card_kind
        rather than a single fixed offset, so two sections can never
        overlap even though the viewport now scrolls instead of forcing the
        whole panel taller."""
        if self.card_kind == "object":
            return 440  # past blocks/interactable/lockable + cell_modes grid's worst case
        if self.is_mob and self.mob_kind == "enemy":
            return 688 + len(self._mob_loot_rows()) * 32 + 20
        # animal/item/pnj -- past capacites/effets (see _capacites_top_offset),
        # nothing else shown below that for any of these 3 kinds.
        return self._capacites_top_offset() + 198

    def _capacites_top_offset(self):
        """Panel-relative y where Capacites/Effets starts -- right after
        whatever kind-specific info precedes it (see module docstring),
        computed per card_kind rather than a single fixed offset sized for
        the worst case (an enemy's Type+Etats info): an item has NOTHING
        above it at all, so that fixed offset used to leave a large dead
        scroll gap before anything useful. Only called for kinds that
        actually show Capacites/Effets (see _shows_capabilities_and_effects
        -- item/mob/pnj), but harmless to call for "object" too."""
        if self.card_kind == "item":
            return 270
        if self.is_mob and self.mob_kind == "enemy":
            return 300
        if self.is_mob:  # animal
            return 320
        return 300  # pnj

    def _layout(self):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        self._clear_rect = pygame.Rect(panel_rect.right - 90, panel_rect.y + 12, 70, 28)
        content_x = self.x + 20
        # Shared preview -- PINNED, never scrolls (state tabs, variable
        # count, computed on demand by _preview_state_rects, sit at y+48;
        # the box itself is fixed).
        self.preview_rect = pygame.Rect(content_x, self.y + 76, 160, 160)
        # Everything below here is scrollable content -- built via _cy(),
        # see its own docstring.
        content_width = self.width - 40 - self.SCROLLBAR_WIDTH - 6
        # Plain-object mechanics rows (blocks/interactable/lockable) --
        # start right below the preview + a one-line info label.
        self._blocks_rect = pygame.Rect(content_x, self._cy(270), content_width, 32)
        self._interactable_rect = pygame.Rect(content_x, self._cy(310), content_width, 32)
        self._lockable_rect = pygame.Rect(content_x, self._cy(350), content_width, 32)
        # Capacites/Effets -- item/mob/pnj cards (see module docstring),
        # starting right after whatever kind-specific info precedes it (see
        # _capacites_top_offset -- dynamic per card_kind, same reasoning as
        # _sounds_top_offset: an item has nothing above it at all, so a
        # single fixed offset sized for "worst case, an enemy's Type+Etats
        # info" left a large dead scroll gap for every other kind). Each
        # row has its own Stepper row (label drawn above it, same idiom as
        # ChestPanelUI's loot rows) directly beneath it, shown only while
        # that row's own checkbox is enabled -- same "always laid out,
        # conditionally shown" style as blocks/interactable/lockable.
        capacites_top = self._capacites_top_offset()
        self._throwable_rect = pygame.Rect(content_x, self._cy(capacites_top), content_width, 28)
        self._explosive_rect = pygame.Rect(content_x, self._cy(capacites_top + 70), content_width, 28)
        self._heal_rect = pygame.Rect(content_x, self._cy(capacites_top + 140), content_width, 28)
        # Enregistrer -- PINNED, never scrolls (same reasoning as the
        # preview above): the panel would be useless if saving your edits
        # required scrolling to find the button first.
        self._save_rect = pygame.Rect(content_x, self.y + self.height - 56, self.width - 40, 40)

        # Sons -- see _sounds_top_offset/_sound_slot_keys. A variable
        # number of rows depending on card_kind (a mob gets one per
        # ENEMY_ANIMATIONS/idle+move state, plus place/destroy) -- this is
        # exactly what the scrollable viewport above exists for, unlike the
        # old fixed 3-row/bottom-anchored layout this replaced. Each row is
        # itself variable-height too (see _sound_row_height) -- an
        # accumulating cursor, not index*SOUND_ROW_HEIGHT, so a row whose
        # pitch slider is showing pushes every row below it down instead of
        # overlapping it.
        sound_keys = self._sound_slot_keys()
        cursor = self._sounds_top_offset()
        row_h = self.SOUND_ROW_HEIGHT - 6
        label_w, btn_w, name_w, play_w, pitch_w, gap = 90, 20, 90, 44, 44, 5
        self._sound_rects = {}
        self._pitch_rects = {}
        for key in sound_keys:
            ry = self._cy(cursor)
            lx = content_x + label_w + gap
            prev_rect = pygame.Rect(lx, ry, btn_w, row_h)
            name_rect = pygame.Rect(prev_rect.right + gap, ry, name_w, row_h)
            next_rect = pygame.Rect(name_rect.right + gap, ry, btn_w, row_h)
            play_rect = pygame.Rect(next_rect.right + gap, ry, play_w, row_h)
            pitch_toggle_rect = pygame.Rect(play_rect.right + gap, ry, pitch_w, row_h)
            self._sound_rects[key] = {
                "label": pygame.Rect(content_x, ry, label_w, row_h),
                "prev": prev_rect, "name": name_rect, "next": next_rect, "play": play_rect,
                "pitch_toggle": pitch_toggle_rect,
            }
            if self.card_sounds.get(key) and self.pitch_enabled.get(key):
                slider_y = self._cy(cursor + self.SOUND_ROW_HEIGHT + 6)
                track = pygame.Rect(content_x + 46, slider_y, content_width - 46 - 96, 12)
                lo_value, hi_value = self.pitch_range.get(key, self.DEFAULT_PITCH_RANGE)
                lo_x = self._pitch_value_to_x(track, lo_value)
                hi_x = self._pitch_value_to_x(track, hi_value)
                self._pitch_rects[key] = {
                    "track": track,
                    "lo": pygame.Rect(lo_x - 5, track.centery - 8, 10, 16),
                    "hi": pygame.Rect(hi_x - 5, track.centery - 8, 10, 16),
                }
            else:
                self._pitch_rects.pop(key, None)
            cursor += self._sound_row_height(key)

    def _throw_speed_stepper(self):
        return Stepper(
            self.x + 40, self._cy(self._capacites_top_offset() + 32),
            self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 20, 800,
        )

    def _blast_radius_stepper(self):
        return Stepper(
            self.x + 40, self._cy(self._capacites_top_offset() + 102),
            self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 6,
        )

    def _blast_damage_stepper(self):
        return Stepper(
            self.x + 260, self._cy(self._capacites_top_offset() + 102),
            self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 10,
        )

    def _heal_amount_stepper(self):
        return Stepper(
            self.x + 40, self._cy(self._capacites_top_offset() + 172),
            self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 10,
        )

    # -- mob stats editing (enemy only) -------------------------------

    def _mob_stat_steppers(self):
        """4 integer steppers -- aggro_range/attack_range are floats in the
        underlying data (e.g. 6.0/1.2) but Stepper is integer-only, rounded
        for editing (today's values are already effectively whole numbers
        for aggro_range; attack_range's sub-1 precision is a deliberately
        accepted loss for this first editing pass, see module docstring)."""
        return {
            "health": Stepper(self.x + 40, self._cy(620), self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 20),
            "move_speed": Stepper(self.x + 260, self._cy(620), self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 10, 200),
            "aggro_range": Stepper(self.x + 40, self._cy(654), self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 15),
            "attack_range": Stepper(self.x + 260, self._cy(654), self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 5),
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
        return Stepper(self.x + 40, self._cy(688 + index * 32), self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 0, 99)

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

    def _shows_capabilities_and_effects(self):
        """Capacites/Effets are editable for item, mob, and PNJ cards --
        not a plain decorative/special object (nothing reads a world
        object's "capabilities"/"effects" yet). One dispatch point instead
        of re-testing the 3-way flag combination separately in
        handle_event and render."""
        return self.card_kind in ("item", "mob", "pnj")

    def _sound_slot_keys(self):
        """Every sound row that applies to the currently loaded card --
        deliberately one slot per ACTION the card can actually trigger, not
        a fixed use/place/destroy triad: an item gets "use" (see
        Explorator._use_interact_item's effects branch), plus "throw" once
        "Lancable" is enabled (the throw itself, see the same method's
        throwable branch -- distinct from "use" since a throwable item
        never goes through the effects branch at all); a mob gets one row
        PER STATE in self.mob_states (ENEMY_ANIMATIONS for an enemy, idle/
        move for an animal -- see entities.py's Enemy.take_damage/
        _on_loop_frame_advanced for which of these are actually wired to
        play yet, "idle"/"movement" are stored but currently inert, no
        looping-sound mechanism exists), plus "place"/"destroy" since a mob
        is placed/destroyed exactly like any other OBJECT_TYPES card; a
        plain object gets "place"/"destroy", plus "interact" once
        "Interagible" is enabled OR the type is hardcoded "linkable" (a
        button, gate, or wall -- these trigger by being walked onto/opened,
        never through the "Interagible" checkbox at all, see
        ObjectManager._activate_button/check_button_trigger); a PNJ keeps
        the original use/place/destroy triad (per-role sounds are a
        possible future extension, not built this pass). Empty for nothing
        loaded."""
        if self.card_kind == "item":
            keys = ["use"]
            if self.throwable_enabled:
                keys.append("throw")
            return keys
        if self.card_kind == "mob":
            return list(self.mob_states) + ["place", "destroy"]
        if self.card_kind == "pnj":
            return ["use", "place", "destroy"]
        if self.card_kind == "object":
            keys = ["place", "destroy"]
            if self.interactable or OBJECT_TYPES.get(self.type_id, {}).get("linkable"):
                keys.append("interact")
            return keys
        return []

    def _sound_slot_label(self, key):
        return "Son : " + self._SOUND_LABEL_OVERRIDES.get(key, key.replace("_", " ").title())

    def _load_sounds(self, sounds):
        self.card_sounds = dict(sounds)

    def _cycle_sound(self, key, step):
        options = [None] + self._available_sound_files
        current = self.card_sounds.get(key)
        index = options.index(current) if current in options else 0
        self.card_sounds[key] = options[(index + step) % len(options)]

    def _load_pitch(self, sound_pitch):
        self.pitch_enabled = {key: True for key in sound_pitch}
        self.pitch_range = {key: list(value) for key, value in sound_pitch.items()}

    def _toggle_pitch(self, key):
        """Flips random-pitch on/off for `key` -- newly enabling it (no
        saved range from a previous session) seeds DEFAULT_PITCH_RANGE
        rather than starting at a degenerate [x, x] (which would just play
        at pitch x always, no randomness at all -- pointless default)."""
        self.pitch_enabled[key] = not self.pitch_enabled.get(key, False)
        if self.pitch_enabled[key] and key not in self.pitch_range:
            self.pitch_range[key] = list(self.DEFAULT_PITCH_RANGE)

    def _pitch_value_to_x(self, track, value):
        span = self.PITCH_SLIDER_MAX - self.PITCH_SLIDER_MIN
        frac = max(0.0, min(1.0, (value - self.PITCH_SLIDER_MIN) / span))
        return track.x + frac * track.width

    def _pitch_x_to_value(self, track, x):
        frac = max(0.0, min(1.0, (x - track.x) / max(1, track.width)))
        return self.PITCH_SLIDER_MIN + frac * (self.PITCH_SLIDER_MAX - self.PITCH_SLIDER_MIN)

    def _build_mob_stats(self):
        """The stats dict to persist for an enemy mob, or None for
        anything else (animal/object/item/pnj have no stats concept) --
        pulled out of _try_save so that method's own item-vs-object
        dispatch doesn't have this whole computation sitting inline in the
        middle of it."""
        if not (self.is_mob and self.mob_kind == "enemy"):
            return None
        # Pass the exact original float through UNCHANGED whenever the
        # user never actually moved that stepper (the rounded editable
        # value still matches round(raw)) -- see mob_aggro_range's own
        # comment in __init__ for why: otherwise saving for any unrelated
        # reason would silently truncate 1.2 to 1 every time.
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
        return stats

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
        sounds = {key: path for key, path in self.card_sounds.items() if path}
        # A pitch range only means anything for a key that ALSO has a real
        # sound assigned and its own toggle enabled -- an orphaned range
        # left over from a sound that's since been cleared (see
        # _cycle_sound) never gets persisted.
        sound_pitch = {
            key: self.pitch_range[key] for key in sounds
            if self.pitch_enabled.get(key) and key in self.pitch_range
        }

        try:
            if self.card_kind == "item":
                if is_builtin_item(self.item_id):
                    update_item_overrides(self.item_id, capabilities, effects, sounds, sound_pitch)
                else:
                    update_item(
                        self.item_id, self.name, self.item_slot, self.icon_path, self.icon_rect,
                        capabilities=capabilities, effects=effects, sounds=sounds, sound_pitch=sound_pitch,
                    )
            else:
                update_type_mechanics(
                    self.type_id,
                    blocks_movement=self.blocks_movement,
                    cell_modes=self._current_cell_modes(),
                    interactable=self.interactable,
                    lockable=self.lockable,
                    capabilities=capabilities,
                    stats=self._build_mob_stats(),
                    effects=effects,
                    sounds=sounds,
                    sound_pitch=sound_pitch,
                )
        except ValueError as exc:
            self.status_text = str(exc)
            return None
        self.status_text = f"'{self.name}' mise a jour."
        return self.item_id if self.item_id is not None else self.type_id

    def handle_event(self, event):
        if self._handle_resize_event(event):
            return None

        # The PNJ preview's click-drag-to-rotate gesture and the scrollbar
        # thumb drag both span multiple event types (unlike everything else
        # in this panel, which only ever reacts to a single
        # MOUSEBUTTONDOWN) -- handled first, before the MOUSEBUTTONDOWN-only
        # gate below short-circuits every other event type. At most one of
        # the two is ever active at once (both require a fresh
        # MOUSEBUTTONDOWN to start, see below).
        if self.is_pnj and self._pnj_dragging_direction:
            if event.type == pygame.MOUSEMOTION:
                self._update_pnj_drag(event)
                return None
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._pnj_dragging_direction = False
                return None

        if self._scrollbar_dragging:
            if event.type == pygame.MOUSEMOTION:
                track = self._scrollbar_track_rect()
                max_scroll = self._max_scroll()
                if max_scroll > 0 and track.height > 0:
                    rel = (event.pos[1] - track.y) / track.height
                    self.scroll_offset = max(0, min(max_scroll, round(rel * max_scroll)))
                return None
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._scrollbar_dragging = False
                return None

        # A pitch slider handle drag, same multi-event shape as the two
        # above -- (key, "lo"/"hi") identifies which row/handle. Dragging
        # "lo" past "hi" (or vice versa) clamps against the OTHER handle's
        # current value rather than crossing it, so the range can never
        # invert.
        if self._pitch_dragging is not None:
            key, handle = self._pitch_dragging
            if event.type == pygame.MOUSEMOTION:
                rects = self._pitch_rects.get(key)
                current = self.pitch_range.get(key, list(self.DEFAULT_PITCH_RANGE))
                if rects is not None:
                    value = self._pitch_x_to_value(rects["track"], event.pos[0])
                    if handle == "lo":
                        current[0] = min(value, current[1])
                    else:
                        current[1] = max(value, current[0])
                    self.pitch_range[key] = current
                return None
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._pitch_dragging = None
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

        if self._max_scroll() > 0 and self._scrollbar_thumb_rect().collidepoint(event.pos):
            self._scrollbar_dragging = True
            return None

        # Everything below reads/writes a row inside the scrollable band --
        # gated on the click actually landing within _viewport_rect (not
        # just within the row's own rect), so a row scrolled out of view
        # can never be hit through the pinned preview/title or Enregistrer
        # areas it might geometrically overlap once shifted by
        # scroll_offset (see _cy's own docstring).
        if not self._viewport_rect().collidepoint(event.pos):
            if self._save_rect.collidepoint(event.pos):
                return self._try_save()
            return None

        if self.card_kind == "object":
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

        if self._shows_capabilities_and_effects():
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

        for key in self._sound_slot_keys():
            rects = self._sound_rects.get(key)
            if rects is None:
                continue
            if rects["prev"].collidepoint(event.pos):
                self._cycle_sound(key, -1)
                return None
            if rects["next"].collidepoint(event.pos):
                self._cycle_sound(key, 1)
                return None
            if rects["play"].collidepoint(event.pos):
                filename = self.card_sounds.get(key)
                if filename:
                    pitch = None
                    if self.pitch_enabled.get(key):
                        lo, hi = sorted(self.pitch_range.get(key, self.DEFAULT_PITCH_RANGE))
                        if hi > lo:
                            pitch = random.uniform(lo, hi)
                    SoundManager().play_path(filename, pitch=pitch)
                return None
            # The pitch toggle only does anything for a row that actually
            # has a sound assigned -- randomizing the pitch of "Aucun" is
            # meaningless, so the button isn't even drawn otherwise (see
            # _render_sounds), but the click-gate is repeated here too in
            # case a stale click lands on a rect from a since-cleared row.
            if self.card_sounds.get(key) and rects["pitch_toggle"].collidepoint(event.pos):
                self._toggle_pitch(key)
                return None
            pitch_rects = self._pitch_rects.get(key)
            if pitch_rects is not None:
                if pitch_rects["lo"].collidepoint(event.pos):
                    self._pitch_dragging = (key, "lo")
                    return None
                if pitch_rects["hi"].collidepoint(event.pos):
                    self._pitch_dragging = (key, "hi")
                    return None
                if pitch_rects["track"].collidepoint(event.pos):
                    # A click on the track itself (not precisely on either
                    # handle) jumps the NEAREST handle there and starts
                    # dragging it from there -- more forgiving than forcing
                    # a pixel-precise grab on a 10px-wide handle.
                    value = self._pitch_x_to_value(pitch_rects["track"], event.pos[0])
                    lo, hi = self.pitch_range.get(key, self.DEFAULT_PITCH_RANGE)
                    handle = "lo" if abs(value - lo) <= abs(value - hi) else "hi"
                    current = self.pitch_range.setdefault(key, list(self.DEFAULT_PITCH_RANGE))
                    if handle == "lo":
                        current[0] = min(value, current[1])
                    else:
                        current[1] = max(value, current[0])
                    self._pitch_dragging = (key, handle)
                    return None

        return None

    def render(self, screen):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        self.border.draw(screen, panel_rect)

        if self.type_id is None and self.item_id is None:
            hint = self.small_font.render("Glisse une carte ici pour l'editer", True, (150, 150, 150))
            screen.blit(hint, (self.x + 20, self.y + 16))
            self._draw_resize_handle(screen)
            return

        # _layout() rebuilds every cached content rect (_blocks_rect,
        # _sound_rects, _save_rect, ...) from self.x/y/width/height/
        # scroll_offset -- previously only re-run on move() (a PanelFrame
        # drag), which silently left every rect stale after a resize-handle
        # drag (self.width/height changing without a matching move()) or a
        # scroll (scroll_offset changing without one either, see _cy).
        # Called here, every frame, rather than hunting down every event
        # path that could invalidate it -- render() always runs once per
        # frame regardless of events (see Creator.run()), so this keeps
        # rects correct for the NEXT event with at most one frame of lag,
        # cheap enough (plain Rect arithmetic) to not matter.
        self._clamp_scroll()
        self._layout()

        title = self.font.render(f"Mecaniques -- {self.name}", True, (255, 255, 255))
        screen.blit(title, (self.x + 20, self.y + 16))
        self.border.draw_centered_label(screen, self._clear_rect, self.small_font, "Vider")

        self._render_preview(screen)

        # Everything below is the scrollable band -- clipped to
        # _viewport_rect so a row scrolled past the top/bottom never bleeds
        # into the pinned preview/title above or the pinned Enregistrer
        # button below. previous_clip is restored afterward rather than
        # cleared to None outright, in case a caller further up already had
        # its own clip active.
        previous_clip = screen.get_clip()
        screen.set_clip(self._viewport_rect())

        if self.card_kind == "mob":
            self._render_mob_info(screen)
        elif self.card_kind == "pnj":
            self._render_pnj_info(screen)
        elif self.card_kind == "object":
            self._render_object_info(screen)
        else:
            item_label = self.small_font.render("Item d'inventaire", True, (200, 200, 200))
            screen.blit(item_label, (self.x + 20, self._cy(244)))

        if self._shows_capabilities_and_effects():
            self._render_capabilities(screen)
            self._render_effects(screen)

        if self.is_mob and self.mob_kind == "enemy":
            self._render_mob_stats_editing(screen)

        self._render_sounds(screen)

        screen.set_clip(previous_clip)
        self._render_scrollbar(screen)

        self.border.draw_centered_label(screen, self._save_rect, self.font, "Enregistrer")

        if self.status_text:
            status = self.small_font.render(self.status_text, True, (220, 220, 120))
            screen.blit(status, (self.x + 20, self._save_rect.y - 22))

        self._draw_resize_handle(screen)

    def _render_scrollbar(self, screen):
        if self._max_scroll() <= 0:
            return
        pygame.draw.rect(screen, (40, 40, 46), self._scrollbar_track_rect())
        pygame.draw.rect(screen, (150, 150, 150), self._scrollbar_thumb_rect())

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

    def _render_sounds(self, screen):
        """Sons section -- one row per _sound_slot_keys entry, each a
        filename cycled from _available_sound_files (< / > buttons, "Aucun"
        at the None end), a Jouer button that previews it immediately via
        SoundManager.play_path (through the row's own pitch range if
        enabled, so previewing actually demonstrates the randomization),
        and -- only once a real file is assigned -- a "Pitch" toggle. Once
        toggled on, a second line renders the double-handle range slider
        (see _render_pitch_slider)."""
        for key in self._sound_slot_keys():
            rects = self._sound_rects.get(key)
            if rects is None:
                continue
            label = self.small_font.render(self._sound_slot_label(key), True, (200, 200, 200))
            screen.blit(label, (rects["label"].x, rects["label"].y + 4))
            self.border.draw_centered_label(screen, rects["prev"], self.small_font, "<")
            self.border.draw_centered_label(screen, rects["next"], self.small_font, ">")
            current = self.card_sounds.get(key)
            display = current if current else "Aucun"
            if len(display) > 12:
                display = display[:10] + "..."
            name_surface = self.small_font.render(display, True, (230, 230, 230))
            screen.blit(name_surface, (rects["name"].x + 4, rects["name"].y + 4))
            self.border.draw_centered_label(screen, rects["play"], self.small_font, "Jouer")
            if current:
                pitch_label = "[x] Pitch" if self.pitch_enabled.get(key) else "[ ] Pitch"
                self.border.draw_centered_label(screen, rects["pitch_toggle"], self.small_font, pitch_label)

            pitch_rects = self._pitch_rects.get(key)
            if pitch_rects is not None:
                self._render_pitch_slider(screen, key, pitch_rects)

    def _render_pitch_slider(self, screen, key, rects):
        track = rects["track"]
        pygame.draw.rect(screen, (40, 40, 46), track, border_radius=4)
        lo, hi = self.pitch_range.get(key, self.DEFAULT_PITCH_RANGE)
        lo_x = self._pitch_value_to_x(track, lo)
        hi_x = self._pitch_value_to_x(track, hi)
        # The filled span between the two handles -- the actual range a
        # random pitch will be drawn from, at a glance.
        pygame.draw.rect(
            screen, (110, 150, 190), pygame.Rect(lo_x, track.y, max(1, hi_x - lo_x), track.height),
        )
        for handle in ("lo", "hi"):
            pygame.draw.rect(screen, (220, 220, 220), rects[handle], border_radius=2)
        readout = self.small_font.render(f"x{lo:.2f} - x{hi:.2f}", True, (200, 200, 200))
        screen.blit(readout, (track.right + 8, track.centery - readout.get_height() / 2))

    def _render_object_info(self, screen):
        """Archetype label + mechanics checkboxes (blocks_movement/
        cell_modes/interactable/lockable) -- plain decorative/special
        OBJECT_TYPES cards only (card_kind == "object"), extracted out of
        render()'s own kind dispatch for symmetry with _render_mob_info/
        _render_pnj_info."""
        type_label = self.small_font.render(f"Archetype : {ARCHETYPES.get(self.archetype, {}).get('label', self.archetype)}", True, (200, 200, 200))
        screen.blit(type_label, (self.x + 20, self._cy(244)))

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

    def _render_mob_info(self, screen):
        """Type + Etats -- always informational (a mob's animation set is
        a fixed constant, never partial like a custom PNJ's, so there's no
        completeness notion to check). Stats/loot editing for an enemy is
        rendered separately, see _render_mob_stats_editing -- not shown
        twice as both read-only text and editable steppers."""
        kind_label = "Ennemi" if self.mob_kind == "enemy" else "Animal"
        type_label = self.small_font.render(f"Type : Mob ({kind_label})", True, (200, 200, 200))
        screen.blit(type_label, (self.x + 20, self._cy(244)))

        states_label = self.small_font.render(f"Etats : {', '.join(self.mob_states)}", True, (200, 200, 200))
        screen.blit(states_label, (self.x + 20, self._cy(266)))

        if self.mob_kind != "enemy":
            note = self.small_font.render(
                "Aucune stat pour un animal -- seuls les ennemis en ont.", True, (150, 150, 150)
            )
            screen.blit(note, (self.x + 20, self._cy(288)))

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
        screen.blit(type_label, (self.x + 20, self._cy(244)))
        pack_label = self.small_font.render(f"Pack : {self.pnj_entity_pack}", True, (150, 150, 150))
        screen.blit(pack_label, (self.x + 20, self._cy(260)))

        tagged, _missing = action_direction_coverage(self.pnj_entity_pack, self.pnj_wander_actions.get(self.preview_state))
        coverage = f"{len(tagged)}/{len(NPC_DIRECTIONS)} directions taguees"
        direction_label = self.small_font.render(
            f"Direction : {self.pnj_direction} ({coverage}) -- glisser sur le sprite pour tourner",
            True, (200, 200, 200),
        )
        screen.blit(direction_label, (self.x + 20, self._cy(276)))

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
