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

**One giant card, not a menu** (_render_card_background, confirmed with the
user through several iterations -- see done.txt/this conversation's history
for the ones that undershot): while a card is loaded, this panel's ENTIRE
background is that card's own backing (assets/cards/card.png, the same
plain flat-color/border art CardRenderer stretches for every other card
view -- safe to stretch non-uniformly to any panel shape, no fine detail to
distort) stretched to cover the whole panel, replacing the generic
BorderManager panel background entirely. Every section below -- the shared
preview/animation-state slider, object mechanics OR Proprietes -- is drawn
AS A ZONE of that one continuous card, not as a separate control panel
glued below a small card portrait. Applies to every
card_kind uniformly (object/tile_decor/tile_special included -- earlier
versions of this only gave the big-card treatment to item/mob/pnj, missed
in review). Sized to occupy a large fraction of a typical window
(STANDARD_WIDTH/HEIGHT), resizable further.

**Proprietes / Dechirer / Coller** (_tearable_fragments/_render_properties,
see core.data.cards.PROPERTY_CARD_PREFIX/core.world.object_manager.fuse_card):
capacites, effets, and -- for an enemy mob -- stats are no longer edited in
place. They're shown for item, mob, and pnj cards (not a plain decorative/
special object -- nothing reads a world object's "capabilities"/"effects"
yet) as one row per fragment; hovering the Proprietes zone highlights
whichever row is vertically closest to the cursor (proximity, not a
pixel-precise hit-test), and a left-click-drag from anywhere in the zone
locks that row in as the tear target -- horizontal drag distance from the
press point maps directly to self._tear_progress in [0, 1] (position-based
so it tracks the cursor exactly, forward or backward, paused or not),
releasing at progress==1.0 commits the tear (_try_tear: consumes 1
exemplaire, credits a standalone property card), releasing earlier cancels,
nothing consumed either way. While dragging, render() routes through
_render_tearing instead of the normal frame: the WHOLE Forge (this panel's
own giant-card background plus every zone drawn on it -- not a small card
popped up next to the row, confirmed with the user after an earlier
version did exactly that) is rendered once to an offscreen surface, then
actually split along a jagged, deterministic boundary via
core.editor.ui.card_tear.create_tear_state(scratch_surface, cut_y,
progress) -- real pixels moved, never a pre-baked frame set or a shape
drawn over the card (see that module's own docstring for the full
contract -- it knows nothing about capacites/gameplay, only pixels). Only
the top piece drifts/rotates (following the drag direction, +x/+y); the
bottom piece never moves at all, keeping the torn-out property legible for
the whole gesture. On a committed release, the top piece is launched into
a separate post-tear THROW (card_tear.start_throw/update_throw/
blit_throw): flies off along a vector derived from the player's own
cursor velocity at the moment of release (self._tear_velocity, resampled
every MOUSEMOTION during the drag -- see handle_event), shrinking and
fading to nothing over card_tear.THROW_DURATION -- unchanged from before
this module's own Dechirer gesture existed. Separately, the bottom
piece -- stationary the whole time, everything from the target property
row downward -- is cut a SECOND time at that row's own bottom edge (see
_start_below_property_burn), isolating just the zone BELOW the extracted
property (any other property rows still below it, down to the panel's own
bottom edge); that lower zone catches fire and burns away in place
(core.editor.ui.card_burn.BurnAnimation) while the property row itself
stays exactly as it always did, drawn by the normal Forge content every
frame -- never thrown, never burned. Both the throw and the burn are
purely visual flourishes, entirely time-based (via update(dt)) since
there's no more mouse input driving either one once the button is
released -- the gameplay consequence (_try_tear) has already happened by
the time either starts.
Dropping a property card onto the shared preview
sprite (preview_rect, see below) glues it onto whatever's loaded instead
(preview_property_drop/fuse_card), always producing a brand new
independent card, never mutating the original -- the same property card
can ALSO be dropped directly onto another owned card in the Collection
itself (Creator._try_fuse_onto), without opening that card in the Forge
first.

No buttons drive any of this anymore (confirmed with the user: "rien dans
des mecaniques parfaitement developpe ne devrait utiliser de boutons").
Every mechanics toggle (blocks_movement/interactable/lockable) persists
itself immediately on click (_try_save, called directly from
handle_event) instead of waiting for a separate save action -- sounds
moved to core.editor.ui.sound_box_panel.SoundBoxPanelUI (see its own
docstring), and dropping to unload the loaded card back out of the panel
(dragging from the preview sprite and releasing outside the panel's own
bounds) replaced the old "Vider" button.

**Unified preview** (_render_preview/_preview_current_frames/
_preview_state_options): a single animated preview area (now just the top
zone of the giant card, see above -- was previously this panel's only
visual before Proprietes existed) replaces what used to be a
permanently-static 48x48 icon shown regardless of card kind.
- PNJ: the vertical animation-state slider (see
  _render_preview_state_slider below) lists whichever wander_actions role
  is configured, a looping animation of that role's tagged sprite for the
  selected direction (see object_manager.load_npc_frames/NPC_DIRECTIONS),
  and click-drag directly on the preview itself (not the slider) to cycle
  through directions (_pnj_dragging_direction/_update_pnj_drag) -- the
  only card kind with a direction concept at all.
- Mob: the same slider lists its fixed animation set (ENEMY_ANIMATIONS for
  an enemy, idle/move for an animal), looping through
  object_manager.load_enemy_frames/load_animal_frames.
- Plain object with more than one frame (torch, lilchest...): no slider
  (nothing to choose between), just an automatic loop through
  object_manager.load_object_frames.
- Item: a single static frame (its own icon) -- nothing to loop, no slider.
update(dt) advances preview_frame whenever the current selection has more
than one frame, called every frame from Creator.run() regardless of what's
loaded (a no-op otherwise) -- the one thing in this panel that needs real
elapsed time rather than just reacting to a click.

Mob stats (see Proprietes above) are enemy-only -- animals carry no stats at
all. active_attack_frames (the attack swing's damage window) is never
exposed via Dechirer/Coller, passed through unchanged on save so tearing/
gluing a mob's stats can't silently break combat timing. No write API exists
for a PNJ's entity_pack/wander_actions, or for creating a new mob type -- those
stay SpriteEditorPanelUI's job / unbuilt, respectively.
"""

import pygame

from core.editor.ui.mixins import _ResizableCornerMixin
from core.editor.ui.card_renderer import CardRenderer
from core.editor.ui import card_tear
from core.editor.ui import card_burn
from core.ui.widgets import BorderManager
from core.ui.fonts import get_font
from core.world.object_manager import (
    OBJECT_TYPES, ITEM_DEFINITIONS, ARCHETYPES, CELL_MODES, ENEMY_ANIMATIONS, mob_kind as _mob_kind,
    NPC_DIRECTIONS, load_npc_frames, load_enemy_frames, load_animal_frames, load_object_frames,
    action_direction_coverage,
    update_type_mechanics, update_item_overrides, update_item, is_builtin_item,
    extract_property_payload, fuse_card,
)
from core.data.cards import (
    resolve_card_sprite, parse_property_card_id, property_label, register_torn_property,
)

CELL_MODES_ARCHETYPES = ("sol", "mur", "porte")


class MechanicsPanelUI(_ResizableCornerMixin):
    # This panel IS one giant card while a card is loaded (see
    # _render_card_background) -- its own width/height must always match
    # card.png's real aspect ratio (CardRenderer.BACKING_SIZE, 64:96,
    # portrait), never stretched, confirmed with the user. HEIGHT is the
    # driving dimension (STANDARD_HEIGHT/MAX_HEIGHT chosen directly, a
    # large fraction of a typical 1280x720 window -- core.data.settings.
    # DEFAULT_RESOLUTION); WIDTH is always DERIVED from it (see
    # _card_width_for_height/_handle_resize_event's override below, which
    # only ever reads vertical drag movement -- dragging the resize handle
    # still works exactly like every other panel's, it just no longer has
    # an independent horizontal axis to stretch).
    STANDARD_HEIGHT = 600
    MAX_HEIGHT = 850
    STANDARD_WIDTH = round(STANDARD_HEIGHT * CardRenderer.BACKING_SIZE[0] / CardRenderer.BACKING_SIZE[1])
    MAX_WIDTH = round(MAX_HEIGHT * CardRenderer.BACKING_SIZE[0] / CardRenderer.BACKING_SIZE[1])
    # Panel-relative y where the scrollable content area begins (right below
    # the shared preview + its animation-state slider) -- every row at or
    # below this, across every card_kind, goes through _cy() instead of
    # `self.y + N` directly, so self.scroll_offset shifts it uniformly. The
    # preview, the title, and the bottom-pinned status text all stay
    # pinned (never scroll) by continuing to use `self.y`/`self.height`
    # directly, never _cy().
    CONTENT_TOP = 244
    SCROLLBAR_WIDTH = 10
    WHEEL_STEP_PX = 48
    CELL_MODE_COLORS = {"block": (190, 90, 90), "behind": (110, 190, 110), "front": (100, 150, 220)}
    # Every plain text label blitted directly onto this panel's own
    # giant-card background (title/info lines/section headers/property
    # rows/sounds/loot -- NOT button-chrome text, which goes through
    # BorderManager.draw_centered_label's own dark button skin and stays
    # readable regardless) -- confirmed with the user: black reads far
    # better than the old light-grey palette against card.png's blue.
    CARD_TEXT_COLOR = (20, 20, 20)
    CARD_TEXT_MUTED_COLOR = (70, 70, 70)
    # The two dashed cut-line indicators on a hovered/targeted property row
    # (see _render_properties) -- grey for the tear (paper, colorless) at
    # the row's own top edge, warm orange for the burn (fire) at its
    # bottom edge, matching which piece actually gets which treatment
    # (top thrown away, bottom below the row burns -- see
    # _start_tear_resolution).
    TEAR_LINE_COLOR = (90, 90, 90)
    BURN_LINE_COLOR = (190, 90, 20)
    GRID_MAX_PX = 140
    STEP_BUTTON_SIZE = 24
    COUNT_DISPLAY_WIDTH = 50
    # Proprietes zone (Dechirer, see _tearable_fragments/_render_properties)
    # -- one plain text row per tearable fragment, drawn straight onto this
    # panel's own giant-card background (see _render_card_background) right
    # below whatever kind-specific info precedes it. A small caption line
    # first (PROPERTIES_HEADER_HEIGHT), then PROPERTY_ROW_HEIGHT per row.
    PROPERTIES_HEADER_HEIGHT = 20
    PROPERTY_ROW_HEIGHT = 30
    # Horizontal drag-scrub -> progress (see the multi-event tear-drag
    # handling in handle_event): position-based, not time/velocity-based,
    # so the animation always exactly tracks the cursor -- fast, slow,
    # reversed, paused mid-drag, all read straight off the current x
    # relative to where the drag started. TEAR_DRAG_TOTAL_PX is how far
    # (in screen px) the cursor has to travel right to reach progress=1.0
    # (fully torn) -- see core.editor.ui.card_tear.create_tear_state,
    # which does the actual procedural pixel-splitting from this progress
    # value, no pre-baked frames of any kind.
    TEAR_DRAG_TOTAL_PX = 160
    # Canonical role order for the PNJ preview's animation-state slider --
    # only roles actually present in a given PNJ's own wander_actions are
    # shown (see _pnj_available_roles), same "idle"/"move" mandatory + "sitting"/
    # "laying"/"run" independently optional split as core.world.entities.Mob
    # itself documents (its entity-pack-backed rest/posture chain).
    PNJ_ROLES = ("idle", "move", "sitting", "laying", "run")
    PREVIEW_ANIMATION_SPEED = 0.2  # matches core.world.entities.Mob's own entity-pack ANIMATION_SPEED
    PNJ_DRAG_STEP_PX = 24  # horizontal pixels dragged per direction step

    def __init__(self, x, y, renderer):
        self.x = x
        self.y = y
        self.width = self.STANDARD_WIDTH
        self.height = self.STANDARD_HEIGHT
        self._resizing = False
        self._resize_last_pos = None
        # Shared with Creator/CardPanelUI -- same
        # assets/cards/card.png backing/Card/sprite caches, so a card
        # loaded here is unmistakably the same object as everywhere else
        # it's shown. card_backing() (the raw, unscaled backing image) is
        # what this panel stretches over its own whole body -- see
        # _render_card_background -- get_card()/get_surface() (the small/
        # list-thumbnail composite) stay CardPanelUI's own
        # thing, never used here.
        self._renderer = renderer

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
        # Only ever shown/editable for a card whose `directions` (see
        # object_manager._build_visual_fields) is non-empty -- meaningless
        # otherwise, see self.has_directions/_render_object_info. "auto" or
        # "manual" (never None once has_directions is True -- open() loads
        # an unset saved value as "manual", the safer default).
        self.direction_mode = None

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
        # (_render_mob_info), plus real stats (torn/glued via the
        # Proprietes section, see _tearable_fragments/_render_properties --
        # self.mob_stats is read-only display data here, still read by
        # _try_save/_build_mob_stats so saving passes it through unchanged,
        # but nothing in this panel edits it directly anymore).
        self.mob_kind = None
        self.mob_states = ()
        self.mob_stats = {}

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
        # Any OTHER capability kind the loaded card carries (e.g.
        # placable_on_floor/placable_on_wall -- see object_manager's own
        # PLACABLE_CAPABILITY_KEYS) that this panel has no dedicated toggle
        # for -- see _load_capabilities. _try_save merges this back in
        # unchanged, same "pass through what you don't actively edit"
        # spirit as active_attack_frames on a mob's own stats (see that
        # field's own comment): without this, Enregistrer would silently
        # drop any capability this UI doesn't know how to render, since it
        # only ever reconstructs "capabilities" from throwable_enabled/
        # explosive_enabled above.
        self._passthrough_capabilities = {}

        # Sons -- {"use"/"place"/"destroy": "filename.wav"|None}, same
        # generic vocabulary as capabilities/effects above (see
        # core.data.cards.Card.sounds/object_manager's "sounds" mechanics
        # field). PASSTHROUGH ONLY now (confirmed with the user): editing
        # sounds moved entirely to core.editor.ui.sound_box_panel.
        # SoundBoxPanelUI -- this panel still loads them at open() and
        # writes them back unchanged at _try_save() (same "preserve what
        # you don't actively edit" spirit as _passthrough_capabilities
        # above), it just no longer renders or lets the player touch them,
        # so Enregistrer here can never silently wipe a card's sounds.
        self.card_sounds = {"use": None, "place": None, "destroy": None}

        # Pitch -- {key: True/False} whether random-pitch is on for that
        # sound slot, {key: [min, max]} its range when it is (see
        # core.data.cards.Card.sound_pitch/core.data.sound_manager.
        # play_card_sound). Same passthrough-only status as card_sounds
        # above -- editing lives in SoundBoxPanelUI now.
        self.pitch_enabled = {}
        self.pitch_range = {}

        # Scrollable-content viewport state (see CONTENT_TOP's own
        # docstring) -- pixel-based, not row-based, since rows here are
        # variable-height/variable-count depending on card_kind, unlike
        # core.ui.widgets.RoomBrowser's uniform row list.
        self.scroll_offset = 0
        self._scrollbar_dragging = False

        self.status_text = ""
        self.border = BorderManager()
        self.font = get_font("button", 16)
        self.title_font = get_font("title", 16)
        self.small_font = get_font("text", 13)

        self._blocks_rect = None
        self._interactable_rect = None
        self._lockable_rect = None
        self._direction_mode_rect = None
        # True from a MOUSEBUTTONDOWN on the shared preview sprite until
        # the matching MOUSEBUTTONUP -- see handle_event's own multi-event
        # block for what it drives (PNJ direction-drag, and "drag the
        # card back out to unload it", the gesture that replaced the old
        # "Vider" button).
        self._preview_dragging = False
        # True from a MOUSEBUTTONDOWN on the animation-state slider's own
        # track until the matching MOUSEBUTTONUP -- see handle_event's
        # multi-event block for the drag/snap behavior it drives.
        self._preview_slider_dragging = False
        # Dechirer's hover+drag-scrub gesture state (see _tearable_fragments/
        # the multi-event tear-drag handling in handle_event) -- (category,
        # kind) locked in at MOUSEBUTTONDOWN, or None while idle/just
        # hovering. Reset by open()/clear() same as every other per-card
        # edit-state field.
        self._tear_target = None
        self._tear_drag_start_x = None
        self._tear_progress = 0.0
        # Cursor velocity tracking for the whole drag (px/sec, resampled
        # every MOUSEMOTION -- see handle_event) -- read once, at the
        # moment of a committed release, to launch the post-tear throw
        # (see card_tear.start_throw). NOT reset by open()/clear() (unlike
        # the fields above): a throw already in flight is a self-contained
        # visual with its own captured surface, independent of whatever
        # card happens to be loaded afterward.
        self._tear_velocity = (0.0, 0.0)
        self._tear_last_sample_pos = None
        self._tear_last_sample_time = None
        # The top piece's own surface/screen rect from the LAST drag frame
        # (see _render_tearing) -- reused as the throw's exact starting
        # point so there's no visible jump between the last drag frame and
        # the first throw frame.
        self._tear_last_top_surface = None
        self._tear_last_top_rect = None
        self._tear_throw = None
        # The (stationary) bottom piece's own surface/LOCAL anchor from the
        # LAST drag frame (see _render_tearing -- LOCAL, i.e. relative to
        # the panel's own (0, 0), same space _tear_cut_y/_property_row_rect
        # already use, not a screen rect like the top piece's own capture
        # above). Reused at commit time to cut a SECOND time, at the
        # target property row's own BOTTOM edge rather than its top (see
        # _start_below_property_burn) -- isolating just the zone below the
        # extracted property to hand to card_burn.BurnAnimation. The
        # property row itself is deliberately never part of this: it stays
        # exactly as before, drawn by the normal Forge content every
        # frame, never thrown or burned.
        self._tear_last_bottom_surface = None
        self._tear_last_bottom_anchor = (0, 0)
        # The target property row's own bottom edge, captured every frame
        # in the SAME local-coordinate window as cut_y above (see
        # _render_tearing) -- MUST be read there, not recomputed later
        # from handle_event's MOUSEBUTTONUP branch, where self.x/self.y
        # are back to their real screen position (see that comment for
        # the bug this avoids).
        self._tear_last_property_row_bottom = None
        # Set on a committed release (see handle_event's MOUSEBUTTONUP
        # branch) from card_burn.BurnAnimation -- NOT reset by open()/
        # clear() (unlike the fields above): a burn already in progress is
        # a self-contained visual with its own captured surface,
        # independent of whatever card happens to be loaded afterward.
        # _tear_burn_origin is the fixed screen position it burns at (this
        # piece never moves, unlike the thrown top piece).
        self._tear_burn = None
        self._tear_burn_origin = (0, 0)
        # True from the moment a tear commits until the isolated property
        # is actually collected (see _start_tear_resolution/handle_event's
        # own gate) -- render()/handle_event both check this FIRST, before
        # anything else, so the isolated property takes over the whole
        # panel for as long as this stays True. NOT reset by open()/clear()
        # either, same "self-contained, independent of whatever's loaded"
        # reasoning as _tear_throw/_tear_burn above -- confirmed with the
        # user: it has to keep waiting to be clicked even if a different
        # card gets opened in the meantime.
        self._tear_resolving = False
        # ("tear", base_card_id, property_card_id) computed by _try_tear
        # at commit time (see _start_tear_resolution) but not RETURNED to
        # Creator -- and so not actually consumed/credited into
        # card_collection -- until the player clicks to collect (see
        # handle_event). Can legitimately be None (an already-documented
        # _try_tear failure case, "shouldn't normally happen") without
        # that meaning nothing is pending -- _tear_resolving above is the
        # actual signal, this is just what to hand back on a successful
        # click.
        self._tear_pending_result = None
        # The isolated property's own pixels/screen position -- cropped
        # from the target property row alone (see _start_tear_resolution),
        # never animated, always static once set. What clicking within
        # _tear_property_rect() actually collects.
        self._tear_property_surface = None
        self._tear_property_origin = (0, 0)
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
        self._tear_target = None
        self._tear_drag_start_x = None
        self._tear_progress = 0.0

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
            self.has_directions = False
            self.direction_mode = None
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

        # A single "mob" flag now covers what used to be split across
        # "animal"/"enemy"/"npc" -- entity-pack-backed (is_pnj below) is
        # checked first since it's mutually exclusive with the flat-frame
        # kind here (see core.world.entities.Mob's own frame-source
        # dispatch, the same rule this mirrors). mob_kind ("enemy" vs
        # "animal") is derived from ENEMY_FOLDERS membership -- the frame-
        # SOURCE that actually exists on disk, not from stats content (a
        # mob given aggro_range/attack_range via the Forge without a
        # matching ENEMY_FOLDERS entry would otherwise crash
        # load_enemy_frames below; see Mob.__init__'s own identical
        # reasoning) -- today this is exactly the old "enemy" flag's set
        # (skeleton1/skeleton2), so existing content is unaffected.
        is_pnj = bool(config.get("entity_pack"))
        # A flat-frame mob (animal/enemy) always has a real file-path
        # "asset" (load_animal_frames/load_enemy_frames both assume that
        # shape unconditionally) -- a custom card's asset is always a
        # tileset-region dict instead. object_manager.fuse_card now
        # refuses to glue "Comportement" onto a card with no entity_pack
        # at all (2026-08-19, a real crash before that guard existed), but
        # this still defends against opening an already-corrupted card
        # saved before the guard existed: falls through to card_kind
        # "object" (a safe, generic preview) instead of crashing.
        is_mob = bool(config.get("mob")) and not is_pnj and isinstance(config.get("asset"), str)
        if is_mob:
            self.mob_kind = _mob_kind(card_id)
            # Fixed sets -- animal/enemy are always fully hand-authored
            # Python entries, never partially registered like a custom
            # PNJ, so there's no per-card variation to read here, unlike
            # config.get("stats") below (skeleton1 vs skeleton2 differ).
            self.mob_states = ENEMY_ANIMATIONS if self.mob_kind == "enemy" else ("idle", "move")
            self.mob_stats = config.get("stats", {})
            if self.mob_kind == "enemy":
                self._preview_frames = load_enemy_frames(card_id)
            else:
                self._preview_frames = load_animal_frames(card_id)
            self.preview_state = self.mob_states[0] if self.mob_states else None
        else:
            self.mob_kind = None
            self.mob_states = ()
            # A PNJ can also carry a stats/aggressivity block (Coller-fused
            # from a true mob) even though it doesn't enter the aggro/
            # attack state machine in-game yet (see entities.Mob's own
            # class docstring on that scope limit) -- it's still a real,
            # tearable/re-fusable fragment and has to survive being loaded
            # here, or _tearable_fragments/_build_mob_stats below would
            # never see it (and _try_save would silently wipe it on the
            # very next unrelated edit).
            self.mob_stats = config.get("stats", {}) if is_pnj else {}

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
        # Whether this card even HAS direction-tagged frames at all (see
        # object_manager._build_visual_fields' `directions` param) decides
        # whether the auto/manuel toggle shows at all (see
        # _render_direction_mode) -- set once at crop time, in
        # SpriteEditorPanelUI, never here.
        self.has_directions = bool(config.get("directions"))
        self.direction_mode = (config.get("direction_mode") or "manual") if self.has_directions else None
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
        self._passthrough_capabilities = {
            key: value for key, value in capabilities.items() if key not in ("throwable", "explosive")
        }

    def _load_effects(self, effects):
        heal = next((effect for effect in effects if effect.get("kind") == "heal"), None)
        self.heal_enabled = heal is not None
        self.heal_amount = (heal or {}).get("amount", 1)

    def _pnj_available_roles(self):
        """PNJ_ROLES filtered to the ones this PNJ's own wander_actions
        actually names (an optional role like "run" simply isn't in the
        dict if never configured) -- these are the only options the
        animation-state slider shows, same "don't offer what isn't there"
        spirit as CELL_MODES_ARCHETYPES'
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

    def _preview_state_slider_rect(self):
        """The vertical track, to the right of the shared preview sprite --
        replaces the old row of horizontal tab buttons (confirmed with the
        user: click-drag the handle instead of clicking a button)."""
        return pygame.Rect(self.preview_rect.right + 16, self.preview_rect.y, 18, self.preview_rect.height)

    def _preview_state_positions(self):
        """(state_id, label, y) for every selectable option, evenly spread
        top-to-bottom along _preview_state_slider_rect's own height, in
        the same order _preview_state_options returns. Empty for a plain
        object/item (nothing to choose, see _preview_state_options)."""
        options = self._preview_state_options()
        if not options:
            return []
        track = self._preview_state_slider_rect()
        count = len(options)
        # track.bottom - 1, not track.y + track.height: Rect.collidepoint
        # excludes the rect's own bottom edge (half-open range), so landing
        # the last option exactly on it would make it unclickable.
        usable_bottom = track.bottom - 1
        positions = []
        for index, (state_id, label) in enumerate(options):
            y = track.centery if count == 1 else track.y + (usable_bottom - track.y) * index / (count - 1)
            positions.append((state_id, label, y))
        return positions

    def _preview_state_handle_rect(self):
        """The draggable handle -- "le cadre" -- currently sitting at
        self.preview_state's own snapped position on the track."""
        track = self._preview_state_slider_rect()
        current_y = track.centery
        for state_id, _label, y in self._preview_state_positions():
            if state_id == self.preview_state:
                current_y = y
                break
        return pygame.Rect(track.x - 5, current_y - 11, track.width + 10, 22)

    def _nearest_preview_state_at(self, y):
        """The state_id whose own track position is closest to `y` -- a
        click/drag anywhere on the track snaps to whichever name is
        nearest, not just a pixel-precise grab on the handle itself (same
        "forgiving track click" idiom as the Sons pitch slider used to
        use before that moved to SoundBoxPanelUI). None if nothing to
        choose from."""
        positions = self._preview_state_positions()
        if not positions:
            return None
        return min(positions, key=lambda entry: abs(entry[2] - y))[0]

    def _render_preview_state_slider(self, screen):
        """Track + tick per option + the draggable handle -- no-op for a
        plain object/item (_preview_state_positions is empty, see
        _preview_state_options), so the slider simply doesn't draw at
        all rather than showing an empty track."""
        positions = self._preview_state_positions()
        if not positions:
            return
        track = self._preview_state_slider_rect()
        pygame.draw.rect(screen, (40, 40, 46), track, border_radius=4)
        for state_id, label, y in positions:
            tick_color = self.CARD_TEXT_COLOR if state_id == self.preview_state else self.CARD_TEXT_MUTED_COLOR
            pygame.draw.line(screen, tick_color, (track.x, y), (track.right, y), 2)
            text = self.small_font.render(label, True, tick_color)
            screen.blit(text, (track.right + 6, y - text.get_height() / 2))
        handle = self._preview_state_handle_rect()
        pygame.draw.rect(screen, (220, 220, 220), handle, border_radius=4)
        pygame.draw.rect(screen, (90, 90, 90), handle, 2, border_radius=4)

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
        state-machine transitions like the real core.world.entities.Mob,
        this is a viewer, not a simulation.

        Also advances the post-tear throw and burn (see card_tear.
        update_throw/card_burn.BurnAnimation), independently of the
        preview -- either can easily still be playing after the player's
        already scrolled past/loaded a different card, so this never gets
        skipped by the early return below."""
        if self._tear_throw is not None:
            if not card_tear.update_throw(self._tear_throw, dt):
                self._tear_throw = None
        if self._tear_burn is not None:
            self._tear_burn.update(dt)
            if self._tear_burn.finished:
                self._tear_burn = None

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
        self._tear_target = None
        self._tear_drag_start_x = None
        self._tear_progress = 0.0
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
        pinned preview/animation-state slider down to just above the
        panel's own bottom-pinned status text. Both the render clip and
        the click-hit gate for every scrollable row go through this one
        rect, so "what's visible" and "what's clickable" can never drift
        apart."""
        top = self.y + self.CONTENT_TOP
        bottom = self.y + self.height - 66
        return pygame.Rect(self.x, top, self.width, max(0, bottom - top))

    def _content_height(self):
        """Total scrollable content height (panel-relative, i.e. as if
        scroll_offset were 0) for the currently loaded card -- always ends
        with Proprietes' own bottom now (see _content_bottom_offset). 0
        while empty (nothing to scroll)."""
        if self.type_id is None and self.item_id is None:
            return 0
        return self._content_bottom_offset() + 10 - self.CONTENT_TOP

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

    def _content_bottom_offset(self):
        """Panel-relative y where the scrollable content actually ends --
        always Proprietes' own bottom now. Used only by _content_height.
        Used to also be where a Cartes/butin loot table or the Sons
        section started, before butin became a tearable "loot" property
        like any other (see _tearable_fragments) and sounds moved to
        core.editor.ui.sound_box_panel.SoundBoxPanelUI -- confirmed with
        the user: both those old button-driven sections are gone now."""
        return self._properties_top_offset() + self._properties_section_height() + 20

    def _properties_top_offset(self):
        """Panel-relative y where the Proprietes section starts -- right
        after whatever kind-specific info precedes it (see module
        docstring), computed per card_kind rather than a single fixed
        offset sized for the worst case (an enemy's Type+Etats info): an
        item has NOTHING above it at all, so that fixed offset used to
        leave a large dead scroll gap before anything useful. Only called
        for kinds that actually show it (see _shows_properties -- item/
        mob/pnj/object)."""
        if self.card_kind == "item":
            return 270
        if self.is_mob and self.mob_kind == "enemy":
            return 300
        if self.is_mob:  # animal
            return 320
        if self.card_kind == "object":
            # past blocks/interactable/lockable(+direction mode, only when
            # has_directions) + cell_modes grid's worst case
            return 480 if self.has_directions else 440
        return 300  # pnj

    def _shows_properties(self):
        """item/mob/pnj/object -- every kind except a room card (which
        never loads into this panel at all, see open()). A plain
        decorative/special object used to be excluded here (nothing read
        a world object's "capabilities" at all, so the section would have
        shown nothing) -- now that placable_on_floor/placable_on_wall
        (see object_manager.is_placable) is a real capability every such
        object carries, its own placement is finally a visible, tearable
        fragment like any other card's capacites."""
        return self.card_kind in ("item", "mob", "pnj", "object")

    def _tearable_fragments(self):
        """(category, kind, payload) for every mechanical fragment the
        currently loaded card ACTUALLY carries -- read straight from the
        live registry (OBJECT_TYPES/ITEM_DEFINITIONS), not this panel's own
        edit-state fields (self.throwable_enabled etc., still populated by
        open() and still read by _try_save so Enregistrer keeps passing
        them through unchanged -- but nothing in THIS panel mutates them
        anymore, capacites/effets/stats are tear/fuse-only now, see module
        docstring's "Dechirer/Coller" section). "stats" is gated to
        self.is_mob or self.is_pnj (not "does the entry happen to carry a
        stats key" alone) since _build_mob_stats never writes one for a
        plain object/item at all -- checking presence alone would be
        harmless in practice, this just documents the same invariant
        _build_mob_stats itself relies on. A PNJ carrying stats (Coller-
        fused from a true mob) doesn't fight in-game yet (see entities.
        Mob's own class docstring), but the fragment is real and has to
        stay visible/tearable/re-savable regardless."""
        base_id = self.item_id if self.item_id is not None else self.type_id
        if base_id is None:
            return []
        entry = OBJECT_TYPES.get(base_id, ITEM_DEFINITIONS.get(base_id))
        if entry is None:
            return []
        fragments = []
        for kind, payload in entry.get("capabilities", {}).items():
            fragments.append(("capability", kind, payload))
        for effect in entry.get("effects", []):
            fragments.append(("effect", effect.get("kind"), effect))
        # "Ouvrable" (2026-08-20, confirmed with the user) -- a view onto
        # this object's own "blocks_until_open" flag (gate/wall today), see
        # object_manager.extract_property_payload's own docstring on why
        # this reads the existing flag rather than a new one. Object cards
        # only -- an item/mob/pnj never carries blocks_until_open at all.
        if self.card_kind == "object" and entry.get("blocks_until_open"):
            fragments.append(("ouvrable", None, True))
        # Any mob's stats block is tearable, not just an "enemy" one --
        # entities.py's Mob is fully data-driven (aggro_capable is just
        # "aggro_range"/"attack_range" in stats, no mob_kind check at all),
        # so an animal's own {"health": 2} is a legitimate fragment, and so
        # is whatever a previous Coller already fused onto it (confirmed
        # with the user: tearing a skeleton's whole combat profile onto a
        # chicken should work, not just enemy-to-enemy).
        if (self.is_mob or self.is_pnj) and entry.get("stats"):
            fragments.append(("stats", None, entry["stats"]))
            # A finer-grained SUBSET of the same stats block -- just
            # aggro_range/attack_range, "l'agressivite" (confirmed with the
            # user) -- so it can be recovered on its own without dragging
            # health/move_speed/loot along too. Deliberately excludes
            # active_attack_frames, same reasoning as everywhere else it's
            # kept out of Dechirer/Coller: those frame indices are specific
            # to the SOURCE mob's own sprite sheet, transplanting them onto
            # a target with a differently-shaped attack animation would
            # silently point at the wrong frames.
            aggressivity = extract_property_payload(entry, "aggressivity")
            if aggressivity is not None:
                fragments.append(("aggressivity", None, aggressivity))
        # A PNJ's wander_actions -- which tagged action of its own entity
        # pack plays for each role (idle/move/sitting/laying/run) -- one
        # tearable fragment per role actually configured (confirmed with
        # the user: "il faut rentrer les etats comme propriete"). Gluing
        # one onto another PNJ only actually does something useful if that
        # target's own pack happens to tag a matching action -- no
        # validation of that here, same "the Forge doesn't second-guess a
        # fuse" spirit as every other category.
        if self.is_pnj:
            for role, action_name in entry.get("wander_actions", {}).items():
                fragments.append(("state", role, action_name))
        # "Comportement" (2026-08-19, confirmed with the user) -- the
        # single flag ("mob") that makes a card come alive at all,
        # offered for ANY live mob (flat-frame or entity-pack alike, see
        # object_manager.extract_property_payload's own docstring on
        # "behavior") so it can be torn off e.g. a chicken and glued onto
        # a typeless card Assembler already gave its own entity_pack/
        # states to -- turning it into a living mob using ITS OWN states,
        # never the chicken's (fuse only ever writes the "mob" flag
        # itself, see object_manager._apply_property_payload).
        if (self.is_mob or self.is_pnj) and entry.get("mob"):
            fragments.append(("behavior", None, True))
        # loot_cards is explicitly-set-or-absent, never falsy-but-present
        # (see object_manager._build_mechanics_fields' own comment) -- an
        # explicit {} ("this card drops nothing") is still a real fragment
        # worth tearing, so this checks "is not None", not truthiness.
        if entry.get("loot_cards") is not None:
            fragments.append(("loot", None, entry["loot_cards"]))
        return fragments

    def _properties_section_height(self):
        if not self._shows_properties():
            return 0
        rows = max(1, len(self._tearable_fragments()))
        return self.PROPERTIES_HEADER_HEIGHT + rows * self.PROPERTY_ROW_HEIGHT

    def _properties_section_rect(self):
        """Overall hit-region for the tearable-fragment rows -- hovering/
        pressing ANYWHERE in here picks the nearest row by vertical
        proximity (see _hovered_property_index), not a pixel-precise row
        hit-test, so the player never has to aim precisely at a specific
        line to start tearing it -- confirmed approach for this gesture."""
        if not self._shows_properties():
            return None
        content_x = self.x + 20
        content_width = self.width - 40 - self.SCROLLBAR_WIDTH - 6
        top = self._properties_top_offset() + self.PROPERTIES_HEADER_HEIGHT
        rows = max(1, len(self._tearable_fragments()))
        return pygame.Rect(content_x, self._cy(top), content_width, rows * self.PROPERTY_ROW_HEIGHT)

    def _property_row_rect(self, index):
        section = self._properties_section_rect()
        return pygame.Rect(
            section.x, section.y + index * self.PROPERTY_ROW_HEIGHT, section.width, self.PROPERTY_ROW_HEIGHT - 4,
        )

    def _hovered_property_index(self, pos):
        fragments = self._tearable_fragments()
        if not fragments:
            return None
        best_index, best_dist = None, None
        for index in range(len(fragments)):
            dist = abs(pos[1] - self._property_row_rect(index).centery)
            if best_dist is None or dist < best_dist:
                best_index, best_dist = index, dist
        return best_index

    @staticmethod
    def _fragment_summary(payload):
        if isinstance(payload, dict):
            return ", ".join(f"{k}={v}" for k, v in payload.items() if not isinstance(v, (list, dict)))
        return str(payload)

    def _layout(self):
        content_x = self.x + 20
        # Shared preview -- PINNED, never scrolls. Animation-state selection
        # is the vertical slider to its own right now (see
        # _preview_state_slider_rect), not a row of tabs above it -- the
        # box's own y is otherwise unchanged from when that row occupied
        # the space above it.
        self.preview_rect = pygame.Rect(content_x, self.y + 76, 160, 160)
        # Everything below here is scrollable content -- built via _cy(),
        # see its own docstring.
        content_width = self.width - 40 - self.SCROLLBAR_WIDTH - 6
        # Plain-object mechanics rows (blocks/interactable/lockable) --
        # start right below the preview + a one-line info label.
        self._blocks_rect = pygame.Rect(content_x, self._cy(270), content_width, 32)
        self._interactable_rect = pygame.Rect(content_x, self._cy(310), content_width, 32)
        self._lockable_rect = pygame.Rect(content_x, self._cy(350), content_width, 32)
        # Only ever shown for a card with `directions` tagged at crop time
        # (see self.has_directions) -- any archetype, not just "porte"
        # (unlike _lockable_rect just above it).
        self._direction_mode_rect = pygame.Rect(content_x, self._cy(390), content_width, 32)
        # Proprietes (capacites/effets/stats -- see _tearable_fragments/
        # _render_properties) -- item/mob/pnj cards, right after whatever
        # kind-specific info precedes it (_properties_top_offset, dynamic
        # per card_kind same as _content_bottom_offset). Row rects are
        # computed on demand (_property_row_rect), not cached here --
        # unlike the old toggle rows this replaced, the row COUNT varies
        # with how many fragments the loaded card actually has, so there's
        # nothing fixed to lay out up front.

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

    def _load_sounds(self, sounds):
        """Passthrough only now (see self.card_sounds' own __init__
        comment) -- editing lives in core.editor.ui.sound_box_panel.
        SoundBoxPanelUI, this just loads what's already there so
        _try_save can write it straight back unchanged."""
        self.card_sounds = dict(sounds)

    def _load_pitch(self, sound_pitch):
        """Passthrough only now, same reasoning as _load_sounds."""
        self.pitch_enabled = {key: True for key in sound_pitch}
        self.pitch_range = {key: list(value) for key, value in sound_pitch.items()}

    def _build_mob_stats(self):
        """The stats dict to persist for the currently loaded mob or PNJ
        (a PNJ can carry one too, Coller-fused from a true mob -- see
        _tearable_fragments), or None for anything else (object/item have
        no stats concept) -- pulled out of _try_save so that method's own
        item-vs-object dispatch doesn't have this whole computation
        sitting inline in the middle of it.

        Nothing in this panel edits a mob's stats directly anymore (see
        module docstring's "Proprietes / Dechirer / Coller") -- the whole
        block (or, for "aggressivity", just its aggro_range/attack_range
        subset) is only ever replaced wholesale by tearing it off one card
        and gluing it onto another. Passing self.mob_stats through
        UNCHANGED here (rather than returning None) matters regardless:
        update_type_mechanics always clears "stats" first and only
        reapplies whatever this returns, so a plain None would silently
        WIPE it on every save -- including the one _try_tear itself runs
        before every tear, which would erase a freshly-transplanted
        aggro/attack behavior the very next time it's touched."""
        if not (self.is_mob or self.is_pnj):
            return None
        return dict(self.mob_stats) if self.mob_stats else None

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
        capabilities = dict(self._passthrough_capabilities)
        if self.throwable_enabled:
            capabilities["throwable"] = {"speed": self.throw_speed}
        if self.explosive_enabled:
            capabilities["explosive"] = {"radius_tiles": self.blast_radius_tiles, "damage": self.blast_damage}
        effects = []
        if self.heal_enabled:
            effects.append({"kind": "heal", "amount": self.heal_amount})
        # card_sounds/pitch_enabled/pitch_range are passthrough-only here
        # now (see their own __init__ comments) -- reconstructed from
        # whatever _load_sounds/_load_pitch last loaded, unedited by this
        # panel, so Enregistrer can never silently wipe a card's sounds
        # even though editing them lives in SoundBoxPanelUI now.
        sounds = {key: path for key, path in self.card_sounds.items() if path}
        # A pitch range only means anything for a key that ALSO has a real
        # sound assigned and its own toggle enabled -- an orphaned range
        # left over from a sound that's since been cleared elsewhere never
        # gets persisted.
        sound_pitch = {
            key: self.pitch_range[key] for key in sounds
            if self.pitch_enabled.get(key) and key in self.pitch_range
        }

        # loot_cards ("Cartes"/butin) is passthrough-only too now -- editing
        # it moved entirely to the tearable "loot" property (see
        # _tearable_fragments/object_manager.extract_property_payload's own
        # "loot" branch, confirmed with the user), this panel just reads
        # whatever's currently live so Enregistrer never wipes it. Read
        # straight from the live entry rather than a field this panel
        # tracks, same "preserve what you don't actively edit" spirit as
        # capabilities/sounds above -- None (never {} by fiat) if the live
        # entry never had one at all, same presence-not-truthiness
        # convention update_type_mechanics/update_item(_overrides) expect.
        live_entry = ITEM_DEFINITIONS.get(self.item_id) if self.item_id is not None else OBJECT_TYPES.get(self.type_id)
        loot_cards = live_entry.get("loot_cards") if live_entry is not None else None

        try:
            if self.card_kind == "item":
                if is_builtin_item(self.item_id):
                    update_item_overrides(self.item_id, capabilities, effects, sounds, sound_pitch, loot_cards)
                else:
                    update_item(
                        self.item_id, self.name, self.item_slot, self.icon_path, self.icon_rect,
                        capabilities=capabilities, effects=effects, sounds=sounds, sound_pitch=sound_pitch,
                        loot_cards=loot_cards,
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
                    loot_cards=loot_cards,
                    direction_mode=self.direction_mode,
                )
        except ValueError as exc:
            self.status_text = str(exc)
            return None
        self.status_text = f"'{self.name}' mise a jour."
        return self.item_id if self.item_id is not None else self.type_id

    # -- Dechirer / Coller (property cards, see core.data.cards.
    # PROPERTY_CARD_PREFIX) -----------------------------------------
    #
    # Dechirer used to be a small per-row button (see git history) -- torn
    # out in favor of a proximity-hover + horizontal-drag-scrub gesture
    # directly on the card's own composited art, still being designed (see
    # done.txt / the conversation that replaced it). _try_tear below is the
    # trigger-agnostic half that survives that redesign unchanged: given a
    # decided (category, kind), it does the save+extract+id-building: only
    # HOW a (category, kind) gets decided is changing, not what happens
    # once it has been.

    def _try_tear(self, category, kind):
        """Consumes 1 exemplaire of whatever's currently loaded to extract
        ONE mechanical fragment (category, kind, see object_manager.
        extract_property_payload) as a standalone property card. Implicitly
        saves first (_try_save) so what gets torn always matches what's
        actually persisted for this card, never an unsaved Forge draft --
        the payload is read live, right here, off the freshly-saved
        source, then frozen into its own snapshot (see
        core.data.cards.register_torn_property) -- property cards no
        longer track or care which card they were torn from (confirmed
        with the user), so this is the only moment that live value is
        ever read at all.

        Returns ("tear", base_card_id, property_card_id) for Creator to
        turn into the actual card_collection bookkeeping (this panel never
        touches a Profile directly, see class docstring) -- None if the
        save itself failed (status_text already set by _try_save) or the
        fragment isn't actually present (the caller -- whatever decided
        this (category, kind) is the one being torn -- is expected to have
        already confirmed it's actually present before calling this)."""
        base_id = self._try_save()
        if base_id is None:
            return None
        source = OBJECT_TYPES.get(base_id, ITEM_DEFINITIONS.get(base_id))
        if source is None:
            return None
        payload = extract_property_payload(source, category, kind)
        if payload is None:
            return None
        prop_id = register_torn_property(category, kind, payload)
        self.status_text = f"'{property_label(category, kind)}' extraite de '{self.name}'."
        return "tear", base_id, prop_id

    def preview_property_drop(self, card_id, pos):
        """Drop target for gluing a property card onto whatever's currently
        loaded -- see module docstring's "Coller" feature. Accepts a drop
        ANYWHERE in the panel (the caller, Creator._resolve_dragged_card,
        already gates on mechanics_frame.contains(pos) before calling this
        at all, so `pos` is guaranteed to already be inside the Forge) --
        widened from the old "must land exactly on the small preview
        sprite" hit test on purpose: this is now the ONLY way to fuse a
        property onto a card (dropping directly onto another card shown in
        the Collection was tried and abandoned, see
        Creator._resolve_dragged_card's own comment -- CardPanelUI's
        Carte/Propriete tab split makes that drag structurally impossible),
        so it needs to be forgiving/discoverable rather than a tiny hidden
        target. Returns None if nothing's loaded, card_id isn't a property
        card, or fuse_card decides this is a no-op (the fragment is already
        present, see its own docstring -- a status message is set either
        way so the player gets feedback even when nothing changed). A
        tuple (base_card_id, new_card_id) on success, for Creator to turn
        into card_collection bookkeeping + reloading this panel onto the
        new card."""
        if self.type_id is None and self.item_id is None:
            return None
        parsed = parse_property_card_id(card_id)
        if parsed is None:
            return None
        category, kind, payload = parsed
        base_id = self.item_id if self.item_id is not None else self.type_id
        try:
            new_id = fuse_card(base_id, category, kind, payload)
        except ValueError as exc:
            self.status_text = str(exc)
            return None
        if new_id is None:
            self.status_text = "Cette carte porte deja cette propriete."
            return None
        self.status_text = f"'{property_label(category, kind)}' greffee -- '{new_id}' creee."
        return base_id, new_id

    @staticmethod
    def _card_width_for_height(height):
        return round(height * CardRenderer.BACKING_SIZE[0] / CardRenderer.BACKING_SIZE[1])

    def _handle_resize_event(self, event):
        """Overrides _ResizableCornerMixin's own version (shared with
        CardPanelUI/GeneratorPanelUI, which DO resize both axes
        independently -- this override is local to this class, doesn't
        touch the shared mixin) -- this panel's width is never dragged
        directly, only ever derived from height via
        _card_width_for_height, so its own aspect ratio always matches
        card.png's real one (see class docstring). Horizontal mouse
        movement during the drag is simply ignored -- only the vertical
        delta drives anything, everything else (hit-test/start/stop) is
        identical to the base version."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._resize_handle_rect().collidepoint(event.pos):
                self._resizing = True
                self._resize_last_pos = event.pos
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._resizing:
                self._resizing = False
                self._resize_last_pos = None
                return True
        elif event.type == pygame.MOUSEMOTION and self._resizing and self._resize_last_pos is not None:
            dy = event.pos[1] - self._resize_last_pos[1]
            self.height = max(self.STANDARD_HEIGHT, min(self.MAX_HEIGHT, self.height + dy))
            self.width = self._card_width_for_height(self.height)
            self._resize_last_pos = event.pos
            return True
        return False

    def handle_event(self, event):
        # A torn property still awaiting collection (see
        # _start_tear_resolution/render()'s own early-return branch) takes
        # over the WHOLE panel -- confirmed with the user: the normal card
        # must NOT reappear underneath the moment the throw/burn overlays
        # finish, the isolated property has to sit there, alone, until the
        # player deliberately clicks it. So nothing else is interactable
        # while it's showing: every event here is either "does this click
        # land on the isolated property, once both flourishes are done" or
        # simply ignored, before any of the panel's normal handling below
        # (resize, drag-drop, mechanics toggles, ...) ever runs.
        if self._tear_resolving:
            still_animating = self._tear_throw is not None or self._tear_burn is not None
            if (
                not still_animating
                and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self._tear_property_rect().collidepoint(event.pos)
            ):
                result = self._tear_pending_result
                self._tear_resolving = False
                self._tear_pending_result = None
                self._tear_property_surface = None
                # "une fois recupere la forge reste vide jusqu'a ce que le
                # joueur vienne glisser une autre carte dedans" -- clear()
                # already does exactly that (empties type_id/item_id
                # without touching disk), same as the manual Vider button.
                self.clear()
                return result
            return None

        if self._handle_resize_event(event):
            return None

        # A press on the shared preview sprite -- PNJ direction-drag (mid-
        # drag, applies its own click-drag-to-rotate) and "drag the card
        # itself back out of the panel to unload it" (any card kind) both
        # live here, span multiple event types (unlike everything else in
        # this panel, which only ever reacts to a single MOUSEBUTTONDOWN)
        # -- handled first, before the MOUSEBUTTONDOWN-only gate below
        # short-circuits every other event type. Replaces the old "Vider"
        # button entirely (confirmed with the user: nothing here should
        # need a button) -- releasing outside the panel's own bounds
        # unloads the card (auto-saving first, same as every other
        # mechanics change); releasing back inside just ends whichever
        # drag was in progress with no other effect (for a PNJ, that's
        # simply "stop rotating").
        if self._preview_dragging:
            if event.type == pygame.MOUSEMOTION:
                if self.is_pnj:
                    self._update_pnj_drag(event)
                return None
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._preview_dragging = False
                self._pnj_dragging_direction = False
                panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
                if not panel_rect.collidepoint(event.pos):
                    self._try_save()
                    self.clear()
                return None

        # The animation-state slider's own drag -- replaces the old row of
        # tab buttons (confirmed with the user). Any position along the
        # track snaps to whichever state name is nearest (see
        # _nearest_preview_state_at), both at grab time and on every
        # subsequent MOUSEMOTION while held.
        if self._preview_slider_dragging:
            if event.type == pygame.MOUSEMOTION:
                new_state = self._nearest_preview_state_at(event.pos[1])
                if new_state is not None:
                    self._select_preview_state(new_state)
                return None
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._preview_slider_dragging = False
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

        # Dechirer's drag-scrub, same multi-event shape as the two above --
        # (category, kind) locked in at MOUSEBUTTONDOWN (see the
        # _properties_section_rect hit-test further down), horizontal
        # position relative to where the drag started maps directly to
        # self._tear_progress in [0, 1] (position-based, not time/velocity-
        # based, so it tracks the cursor exactly both directions and
        # freezes if the player stops -- confirmed approach; the actual
        # procedural pixel-splitting for the current progress happens in
        # core.editor.ui.card_tear, see _render_properties). Alongside
        # progress, every MOUSEMOTION also resamples self._tear_velocity
        # (px/sec since the last sample) -- unlike progress, this one IS
        # time-based, purely so the eventual release-throw (see below) can
        # carry however fast the player was actually moving the cursor.
        # Releasing at progress==1.0 (fully torn) commits the tear
        # (_try_tear), launches the top piece's throw from its last drawn
        # position (self._tear_last_top_surface/_rect, captured by
        # _render_tearing every frame), and starts the zone BELOW the
        # extracted property burning (see _start_below_property_burn) --
        # releasing any earlier cancels, nothing is consumed and nothing
        # thrown/burned either way until MOUSEBUTTONUP confirms it.
        if self._tear_target is not None:
            if event.type == pygame.MOUSEMOTION:
                now = pygame.time.get_ticks()
                dt_seconds = max(0.001, (now - self._tear_last_sample_time) / 1000.0)
                self._tear_velocity = (
                    (event.pos[0] - self._tear_last_sample_pos[0]) / dt_seconds,
                    (event.pos[1] - self._tear_last_sample_pos[1]) / dt_seconds,
                )
                self._tear_last_sample_pos = event.pos
                self._tear_last_sample_time = now
                dx = max(0, event.pos[0] - self._tear_drag_start_x)
                self._tear_progress = min(1.0, dx / self.TEAR_DRAG_TOTAL_PX)
                return None
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                category, kind = self._tear_target
                committed = self._tear_progress >= 1.0
                # NOT recomputed here -- self.x/self.y are back to their
                # REAL screen position by now (see _render_tearing's own
                # temporary-zero window), so _tear_property_row_bottom()
                # would return a value offset by the panel's own screen y
                # instead of a local one (see _render_tearing's own
                # comment on this exact bug). Use the value it already
                # captured, in local coordinates, during the last drag
                # frame's render pass instead.
                property_row_bottom = self._tear_last_property_row_bottom if committed else None
                self._tear_target = None
                self._tear_drag_start_x = None
                self._tear_progress = 0.0
                if committed:
                    if self._tear_last_top_surface is not None:
                        origin = self._tear_last_top_rect.topleft
                        self._tear_throw = card_tear.start_throw(
                            self._tear_last_top_surface, origin, self._tear_velocity,
                            min_velocity_x=self._tear_min_throw_velocity_x(origin[0]),
                        )
                    self._start_tear_resolution(category, kind, property_row_bottom)
                    return None
                self.status_text = "Dechirement annule."
                return None

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        if self.type_id is None and self.item_id is None:
            return None

        # Animation-state slider grab -- generic, works for both PNJ (roles)
        # and mob (its fixed animation set). Empty for a plain object/item,
        # see _preview_state_options, so the track never intercepts a click
        # in that case. Checked before the preview-drag start below since
        # the track sits just to the sprite's own right, outside
        # preview_rect itself.
        if self._preview_state_slider_rect().collidepoint(event.pos):
            self._preview_slider_dragging = True
            new_state = self._nearest_preview_state_at(event.pos[1])
            if new_state is not None:
                self._select_preview_state(new_state)
            return None

        # Preview drag start -- for a PNJ this doubles as the direction-
        # drag (see the multi-event handling above); for every card kind
        # it's also the start of "drag the card back out to unload it"
        # (see the same block's MOUSEBUTTONUP branch).
        if self.preview_rect.collidepoint(event.pos):
            self._preview_dragging = True
            if self.is_pnj:
                self._pnj_dragging_direction = True
                self._pnj_drag_last_pos = event.pos
            return None

        if self._max_scroll() > 0 and self._scrollbar_thumb_rect().collidepoint(event.pos):
            self._scrollbar_dragging = True
            return None

        # Everything below reads/writes a row inside the scrollable band --
        # gated on the click actually landing within _viewport_rect (not
        # just within the row's own rect), so a row scrolled out of view
        # can never be hit through the pinned preview/title areas it might
        # geometrically overlap once shifted by scroll_offset (see _cy's
        # own docstring).
        if not self._viewport_rect().collidepoint(event.pos):
            return None

        # No more "Enregistrer" button (confirmed with the user: nothing
        # in a properly-built mechanics UI should need a save button) --
        # every mechanics toggle below persists itself immediately via
        # _try_save, exactly like a tear/fuse already does (see
        # _try_tear's own call to it). Returning the save result (the
        # saved id, or None on failure) rather than a bare None keeps
        # Creator's existing "non-None result -> refresh the Collection"
        # handling working unchanged.
        if self.card_kind == "object":
            if self.archetype in CELL_MODES_ARCHETYPES:
                if not self._is_multi_cell():
                    if self.archetype == "sol" and self._blocks_rect.collidepoint(event.pos):
                        self.blocks_movement = not self.blocks_movement
                        return self._try_save()
                else:
                    for (row, col), rect in self._cell_mode_grid_rects().items():
                        if rect.collidepoint(event.pos):
                            self._cycle_cell_mode(row, col, 1)
                            return self._try_save()

            if self._interactable_rect.collidepoint(event.pos):
                self.interactable = not self.interactable
                return self._try_save()

            if self.archetype == "porte" and self._lockable_rect.collidepoint(event.pos):
                self.lockable = not self.lockable
                return self._try_save()

            if self.has_directions and self._direction_mode_rect.collidepoint(event.pos):
                self.direction_mode = "manual" if self.direction_mode == "auto" else "auto"
                return self._try_save()

        if self._shows_properties():
            section_rect = self._properties_section_rect()
            if section_rect is not None and section_rect.collidepoint(event.pos):
                index = self._hovered_property_index(event.pos)
                if index is not None:
                    self._tear_target = self._tearable_fragments()[index][:2]
                    self._tear_drag_start_x = event.pos[0]
                    self._tear_progress = 0.0
                    self._tear_velocity = (0.0, 0.0)
                    self._tear_last_sample_pos = event.pos
                    self._tear_last_sample_time = pygame.time.get_ticks()
                return None

        return None

    def _render_card_background(self, screen, panel_rect):
        """The loaded card's own backing (assets/cards/card.png, via
        CardRenderer.card_backing() -- a plain flat-color rounded rect
        with a border, no fine detail/pattern, safe to stretch
        non-uniformly to any panel shape without visible distortion),
        stretched to cover the WHOLE panel -- confirmed with the user
        after a couple of iterations that undershot: every Forge section
        (preview/slider/mechanics/proprietes) should read as zones of ONE
        continuous giant card, not a small card portrait glued above an
        unrelated plain panel. Replaces the generic BorderManager panel
        background entirely while a card is loaded -- that one's still
        used for the empty placeholder state, drawn on top of this."""
        backing = self._renderer.card_backing()
        scaled = pygame.transform.scale(backing, (panel_rect.width, panel_rect.height))
        screen.blit(scaled, panel_rect.topleft)

    def render(self, screen):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)

        # A torn property awaiting collection completely REPLACES the
        # normal panel view -- confirmed with the user: no background, no
        # giant-card content, not even the empty-placeholder hint, just the
        # throw/burn overlays (while still playing) and the isolated
        # property itself, floating alone until clicked. Checked before
        # even the "nothing loaded" branch below since _tear_resolving
        # deliberately outlives whatever's loaded (see its own __init__
        # comment) -- it must keep showing even if a different card got
        # opened in the meantime. self._tear_throw/_tear_burn are only ever
        # non-None while _tear_resolving is True (see _start_tear_resolution/
        # handle_event's own collection branch, which requires both to
        # already be finished before it will even fire) -- so this is the
        # ONLY branch that ever needs to draw either of them; the two
        # branches below never see one active.
        if self._tear_resolving:
            self._render_tear_throw(screen)
            self._render_tear_burn(screen)
            self._render_tear_property(screen)
            return

        if self.type_id is None and self.item_id is None:
            self.border.draw(screen, panel_rect)
            hint = self.small_font.render("Glisse une carte ici pour l'editer", True, (150, 150, 150))
            screen.blit(hint, (self.x + 20, self.y + 16))
            self._draw_resize_handle(screen)
            return

        if self._tear_target is not None:
            self._render_tearing(screen, panel_rect)
            return

        self._render_forge_content(screen, panel_rect)

    def _render_tear_property(self, screen):
        """The isolated property piece awaiting collection (see
        _start_tear_resolution/handle_event's _tear_resolving branch) --
        static, never animated, drawn at its own captured position for as
        long as _tear_resolving stays True (i.e. until the player clicks
        it)."""
        if self._tear_property_surface is not None:
            screen.blit(self._tear_property_surface, self._tear_property_origin)

    def _render_tear_throw(self, screen):
        """The torn-off top piece flying away and shrinking after a
        committed tear (see card_tear.start_throw/handle_event's
        MOUSEBUTTONUP branch) -- drawn as a plain overlay on top of
        whatever's currently showing (loaded card or the empty
        placeholder), independent of both: the throw already captured its
        own surface at release time, it doesn't care what's loaded now."""
        if self._tear_throw is not None:
            card_tear.blit_throw(screen, self._tear_throw)

    def _render_tear_burn(self, screen):
        """The zone below the extracted property burning away in place
        after a committed tear (see card_burn.BurnAnimation/
        _start_below_property_burn) -- drawn as a plain overlay on top of
        whatever's currently showing (loaded card or the empty
        placeholder), independent of both: the burn already captured its
        own surface/position at release time, it doesn't care what's
        loaded now."""
        if self._tear_burn is not None:
            screen.blit(self._tear_burn.get_surface(), self._tear_burn_origin)
            self._tear_burn.draw_flames(screen, self._tear_burn_origin)

    def _render_tearing(self, screen, panel_rect):
        """While a Dechirer drag is active, tears the WHOLE Forge -- not a
        small card popped up next to the dragged row (confirmed with the
        user: that read as a second, unrelated card appearing, not the
        Forge itself tearing). Renders everything _render_forge_content
        normally draws (background/preview/mechanics/proprietes/butin/
        Enregistrer, byte-for-byte the same code path) onto an
        offscreen scratch surface at LOCAL (0, 0) coordinates, then splits
        THAT single flattened image via card_tear.create_tear_state and
        blits the two resulting pieces at the panel's real screen
        position instead of the intact scratch surface.

        self.x/self.y are temporarily swapped to 0 for the one offscreen
        pass so every existing rect helper (_cy, _property_row_rect, ...)
        computes exactly as it always does, just against
        the scratch surface -- restored (and _layout() rerun against the
        REAL position) before returning, so hit-testing for the next
        frame's events is never left pointing at the wrong coordinates."""
        scratch = pygame.Surface((panel_rect.width, panel_rect.height), pygame.SRCALPHA)
        real_x, real_y = self.x, self.y
        self.x, self.y = 0, 0
        self._render_forge_content(scratch, pygame.Rect(0, 0, panel_rect.width, panel_rect.height))
        cut_y = self._tear_cut_y()
        # MUST be read here too, in this same self.x/self.y == (0, 0)
        # window -- _property_row_rect (like every other rect helper) folds
        # in self.y, so calling this later, from handle_event's
        # MOUSEBUTTONUP branch after self.x/self.y are back to their REAL
        # screen position, silently returned a value offset by the panel's
        # own screen y instead of a local one (proven: at panel y=50 it
        # returned 366, at y=400 it returned 716 -- a 350px difference
        # matching the y difference exactly). That bug fed a wildly-too-
        # large local_cut_y into _start_tear_resolution, which
        # create_tear_state then clamped to the very bottom of the
        # "below" piece -- so only a sliver ever actually burned, and
        # every OTHER property row silently ended up on the KEPT piece
        # instead of the burned one. Captured here, in local coordinates,
        # exactly like cut_y right above, fixes that at the source.
        self._tear_last_property_row_bottom = self._tear_property_row_bottom()
        self.x, self.y = real_x, real_y
        self._layout()

        state = card_tear.create_tear_state(scratch, cut_y, self._tear_progress)
        top_surface, top_rect = card_tear.blit_tear_piece(screen, state.top, panel_rect.topleft)
        card_tear.blit_tear_piece(screen, state.bottom, panel_rect.topleft)
        # Captured every frame (not just the last one) so whichever frame
        # actually turns out to be the last -- the release could land on
        # any of them -- already has an up-to-date surface/position ready,
        # see the MOUSEBUTTONUP commit branch in handle_event. The bottom
        # piece is captured pre-blit (surface + LOCAL anchor, not a screen
        # rect) since _start_below_property_burn needs to cut it again in
        # the same local coordinate space _property_row_rect already uses
        # -- it's never rotated/offset (always drawn at its own anchor, see
        # card_tear._piece_transform), so this is exactly what's on screen.
        self._tear_last_top_surface = top_surface
        self._tear_last_top_rect = top_rect
        self._tear_last_bottom_surface = state.bottom.surface
        self._tear_last_bottom_anchor = state.bottom.anchor

    def _tear_cut_y(self):
        """Local (panel-relative) y where the tear boundary sits -- the
        line ABOVE whichever row is currently being dragged (see
        _property_row_rect), not through its middle: the target row's own
        `.top` is exactly the separator between it and the row before it,
        so the whole targeted property stays intact on the bottom piece
        instead of being sliced in half by the tear (confirmed with the
        user -- centery used to run the cut straight through the row's own
        text). Read while self.x/self.y are temporarily (0, 0) (see
        _render_tearing) so this is already local/scratch-surface-relative
        with no further conversion. 0 if _tear_target somehow doesn't
        match any current fragment (can't normally happen -- a target is
        only ever set from a fragment that existed at drag-start -- but
        never worth crashing render() over)."""
        if self._tear_target is None:
            return 0
        for index, (category, kind, _payload) in enumerate(self._tearable_fragments()):
            if (category, kind) == self._tear_target:
                return self._property_row_rect(index).top
        return 0

    def _tear_property_row_bottom(self):
        """Local (panel-relative) y where the target property row ENDS --
        the mirror of _tear_cut_y's own `.top`, used at commit time (see
        _start_tear_resolution) to isolate the zone below the property
        from the rest of the (stationary) bottom piece. Same "read while
        self.x/self.y are temporarily (0, 0)" caveat as _tear_cut_y --
        MUST be called from within _render_tearing's own zero-window
        (which does, every frame, caching the result as
        self._tear_last_property_row_bottom for handle_event's
        MOUSEBUTTONUP branch to read later), never called directly from
        handle_event itself: by the time a MOUSEBUTTONUP fires, self.x/
        self.y are back to their real screen position, and this would
        silently return a value offset by the panel's own screen y
        instead of a local one (a real bug this once had -- see
        _render_tearing's own comment on it). None if _tear_target
        somehow doesn't match any current fragment (see _tear_cut_y's own
        docstring for why that can't normally happen)."""
        if self._tear_target is None:
            return None
        for index, (category, kind, _payload) in enumerate(self._tearable_fragments()):
            if (category, kind) == self._tear_target:
                return self._property_row_rect(index).bottom
        return None

    def _start_tear_resolution(self, category, kind, property_row_bottom):
        """Called once, at the moment a Dechirer drag commits (alongside
        starting the top piece's throw -- see handle_event's MOUSEBUTTONUP
        branch). Cuts the (already captured, stationary) bottom piece a
        SECOND time -- at the target property row's own bottom edge, not
        the row's top edge _tear_cut_y already cuts the whole Forge at --
        producing exactly two pieces: the property row itself (kept,
        isolated, never animated) and everything below it (handed to
        card_burn.BurnAnimation). Reuses card_tear.create_tear_state at
        progress=0.0 purely for its jagged-boundary splitting (see that
        module's own _piece_transform: both pieces get zero drift/rotation
        at progress=0, exactly the plain crop this needs -- no separate
        splitting code required here).

        Calls _try_tear right here, immediately -- NOT deferred to the
        click -- while self.type_id/item_id and every other edit-state
        field still reflect the card that was just torn (a different card
        could get opened while the isolated property sits there waiting,
        see this class' own __init__ comment on _tear_resolving/
        _tear_pending_result, so waiting to derive base_id from "whatever's
        currently loaded" until the click would silently tear the WRONG
        card). _try_tear only persists mechanics (an "Enregistrer"-
        equivalent flush, see its own docstring) and computes ids, it
        never touches card_collection itself, so doing this early has no
        player-visible effect yet -- the RESULT is what's deferred to the
        click (see handle_event's own _tear_resolving branch): that's what
        actually credits/consumes card_collection, via Creator, only once
        the player clicks the isolated property. No-op (nothing pending,
        nothing to isolate) if the bottom piece was never captured --
        shouldn't normally happen once committed==True, same defensive
        shape as the throw's own guard right above this call in
        handle_event."""
        if self._tear_last_bottom_surface is None or property_row_bottom is None:
            return
        local_cut_y = property_row_bottom - self._tear_last_bottom_anchor[1]
        below_state = card_tear.create_tear_state(self._tear_last_bottom_surface, local_cut_y, 0.0)

        # Default ignition_edge ("perimeter"): the fire catches all around
        # this piece's own outer edges (including its freshly torn top,
        # right at the property line) and closes in toward the center,
        # rather than sweeping in from a single direction -- confirmed
        # with the user, reads more like paper actually catching fire.
        self._tear_burn = card_burn.BurnAnimation(below_state.bottom.surface)
        self._tear_burn_origin = (
            self.x + self._tear_last_bottom_anchor[0] + below_state.bottom.anchor[0],
            self.y + self._tear_last_bottom_anchor[1] + below_state.bottom.anchor[1],
        )

        self._tear_property_surface = below_state.top.surface
        self._tear_property_origin = (
            self.x + self._tear_last_bottom_anchor[0] + below_state.top.anchor[0],
            self.y + self._tear_last_bottom_anchor[1] + below_state.top.anchor[1],
        )
        self._tear_resolving = True
        self._tear_pending_result = self._try_tear(category, kind)

    def _tear_property_rect(self):
        """Screen-space click target for the isolated property piece
        awaiting collection (see handle_event's _tear_resolving branch) --
        an empty rect (collides with nothing) if nothing's actually
        captured, shouldn't happen while _tear_resolving is True, but this
        is read directly off event handling, never worth crashing over."""
        if self._tear_property_surface is None:
            return pygame.Rect(0, 0, 0, 0)
        return pygame.Rect(self._tear_property_origin, self._tear_property_surface.get_size())

    def _tear_min_throw_velocity_x(self, origin_x):
        """The minimum rightward launch speed (already in "final launch
        speed" px/sec terms, see start_throw's own min_velocity_x)
        guaranteeing the thrown piece clears the Forge's own right edge by
        the time THROW_DURATION elapses, whatever the player's actual
        release velocity was -- confirmed with the user: it should always
        end up falling off to the right of the panel, at minimum. A flat
        40px margin past the edge so it visibly clears rather than
        stopping exactly at the border."""
        distance = (self.x + self.width) - origin_x + 40
        return max(0.0, distance / card_tear.THROW_DURATION)

    def _render_forge_content(self, screen, panel_rect):
        """Everything a loaded card's Forge view draws, in one place --
        called directly by render() for a normal frame, and once more
        (onto an offscreen scratch surface, see _render_tearing) per
        frame while a Dechirer drag is active, so the tear animation
        splits the EXACT same pixels a normal frame would have shown, not
        a separate simplified re-draw."""
        self._render_card_background(screen, panel_rect)

        # _layout() rebuilds every cached content rect (_blocks_rect, ...)
        # from self.x/y/width/height/scroll_offset -- previously only
        # re-run on move() (a PanelFrame drag), which silently left every
        # rect stale after a resize-handle drag (self.width/height
        # changing without a matching move()) or a scroll (scroll_offset
        # changing without one either, see _cy). Called here, every frame,
        # rather than hunting down every event path that could invalidate
        # it -- render() always runs once per frame regardless of events
        # (see Creator.run()), so this keeps rects correct for the NEXT
        # event with at most one frame of lag, cheap enough (plain Rect
        # arithmetic) to not matter.
        self._clamp_scroll()
        self._layout()

        title = self.title_font.render(f"Mecaniques -- {self.name}", True, self.CARD_TEXT_COLOR)
        screen.blit(title, (self.x + 20, self.y + 16))

        self._render_preview(screen)

        # Everything below is the scrollable band -- clipped to
        # _viewport_rect so a row scrolled past the top/bottom never bleeds
        # into the pinned preview/title above. previous_clip is restored
        # afterward rather than cleared to None outright, in case a caller
        # further up already had its own clip active.
        previous_clip = screen.get_clip()
        screen.set_clip(self._viewport_rect())

        if self.card_kind == "mob":
            self._render_mob_info(screen)
        elif self.card_kind == "pnj":
            self._render_pnj_info(screen)
        elif self.card_kind == "object":
            self._render_object_info(screen)
        else:
            item_label = self.small_font.render("Item d'inventaire", True, self.CARD_TEXT_COLOR)
            screen.blit(item_label, (self.x + 20, self._cy(244)))

        self._render_properties(screen)

        screen.set_clip(previous_clip)
        self._render_scrollbar(screen)

        # No more "Enregistrer" button -- every mechanics change persists
        # itself immediately (see handle_event), this is just feedback
        # that it happened, pinned to the panel's own bottom edge like the
        # button used to be.
        if self.status_text:
            status = self.small_font.render(self.status_text, True, self.CARD_TEXT_COLOR)
            screen.blit(status, (self.x + 20, self.y + self.height - 26))

        self._draw_resize_handle(screen)

    def _render_scrollbar(self, screen):
        if self._max_scroll() <= 0:
            return
        pygame.draw.rect(screen, (40, 40, 46), self._scrollbar_track_rect())
        pygame.draw.rect(screen, (150, 150, 150), self._scrollbar_thumb_rect())

    def _render_preview(self, screen):
        """Shared preview area for EVERY card kind -- see module docstring's
        "Unified preview" section. Animation selection is the vertical
        slider to the sprite's own right (see _render_preview_state_slider)
        now, not a row of tab buttons -- confirmed with the user."""
        self._render_preview_state_slider(screen)

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

    @staticmethod
    def _draw_dashed_hline(screen, y, left, right, color, dash_len=5, gap_len=4, width=1):
        """A horizontal dashed line from `left` to `right` at height `y` --
        pygame has no built-in dashed line, this is the whole
        implementation (only ever called for horizontal cut-line
        indicators, see _render_properties, so no general-direction
        version is needed)."""
        x = left
        while x < right:
            segment_end = min(x + dash_len, right)
            pygame.draw.line(screen, color, (x, y), (segment_end, y), width)
            x += dash_len + gap_len

    def _render_properties(self, screen):
        """Proprietes section/zone -- one plain text row per tearable
        fragment (see _tearable_fragments), drawn directly over this
        panel's own giant-card background (see _render_card_background --
        the WHOLE Forge is one continuous card now, this is just one of
        its zones, not a separate card image of its own anymore).
        Deliberately no button-like background box on an idle row, only a
        hover/drag highlight, so the row list reads as labels printed on
        the card rather than a separate control panel. Torn (Dechirer,
        drag right to the last frame) or glued from another card (Coller,
        drop a property card onto the shared preview sprite -- see
        preview_property_drop) -- nothing here is directly editable in
        place anymore."""
        if not self._shows_properties():
            return
        top = self._properties_top_offset()
        header = self.small_font.render("Glisser une propriete vers la droite pour la dechirer", True, self.CARD_TEXT_MUTED_COLOR)
        screen.blit(header, (self.x + 20, self._cy(top)))

        fragments = self._tearable_fragments()
        if not fragments:
            hint = self.small_font.render("(aucune propriete dechirable)", True, self.CARD_TEXT_MUTED_COLOR)
            screen.blit(hint, (self.x + 20, self._cy(top + 24)))
            return

        section_rect = self._properties_section_rect()
        mouse_pos = pygame.mouse.get_pos()
        hovered_index = (
            self._hovered_property_index(mouse_pos)
            if self._tear_target is None and section_rect.collidepoint(mouse_pos)
            else None
        )
        for index, (category, kind, payload) in enumerate(fragments):
            rect = self._property_row_rect(index)
            is_target = self._tear_target == (category, kind)
            is_hovered = index == hovered_index
            label = f"{property_label(category, kind)} -- {self._fragment_summary(payload)}"
            text = self.small_font.render(label, True, (0, 0, 0))
            screen.blit(text, (rect.x + 4, rect.centery - text.get_height() / 2))
            if is_target or is_hovered:
                # Where the two cuts will ACTUALLY land if this row is
                # torn -- the tear line at rect.top (see _tear_cut_y, the
                # boundary the thrown-away top piece is cut along) and the
                # burn line at rect.bottom (see _tear_property_row_bottom,
                # where the burned-away zone starts) -- confirmed with the
                # user: replaces the old single underline-under-the-text
                # highlight, which showed interest in a row but not where
                # either cut actually falls.
                self._draw_dashed_hline(screen, rect.top, rect.left, rect.right, self.TEAR_LINE_COLOR)
                self._draw_dashed_hline(screen, rect.bottom, rect.left, rect.right, self.BURN_LINE_COLOR)

    def _render_object_info(self, screen):
        """Archetype label + mechanics checkboxes (blocks_movement/
        cell_modes/interactable/lockable) -- plain decorative/special
        OBJECT_TYPES cards only (card_kind == "object"), extracted out of
        render()'s own kind dispatch for symmetry with _render_mob_info/
        _render_pnj_info."""
        type_label = self.small_font.render(f"Archetype : {ARCHETYPES.get(self.archetype, {}).get('label', self.archetype)}", True, self.CARD_TEXT_COLOR)
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

        if self.has_directions:
            direction_label = "Direction : Auto" if self.direction_mode == "auto" else "Direction : Manuel"
            self.border.draw_centered_label(screen, self._direction_mode_rect, self.font, direction_label)

    def _render_mob_info(self, screen):
        """Type + Etats -- always informational (a mob's animation set is
        a fixed constant, never partial like a custom PNJ's, so there's no
        completeness notion to check). An enemy's stats are shown/torn via
        the Proprietes section instead (see _render_properties), not
        duplicated here."""
        kind_label = "Ennemi" if self.mob_kind == "enemy" else "Animal"
        type_label = self.small_font.render(f"Type : Mob ({kind_label})", True, self.CARD_TEXT_COLOR)
        screen.blit(type_label, (self.x + 20, self._cy(244)))

        states_label = self.small_font.render(f"Etats : {', '.join(self.mob_states)}", True, self.CARD_TEXT_COLOR)
        screen.blit(states_label, (self.x + 20, self._cy(266)))

        if self.mob_kind != "enemy":
            note = self.small_font.render(
                "Aucune stat pour un animal -- seuls les ennemis en ont.", True, self.CARD_TEXT_MUTED_COLOR
            )
            screen.blit(note, (self.x + 20, self._cy(288)))

    def _render_pnj_info(self, screen):
        """PNJ-specific info below the shared preview -- entity pack name
        and the currently-selected direction + how much of the current
        action is actually tagged (see object_manager.
        action_direction_coverage) -- the preview itself (slider/box/frame)
        is drawn generically by _render_preview."""
        type_label = self.small_font.render("Type : PNJ", True, self.CARD_TEXT_COLOR)
        screen.blit(type_label, (self.x + 20, self._cy(244)))
        pack_label = self.small_font.render(f"Pack : {self.pnj_entity_pack}", True, self.CARD_TEXT_MUTED_COLOR)
        screen.blit(pack_label, (self.x + 20, self._cy(260)))

        tagged, _missing = action_direction_coverage(self.pnj_entity_pack, self.pnj_wander_actions.get(self.preview_state))
        coverage = f"{len(tagged)}/{len(NPC_DIRECTIONS)} directions taguees"
        direction_label = self.small_font.render(
            f"Direction : {self.pnj_direction} ({coverage}) -- glisser sur le sprite pour tourner",
            True, self.CARD_TEXT_COLOR,
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
        legend = self.small_font.render("B = bloquant | D = derriere | F = devant", True, self.CARD_TEXT_MUTED_COLOR)
        screen.blit(legend, (self._blocks_rect.x, legend_y))
