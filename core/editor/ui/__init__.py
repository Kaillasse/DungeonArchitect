"""Creator's UI panels -- split out of what used to be one 2988-line
core/editor/ui.py file (10 classes, SpriteEditorPanelUI alone over half the
file) into one module per panel, for the same reason exploration/ split
Explorator's own helpers into player_session.py/inventory_ui.py rather than
growing forever: each panel's own concerns (layout, event handling,
rendering) are easier to find and change in isolation. This module keeps
every name callers imported from `core.editor.ui` (chiefly
core.editor.creator.Creator) importable exactly the same way -- no caller
outside this package needed to change."""

from core.editor.ui.tool_palette import ToolPaletteUI
from core.editor.ui.room_panel import RoomPanelUI
from core.editor.ui.card_renderer import CardRenderer
from core.editor.ui.card_panel import CardPanelUI
from core.editor.ui.generator_panel import GeneratorPanelUI
from core.editor.ui.role_panel import RolePanelUI
from core.editor.ui.chest_panel import ChestPanelUI
from core.editor.ui.autotile_theme_panel import AutotileThemePanelUI
from core.editor.ui.sprite_editor import SpriteEditorPanelUI
from core.editor.ui.mechanics_panel import MechanicsPanelUI
from core.editor.ui.stash_panel import StashPanelUI

__all__ = [
    "ToolPaletteUI",
    "RoomPanelUI",
    "CardRenderer",
    "CardPanelUI",
    "GeneratorPanelUI",
    "RolePanelUI",
    "ChestPanelUI",
    "AutotileThemePanelUI",
    "SpriteEditorPanelUI",
    "MechanicsPanelUI",
    "StashPanelUI",
]
