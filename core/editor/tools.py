
import pygame
from core.world.object_manager import OBJECT_LIST
from core.data.ressources import DEFAULT_ANIM_SPEED

class ObjectTool:

    def __init__(self):

        self.object_type = None

        self.origin = pygame.Vector2(100,230)
        self.position = self.origin.copy()
        self.dragging = False

        self.timer = 0
        self.speed = DEFAULT_ANIM_SPEED
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

    def update(self, dt, mouse_pos):

        if not self.dragging:
            return

        self.position.update(mouse_pos)
