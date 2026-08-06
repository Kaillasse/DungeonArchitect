
import pygame
from core.world.object_manager import OBJECT_LIST

class ObjectTool:

    def __init__(self, palette):

        self.object_type = None

        self.origin = pygame.Vector2(100,230)
        self.position = self.origin.copy()
        self.palette = palette
        self.dragging = False

        self.timer = 0
        self.speed = 0.12
        self.available_objects = OBJECT_LIST

    def start_drag(self, object_type, mouse_pos):

        self.object_type = object_type
        self.position.update(mouse_pos)
        self.dragging = True



    def handle_event(self, event):

        if not self.dragging:
            return

        if event.type == pygame.MOUSEMOTION:

            self.position.update(event.pos)

    def draw(self, screen):

        if not self.dragging:
            return

        sprite = self.palette.get_current_frame(
            self.object_type
        )

        rect = sprite.get_rect(
            center=self.position
        )

        screen.blit(
            sprite,
            rect,
        )

    def update(self, dt, mouse_pos):

        if not self.dragging:
            return

        self.position.update(mouse_pos)
