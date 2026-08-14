
import pygame

class ObjectTool:

    def __init__(self):

        self.object_type = None

        self.position = pygame.Vector2(100, 230)
        self.dragging = False
        # "collection" (the default -- a card dragged from CardPanelUI, the
        # only source before StashPanelUI existed) or "stash" (dragged from
        # core.editor.ui.stash_panel.StashPanelUI instead) -- lets
        # Creator._resolve_dragged_card tell the two apart on drop, since a
        # stash-sourced card isn't actually owned yet (never placeable in
        # the world, never opens the Forge -- its only valid drop target is
        # the collection panel itself, to deposit it).
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
