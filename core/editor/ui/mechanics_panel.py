"""MechanicsPanelUI -- the "mechanical" counterpart to SpriteEditorPanelUI.

Where SpriteEditorPanelUI owns a custom type's visual/identity data (asset/
name/size/frames), this panel owns its gameplay flags (blocks_movement/
cell_modes/interactable/lockable) -- confirmed split with the user, framed as
the long-term "Artiste" (sprite editor) vs "Forgeron" (this panel) divide,
though no NPC/dialogue gating exists yet: reachable today by dragging an
owned card from CardPanelUI directly onto this panel's own body (wrapped in
a PanelFrame titled "Forge" -- see Creator.__init__/the drop handling in
Creator.run()).

Docked/draggable/resizable exactly like CardPanelUI/GeneratorPanelUI, NOT
modal -- a dropped card stays loaded and editable at leisure, without
blocking the rest of the editor. "Empty" (nothing dropped yet) vs "populated"
is read directly off self.type_id, no separate open/active flag.

Never touches a built-in type (isinstance(config["asset"], dict) is the same
guard SpriteEditorPanelUI itself uses) -- open() just leaves type_id alone
(stays/remains empty) for one of those, a room card, or an unknown id.
Persists through update_custom_type exactly as SpriteEditorPanelUI's own edit
flow does, passing tileset/rect/frame_rects/size/archetype straight through
UNCHANGED (reconstructed from the loaded config, same lookup
SpriteEditorPanelUI._load_existing_card_for_edit already uses) -- only the
mechanical flags this panel actually exposes controls for can change.
"""

import pygame

from core.editor.ui.mixins import _ResizableCornerMixin
from core.ui.widgets import BorderManager
from core.world.object_manager import OBJECT_TYPES, ARCHETYPES, CELL_MODES, update_custom_type
from core.data.cards import resolve_card_sprite

CELL_MODES_ARCHETYPES = ("sol", "mur", "porte")


class MechanicsPanelUI(_ResizableCornerMixin):
    STANDARD_WIDTH = 420
    STANDARD_HEIGHT = 420
    MAX_WIDTH = 900
    MAX_HEIGHT = 700
    CELL_MODE_COLORS = {"block": (190, 90, 90), "behind": (110, 190, 110), "front": (100, 150, 220)}
    GRID_MAX_PX = 140

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.width = self.STANDARD_WIDTH
        self.height = self.STANDARD_HEIGHT
        self._resizing = False
        self._resize_last_pos = None

        self.type_id = None
        self.name = ""
        self.icon = None

        # Reconstructed from the loaded config, passed straight through to
        # update_custom_type unchanged -- this panel never edits any of
        # these, only the mechanical flags below.
        self.tileset = None
        self.rect = None
        self.frame_rects = None
        self.size = (1, 1)
        self.archetype = "sol"

        # The actual editable state.
        self.blocks_movement = False
        self.cell_modes_grid = None
        self.interactable = False
        self.lockable = False

        self.status_text = ""
        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 16)
        self.small_font = pygame.font.SysFont("arial", 13)

        self._blocks_rect = None
        self._interactable_rect = None
        self._lockable_rect = None
        self._save_rect = None
        self._clear_rect = None
        self._layout()

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
        """Loads `card_id`'s current mechanical flags for editing -- stays
        empty (self.type_id untouched) for anything that isn't a custom
        type (built-in type, room card, or unknown id): mirrors
        SpriteEditorPanelUI's own "never touches a type it didn't create"
        guard."""
        config = OBJECT_TYPES.get(card_id)
        if config is None or not isinstance(config.get("asset"), dict):
            return

        self.type_id = card_id
        self.name = config.get("name", card_id)
        self.icon = resolve_card_sprite(card_id)

        asset = config["asset"]
        if "rects" in asset:
            self.frame_rects = [list(r) for r in asset["rects"]]
            self.rect = self.frame_rects[0]
        else:
            self.frame_rects = None
            self.rect = asset["rect"]
        self.tileset = asset["tileset"]
        self.size = tuple(config.get("size", [1, 1]))
        self.archetype = next(
            (aid for aid, preset in ARCHETYPES.items() if preset["placement"] == config.get("placement")),
            "sol",
        )

        self.blocks_movement = config.get("blocks_movement", False)
        self.interactable = config.get("interactable", False)
        self.lockable = bool(config.get("blocks_until_open"))
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

        self.status_text = ""

    def clear(self):
        """"Vider" -- returns to the empty placeholder state without
        touching disk, so the player can back out of a card they dropped by
        mistake without having to drop another one over it."""
        self.type_id = None
        self.status_text = ""

    def _layout(self):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        self._clear_rect = pygame.Rect(panel_rect.right - 90, panel_rect.y + 12, 70, 28)
        content_x = self.x + 20
        self._blocks_rect = pygame.Rect(content_x, self.y + 140, self.width - 40, 32)
        self._interactable_rect = pygame.Rect(content_x, self.y + 180, self.width - 40, 32)
        self._lockable_rect = pygame.Rect(content_x, self.y + 220, self.width - 40, 32)
        self._save_rect = pygame.Rect(content_x, self.y + self.height - 56, self.width - 40, 40)

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

    def _try_save(self):
        """"Enregistrer" -- update_custom_type with every non-mechanical
        field passed through exactly as loaded (see open()), so this panel
        can never accidentally touch the visual/identity data
        SpriteEditorPanelUI owns. Returns type_id on success (Creator
        credits nothing new -- the card already exists -- but does refresh
        CardPanelUI so a completeness badge/detail line picks up the
        change immediately), None on failure. Stays populated after saving
        (unlike the old modal version's auto-close) -- this is a docked
        panel now, closing would just mean re-dropping the same card."""
        try:
            update_custom_type(
                self.type_id, self.name, self.tileset, self.rect, self.size, self.archetype,
                blocks_movement=self.blocks_movement,
                cell_modes=self._current_cell_modes(),
                interactable=self.interactable,
                lockable=self.lockable,
                frame_rects=self.frame_rects,
            )
        except ValueError as exc:
            self.status_text = str(exc)
            return None
        self.status_text = f"'{self.name}' mise a jour."
        return self.type_id

    def handle_event(self, event):
        if self._handle_resize_event(event):
            return None
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        if self.type_id is None:
            return None

        if self._clear_rect.collidepoint(event.pos):
            self.clear()
            return None

        if self.archetype in CELL_MODES_ARCHETYPES:
            if not self._is_multi_cell():
                if self.archetype == "sol" and self._blocks_rect.collidepoint(event.pos):
                    self.blocks_movement = not self.blocks_movement
                    return None
            else:
                for (row, col), rect in self._cell_mode_grid_rects().items():
                    if rect.collidepoint(event.pos):
                        self._cycle_cell_mode(row, col, 1)
                        return None

        if self._interactable_rect.collidepoint(event.pos):
            self.interactable = not self.interactable
            return None

        if self.archetype == "porte" and self._lockable_rect.collidepoint(event.pos):
            self.lockable = not self.lockable
            return None

        if self._save_rect.collidepoint(event.pos):
            return self._try_save()

        return None

    def render(self, screen):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        self.border.draw(screen, panel_rect)

        if self.type_id is None:
            hint = self.small_font.render("Glisse une carte ici pour l'editer", True, (150, 150, 150))
            screen.blit(hint, (self.x + 20, self.y + 16))
            self._draw_resize_handle(screen)
            return

        title = self.font.render(f"Mecaniques -- {self.name}", True, (255, 255, 255))
        screen.blit(title, (self.x + 20, self.y + 16))
        self.border.draw_centered_label(screen, self._clear_rect, self.small_font, "Vider")

        if self.icon is not None:
            icon_rect = pygame.Rect(self.x + 20, self.y + 48, 48, 48)
            scaled = pygame.transform.scale(self.icon, icon_rect.size)
            screen.blit(scaled, icon_rect.topleft)

        type_label = self.small_font.render(f"Archetype : {ARCHETYPES.get(self.archetype, {}).get('label', self.archetype)}", True, (200, 200, 200))
        screen.blit(type_label, (self.x + 80, self.y + 60))

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

        self.border.draw_centered_label(screen, self._save_rect, self.font, "Enregistrer")

        if self.status_text:
            status = self.small_font.render(self.status_text, True, (220, 220, 120))
            screen.blit(status, (self.x + 20, self._save_rect.y - 22))

        self._draw_resize_handle(screen)

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
        legend = self.small_font.render("B = bloquant | D = derriere | F = devant", True, (170, 170, 170))
        screen.blit(legend, (self._blocks_rect.x, legend_y))
