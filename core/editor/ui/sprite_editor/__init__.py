"""SpriteEditorPanelUI split into a package -- see panel.py for why and
for the overall docstring. Re-exports SpriteEditorPanelUI so
`from core.editor.ui.sprite_editor import SpriteEditorPanelUI` (and
`from core.editor.ui import SpriteEditorPanelUI`, see the parent
package's own __init__.py) keep working unchanged."""

from .panel import SpriteEditorPanelUI

__all__ = ["SpriteEditorPanelUI"]
