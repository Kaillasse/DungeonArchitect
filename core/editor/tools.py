
import pygame

class ObjectTool:

    def __init__(self):

        self.object_type = None

        self.position = pygame.Vector2(100, 230)
        self.dragging = False
        # "collection" is the only source today -- a card dragged from
        # CardPanelUI. Kept as an explicit field (rather than assuming
        # "collection" everywhere) since Creator._resolve_dragged_card
        # branches on it for property-card fuse drags.
        self.drag_source = "collection"

    def start_drag(self, object_type, mouse_pos, source="collection"):

        self.object_type = object_type
        self.position.update(mouse_pos)
        self.dragging = True
        self.drag_source = source



    def handle_event(self, event):

        if not self.dragging:
            return

        if event.type == pygame.MOUSEMOTION:

            self.position.update(event.pos)
