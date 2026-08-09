# Contient toute la logique du game state Creator

import os
import pygame

from core.world.dungeon import DEFAULT_GRID_SAVE_PATH, Dungeon
from core.world.assembly import generate_assembly, load_assembly, save_assembly
from core.editor.ui import ToolPaletteUI
from core.ui.widgets import PanelFrame
from core.engine.gamestate import GameState
from core.engine.room_manager import RoomManager
from core.engine.camera import Camera
from core.data.ressources import FLOOR, next_new_donjon_name
from core.data.profile_manager import ProfileManager
from core.data.progression import unlocked_objects
from core.world.home import home_room_name, wants_exploration
from core.editor.ui import GeneratorPanelUI, ObjectPalette, RoomPanelUI, ChestPanelUI, RolePanelUI
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
        self.object_palette = ObjectPalette(unlocked_types=unlocked_objects(self._current_level()))
        self.object_palette.move(0, 30)
        self.object_tool = ObjectTool(self.object_palette)
        self.object_palette.tool = self.object_tool

        self.generator_panel = GeneratorPanelUI(
            self.room_manager,
            x=10,
            y=self.object_palette.y + self.object_palette.height + 20,
            on_rename=self._rename_room, on_delete=self._delete_room, can_rename=self._can_rename_room,
        )
        self.chest_panel = ChestPanelUI(
            x=self.screen.get_width() / 2 - 130,
            y=180,
        )
        self.role_panel = RolePanelUI(
            x=self.screen.get_width() / 2 - 130,
            y=180,
        )

        # Draggable/collapsible title-bar wrappers around the 4 docked
        # panels (not the modal chest/role popups, which open centered on
        # demand and auto-close -- dragging them wouldn't make sense).
        # panel_frames' order is z-order for rendering/hit-testing (last =
        # topmost) -- a click on any frame brings it to the end of this
        # list, see run()'s event loop.
        self.tools_frame = PanelFrame(self.palette, "Outils", on_change=self._on_panel_frame_change)
        self.object_frame = PanelFrame(self.object_palette, "Palette d'objets", on_change=self._on_panel_frame_change)
        self.room_frame = PanelFrame(self.room_panel, "Sauvegarder / Charger", on_change=self._on_panel_frame_change)
        self.generator_frame = PanelFrame(self.generator_panel, "Generation procedurale", on_change=self._on_panel_frame_change)
        self.panel_frames = [self.tools_frame, self.object_frame, self.room_frame, self.generator_frame]
        # name -> frame, purely for _refresh_panel_layout/_on_panel_frame_change's
        # own round-trip through Profile.panel_layout (see those methods).
        self._panel_frames_by_name = {
            "tools": self.tools_frame,
            "object_palette": self.object_frame,
            "room": self.room_frame,
            "generator": self.generator_frame,
        }

        # See _refresh_generator_panel/_refresh_panel_layout -- seeded
        # lazily from the local profile once a player identity actually
        # exists, not here (Creator is constructed before Menu's name-entry
        # screen has necessarily run).
        self._generator_panel_seeded = False
        self._panel_layout_seeded = False

        self.painting = False
        self.erasing = False

        self.link_source = None
        self.link_drag_pos = None

        self.moving_object = None
        self.move_drag_pos = None

        self.panning = False
        self.pan_last_pos = None

        self.camera = Camera(zoom=1.0)
        self.grid_zoom = self.camera.zoom

        self.spawn_preview = None

        self.grid_width_px = (
            self.dungeon.width
            * self.dungeon.tile_size
            * self.grid_zoom
        )

        self.grid_height_px = (
            self.dungeon.height
            * self.dungeon.tile_size
            * self.grid_zoom
        )

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
        staying in a saved pool."""
        self.room_manager.delete(name)
        if self.current_room == name:
            self.current_room = None

        profile = self._load_profile()
        if profile is not None and name in profile.generator_room_names:
            profile.generator_room_names = [n for n in profile.generator_room_names if n != name]
            ProfileManager().save(profile)

        self.room_panel.refresh_rooms()
        self.generator_panel.refresh_rooms()

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

    def _paint_at_mouse(self, mouse_pos, erase=False):

        grid_x, grid_y = self._mouse_to_grid(mouse_pos)

        self.dungeon.paint_cell(
            grid_x,
            grid_y,
            erase=erase,
        )

    def _try_place_object(self):

        world = self.camera.screen_to_world(
            *self.object_tool.position
        )

        grid_x, grid_y = self.dungeon.world_to_grid(
            *world
        )

        return self.dungeon.object_manager.add_object(
            self.object_tool.object_type,
            grid_x,
            grid_y
        )

    def _current_level(self):
        """The local player's progression level, driving which object types
        ObjectPalette offers (see _refresh_object_palette). Falls back to
        level 1 (the most restrictive) if there's no local identity yet --
        never "everything unlocked" by default -- which covers the headless
        smoke test (DUNGEONARCHITECT_HEADLESS, no Menu name-entry ever ran)."""
        settings = self.game_manager.settings
        name = settings.local_player_name if settings is not None else None
        if not name:
            return 1
        return ProfileManager().load(name).level

    def _refresh_object_palette(self):
        """Re-derives the unlocked object set from the current level and
        rebuilds the palette if it changed -- called once per entry into
        this state (see run()) rather than every frame, since the level only
        ever changes while playing Exploration, not while the Creator loop
        itself is running. Only auto-follows the generator panel under the
        object palette while the player has never actually dragged it
        (generator_frame.user_moved) -- once they've placed it themselves,
        a level-up's palette height change must not silently yank it back
        out from under their chosen layout."""
        unlocked = unlocked_objects(self._current_level())
        if self.object_palette.set_unlocked_types(unlocked) and not self.generator_frame.user_moved:
            target_y = self.object_palette.y + self.object_palette.height + 20
            self.generator_panel.move(0, target_y - self.generator_panel.y)

    def _load_profile(self):
        """The local player's Profile, or None if there's no identity yet
        (headless smoke test, or -- Creator itself is constructed before
        Menu's name-entry screen has necessarily run -- the very first
        frame of a fresh install). Reloaded on demand rather than cached,
        same as _current_level, since XP/level can change during
        Exploration between visits to Creator."""
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

    def _refresh_panel_layout(self):
        """Restores each PanelFrame's saved position/collapsed state from
        the local profile's Profile.panel_layout, exactly once (same lazy,
        seeded-only-when-a-real-identity-exists shape as
        _refresh_generator_panel -- Creator is constructed before Menu's
        name-entry screen has necessarily run, so this can't happen in
        __init__). A missing/empty entry (a fresh profile, or a frame added
        after the profile was last saved) leaves that panel at whatever its
        constructor already placed it at. user_moved is set True for every
        restored frame so _refresh_object_palette's auto-follow (see above)
        never fights a layout the player explicitly saved."""
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
            frame.user_moved = True
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

    def run(self):

        pygame.display.set_caption("DungeonArchitect - Dungeon Editor")

        # Layout restore must happen before _refresh_object_palette -- it
        # sets generator_frame.user_moved, which _refresh_object_palette's
        # auto-follow-under-the-palette logic checks to avoid immediately
        # overwriting a just-restored position.
        self._refresh_panel_layout()
        self._refresh_object_palette()
        self._refresh_generator_panel()

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

                if self.chest_panel.is_open or self.role_panel.is_open:
                    # Fully modal -- every other tool/panel acts on
                    # self.dungeon, which is exactly what the open chest/E-S
                    # belongs to, so letting painting/saving/etc. run
                    # "underneath" it would be confusing at best. QUIT must
                    # still always work.
                    if event.type == pygame.QUIT:
                        running = False
                        self.game_manager.running = False
                        break
                    if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                        if self.chest_panel.is_open:
                            self.chest_panel.handle_event(event)
                        else:
                            role = self.role_panel.handle_event(event)
                            if role is not None:
                                self.dungeon.object_manager.set_role(self.role_panel.obj, role)
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

                if event.type == pygame.MOUSEBUTTONDOWN and not self.object_frame.collapsed:

                    selected = self.object_palette.handle_click(event.pos)

                    if selected is not None:

                        self.object_tool.start_drag(
                            selected,
                            event.pos
                        )

                        continue

                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION, pygame.MOUSEBUTTONUP):

                    panel_click = event.type == pygame.MOUSEBUTTONDOWN and (
                        self.room_frame.contains(event.pos)
                        or self.generator_frame.contains(event.pos)
                    )

                    if not self.room_frame.collapsed:
                        room_action = self.room_panel.handle_event(event)

                        if room_action is not None:
                            self._apply_room_action(room_action)

                    if not self.generator_frame.collapsed:
                        generation_request = self.generator_panel.handle_event(event)

                        if generation_request is not None:
                            self._apply_generation(generation_request)

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

                        if not self.tools_frame.collapsed and self.palette.hit_autotile_toggle(event.pos):
                            self.dungeon.autotile_enabled = not self.dungeon.autotile_enabled
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

                        if self._is_valid_grid_cell(event.pos):

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

                        if self.link_source is not None:

                            target_obj = self._find_indicator_at(event.pos)

                            if target_obj is not None and target_obj is not self.link_source:
                                self.dungeon.object_manager.link(self.link_source, target_obj)

                            self.link_source = None
                            self.link_drag_pos = None

                        elif self.moving_object is not None:

                            grid_x, grid_y = self._mouse_to_grid(event.pos)
                            self.dungeon.object_manager.move_object(self.moving_object, grid_x, grid_y)

                            self.moving_object = None
                            self.move_drag_pos = None

                        elif self.object_tool.dragging:

                            self._try_place_object()

                            self.object_tool.dragging = False

                    elif event.button == 3:

                        self.erasing = False

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

                    elif self.painting and self._is_valid_grid_cell(event.pos):

                        self._paint_at_mouse(event.pos, erase=False)

                    elif self.erasing and self._is_valid_grid_cell(event.pos):

                        self._paint_at_mouse(event.pos, erase=True)

                elif event.type == pygame.MOUSEWHEEL:
                    mouse_x, mouse_y = pygame.mouse.get_pos()
                    self.camera.zoom_at(mouse_x, mouse_y, event.y, self.screen.get_width(), self.screen.get_height())
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
            self.object_palette.update(
                dt,
                pygame.mouse.get_pos()
            )
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

            title_font = pygame.font.SysFont("arial", 24)

            self.screen.blit(
                title_font.render(
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

                hint_font = pygame.font.SysFont("arial", 16)
                self.screen.blit(
                    hint_font.render(
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

                    sprite = self.object_palette.get_current_frame(
                        self.moving_object["type"]
                    )

                    rect = sprite.get_rect(
                        center=self.move_drag_pos
                    )

                    self.screen.blit(sprite, rect)

                if self.object_tool.dragging:

                    sprite = self.object_palette.get_current_frame(
                        self.object_tool.object_type
                    )

                    rect = sprite.get_rect(
                        center=self.object_tool.position
                    )

                    self.screen.blit(sprite, rect)

            # Rendered in panel_frames' own z-order (last = topmost, see its
            # docstring) rather than a fixed sequence, so a frame dragged on
            # top of another actually draws on top of it.
            for frame in self.panel_frames:
                if frame is self.tools_frame:
                    frame.render(self.screen, autotile_enabled=self.dungeon.autotile_enabled)
                else:
                    frame.render(self.screen)
            self.chest_panel.render(self.screen)
            self.role_panel.render(self.screen)

            pygame.display.flip()


        if self.current_room is not None:
            self.dungeon.save_to_json(self.current_room)