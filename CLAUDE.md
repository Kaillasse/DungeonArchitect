# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Dungeon Architect — a top-down, tile-based roguelike editor/game built with pygame. Players will explore procedurally-composed dungeons and unlock tiles/monsters/traps/entities for a fully customizable, destructible home base between runs. See `DA.txt` (French) for the full design pitch and current priority list.

The grid uses 16x16px source art; each world grid cell renders that art at 2x, so a logical cell is 32x32px (see `core.data.ressources.WORLD_SCALE`). Rooms are composed of these cells and saved as JSON under `assets/rooms/`.

## Commands

- Run the app: `python main.py` (opens the main menu, `GameState.MENU`).
- Dependencies: `pygame==2.6.1`, declared in `requirements.txt`. **That file is UTF-16LE encoded** (not UTF-8) — `pip install -r requirements.txt` may fail to parse depending on pip version; if so just `pip install pygame==2.6.1` directly. A `.venv` already exists in the repo root.
- Headless smoke-test of the editor: set `DUNGEONARCHITECT_HEADLESS=1` before running — `GameManager` skips the menu and starts straight in `GameState.CREATOR`, and `Creator.run()` saves the current room and exits immediately instead of opening the pygame window/event loop.
- There is no test suite, linter, or build config in the repo.

## In-app controls

- Menu: `UP`/`DOWN` (or `Z`/`S`) to move the selection, `ENTER` or mouse click to confirm, `ESC` quits.
- Editor (Creator): left-click paint floor / drag object icons from the palette onto the grid, right-click erase, mouse-wheel zoom, `TAB` switch to exploration, `ESC` quit. `F1` save room / `F2` delete room / `F3` load room / `F4` list rooms — these block on `input()` in the terminal (see `RoomManager`), not in the pygame window.
- Exploration (Explorator): French AZERTY movement (`Z`/`Q`/`S`/`D`, not WASD), mouse-wheel zoom, `TAB` back to editor, `ESC` quit.

## Architecture

`main.py` builds the pygame `screen` and hands it to `GameManager`, whose `run()` loop dispatches on `core.engine.gamestate.GameState` (`MENU` / `CREATOR` / `EXPLORATION`). Each state object owns **its own inner pygame event loop** (`Menu.run()`, `Creator.run()`, `Explorator.run()`) rather than there being one shared frame loop — switching state means setting `self.state` and breaking out of the current inner `while` loop, which returns control to `GameManager.run()` to dispatch into the next state's loop.

Package layout (`core/`):
- `engine/` — state machine plumbing: `GameManager`, `GameState`, `Camera` (world↔screen coordinate/zoom transform), `RoomManager` (console-driven save/load/delete/list of rooms, via `input()`).
- `editor/` — the room editor (`Creator`, the `CREATOR` state): `ui.py` has `BorderManager` (singleton 9-slice panel renderer), `ToolPaletteUI`, `ObjectPalette` (the draggable object-type icon tray, reuses `object_manager.load_object_frames`); `tools.py` has `ObjectTool` (drag state for placing an object from the palette onto the grid); `autotile.py` is the tile-logic core (see below).
- `world/` — the dungeon data model: `dungeon.py` (`Dungeon` owns `width`/`height`/`logical_grid`/`sprite_grid` directly and orchestrates an `ObjectManager` + `WorldRenderer` + `SaveManager`; grid↔world coordinate conversion; `is_rect_walkable` collision check — it draws nothing, saves nothing, and doesn't manage objects itself), `object_manager.py` (`ObjectManager(dungeon)` — takes the dungeon it belongs to; the `OBJECT_TYPES`/`OBJECT_LIST` registry of placeable object metadata — asset path, placement surface, footprint size in cells, frame count; `load_object_frames()` slices a sprite sheet, shared by the editor palette and the renderer), `entities.py` (`Player` — sprite-sheet animation keyed by direction, mirrors left-facing sprites from the right-facing frames, hitbox anchored at the feet; stub `NPC`/`Enemies` classes not yet wired up).
- `data/` — `ressources.py` (asset/tileset path resolution, tile metadata JSON loading, the `ROOMS_DIRECTORY` constant, `TILE_SIZE`/`WORLD_SCALE`), `save_manager.py` (`SaveManager` — stateless `save(dungeon, room_name)` / `load(dungeon, room_name)`, converts a `Dungeon` to/from its JSON room file).
- `rendering/` — `world_renderer.py` (`WorldRenderer.render(screen, dungeon, camera, spawn_preview=None)`: draws the tile grid with a `(tile_index, zoom)` surface cache, placed objects sized from `OBJECT_TYPES[type]["size"]` (in grid cells, not raw sprite pixels), debug grid lines, and the spawn-preview marker. Holds no world state itself — only pygame surface caches).
- `menu.py`, `explorator.py` (top-level, not in a subpackage) — `Menu` (the `MENU` state: title screen, routes to `CREATOR`/`EXPLORATION`) and `Explorator` (the `EXPLORATION` state: player movement/collision, camera follow).

Autotiling (`core/editor/autotile.py`), the core "logical grid" algorithm: cells are `EMPTY`/`FLOOR`/`WALL` ints. `build_walls()` does a two-pass pass over the grid — strip existing `WALL` cells back to `EMPTY`, then surround every `FLOOR` cell's empty neighbors (8-directional) with `WALL`. `resolve_sprite_grid()` then computes a 4-directional (`up`/`right`/`down`/`left`) neighbor bitmask string like `"0212"` per non-empty cell and looks up `(category, bitmask)` in `AUTOTILE_LOOKUP`, which is built at import time from `assets/tiles/tile_categories.json`, to pick the concrete sprite index.

## Roadmap (planned, not yet implemented)

The following is the design spec for the next round of work — recorded here so a future session has the intent even if the code doesn't exist yet. Don't assume any of this is wired up; check the actual files first.

**Object placement rules** (none of this is enforced yet — `ObjectManager.add_object` currently only checks that the target cell is `FLOOR`; `OBJECT_TYPES[type]["placement"]` is defined in the registry but never read):
- `spawn` should not render during `EXPLORATION` (editor-only marker) — `WorldRenderer` currently draws every object in `dungeon.object_manager.objects` unconditionally.
- `gate`/`wall`/`button` are floor-only and should be destroyed if their underlying floor cell is destroyed (no such linkage exists yet between `paint_cell(erase=True)` and placed objects).
- `torch` is wall-only, with an L/R variant depending on which side the adjacent floor has a wall on (right-adjacent wall → R variant, left-adjacent wall → L variant). Asset files for these variants already exist (`assets/tiles/Torch Yellow L.png`, `Torch Yellow R.png`) but aren't referenced by `OBJECT_TYPES` yet.
- Dynamic/stateful objects: stepping on a `button` should trigger the button's own animation plus the linked `gate`/`wall` object's open animation, and make that cell walkable. This needs some form of object-to-object linking (e.g. button → target gate/wall) that doesn't exist yet — today `logical_grid` only encodes static `EMPTY`/`FLOOR`/`WALL`, with no notion of a runtime-toggleable walkable state.

**Procedural room-to-room generation**: detect a room's entry/exit points (via its `gate`/`wall` objects), then propose or procedurally place adjacent rooms whose own entry/exit objects match type-for-type. Overlap at a junction should be resolved by shifting the new room ±1 floor/layer (multi-floor dungeons, not just single rooms) rather than by moving tiles within a floor. When floors are stacked, the player standing below an occupied floor above them should be able to see through to it (a rendering concern — `WorldRenderer` currently renders exactly one `Dungeon`'s grid, with no concept of multiple stacked floors at all).
