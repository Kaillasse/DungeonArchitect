
import pygame

class ObjectTool:

    def __init__(self):

        self.object_type = None

        self.position = pygame.Vector2(100, 230)
        self.dragging = False

    def start_drag(self, object_type, mouse_pos):

        self.object_type = object_type
        self.position.update(mouse_pos)
        self.dragging = True



    def handle_event(self, event):

        if not self.dragging:
            return

        if event.type == pygame.MOUSEMOTION:

            self.position.update(event.pos)
