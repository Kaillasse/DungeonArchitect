# Contient toute la logique du game state Creator

import os
import pygame

from core.world.dungeon import DEFAULT_GRID_SAVE_PATH, Dungeon
from core.world.assembly import generate_assembly, load_assembly, save_assembly
from core.editor.ui import ToolPaletteUI
from core.ui.widgets import PanelFrame, BorderManager
from core.engine.gamestate import GameState
from core.engine.room_manager import RoomManager
from core.engine.camera import Camera
from core.data.ressources import FLOOR, next_new_donjon_name
from core.editor.autotile import WALL, LOCAL_EDIT_SPRITE_RADIUS
from core.data.profile_manager import ProfileManager, ADMINGOD_STOCK
from core.data.cards import room_name_from_card_id, room_card_manifest
from core.world.object_manager import ITEM_DEFINITIONS, OBJECT_TYPES
from core.data.sound_manager import play_card_sound
from core.world.home import home_room_name, wants_exploration
from core.editor.ui import (
    GeneratorPanelUI, RoomPanelUI, ChestPanelUI, RolePanelUI, CardPanelUI, CardRenderer,
    SpriteEditorPanelUI, AutotileThemePanelUI, MechanicsPanelUI, StashPanelUI,
)
from core.editor.tools import ObjectTool

class Creator:

    INDICATOR_HIT_RADIUS = 10
    LINK_LINE_COLOR = (60, 220, 90)

    def __init__(self, game_manager):

        self.game_manager = game_manager
        self.screen = game_manager.screen

        self.dungeon = Dungeon()
        self.room_manager = RoomManager(self.dungeon)
        self.current_room = "room_001"
        self.dungeon.load_from_json(self.current_room)
        self.palette = ToolPaletteUI()
        # Every docked panel's own default y leaves no room for a PanelFrame
        # title bar (drawn just ABOVE panel.y, see PanelFrame.title_rect) --
        # nudged down here once, at construction, rather than baking the
        # offset into each panel's own class default (which Explorator/other
        # non-Creator callers of these same widgets don't need).
        self.palette.move(0, 30)
        self.room_panel = RoomPanelUI(
            self.room_manager, y=40,
            on_rename=self._rename_room, on_delete=self._delete_room, can_rename=self._can_rename_room,
        )
        self.last_assembly = None
        self.assembly_active_floor = 0

        self.object_type = "spawn" # Type d'objet par défaut
        self.object_tool = ObjectTool()

        # Vision produit v0.05 -- the card collection is now also the
        # object-placement tool (ObjectPalette retired, see CardPanelUI's
        # own docstring) -- shared CardRenderer so Creator's own drag-follow
        # sprite (see run()'s render section), CardPanelUI's grid/list
        # rendering, and GeneratorPanelUI's own room-card grid (rooms as
        # cards) all read from the exact same composited-card cache instead
        # of each loading assets/cards/card.png separately. Constructed
        # before generator_panel below so it can be passed in.
        self.card_renderer = CardRenderer()

        self.generator_panel = GeneratorPanelUI(
            self.room_manager,
            x=10,
            # ToolPaletteUI ("Tuile de base") has a fixed height (unlike the
            # now-retired ObjectPalette, whose dynamic height this used to
            # chain off of) -- a static anchor is enough, never needs
            # re-deriving when the card collection's contents change.
            y=self.palette.y + self.palette.height + 20,
            on_rename=self._rename_room, on_delete=self._delete_room, can_rename=self._can_rename_room,
            renderer=self.card_renderer,
        )
        self.chest_panel = ChestPanelUI(
            x=self.screen.get_width() / 2 - 130,
            y=180,
        )
        self.role_panel = RolePanelUI(
            x=self.screen.get_width() / 2 - 130,
            y=180,
        )
        self.autotile_theme_panel = AutotileThemePanelUI(
            x=self.screen.get_width() / 2 - 130,
            y=180,
        )
        self.card_panel = CardPanelUI(x=460, y=340, renderer=self.card_renderer)
        # Cards found during a run (Profile.card_stash) but not yet
        # deposited into card_collection -- see StashPanelUI's own module
        # docstring and _resolve_dragged_card's "stash" drag_source branch
        # below. Docked next to card_panel since depositing means dragging
        # straight from one onto the other.
        self.stash_panel = StashPanelUI(x=750, y=340, renderer=self.card_renderer)
        # Fondation "carte"/sprite editor -- panneau modal centre (comme
        # chest_panel/role_panel), pas un panneau docke/draggable (pas
        # besoin de PanelFrame ici). Bouton d'ouverture toujours visible,
        # voir sprite_editor_button_rect ci-dessous et son check dans run().
        self.sprite_editor_panel = SpriteEditorPanelUI(
            x=self.screen.get_width() / 2 - SpriteEditorPanelUI.PANEL_WIDTH / 2,
            y=self.screen.get_height() / 2 - SpriteEditorPanelUI.PANEL_HEIGHT / 2,
        )
        self.sprite_editor_button_rect = pygame.Rect(730, 10, 220, 32)
        self._sprite_editor_border = BorderManager()
        self.sprite_editor_button_font = pygame.font.SysFont("arial", 15)
        # Same one-off "always-visible button opening a centered modal
        # panel" shape as sprite_editor_button_rect just above -- Parametres
        # used to live only in the main Menu, which has no real purpose
        # once a session is already running (see GameManager.settings_panel/
        # Explorator's own inventory-panel button for the other entry
        # point this same shared panel is opened from).
        self.settings_button_rect = pygame.Rect(730, 50, 220, 32)
        # Small preview size for the sprite that follows the mouse while
        # dragging a card to place it or relocating an already-placed
        # object -- see run()'s render section.
        self.DRAG_CARD_HEIGHT = 64

        # Built once here instead of every render() frame (run() used to
        # call pygame.font.SysFont("arial", ...) unconditionally each frame
        # for the title, and again every frame an assembly preview was open
        # for the hint text) -- every other font in this UI layer is already
        # a constructor-built instance attribute (see ToolPaletteUI/
        # CardPanelUI/etc in core.editor.ui); these two were the only
        # stragglers left rebuilding themselves per frame.
        self.title_font = pygame.font.SysFont("arial", 24)
        self.assembly_hint_font = pygame.font.SysFont("arial", 16)

        # Draggable/collapsible title-bar wrappers around the docked panels
        # (not the modal chest/role popups, which open centered on demand
        # and auto-close -- dragging them wouldn't make sense).
        # panel_frames' order is z-order for rendering/hit-testing (last =
        # topmost) -- a click on any frame brings it to the end of this
        # list, see run()'s event loop.
        self.tools_frame = PanelFrame(self.palette, "Tuile de base", on_change=self._on_panel_frame_change)
        self.room_frame = PanelFrame(self.room_panel, "Sauvegarder / Charger", on_change=self._on_panel_frame_change)
        self.generator_frame = PanelFrame(self.generator_panel, "Generation procedurale", on_change=self._on_panel_frame_change)
        self.card_frame = PanelFrame(self.card_panel, "Cartes", on_change=self._on_panel_frame_change)
        self.stash_frame = PanelFrame(self.stash_panel, "Cartes trouvees", on_change=self._on_panel_frame_change)
        # Mechanical counterpart to sprite_editor_panel (visual/identity vs.
        # gameplay flags -- see MechanicsPanelUI's own module docstring) --
        # docked/draggable/resizable like every other panel here, not
        # modal. Reached only by dragging an owned card onto its own body
        # (see the object_tool.dragging handling in run()), never a
        # dedicated open button.
        self.mechanics_panel = MechanicsPanelUI(x=460, y=460)
        self.mechanics_frame = PanelFrame(self.mechanics_panel, "Forge", on_change=self._on_panel_frame_change)
        self.panel_frames = [
            self.tools_frame, self.room_frame, self.generator_frame, self.card_frame, self.stash_frame,
            self.mechanics_frame,
        ]
        # name -> frame, purely for _refresh_panel_layout/_on_panel_frame_change's
        # own round-trip through Profile.panel_layout (see those methods).
        self._panel_frames_by_name = {
            "tools": self.tools_frame,
            "room": self.room_frame,
            "generator": self.generator_frame,
            "card": self.card_frame,
            "stash": self.stash_frame,
            "mechanics": self.mechanics_frame,
        }

        # See _refresh_generator_panel/_refresh_panel_layout -- seeded
        # lazily from the local profile once a player identity actually
        # exists, not here (Creator is constructed before Menu's name-entry
        # screen has necessarily run).
        self._generator_panel_seeded = False
        self._panel_layout_seeded = False

        self.painting = False
        self.erasing = False
        # Set from a MOUSEBUTTONDOWN's own position (see run()'s panel_click
        # computation) and reused as-is on the matching MOUSEBUTTONUP --
        # fixes a real bug: dragging a panel's own slider (e.g. the card
        # panel's enlarged-grid scrollbar) released fine, since MOUSEMOTION/
        # MOUSEBUTTONUP both still reach the panel's handle_event, but
        # panel_click used to be recomputed fresh from the CURRENT event's
        # position on every event -- always False for a MOUSEBUTTONUP (only
        # ever computed for MOUSEBUTTONDOWN) -- so releasing the slider fell
        # through to the generic left-click-up handling below (which flushes
        # the profile and calls _refresh_card_panel(), silently resetting
        # the card panel's own scroll position back to 0 on every release).
        # Remembering which press this drag started from fixes it for good,
        # not just for the card panel.
        self._panel_owns_drag = False

        # Vision produit v0.05 -- Sol/Mur tools connected to the card
        # collection (core.data.cards "tile_floor"/"tile_wall"). Both True
        # by default, same as today's implicit always-floor-with-autotile
        # behavior -- Creator.dungeon.autotile_enabled is derived from these
        # two (see the ToolPaletteUI toggle handling below), never set
        # directly anymore. self._active_profile is the local player's
        # Profile, cached for the whole Creator session and mutated in
        # place by painting/placing (see _refresh_active_profile,
        # _paint_at_mouse, _try_place_object) -- reloading it from disk on
        # every single paint click would be wasteful and would also lose
        # in-memory decrements made earlier in the same drag stroke.
        self.floor_tool_active = True
        self.wall_tool_active = True
        self._active_profile = None
        # Set by _consume_card/_refund_card whenever a card's stock actually
        # changed -- lets the MOUSEBUTTONUP handlers below only pay for
        # _refresh_card_panel() (which wipes CardRenderer's whole cache and
        # rescans the card/room directories, see CardPanelUI.refresh) when a
        # stroke genuinely spent or refunded something, instead of on every
        # single paint/erase stroke regardless of outcome.
        self._card_stock_dirty = False

        self.link_source = None
        self.link_drag_pos = None

        self.moving_object = None
        self.move_drag_pos = None

        self.panning = False
        self.pan_last_pos = None

        self.camera = Camera(zoom=1.0)
        self.grid_zoom = self.camera.zoom

        self.spawn_preview = None

    def _mouse_to_grid(self, mouse_pos):

        world_x, world_y = self.camera.screen_to_world(*mouse_pos)

        return self.dungeon.world_to_grid(world_x, world_y)

    def _is_valid_grid_cell(self, mouse_pos):

        grid_x, grid_y = self._mouse_to_grid(mouse_pos)

        return (
            0 <= grid_x < self.dungeon.width
            and
            0 <= grid_y < self.dungeon.height
        )

    def _grow_dungeon_for_mouse(self, mouse_pos):
        """Painting's own version of _is_valid_grid_cell -- instead of
        just rejecting a click outside the current grid, grows self.dungeon
        (see Dungeon.grow) exactly enough to bring it in bounds, in
        whichever of the 4 directions are needed, then recenters the
        camera so the view doesn't visually jump (a left/top grow inserts
        new columns/rows before the existing ones, so every already-
        painted cell's own grid index -- and therefore its screen position
        under an unmoved camera -- would otherwise shift). Deliberately
        does NOT return adjusted grid coordinates -- every caller already
        calls _mouse_to_grid again right after this (existing code,
        unchanged), and that naturally resolves to the right cell once the
        camera has been recentered here, with no coordinate math needed at
        any call site. Returns False (nothing painted) if growing enough
        would exceed Dungeon.MAX_ROOM_DIMENSION -- same silent-reject
        contract _is_valid_grid_cell already had for an out-of-bounds
        click, just reachable from a different distance now. Only used by
        the two PAINT entry points (left-click, drag-paint) -- erasing and
        the object-drop preview keep using _is_valid_grid_cell unchanged,
        since growing the room for either of those makes no sense."""
        grid_x, grid_y = self._mouse_to_grid(mouse_pos)
        left = max(0, -grid_x)
        top = max(0, -grid_y)
        right = max(0, grid_x + 1 - self.dungeon.width)
        bottom = max(0, grid_y + 1 - self.dungeon.height)
        if not (left or top or right or bottom):
            return True
        if not self.dungeon.grow(left=left, right=right, top=top, bottom=bottom):
            return False
        self.camera.x += left * self.dungeon.tile_size
        self.camera.y += top * self.dungeon.tile_size
        return True

    def open_room(self, name):
        self.current_room = name
        self.last_assembly = None
        self.chest_panel.close()
        self.role_panel.close()
        self.dungeon.load_from_json(name)

    def open_donjon(self, name):
        """Preview a saved procedurally-assembled dungeon instead of a single room."""
        self.last_assembly = load_assembly(name)
        self.assembly_active_floor = 0
        self.current_room = None
        self.chest_panel.close()
        self.role_panel.close()

    def _is_home_room(self):
        """True while the currently-open room is the local player's own
        home -- gates the zoom-driven switch to Exploration in run() below
        (core.world.home), never true while previewing a generated donjon
        (current_room is None there) or before a player name exists."""
        settings = self.game_manager.settings
        if settings is None or not settings.local_player_name:
            return False
        return self.current_room == home_room_name(settings.local_player_name)

    def _apply_room_action(self, action):
        mode, selection = action

        if mode == "save":
            self.room_manager.save(selection)
            self.current_room = selection
            # A saved room's card (a new room-card if `selection` is a brand
            # new name, or an existing one whose manifest/properties/
            # thumbnail just changed) must not keep showing whatever
            # CardRenderer cached before this save -- see CardRenderer.
            # get_room_properties/_sprite_for, both keyed off the room's
            # on-disk content and only invalidated by clear_cache().
            self._refresh_card_panel()

        elif mode == "load":
            kind, name = selection
            if kind == "donjon":
                self.open_donjon(name)
            else:
                self.open_room(name)

        elif mode == "delete":
            self._delete_room(selection)

        self.generator_panel.refresh_rooms()

    def _can_rename_room(self, name):
        """RoomBrowser's can_rename predicate (see RoomPanelUI/
        GeneratorPanelUI wiring in __init__) -- False for a name matching
        home_room_name(...) for the local player, so "Renommer" simply
        never appears in that row's right-click menu. home_room_name() is
        always recomputed from the player's own name, never stored --
        renaming the file out from under it would silently orphan the
        player's home (the next home_room_name() check would find nothing
        there and ensure_home_room would recreate a brand-new blank one)."""
        settings = self.game_manager.settings
        if settings is None or not settings.local_player_name:
            return True
        return name != home_room_name(settings.local_player_name)

    def _rename_room(self, old_name, new_name):
        """RoomBrowser's on_rename callback, wired into both RoomPanelUI's
        and GeneratorPanelUI's room lists (see __init__) -- a single
        implementation reachable from either. _can_rename_room already
        keeps a home_<player> room from ever reaching here through the
        normal right-click flow; re-checked here too as cheap defense in
        depth."""
        if not self._can_rename_room(old_name):
            return

        actual_new_name = self.room_manager.rename(old_name, new_name)
        if actual_new_name is None:
            return  # refused (bad/colliding name) -- RoomManager already validated, silent no-op

        if self.current_room == old_name:
            self.current_room = actual_new_name

        profile = self._load_profile()
        if profile is not None and old_name in profile.generator_room_names:
            profile.generator_room_names = [
                actual_new_name if name == old_name else name
                for name in profile.generator_room_names
            ]
            ProfileManager().save(profile)

        # Preserve the generation pool's checkbox through the rename --
        # GeneratorPanelUI.refresh_rooms() below re-derives selection from
        # name equality against whatever was selected *before* the
        # refresh, which still says the OLD name at that point; without
        # this, a room checked in the pool would silently uncheck itself
        # the moment it's renamed.
        was_selected = old_name in self.generator_panel.pool_browser.selected_names

        self.room_panel.refresh_rooms()
        self.generator_panel.refresh_rooms()

        if was_selected:
            for index, name in enumerate(self.generator_panel.pool_browser.rooms):
                if name == actual_new_name:
                    self.generator_panel.pool_browser.selected_set.add(index)
                    break

    def _delete_room(self, name):
        """RoomBrowser's on_delete callback -- same mechanics as
        RoomPanelUI's own "Supprimer" button flow (_apply_room_action now
        just calls this too, see above), reachable from either room list's
        right-click menu as well. Also drops `name` from the current
        profile's generation pool if it was selected there, for the same
        reason a rename updates it -- a deleted room has no business
        staying in a saved pool.

        Vision produit v0.05 -- rooms as cards: a room "stores" the tile/
        object cards spent building it, so deleting one must refund them
        (room_card_manifest) before the file disappears -- via
        self._active_profile/_flush_active_profile, not a separately loaded
        profile, to avoid the exact "stale profile clobbers a concurrent
        change" class of bug fixed earlier in Explorator._grant_xp."""
        if self._active_profile is not None:
            for card_id, count in room_card_manifest(name).items():
                self._active_profile.card_collection[card_id] = (
                    self._active_profile.card_collection.get(card_id, 0) + count
                )
            self._flush_active_profile()

        self.room_manager.delete(name)
        if self.current_room == name:
            self.current_room = None

        profile = self._load_profile()
        if profile is not None and name in profile.generator_room_names:
            profile.generator_room_names = [n for n in profile.generator_room_names if n != name]
            ProfileManager().save(profile)

        self.room_panel.refresh_rooms()
        self.generator_panel.refresh_rooms()
        self._refresh_card_panel()

    def _toggle_room_in_pool(self, room_name):
        """Drop target for dragging a room-card onto the Generator (see
        run()'s MOUSEBUTTONUP handling) -- simple add/retire toggle of pool
        membership, confirmed with the user over a weighted/duplicate-adding
        mechanic. Silent no-op if room_name isn't (or is no longer) in the
        pool browser's own room list."""
        browser = self.generator_panel.pool_browser
        if room_name not in browser.rooms:
            return
        index = browser.rooms.index(room_name)
        if index in browser.selected_set:
            browser.selected_set.discard(index)
        else:
            browser.selected_set.add(index)

    def _resolve_dragged_card(self, event):
        """Resolves an in-progress card drag (self.object_tool.dragging) on
        its matching MOUSEBUTTONUP -- see the call site in run() for why
        this must run unconditionally, before panel_click's own gate,
        rather than from inside the generic MOUSEBUTTONUP handler below
        (where this logic used to live and could never actually run for a
        card-panel-originated drag)."""
        card_id = self.object_tool.object_type

        if self.object_tool.drag_source == "stash":
            # A stash-sourced card isn't owned yet -- the only meaningful
            # drop target is the collection panel itself, to deposit it
            # (see _deposit_stash_card). Never placeable in the world,
            # never opens the Forge, regardless of card_id/card_type --
            # checked first, before every other branch below, so a stash
            # drag can never be misrouted into one of those.
            if self.card_frame.contains(event.pos):
                self._deposit_stash_card(card_id)
            self.object_tool.dragging = False
            self.object_tool.drag_source = "collection"
            return

        room_name = room_name_from_card_id(card_id)
        if room_name is not None:
            # A room-card is never placeable in the world grid
            # (_try_place_object assumes OBJECT_TYPES/add_object semantics)
            # -- the only meaningful drop target is the Generator, which
            # toggles pool membership. Dropping anywhere else just cancels,
            # same as any other drag that misses its target.
            if self.generator_frame.contains(event.pos) and self._generator_unlocked():
                self._toggle_room_in_pool(room_name)
        elif card_id in ITEM_DEFINITIONS:
            # An item-card is never placeable in the world grid either
            # (items live in inventory slots/loot tables, not OBJECT_TYPES'
            # add_object -- _try_place_object would KeyError on an id it
            # doesn't know) -- the only meaningful drop target is the
            # Forge, to inspect/edit its capacites/effets.
            if self.mechanics_frame.contains(event.pos) and self._forge_unlocked():
                if not self.mechanics_panel.try_add_loot_card(card_id, event.pos):
                    self.mechanics_panel.open(card_id)
        elif self.mechanics_frame.contains(event.pos) and self._forge_unlocked():
            # try_add_loot_card first: a drop landing specifically on the
            # Forge's own Cartes section (only possible while it's already
            # showing a card that supports one, see
            # MechanicsPanelUI._shows_loot_cards) adds this card as a loot
            # entry instead of replacing what's loaded -- open() is the
            # fallback for everywhere else on the panel, same as before.
            # MechanicsPanelUI.open() already refuses (stays empty) for
            # anything that isn't a real OBJECT_TYPES/ITEM_DEFINITIONS id --
            # no extra guard needed here.
            if not self.mechanics_panel.try_add_loot_card(card_id, event.pos):
                self.mechanics_panel.open(card_id)
        elif not any(frame.contains(event.pos) for frame in self.panel_frames):
            # Only attempt world placement if the drop isn't sitting over
            # ANY docked panel -- without this, a drop on e.g. tools_frame/
            # room_frame (which can visually overlap the grid) would
            # silently "pass through" to whatever world cell happens to be
            # behind it. Covers every current AND future panel in
            # panel_frames, not a hardcoded list.
            self._try_place_object()
        # else: dropped on some other docked panel -- clean cancel, nothing
        # placed/consumed, same as any other drag that misses its target.

        self.object_tool.dragging = False
        self.object_tool.drag_source = "collection"

    def _apply_generation(self, request):
        room_names, room_count = request

        assembly = generate_assembly(room_names, room_count)

        if assembly is None:
            self.generator_panel.status_text = "Aucune salle avec spawn + sortie dans la selection."
            return

        donjon_name = next_new_donjon_name()
        save_assembly(assembly, donjon_name)

        self.last_assembly = assembly
        self.assembly_active_floor = 0
        self.generator_panel.status_text = (
            f"{donjon_name} : {len(assembly.rooms)} salle(s) sur {len(assembly.floors())} etage(s)."
        )

        # Persist this pool/count so a dungeon_entrance crossing (see
        # Explorator._check_dungeon_entrance) has the same parameters to
        # generate from later, and so the panel reopens with this choice
        # on a fresh app launch instead of resetting to "every room, 3".
        profile = self._load_profile()
        if profile is not None:
            profile.generator_room_names = list(room_names)
            profile.generator_room_count = room_count
            ProfileManager().save(profile)

    def _find_indicator_at(self, mouse_pos):
        mx, my = mouse_pos
        object_manager = self.dungeon.object_manager

        for obj in object_manager.objects:
            # Also matches E/S types (gate/wall/cave_entrance/big_entrance)
            # even when not "linkable" -- cave_entrance/big_entrance never
            # button-link to anything, but still need a dot to right-click
            # for RolePanelUI (see run()'s MOUSEBUTTONDOWN handling).
            if not (object_manager.is_linkable(obj["type"]) or object_manager.is_es_type(obj["type"])):
                continue

            sx, sy = self.camera.world_to_screen(*self.dungeon.object_indicator_position(obj))

            if (sx - mx) ** 2 + (sy - my) ** 2 <= self.INDICATOR_HIT_RADIUS ** 2:
                return obj

        return None

    def _consume_card(self, card_id):
        """True (and decrements) if the cached local profile has >=1 of
        card_id in stock; False (nothing changed) if there's no profile or
        none left -- the single gate every terrain-paint path goes through
        (see _paint_at_mouse). Object placement (_try_place_object) checks/
        decrements inline instead, since it needs to peek the stock BEFORE
        attempting a placement that can itself still fail validation.

        Profile.admingod pins card_collection[card_id] to ADMINGOD_STOCK and
        always succeeds instead of checking/decrementing -- works even for a
        card_id never actually granted (e.g. one just created via the
        sprite editor this session), unlike a plain "give a huge count"
        seed would for anything registered afterward."""
        if self._active_profile is None:
            return False
        if self._active_profile.admingod:
            self._active_profile.card_collection[card_id] = ADMINGOD_STOCK
            self._card_stock_dirty = True
            return True
        if self._active_profile.card_collection.get(card_id, 0) <= 0:
            return False
        self._active_profile.card_collection[card_id] -= 1
        self._card_stock_dirty = True
        return True

    def _refund_card(self, card_id):
        """Credits one card back -- erasing terrain/removing an object is
        the symmetric inverse of _consume_card, and is never blocked
        (unlike consuming, there's no "can't refund" case). card_id=None
        (nothing to refund, e.g. erasing an already-EMPTY cell) is a
        no-op. A no-op under admingod too -- _consume_card already pins the
        stock, nothing was ever really spent to give back (and the sprite
        editor's own "grant the first copy of a new card" call goes through
        this too -- see run()'s sprite-editor block -- where under
        admingod every card already reads as unlimited, so there's nothing
        useful left for this to do)."""
        if self._active_profile is None or card_id is None or self._active_profile.admingod:
            return
        self._active_profile.card_collection[card_id] = self._active_profile.card_collection.get(card_id, 0) + 1
        self._card_stock_dirty = True

    def _deposit_stash_card(self, card_id):
        """Moves one copy of `card_id` from the cached profile's card_stash
        into card_collection -- the only thing a "stash" drag_source drag
        can ever do (see _resolve_dragged_card), dropped onto card_frame.
        No-op if there's no active profile or this card isn't actually in
        the stash (stale drag, e.g. StashPanelUI wasn't refreshed after
        some other change emptied it first)."""
        if self._active_profile is None:
            return
        stash = self._active_profile.card_stash
        if stash.get(card_id, 0) <= 0:
            return
        stash[card_id] -= 1
        if stash[card_id] <= 0:
            del stash[card_id]
        self._active_profile.card_collection[card_id] = self._active_profile.card_collection.get(card_id, 0) + 1
        self._flush_active_profile()
        self._refresh_card_panel()

    def _flush_active_profile(self):
        """Persists the cached profile's card_collection to disk -- called
        at the END of a paint/erase stroke (MOUSEBUTTONUP) or right after a
        successful object placement, never per-cell/per-frame during a
        drag (which can call _paint_at_mouse dozens of times a second)."""
        if self._active_profile is not None:
            ProfileManager().save(self._active_profile)

    def _paint_at_mouse(self, mouse_pos, erase=False):
        """Thin dispatcher -- see ToolPaletteUI for what Sol/Mur mean.

        Erasing is always a single, raw cell removal, independent of
        floor_tool_active/wall_tool_active (simplified at the user's
        request: the eraser used to inherit floor_tool_active-and-
        wall_tool_active's derived autotile_enabled, so what erase reached
        -- a lone cell or a whole wall-halo cascade -- depended on
        whatever happened to be selected for *placing*, two genuinely
        unrelated concerns that "delete this" shouldn't have to think
        about). Painting still derives autotile_enabled from the two
        Sol/Mur flags exactly as before -- only erase changed."""
        grid_x, grid_y = self._mouse_to_grid(mouse_pos)

        if erase:
            self.dungeon.autotile_enabled = False
            self._erase_and_refund(grid_x, grid_y)
            return

        self.dungeon.autotile_enabled = self.floor_tool_active and self.wall_tool_active
        if self.floor_tool_active and self.wall_tool_active:
            self._paint_autotile_and_charge(grid_x, grid_y)
        elif self.floor_tool_active:
            self._paint_raw_and_charge(grid_x, grid_y, FLOOR, "tile_floor")
        elif self.wall_tool_active:
            self._paint_raw_and_charge(grid_x, grid_y, WALL, "tile_wall")
        # else: neither tool active -- nothing to paint.

    def _objects_near(self, grid_x, grid_y, radius=LOCAL_EDIT_SPRITE_RADIUS):
        """Every currently-placed object whose footprint falls within
        `radius` (Chebyshev) of (grid_x, grid_y) -- id(obj) -> obj, for
        _refund_pruned_objects to snapshot before a terrain edit. A single
        paint/erase can only ever change logical_grid cells within
        LOCAL_EDIT_SPRITE_RADIUS of the clicked cell (see autotile.py's own
        docstring on that constant), and every placement rule
        (_resolve_placement) only ever reads an object's own cell plus at
        most one more cell out (a torch's adjacent wall, an E/S doorway's 4
        neighbors, a stairs neighbor) -- so an object more than
        LOCAL_EDIT_SPRITE_RADIUS away from the click can never have its
        validity affected by that edit, and doesn't need to be in this
        snapshot at all. Uses ObjectManager.get_object_at (O(1) per cell via
        its own cell index) over the padded neighborhood instead of scanning
        the dungeon's full object list, which is what made the old
        before/after diff cost O(total placed objects) per painted cell of
        a drag stroke regardless of room size."""
        object_manager = self.dungeon.object_manager
        found = {}
        for y in range(grid_y - radius, grid_y + radius + 1):
            for x in range(grid_x - radius, grid_x + radius + 1):
                obj = object_manager.get_object_at(x, y)
                if obj is not None:
                    found[id(obj)] = obj
        return found

    def _refund_pruned_objects(self, objects_before):
        """Refunds the card of any object in `objects_before` (id(obj) ->
        obj, gathered via _objects_near right before a terrain edit -- see
        call sites below) that's no longer the object occupying its own
        recorded cell -- prune_invalid() (run at the end of every Dungeon.
        paint_cell call, pose or erase) only ever REMOVES an object, never
        relocates one, so "is this exact object dict still what
        get_object_at(obj.x, obj.y) returns" is a sufficient, O(1)-per-
        candidate presence check -- no need to re-diff the whole object
        list to find out."""
        object_manager = self.dungeon.object_manager
        for obj in objects_before.values():
            if object_manager.get_object_at(obj["x"], obj["y"]) is not obj:
                self._refund_card(obj["type"])

    def _paint_raw_and_charge(self, grid_x, grid_y, cell_type, card_id):
        """Sol-only or Mur-only: paints cell_type directly, no autotile.
        A no-op if the cell is already cell_type (avoids re-charging a
        redundant repaint of an unchanged cell during a drag stroke).
        Converting the cell FROM the opposite terrain type (FLOOR<->WALL --
        a cell can only ever hold one) refunds THAT type's own card first:
        the wall tile visually replaces the floor tile there (or vice
        versa), so the card that was "covering" that cell is freed the
        moment a different one takes its place. Also refunds any placed
        object this conversion prunes (e.g. painting a wall over a vase's
        floor cell) -- a real bug reported by the user, previously only
        handled on the erase side (_erase_and_refund)."""
        previous = self.dungeon.logical_grid[grid_y][grid_x]
        if previous == cell_type:
            return
        if not self._consume_card(card_id):
            return
        previous_card = {FLOOR: "tile_floor", WALL: "tile_wall"}.get(previous)
        if previous_card is not None:
            self._refund_card(previous_card)
        objects_before = self._objects_near(grid_x, grid_y)
        self.dungeon.paint_cell(grid_x, grid_y, erase=False, cell_type=cell_type)
        self._refund_pruned_objects(objects_before)

    def _paint_autotile_and_charge(self, grid_x, grid_y):
        """Sol+Mur both active: today's full-autotile placement, but now
        charging exactly what actually gets placed -- 1 tile_floor for the
        clicked cell, plus 1 tile_wall for each empty neighbor
        build_walls_around actually walls. wall_gate is called once per
        candidate halo cell, live, as build_walls_around iterates them --
        _consume_card only returns True while stock remains, so running out
        of tile_wall partway through leaves the rest of the halo empty
        (a partial fill) instead of overspending or blocking the floor
        placement itself (confirmed with the user). Same conversion-refund
        rule as _paint_raw_and_charge if the clicked cell was previously a
        WALL, and the same pruned-object refund (a vase under the clicked
        cell, or under a neighbor the halo walls over)."""
        previous = self.dungeon.logical_grid[grid_y][grid_x]
        if previous == FLOOR:
            return
        if not self._consume_card("tile_floor"):
            return
        if previous == WALL:
            self._refund_card("tile_wall")
        objects_before = self._objects_near(grid_x, grid_y)
        self.dungeon.paint_cell(
            grid_x, grid_y, erase=False,
            wall_gate=lambda nx, ny: self._consume_card("tile_wall"),
        )
        self._refund_pruned_objects(objects_before)

    def _erase_and_refund(self, grid_x, grid_y):
        """Erasing is now always the raw single-cell branch (see
        _paint_at_mouse -- autotile_enabled is forced False before this is
        ever called), so the clicked cell is the only terrain cell that
        can possibly change -- refunds its prior type directly, no
        before/after grid diff needed for the terrain itself. Object
        pruning still needs the bounded-neighborhood diff -- see
        _refund_pruned_objects/_objects_near."""
        cell_before = self.dungeon.logical_grid[grid_y][grid_x]
        objects_before = self._objects_near(grid_x, grid_y)

        self.dungeon.paint_cell(grid_x, grid_y, erase=True)

        self._refund_card({FLOOR: "tile_floor", WALL: "tile_wall"}.get(cell_before))
        self._refund_pruned_objects(objects_before)

    def _drag_sprite(self, object_type):
        """The small card image that follows the mouse while dragging a
        card to place it (from the collection, see the MOUSEBUTTONDOWN
        handling in run()) or relocating an already-placed object
        (self.moving_object) -- replaces the old ObjectPalette.
        get_current_frame(type), now that the card collection is the
        object-placement tool. Uses the same shared CardRenderer/cache the
        Cards panel itself renders from -- get_card() resolves object_type
        once per clear_cache() cycle (not once per rendered frame of the
        drag, which used to mean a fresh CardManager().load() disk read on
        every single frame the drag sprite was drawn)."""
        card = self.card_renderer.get_card(object_type)
        return self.card_renderer.get_surface(card, self.DRAG_CARD_HEIGHT)

    def _try_place_object(self):
        """Checks the object type's card stock BEFORE attempting placement
        (unlike terrain painting, add_object can still fail its own
        placement-rule validation, so the stock is only ever actually
        decremented once placement has genuinely succeeded -- never
        consume-then-refund)."""
        object_type = self.object_tool.object_type
        if self._active_profile is None:
            return False
        admingod = self._active_profile.admingod
        if not admingod and self._active_profile.card_collection.get(object_type, 0) <= 0:
            return False

        # object_tool.position is where the cursor is, which is now treated
        # as the anchor cell (bottom-center of the footprint -- see
        # ObjectManager._anchor_cell/origin_for_anchor), not the object's
        # top-left origin -- otherwise a multi-cell object's terrain check
        # lands size_x/size_y cells away from wherever the player is
        # actually pointing.
        world = self.camera.screen_to_world(*self.object_tool.position)
        anchor_x, anchor_y = self.dungeon.world_to_grid(*world)
        grid_x, grid_y = self.dungeon.object_manager.origin_for_anchor(object_type, anchor_x, anchor_y)

        if not self.dungeon.object_manager.add_object(object_type, grid_x, grid_y):
            return False

        placed_config = OBJECT_TYPES.get(object_type, {})
        play_card_sound(
            placed_config.get("sounds", {}), "place",
            pitch_range=placed_config.get("sound_pitch", {}).get("place"),
        )

        if admingod:
            self._active_profile.card_collection[object_type] = ADMINGOD_STOCK
        else:
            self._active_profile.card_collection[object_type] -= 1
        self._flush_active_profile()
        # A type that just hit 0 stock must disappear from the collection
        # panel's grid/list right away, not wait for the next entry into
        # Creator -- CardPanelUI itself is the single source of truth for
        # "what's placeable" now (ObjectPalette retired), so refreshing it
        # is the only bookkeeping needed here.
        self._refresh_card_panel()
        return True

    def _refresh_active_profile(self):
        """Loads (or reloads) the local player's Profile once per entry
        into Creator (see run()) -- _refresh_card_panel/_paint_at_mouse/
        _try_place_object all read and mutate this same cached instance for
        the rest of the session instead of each reloading their own copy
        from disk, which would be wasteful (a paint stroke can call
        _paint_at_mouse dozens of times a second) and would lose in-memory
        decrements made earlier in the same stroke."""
        self._active_profile = self._load_profile()

    def _load_profile(self):
        """The local player's Profile, or None if there's no identity yet
        (headless smoke test, or -- Creator itself is constructed before
        Menu's name-entry screen has necessarily run -- the very first
        frame of a fresh install). A fresh disk read every call -- callers
        that need a stable, mutate-in-place instance across a whole Creator
        session (card consumption/refund) go through
        self._active_profile/_refresh_active_profile instead of calling
        this directly."""
        settings = self.game_manager.settings
        name = settings.local_player_name if settings is not None else None
        if not name:
            return None
        return ProfileManager().load(name)

    def _refresh_generator_panel(self):
        """Seeds GeneratorPanelUI's room pool/count from the local profile's
        saved selection exactly once (self._generator_panel_seeded) -- not
        on every entry into Creator, which would otherwise stomp on
        whatever the player has live-selected in the panel this session
        with whatever was last saved to disk."""
        if self._generator_panel_seeded:
            return
        profile = self._load_profile()
        if profile is None:
            return
        self.generator_panel.apply_profile(profile)
        self._generator_panel_seeded = True

    def _refresh_card_panel(self):
        """Reloads the Card panel's list/owned-counts, and the found-cards
        Stash panel's own list, from the cached local profile
        (self._active_profile, see _refresh_active_profile) -- called once
        per entry into Creator, and again after any card-consuming action
        (_try_place_object, a stash deposit) so both panels' counts stay
        live instead of waiting for the next entry. A no-op with no local
        identity yet (headless smoke test, or the very first frame before
        Menu's name-entry has run) -- both panels just stay on whatever
        they last showed, empty at the very start."""
        if self._active_profile is not None:
            self.card_panel.refresh(self._active_profile)
            self.stash_panel.refresh(self._active_profile)

    def _refresh_panel_layout(self):
        """Restores each PanelFrame's saved position/collapsed state from
        the local profile's Profile.panel_layout, exactly once (same lazy,
        seeded-only-when-a-real-identity-exists shape as
        _refresh_generator_panel -- Creator is constructed before Menu's
        name-entry screen has necessarily run, so this can't happen in
        __init__). A missing/empty entry (a fresh profile, or a frame added
        after the profile was last saved) leaves that panel at whatever its
        constructor already placed it at."""
        if self._panel_layout_seeded:
            return
        profile = self._load_profile()
        if profile is None:
            return
        for name, frame in self._panel_frames_by_name.items():
            saved = profile.panel_layout.get(name)
            if saved is None:
                continue
            frame.move_to(saved["x"], saved["y"])
            frame.collapsed = saved.get("collapsed", False)
        self._panel_layout_seeded = True

    def _on_panel_frame_change(self, _frame):
        """PanelFrame's on_change callback (a drag ended, or the collapse
        toggle was clicked) -- saves every frame's current position/
        collapsed state to the local profile right away, same
        save-immediately-after-the-action principle as
        _apply_generation saving generator_room_names/count. `_frame`
        itself is unused (every frame is re-saved together, simplest
        correct thing for 4 small dicts) -- named with a leading
        underscore to say so without the linter flagging an unused
        parameter as a real one."""
        profile = self._load_profile()
        if profile is None:
            return
        profile.panel_layout = {
            name: {"x": frame.panel.x, "y": frame.panel.y, "collapsed": frame.collapsed}
            for name, frame in self._panel_frames_by_name.items()
        }
        ProfileManager().save(profile)

    # Entity-gated tools -- Generateur unlocks near a placed "djepeto",
    # Forge unlocks near a placed "totem3" (first pass of attributing
    # editor tools to specific in-world entities instead of leaving every
    # tool globally available). Creator itself owns no player entity (only
    # a camera) -- see Profile.home_player_position/
    # Explorator._check_home_zoom_switch for where the position this reads
    # actually comes from.
    GENERATOR_ENTITY_TYPE = "djepeto"
    FORGE_ENTITY_TYPE = "totem3"

    def _entity_field_radius(self):
        """Mirrors Explorator._magnet_radius's exact 'champ de vision'
        formula (half the screen's smaller dimension, scaled by zoom) so an
        entity-gated tool unlocks at the same in-game distance regardless
        of whether the check happens in Explo or here."""
        return min(self.screen.get_width(), self.screen.get_height()) / (2 * self.camera.zoom)

    def _player_position(self):
        """Last position saved when the player crossed from Exploration into
        Creator on the home room (Profile.home_player_position) -- None if
        that has never happened yet (fresh profile, headless smoke test, or
        no local identity), which fails every entity gate closed rather than
        guessing a position."""
        if self._active_profile is None:
            return None
        saved = self._active_profile.home_player_position
        if saved is None:
            return None
        return saved.get("x"), saved.get("y")

    def _entity_in_range(self, object_type):
        """True if the currently open room has at least one placed object of
        `object_type` within _entity_field_radius of the saved player
        position. No saved position, or no such object placed in this room,
        both fail closed -- a tool tied to an entity that was never
        approached (or isn't even placed here) stays locked."""
        player_pos = self._player_position()
        if player_pos is None:
            return False
        px, py = player_pos
        radius_sq = self._entity_field_radius() ** 2
        for obj in self.dungeon.object_manager.objects:
            if obj["type"] != object_type:
                continue
            ox, oy = self.dungeon.grid_to_world(obj["x"], obj["y"])
            if (ox - px) ** 2 + (oy - py) ** 2 <= radius_sq:
                return True
        return False

    def _generator_unlocked(self):
        return self._entity_in_range(self.GENERATOR_ENTITY_TYPE)

    def _forge_unlocked(self):
        return self._entity_in_range(self.FORGE_ENTITY_TYPE)

    def _draw_panel_lock_overlay(self, frame, message):
        """Dims a docked panel's body and explains why it's inaccessible --
        the title bar stays undimmed/draggable (PanelFrame.handle_title_event
        never checks lock state), so a locked panel can still be repositioned
        or collapsed, it just refuses interaction until the matching entity
        is back in range."""
        if frame.collapsed:
            return
        body_rect = pygame.Rect(frame.panel.x, frame.panel.y, frame.panel.width, frame.panel.height)
        overlay = pygame.Surface(body_rect.size, pygame.SRCALPHA)
        overlay.fill((10, 10, 16, 215))
        self.screen.blit(overlay, body_rect.topleft)
        label = self.assembly_hint_font.render(message, True, (255, 205, 110))
        self.screen.blit(label, label.get_rect(center=body_rect.center))

    def _is_quit_event(self, event):
        """QUIT must always work even while a modal panel (chest/role/
        autotile_theme/sprite_editor) has swallowed every other event type
        in run()'s loop below -- every modal branch there needs this exact
        same reaction, previously copy-pasted at each one."""
        if event.type != pygame.QUIT:
            return False
        self.game_manager.running = False
        return True

    def run(self):

        pygame.display.set_caption("DungeonArchitect - Dungeon Editor")

        # _refresh_active_profile must happen before _refresh_card_panel,
        # which reads self._active_profile instead of loading its own copy.
        self._refresh_panel_layout()
        self._refresh_active_profile()
        self._refresh_generator_panel()
        self._refresh_card_panel()

        clock = pygame.time.Clock()

        if os.environ.get("DUNGEONARCHITECT_HEADLESS") == "1":
            self.dungeon.save_to_json(DEFAULT_GRID_SAVE_PATH)
            self.game_manager.running = False
            pygame.quit()
            return

        running = True

        while running:

            # -------------------------------------------------
            # Events
            # -------------------------------------------------

            for event in pygame.event.get():

                if self.chest_panel.is_open or self.role_panel.is_open or self.autotile_theme_panel.is_open:
                    # Fully modal -- every other tool/panel acts on
                    # self.dungeon, which is exactly what the open chest/E-S
                    # belongs to, so letting painting/saving/etc. run
                    # "underneath" it would be confusing at best. QUIT must
                    # still always work.
                    if self._is_quit_event(event):
                        running = False
                        break
                    if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                        if self.chest_panel.is_open:
                            self.chest_panel.handle_event(event)
                        elif self.role_panel.is_open:
                            role = self.role_panel.handle_event(event)
                            if role is not None:
                                self.dungeon.object_manager.set_role(self.role_panel.obj, role)
                        else:
                            # Read role BEFORE handle_event -- it calls
                            # self.close() internally on a row click, which
                            # clears .role, so reading it after would always
                            # see None regardless of which button opened this.
                            role = self.autotile_theme_panel.role
                            changed, pack_name = self.autotile_theme_panel.handle_event(event)
                            if changed:
                                # Only changes the active BRUSH -- never
                                # resyncs the whole grid anymore, since that
                                # would retroactively repaint every already-
                                # placed floor/wall cell with the new pack
                                # instead of just future strokes (see
                                # Dungeon.theme_grid/paint_cell).
                                if role == "floor":
                                    self.dungeon.floor_theme = pack_name
                                else:
                                    self.dungeon.wall_theme = pack_name
                    continue

                if self.sprite_editor_panel.is_open:
                    # Same fully-modal treatment as chest_panel/role_panel
                    # above, kept as its own block since this one also needs
                    # KEYDOWN (the name field) -- QUIT must still work.
                    if self._is_quit_event(event):
                        running = False
                        break
                    if event.type in (
                        pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION, pygame.KEYDOWN,
                        pygame.MOUSEWHEEL,
                    ):
                        new_type_id = self.sprite_editor_panel.handle_event(event)
                        if new_type_id is not None:
                            # Same "credit one card back" gesture _refund_card
                            # already uses for erasing terrain/objects -- a
                            # freshly-registered type starts at 0 owned, so
                            # crediting 1 makes it immediately placeable/
                            # testable, matching --give-card's own intent.
                            self._refund_card(new_type_id)
                            self._flush_active_profile()
                            self._refresh_card_panel()
                    continue

                if self.game_manager.settings_panel.is_open:
                    # Same fully-modal treatment as the other panels above
                    # -- QUIT must still work. Shared with Explorator (see
                    # its own copy of this same check), not Creator-only,
                    # so this deliberately calls the panel's own
                    # handle_event directly rather than routing through
                    # anything Creator-specific.
                    if self._is_quit_event(event):
                        running = False
                        break
                    self.game_manager.settings_panel.handle_event(event)
                    continue

                # Draggable/collapsible panel title bars -- topmost frame
                # first (see panel_frames' own z-order docstring), checked
                # and fully consumed (continue) before anything else here
                # gets a look at the event, so a title-bar click/drag can
                # never also start painting, an object-palette drag, etc.
                # underneath it. handle_title_event only ever returns True
                # for an in-progress drag's own MOUSEMOTION/MOUSEBUTTONUP
                # (at most one frame is ever mid-drag at once), so iteration
                # order only actually matters for MOUSEBUTTONDOWN.
                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                    frame_claimed = False
                    for frame in reversed(self.panel_frames):
                        if frame.handle_title_event(event):
                            if event.type == pygame.MOUSEBUTTONDOWN:
                                self.panel_frames.remove(frame)
                                self.panel_frames.append(frame)
                            frame_claimed = True
                            break
                    if frame_claimed:
                        continue

                self.object_tool.handle_event(event)

                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION, pygame.MOUSEBUTTONUP):

                    if event.type == pygame.MOUSEBUTTONDOWN:
                        # Decided once, from THIS press's own position --
                        # see self._panel_owns_drag's own comment in
                        # __init__ for why the matching MOUSEBUTTONUP must
                        # reuse this instead of recomputing from wherever
                        # the mouse happens to be at release time.
                        self._panel_owns_drag = (
                            self.room_frame.contains(event.pos)
                            or self.generator_frame.contains(event.pos)
                            or self.card_frame.contains(event.pos)
                            or self.stash_frame.contains(event.pos)
                            or self.mechanics_frame.contains(event.pos)
                        )
                    panel_click = self._panel_owns_drag
                    if event.type == pygame.MOUSEBUTTONUP:
                        # The drag (if any) is over -- clear it now so a
                        # later idle MOUSEMOTION (hovering with no button
                        # held) doesn't keep inheriting a stale True from
                        # this press and wrongly skip its own hover/preview
                        # handling below.
                        self._panel_owns_drag = False

                    if not self.room_frame.collapsed:
                        room_action = self.room_panel.handle_event(event)

                        if room_action is not None:
                            self._apply_room_action(room_action)

                    if not self.generator_frame.collapsed and self._generator_unlocked():
                        generation_request = self.generator_panel.handle_event(event)

                        if generation_request is not None:
                            self._apply_generation(generation_request)

                    if not self.card_frame.collapsed:
                        # The card collection is now also the object-
                        # placement tool (ObjectPalette retired) -- a
                        # non-None return means this event just grabbed a
                        # placeable, owned card to start dragging it, from
                        # either display mode (see CardPanelUI.handle_event).
                        drag_card_id = self.card_panel.handle_event(event)
                        if drag_card_id is not None:
                            self.object_tool.start_drag(drag_card_id, event.pos)

                    if not self.stash_frame.collapsed:
                        # A found-but-undeposited card, dragged from here,
                        # is never placeable/openable -- see
                        # StashPanelUI.handle_event and
                        # _resolve_dragged_card's "stash" drag_source
                        # branch, which is the only thing that treats this
                        # drag differently from a normal collection one.
                        drag_stash_card_id = self.stash_panel.handle_event(event)
                        if drag_stash_card_id is not None:
                            self.object_tool.start_drag(drag_stash_card_id, event.pos, source="stash")

                    if not self.mechanics_frame.collapsed and self._forge_unlocked():
                        saved_type_id = self.mechanics_panel.handle_event(event)
                        if saved_type_id is not None:
                            self._refresh_card_panel()

                    # Resolves an in-progress card drag BEFORE the
                    # panel_click gate below -- a card drag always STARTS
                    # with a press inside card_frame's bounds (that's where
                    # cards live), so panel_click is always True for one and
                    # stays True through to the release, wherever that
                    # release actually is. panel_click/_panel_owns_drag was
                    # designed for an internal-to-one-panel gesture (see its
                    # own docstring in __init__, e.g. dragging the card
                    # panel's own scrollbar), not a drag meant to travel
                    # elsewhere -- if this resolution stayed gated behind
                    # "if panel_click: continue" like it used to, it would
                    # never run, and self.object_tool.dragging (only ever
                    # cleared inside _resolve_dragged_card) would stay True
                    # forever after the very first card drag, silently
                    # hijacking the next unrelated click anywhere on screen.
                    if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.object_tool.dragging:
                        self._resolve_dragged_card(event)

                    if panel_click:
                        continue

                if self.last_assembly is not None and event.type in (
                    pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION
                ):
                    # Previewing a generated assembly -- painting/object tools all act
                    # on self.dungeon, which isn't what's on screen right now.
                    # Middle-click pan is the one exception let through below:
                    # it only ever moves self.camera, never touches
                    # self.dungeon, so it's just as harmless (and just as
                    # useful for looking around a multi-room layout) here as
                    # it is on the normal single-room edit view.
                    is_middle_click = (
                        event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP)
                        and event.button == 2
                    )
                    is_pan_motion = event.type == pygame.MOUSEMOTION and self.panning
                    if not (is_middle_click or is_pan_motion):
                        continue

                if event.type == pygame.QUIT:

                    running = False
                    self.game_manager.running = False
                    break

                elif event.type == pygame.MOUSEBUTTONDOWN:

                    if event.button == 1:

                        if self.sprite_editor_button_rect.collidepoint(event.pos):
                            self.sprite_editor_panel.open()
                            continue

                        if self.settings_button_rect.collidepoint(event.pos):
                            self.game_manager.settings_panel.open()
                            continue

                        if not self.tools_frame.collapsed and self.palette.hit_floor_toggle(event.pos):
                            self.floor_tool_active = not self.floor_tool_active
                            continue

                        if not self.tools_frame.collapsed and self.palette.hit_wall_toggle(event.pos):
                            self.wall_tool_active = not self.wall_tool_active
                            continue

                        if not self.tools_frame.collapsed and self.palette.handle_click(event.pos):
                            continue

                        indicator_obj = self._find_indicator_at(event.pos)

                        if indicator_obj is not None:

                            if self.dungeon.object_manager.is_chest(indicator_obj["type"]):
                                self.chest_panel.open(indicator_obj)
                            elif self.dungeon.object_manager.is_linkable(indicator_obj["type"]):
                                self.link_source = indicator_obj
                                self.link_drag_pos = event.pos
                            # else: a cave_entrance/big_entrance dot (E/S but
                            # not linkable) -- left-click has no meaning for
                            # it, just consumed; right-click on the same dot
                            # opens RolePanelUI (below).
                            continue

                        if self._grow_dungeon_for_mouse(event.pos):

                            grid_x, grid_y = self._mouse_to_grid(event.pos)
                            existing_obj = self.dungeon.object_manager.get_object_at(grid_x, grid_y)

                            if existing_obj is not None:

                                self.moving_object = existing_obj
                                self.move_drag_pos = event.pos
                                continue

                            self.painting = True
                            self._paint_at_mouse(event.pos,erase=False)
                            self.erasing = False

                    elif event.button == 3:

                        if not self.tools_frame.collapsed and self.palette.hit_floor_toggle(event.pos):
                            self.autotile_theme_panel.open("floor", self.dungeon.floor_theme)
                            continue

                        if not self.tools_frame.collapsed and self.palette.hit_wall_toggle(event.pos):
                            self.autotile_theme_panel.open("wall", self.dungeon.wall_theme)
                            continue

                        indicator_obj = self._find_indicator_at(event.pos)

                        if indicator_obj is not None and self.dungeon.object_manager.is_es_type(indicator_obj["type"]):
                            self.role_panel.open(indicator_obj, allow_dungeon_entrance=self._is_home_room())
                            continue

                        if self._is_valid_grid_cell(event.pos):

                            self.erasing = True
                            self.painting = False

                            self._paint_at_mouse(event.pos, erase=True)

                    elif event.button == 2:

                        self.panning = True
                        self.pan_last_pos = event.pos


                elif event.type == pygame.MOUSEBUTTONUP:

                    if event.button == 1:

                        self.painting = False
                        # Persists whatever this stroke consumed -- see
                        # _flush_active_profile's own docstring for why this
                        # only happens here, not per-cell during the drag.
                        # _try_place_object also flushes internally on a
                        # successful placement -- a second, cheap no-op-ish
                        # save here for that case is harmless.
                        self._flush_active_profile()
                        if self._card_stock_dirty:
                            self._refresh_card_panel()
                            self._card_stock_dirty = False

                        if self.link_source is not None:

                            target_obj = self._find_indicator_at(event.pos)

                            if target_obj is not None and target_obj is not self.link_source:
                                self.dungeon.object_manager.link(self.link_source, target_obj)

                            self.link_source = None
                            self.link_drag_pos = None

                        elif self.moving_object is not None:

                            # Same anchor-based conversion as _try_place_object
                            # -- the cursor's grid cell is where the object's
                            # anchor (bottom-center) should land, not its
                            # top-left origin.
                            anchor_x, anchor_y = self._mouse_to_grid(event.pos)
                            grid_x, grid_y = self.dungeon.object_manager.origin_for_anchor(
                                self.moving_object["type"], anchor_x, anchor_y
                            )
                            self.dungeon.object_manager.move_object(self.moving_object, grid_x, grid_y)

                            self.moving_object = None
                            self.move_drag_pos = None
                        # object_tool.dragging (a card drag) is resolved
                        # earlier now, unconditionally, before the
                        # panel_click gate -- see _resolve_dragged_card and
                        # its call site above (this is the matching
                        # MOUSEBUTTONUP, but it isn't guaranteed to be
                        # reached for a card-drag release, see that call
                        # site's own comment for why).

                    elif event.button == 3:

                        self.erasing = False
                        # Erasing can refund an object's card back above 0
                        # stock (see _paint_at_mouse's erase branch), so the
                        # collection panel needs a chance to show it again.
                        self._flush_active_profile()
                        if self._card_stock_dirty:
                            self._refresh_card_panel()
                            self._card_stock_dirty = False

                    elif event.button == 2:

                        self.panning = False
                        self.pan_last_pos = None

                elif event.type == pygame.MOUSEMOTION:

                    if self.panning and self.pan_last_pos is not None:

                        dx = event.pos[0] - self.pan_last_pos[0]
                        dy = event.pos[1] - self.pan_last_pos[1]
                        self.camera.x -= dx / self.camera.zoom
                        self.camera.y -= dy / self.camera.zoom
                        self.pan_last_pos = event.pos

                    elif self.link_source is not None:

                        self.link_drag_pos = event.pos

                    elif self.moving_object is not None:

                        self.move_drag_pos = event.pos

                    elif self.painting and self._grow_dungeon_for_mouse(event.pos):

                        self._paint_at_mouse(event.pos, erase=False)

                    elif self.erasing and self._is_valid_grid_cell(event.pos):

                        self._paint_at_mouse(event.pos, erase=True)

                elif event.type == pygame.MOUSEWHEEL:
                    mouse_pos = pygame.mouse.get_pos()
                    # Hovering the card panel scrolls IT instead of zooming
                    # the grid underneath -- confirmed with the user: they
                    # want wheel-scroll to work anywhere over the panel, not
                    # just by precisely grabbing the thin slider thumb.
                    if not self.card_frame.collapsed and self.card_panel.handle_wheel(mouse_pos, event.y):
                        continue
                    if not self.stash_frame.collapsed and self.stash_panel.handle_wheel(mouse_pos, event.y):
                        continue
                    if not self.mechanics_frame.collapsed and self.mechanics_panel.handle_wheel(mouse_pos, event.y):
                        continue
                    self.camera.zoom_at(mouse_pos[0], mouse_pos[1], event.y, self.screen.get_width(), self.screen.get_height())
                    self.grid_zoom = self.camera.zoom

                elif event.type == pygame.KEYDOWN:

                    if event.key == pygame.K_TAB:
                        self.game_manager.state = GameState.EXPLORATION
                        running = False

                    elif event.key == pygame.K_ESCAPE:
                        if self.last_assembly is not None:
                            self.last_assembly = None
                        else:
                            self.game_manager.state = GameState.MENU
                            running = False

            # Zoom-driven Explo/Creator switch, home room only (see
            # core.world.home) -- everywhere else TAB is still the only
            # way to switch, unchanged.
            if running and self._is_home_room() and wants_exploration(self.camera.zoom):
                self.game_manager.pending_room = ("room", self.current_room)
                self.game_manager.pending_zoom_carry = self.camera.zoom
                self.game_manager.state = GameState.EXPLORATION
                running = False

            # -------------------------------------------------
            # Render
            # -------------------------------------------------
            dt = clock.tick(60) / 1000
            # The one piece of this static editor that needs real elapsed
            # time to animate -- MechanicsPanelUI's PNJ preview (see its own
            # update() docstring). A no-op call for every other card kind/
            # when nothing is loaded, so unconditional here is simplest.
            self.mechanics_panel.update(dt)
            if self.object_tool.dragging:

                grid_x, grid_y = self._mouse_to_grid(
                    self.object_tool.position
                )

                if (
                    0 <= grid_x < self.dungeon.width
                    and
                    0 <= grid_y < self.dungeon.height
                ):

                    if self.dungeon.logical_grid[grid_y][grid_x] == FLOOR:

                        self.spawn_preview = (
                            grid_x,
                            grid_y
                        )

                    else:

                        self.spawn_preview = None

            else:

                self.spawn_preview = None

            self.screen.fill((20, 20, 20))

            self.screen.blit(
                self.title_font.render(
                    "Editeur de salle",
                    True,
                    (255, 255, 255),
                ),
                (250, 5),
            )

            if self.last_assembly is not None:

                self.last_assembly.render(
                    self.screen,
                    self.camera,
                    active_floor=self.assembly_active_floor,
                )

                self.screen.blit(
                    self.assembly_hint_font.render(
                        "Apercu du donjon genere -- ECHAP pour revenir a l'edition",
                        True,
                        (220, 220, 220),
                    ),
                    (250, 34),
                )

            else:

                self.dungeon.render(
                    self.screen,
                    self.camera,
                    spawn_preview=self.spawn_preview,
                    show_link_indicators=True,
                )

                if self.link_source is not None and self.link_drag_pos is not None:

                    source_screen = self.camera.world_to_screen(
                        *self.dungeon.object_indicator_position(self.link_source)
                    )
                    pygame.draw.line(self.screen, self.LINK_LINE_COLOR, source_screen, self.link_drag_pos, 2)

                if self.moving_object is not None and self.move_drag_pos is not None:

                    sprite = self._drag_sprite(self.moving_object["type"])

                    # midbottom, not center -- the cursor is where the
                    # object's anchor (bottom-center of its footprint) will
                    # land (see the MOUSEBUTTONUP handler's origin_for_anchor
                    # call above), so the preview should show that same
                    # point under the cursor instead of the sprite's middle.
                    rect = sprite.get_rect(
                        midbottom=self.move_drag_pos
                    )

                    self.screen.blit(sprite, rect)

            # Rendered in panel_frames' own z-order (last = topmost, see its
            # docstring) rather than a fixed sequence, so a frame dragged on
            # top of another actually draws on top of it.
            for frame in self.panel_frames:
                if frame is self.tools_frame:
                    stock = self._active_profile.card_collection if self._active_profile is not None else {}
                    frame.render(
                        self.screen,
                        floor_active=self.floor_tool_active,
                        wall_active=self.wall_tool_active,
                        floor_stock=stock.get("tile_floor", 0),
                        wall_stock=stock.get("tile_wall", 0),
                        floor_preview=self.dungeon.renderer.get_theme_preview_surface(
                            self.dungeon.floor_theme, "floor", self.palette.PREVIEW_SIZE,
                        ),
                        wall_preview=self.dungeon.renderer.get_theme_preview_surface(
                            self.dungeon.wall_theme, "wall", self.palette.PREVIEW_SIZE,
                        ),
                    )
                else:
                    frame.render(self.screen)
                if frame is self.generator_frame and not self._generator_unlocked():
                    self._draw_panel_lock_overlay(frame, "Approchez-vous de Djepeto")
                elif frame is self.mechanics_frame and not self._forge_unlocked():
                    self._draw_panel_lock_overlay(frame, "Approchez-vous du Totem 3")
            self.chest_panel.render(self.screen)
            self.role_panel.render(self.screen)
            self.autotile_theme_panel.render(self.screen)
            self._sprite_editor_border.draw_centered_label(
                self.screen, self.sprite_editor_button_rect, self.sprite_editor_button_font, "Editeur de sprite",
            )
            self._sprite_editor_border.draw_centered_label(
                self.screen, self.settings_button_rect, self.sprite_editor_button_font, "Parametres",
            )
            self.sprite_editor_panel.render(self.screen)

            if self.game_manager.settings_panel.is_open:
                self.game_manager.settings_panel.render(self.screen)

            # Drawn dead last, after every panel above -- fixes a real bug:
            # this used to render before the panel_frames loop, so the
            # dragged card's own preview sprite drew UNDER card_frame (or
            # any other panel) whenever the mouse hovered its bounds,
            # vanishing until the cursor left it. Rendering last guarantees
            # it's always on top, regardless of which panel it's hovering.
            # Same "no assembly preview" guard as before (self.last_assembly
            # is checked by the enclosing if/else this block used to live
            # inside).
            if self.last_assembly is None and self.object_tool.dragging:
                sprite = self._drag_sprite(self.object_tool.object_type)
                rect = sprite.get_rect(midbottom=self.object_tool.position)
                self.screen.blit(sprite, rect)

            pygame.display.flip()


        if self.current_room is not None:
            self.dungeon.save_to_json(self.current_room)