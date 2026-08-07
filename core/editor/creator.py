# Contient toute la logique du game state Creator

import os
import pygame

from core.world.dungeon import DEFAULT_GRID_SAVE_PATH, Dungeon
from core.world.assembly import generate_assembly, load_assembly, save_assembly
from core.editor.ui import ToolPaletteUI
from core.engine.gamestate import GameState
from core.engine.room_manager import RoomManager
from core.engine.camera import Camera
from core.data.ressources import FLOOR, next_new_donjon_name
from core.data.profile_manager import ProfileManager
from core.data.progression import unlocked_objects
from core.world.home import home_room_name, wants_exploration
from core.editor.ui import GeneratorPanelUI, ObjectPalette, RoomPanelUI, ChestPanelUI
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
        self.room_panel = RoomPanelUI(self.room_manager)
        self.last_assembly = None
        self.assembly_active_floor = 0

        self.object_type = "spawn" # Type d'objet par défaut
        self.object_palette = ObjectPalette(unlocked_types=unlocked_objects(self._current_level()))
        self.object_tool = ObjectTool(self.object_palette)
        self.object_palette.tool = self.object_tool

        self.generator_panel = GeneratorPanelUI(
            self.room_manager,
            x=10,
            y=self.object_palette.y + self.object_palette.height + 20,
        )
        self.chest_panel = ChestPanelUI(
            x=self.screen.get_width() / 2 - 130,
            y=180,
        )

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
        self.dungeon.load_from_json(name)

    def open_donjon(self, name):
        """Preview a saved procedurally-assembled dungeon instead of a single room."""
        self.last_assembly = load_assembly(name)
        self.assembly_active_floor = 0
        self.current_room = None
        self.chest_panel.close()

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
            self.room_manager.delete(selection)
            if self.current_room == selection:
                self.current_room = None

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

    def _find_indicator_at(self, mouse_pos):
        mx, my = mouse_pos

        for obj in self.dungeon.object_manager.objects:
            if not self.dungeon.object_manager.is_linkable(obj["type"]):
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
        itself is running."""
        unlocked = unlocked_objects(self._current_level())
        if self.object_palette.set_unlocked_types(unlocked):
            self.generator_panel.set_y(self.object_palette.y + self.object_palette.height + 20)

    def run(self):

        pygame.display.set_caption("DungeonArchitect - Dungeon Editor")

        self._refresh_object_palette()

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

                if self.chest_panel.is_open:
                    # Fully modal -- every other tool/panel acts on
                    # self.dungeon, which is exactly what the open chest
                    # belongs to, so letting painting/saving/etc. run
                    # "underneath" it would be confusing at best. QUIT must
                    # still always work.
                    if event.type == pygame.QUIT:
                        running = False
                        self.game_manager.running = False
                        break
                    if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                        self.chest_panel.handle_event(event)
                    continue

                self.object_tool.handle_event(event)

                if event.type == pygame.MOUSEBUTTONDOWN:

                    selected = self.object_palette.handle_click(event.pos)

                    if selected is not None:

                        self.object_tool.start_drag(
                            selected,
                            event.pos
                        )

                        continue

                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION, pygame.MOUSEBUTTONUP):

                    panel_click = event.type == pygame.MOUSEBUTTONDOWN and (
                        self.room_panel.contains(event.pos)
                        or self.generator_panel.contains(event.pos)
                    )

                    room_action = self.room_panel.handle_event(event)

                    if room_action is not None:
                        self._apply_room_action(room_action)

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
                    continue

                if event.type == pygame.QUIT:

                    running = False
                    self.game_manager.running = False
                    break

                elif event.type == pygame.MOUSEBUTTONDOWN:

                    if event.button == 1:

                        if self.palette.hit_autotile_toggle(event.pos):
                            self.dungeon.autotile_enabled = not self.dungeon.autotile_enabled
                            continue

                        if self.palette.handle_click(event.pos):
                            continue

                        indicator_obj = self._find_indicator_at(event.pos)

                        if indicator_obj is not None:

                            if self.dungeon.object_manager.is_chest(indicator_obj["type"]):
                                self.chest_panel.open(indicator_obj)
                            else:
                                self.link_source = indicator_obj
                                self.link_drag_pos = event.pos
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

            self.palette.render(self.screen, autotile_enabled=self.dungeon.autotile_enabled)
            self.object_palette.render(self.screen)
            self.room_panel.render(self.screen)
            self.generator_panel.render(self.screen)
            self.chest_panel.render(self.screen)

            pygame.display.flip()


        if self.current_room is not None:
            self.dungeon.save_to_json(self.current_room)