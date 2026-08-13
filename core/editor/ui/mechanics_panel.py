"""MechanicsPanelUI -- the "mechanical" counterpart to SpriteEditorPanelUI.

Where SpriteEditorPanelUI owns a custom type's visual/identity data (asset/
name/size/frames), this panel owns its gameplay flags (blocks_movement/
cell_modes/interactable/lockable) AND capacities (throwable/explosive) --
confirmed split with the user, framed as the long-term "Artiste" (sprite
editor) vs "Forgeron" (this panel) divide, though no NPC/dialogue gating
exists yet: reachable today by dragging an owned card from CardPanelUI
directly onto this panel's own body (wrapped in a PanelFrame titled "Forge"
-- see Creator.__init__/the drop handling in Creator.run()).

Docked/draggable/resizable exactly like CardPanelUI/GeneratorPanelUI, NOT
modal -- a dropped card stays loaded and editable at leisure, without
blocking the rest of the editor. "Empty" (nothing dropped yet) vs "populated"
is read directly off self.type_id/self.item_id (mutually exclusive -- a
dropped card is either an OBJECT_TYPES entry or an ITEM_DEFINITIONS entry,
never both), no separate open/active flag.

Built-in OBJECT_TYPES entries are now fully in scope for the gameplay-flag
half (see object_manager.update_type_mechanics -- the dict-asset guard only
applies to the VISUAL half, SpriteEditorPanelUI's domain): open() only
refuses a room card or an unknown id. Persists through update_type_mechanics
(OBJECT_TYPES entries) or update_item_capabilities (ITEM_DEFINITIONS
entries) -- never touches asset/name/size/frames/archetype, which stay
whatever SpriteEditorPanelUI (or, for a builtin, the Python source) already
set.
"""

import pygame

from core.editor.ui.mixins import _ResizableCornerMixin
from core.ui.widgets import BorderManager, Stepper
from core.world.object_manager import (
    OBJECT_TYPES, ITEM_DEFINITIONS, ARCHETYPES, CELL_MODES,
    update_type_mechanics, update_item_capabilities,
)
from core.data.cards import resolve_card_sprite

CELL_MODES_ARCHETYPES = ("sol", "mur", "porte")


class MechanicsPanelUI(_ResizableCornerMixin):
    STANDARD_WIDTH = 420
    STANDARD_HEIGHT = 500
    MAX_WIDTH = 900
    MAX_HEIGHT = 700
    CELL_MODE_COLORS = {"block": (190, 90, 90), "behind": (110, 190, 110), "front": (100, 150, 220)}
    GRID_MAX_PX = 140
    STEP_BUTTON_SIZE = 24
    COUNT_DISPLAY_WIDTH = 50

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.width = self.STANDARD_WIDTH
        self.height = self.STANDARD_HEIGHT
        self._resizing = False
        self._resize_last_pos = None

        self.type_id = None
        self.item_id = None
        self.name = ""
        self.icon = None

        # Reconstructed from the loaded config, passed straight through to
        # update_type_mechanics unchanged -- this panel never edits any of
        # these, only the mechanical flags/capacities below. Stay at their
        # defaults for an item card (self.item_id set) -- meaningless there.
        self.tileset = None
        self.rect = None
        self.frame_rects = None
        self.size = (1, 1)
        self.archetype = "sol"

        # The actual editable state -- OBJECT_TYPES cards only (self.type_id).
        self.blocks_movement = False
        self.cell_modes_grid = None
        self.interactable = False
        self.lockable = False

        # Capacites -- available on BOTH OBJECT_TYPES and ITEM_DEFINITIONS
        # cards (see _build_mechanics_fields/update_item_capabilities), same
        # "throwable"/"explosive" vocabulary either way.
        self.throwable_enabled = False
        self.throw_speed = 220
        self.explosive_enabled = False
        self.blast_radius_tiles = 2
        self.blast_damage = 1

        self.status_text = ""
        self.border = BorderManager()
        self.font = pygame.font.SysFont("arial", 16)
        self.small_font = pygame.font.SysFont("arial", 13)

        self._blocks_rect = None
        self._interactable_rect = None
        self._lockable_rect = None
        self._throwable_rect = None
        self._explosive_rect = None
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
        """Loads `card_id`'s current mechanical flags/capacites for editing
        -- stays empty (self.type_id/self.item_id untouched) for a room
        card or an unknown id, the only two kinds this panel can't do
        anything with. An ITEM_DEFINITIONS id (self.item_id) and an
        OBJECT_TYPES id (self.type_id) are mutually exclusive and checked
        first/second respectively -- no id is ever both."""
        item_def = ITEM_DEFINITIONS.get(card_id)
        if item_def is not None:
            self.item_id = card_id
            self.type_id = None
            self.name = item_def.get("name", card_id)
            self.icon = resolve_card_sprite(card_id)
            self.tileset = None
            self.rect = None
            self.frame_rects = None
            self.size = (1, 1)
            self.archetype = None
            self.blocks_movement = False
            self.cell_modes_grid = None
            self.interactable = False
            self.lockable = False
            self._load_capabilities(item_def.get("capabilities", {}))
            self.status_text = ""
            return

        config = OBJECT_TYPES.get(card_id)
        if config is None:
            return

        self.type_id = card_id
        self.item_id = None
        self.name = config.get("name", card_id)
        self.icon = resolve_card_sprite(card_id)

        asset = config["asset"]
        if isinstance(asset, dict):
            if "rects" in asset:
                self.frame_rects = [list(r) for r in asset["rects"]]
                self.rect = self.frame_rects[0]
            else:
                self.frame_rects = None
                self.rect = asset["rect"]
            self.tileset = asset["tileset"]
        else:
            # A built-in's asset is its own dedicated sprite sheet path, not
            # a tileset crop -- this panel never edits it (that stays
            # SpriteEditorPanelUI's job, still gated to custom types only,
            # see update_type_visual), so these just stay at a harmless
            # default. _try_save only ever calls update_type_mechanics,
            # which ignores tileset/rect/frame_rects entirely.
            self.tileset = None
            self.rect = None
            self.frame_rects = None
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

        self._load_capabilities(config.get("capabilities", {}))
        self.status_text = ""

    def _load_capabilities(self, capabilities):
        throwable = capabilities.get("throwable")
        self.throwable_enabled = throwable is not None
        self.throw_speed = (throwable or {}).get("speed", 220)
        explosive = capabilities.get("explosive")
        self.explosive_enabled = explosive is not None
        self.blast_radius_tiles = (explosive or {}).get("radius_tiles", 2)
        self.blast_damage = (explosive or {}).get("damage", 1)

    def clear(self):
        """"Vider" -- returns to the empty placeholder state without
        touching disk, so the player can back out of a card they dropped by
        mistake without having to drop another one over it."""
        self.type_id = None
        self.item_id = None
        self.status_text = ""

    def _layout(self):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        self._clear_rect = pygame.Rect(panel_rect.right - 90, panel_rect.y + 12, 70, 28)
        content_x = self.x + 20
        self._blocks_rect = pygame.Rect(content_x, self.y + 140, self.width - 40, 32)
        self._interactable_rect = pygame.Rect(content_x, self.y + 180, self.width - 40, 32)
        self._lockable_rect = pygame.Rect(content_x, self.y + 220, self.width - 40, 32)
        # Capacites -- fixed rows below the OBJECT_TYPES-only ones above
        # (unused/not hit-tested for an item card, see render/handle_event),
        # each with its own Stepper row (label drawn above it, same idiom
        # as ChestPanelUI's loot rows) directly beneath it, shown only
        # while that capacity's checkbox is enabled -- same "always laid
        # out, conditionally shown" style as blocks/interactable/lockable.
        self._throwable_rect = pygame.Rect(content_x, self.y + 256, self.width - 40, 28)
        self._explosive_rect = pygame.Rect(content_x, self.y + 344, self.width - 40, 28)
        self._save_rect = pygame.Rect(content_x, self.y + self.height - 56, self.width - 40, 40)

    def _throw_speed_stepper(self):
        return Stepper(self.x + 40, self.y + 308, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 20, 800)

    def _blast_radius_stepper(self):
        return Stepper(self.x + 40, self.y + 398, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 6)

    def _blast_damage_stepper(self):
        return Stepper(self.x + 260, self.y + 398, self.STEP_BUTTON_SIZE, self.COUNT_DISPLAY_WIDTH, 1, 10)

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
        """"Enregistrer" -- update_type_mechanics (OBJECT_TYPES cards) or
        update_item_capabilities (ITEM_DEFINITIONS cards), never anything
        touching visual/identity data (SpriteEditorPanelUI's domain).
        Returns the saved id on success (Creator credits nothing new -- the
        card already exists -- but does refresh CardPanelUI so a
        completeness badge/detail line picks up the change immediately),
        None on failure. Stays populated after saving (unlike the old modal
        version's auto-close) -- this is a docked panel now, closing would
        just mean re-dropping the same card."""
        capabilities = {}
        if self.throwable_enabled:
            capabilities["throwable"] = {"speed": self.throw_speed}
        if self.explosive_enabled:
            capabilities["explosive"] = {"radius_tiles": self.blast_radius_tiles, "damage": self.blast_damage}

        try:
            if self.item_id is not None:
                update_item_capabilities(self.item_id, capabilities)
            else:
                update_type_mechanics(
                    self.type_id,
                    blocks_movement=self.blocks_movement,
                    cell_modes=self._current_cell_modes(),
                    interactable=self.interactable,
                    lockable=self.lockable,
                    capabilities=capabilities,
                )
        except ValueError as exc:
            self.status_text = str(exc)
            return None
        self.status_text = f"'{self.name}' mise a jour."
        return self.item_id if self.item_id is not None else self.type_id

    def handle_event(self, event):
        if self._handle_resize_event(event):
            return None
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        if self.type_id is None and self.item_id is None:
            return None

        if self._clear_rect.collidepoint(event.pos):
            self.clear()
            return None

        if self.type_id is not None:
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

        if self._throwable_rect.collidepoint(event.pos):
            self.throwable_enabled = not self.throwable_enabled
            return None
        if self.throwable_enabled:
            new_speed = self._throw_speed_stepper().handle_click(event.pos, self.throw_speed)
            if new_speed is not None:
                self.throw_speed = new_speed
                return None

        if self._explosive_rect.collidepoint(event.pos):
            self.explosive_enabled = not self.explosive_enabled
            return None
        if self.explosive_enabled:
            new_radius = self._blast_radius_stepper().handle_click(event.pos, self.blast_radius_tiles)
            if new_radius is not None:
                self.blast_radius_tiles = new_radius
                return None
            new_damage = self._blast_damage_stepper().handle_click(event.pos, self.blast_damage)
            if new_damage is not None:
                self.blast_damage = new_damage
                return None

        if self._save_rect.collidepoint(event.pos):
            return self._try_save()

        return None

    def render(self, screen):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        self.border.draw(screen, panel_rect)

        if self.type_id is None and self.item_id is None:
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

        if self.type_id is not None:
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
        else:
            item_label = self.small_font.render("Item d'inventaire", True, (200, 200, 200))
            screen.blit(item_label, (self.x + 80, self.y + 60))

        self._render_capabilities(screen)

        self.border.draw_centered_label(screen, self._save_rect, self.font, "Enregistrer")

        if self.status_text:
            status = self.small_font.render(self.status_text, True, (220, 220, 120))
            screen.blit(status, (self.x + 20, self._save_rect.y - 22))

        self._draw_resize_handle(screen)

    def _render_capabilities(self, screen):
        """Capacites section -- "Lançable"/"Explosif" toggles, each backed
        by ITEM_DEFINITIONS/OBJECT_TYPES' own "capabilities" dict (see
        _load_capabilities/_try_save). Available for both an item card and
        an OBJECT_TYPES card (a decorative object could become explosive
        too, not just an inventory item) -- unlike the rows above, never
        gated on self.type_id/self.archetype."""
        throw_label = "[x] Lancable" if self.throwable_enabled else "[ ] Lancable"
        self.border.draw_centered_label(screen, self._throwable_rect, self.font, throw_label)
        if self.throwable_enabled:
            stepper = self._throw_speed_stepper()
            speed_label = self.small_font.render("Vitesse", True, (200, 200, 200))
            screen.blit(speed_label, (stepper.minus_rect.x, stepper.minus_rect.y - speed_label.get_height() - 2))
            stepper.render(screen, self.border, self.small_font, self.throw_speed)

        explosive_label = "[x] Explosif" if self.explosive_enabled else "[ ] Explosif"
        self.border.draw_centered_label(screen, self._explosive_rect, self.font, explosive_label)
        if self.explosive_enabled:
            radius_stepper = self._blast_radius_stepper()
            radius_label = self.small_font.render("Rayon (cases)", True, (200, 200, 200))
            screen.blit(radius_label, (radius_stepper.minus_rect.x, radius_stepper.minus_rect.y - radius_label.get_height() - 2))
            radius_stepper.render(screen, self.border, self.small_font, self.blast_radius_tiles)

            damage_stepper = self._blast_damage_stepper()
            damage_label = self.small_font.render("Degats", True, (200, 200, 200))
            screen.blit(damage_label, (damage_stepper.minus_rect.x, damage_stepper.minus_rect.y - damage_label.get_height() - 2))
            damage_stepper.render(screen, self.border, self.small_font, self.blast_damage)

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
