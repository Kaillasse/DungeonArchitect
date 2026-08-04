# Contient toute la logique du game state Creator

import os
import pygame

from core.world.dungeon import DEFAULT_GRID_SAVE_PATH, Dungeon
from core.editor.ui import ToolPaletteUI
from core.engine.gamestate import GameState
from core.engine.room_manager import RoomManager
from core.engine.camera import Camera
from core.data.ressources import FLOOR
from core.editor.ui import ObjectPalette
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

        self.object_type = "spawn" # Type d'objet par défaut
        self.object_palette = ObjectPalette()
        self.object_tool = ObjectTool(self.object_palette)
        self.object_palette.tool = self.object_tool

        self.painting = False
        self.erasing = False

        self.link_source = None
        self.link_drag_pos = None

        self.moving_object = None
        self.move_drag_pos = None

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

    def run(self):

        pygame.display.set_caption("DungeonArchitect - Dungeon Editor")

        clock = pygame.time.Clock()

        if os.environ.get("DUNGEONARCHITECT_HEADLESS") == "1":
            self.dungeon.save_to_json(DEFAULT_GRID_SAVE_PATH)
            self.game_manager.running = False
            pygame.quit()
            return

        running = True
        
        while running:

            dt = clock.tick(60) / 1000

            # -------------------------------------------------
            # Events
            # -------------------------------------------------

            for event in pygame.event.get():
                self.object_tool.handle_event(event)

                if event.type == pygame.MOUSEBUTTONDOWN:

                    selected = self.object_palette.handle_click(event.pos)

                    if selected is not None:

                        self.object_tool.start_drag(
                            selected,
                            event.pos
                        )

                        continue


                if event.type == pygame.QUIT:

                    running = False
                    self.game_manager.running = False
                    break

                elif event.type == pygame.MOUSEBUTTONDOWN:

                    if event.button == 1:


                        if self.palette.handle_click(event.pos):
                            continue

                        indicator_obj = self._find_indicator_at(event.pos)

                        if indicator_obj is not None:

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

                elif event.type == pygame.MOUSEMOTION:

                    if self.link_source is not None:

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
                        self.game_manager.state = GameState.MENU
                        running = False

                    elif event.key == pygame.K_F1:
                        self.room_manager.save_room()

                    elif event.key == pygame.K_F2:
                        self.room_manager.delete_room()

                    elif event.key == pygame.K_F3:
                        self.room_manager.load_room()

                    elif event.key == pygame.K_F4:
                        self.room_manager.list_rooms()

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

            self.palette.render(self.screen)
            if self.object_tool.dragging:

                sprite = self.object_palette.get_current_frame(
                    self.object_tool.object_type
                )

                rect = sprite.get_rect(
                    center=self.object_tool.position
                )

                self.screen.blit(sprite, rect)
            self.object_palette.render(self.screen)

            pygame.display.flip()


        self.dungeon.save_to_json(self.room_manager.current_room)