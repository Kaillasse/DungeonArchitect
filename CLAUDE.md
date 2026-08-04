# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Dungeon Architect — a top-down, tile-based roguelike editor/game built with pygame. Players will explore procedurally-composed dungeons and unlock tiles/monsters/traps/entities for a fully customizable, destructible home base between runs. See `DA.txt` (French) for the full design pitch and current priority list.

The grid uses 16x16px logical cells; rooms are composed of these cells and saved as JSON under `assets/rooms/`.

## Commands

- Run the app: `python main.py` (launches straight into the room editor, `GameState.CREATOR`).
- Dependencies: `pygame==2.6.1`, declared in `requirements.txt`. **That file is UTF-16LE encoded** (not UTF-8) — `pip install -r requirements.txt` may fail to parse depending on pip version; if so just `pip install pygame==2.6.1` directly. A `.venv` already exists in the repo root.
- Headless smoke-test of the editor: set `DUNGEONARCHITECT_HEADLESS=1` before running — `Creator.run()` will save the current room and exit immediately instead of opening the pygame window/event loop.
- There is no test suite, linter, or build config in the repo.

## In-app controls

- Editor (Creator): left-click paint floor / drag object icons from the palette onto the grid, right-click erase, mouse-wheel zoom, `TAB` switch to exploration, `ESC` quit. `F1` save room / `F2` delete room / `F3` load room / `F4` list rooms — these block on `input()` in the terminal (see `RoomManager`), not in the pygame window.
- Exploration (Explorator): French AZERTY movement (`Z`/`Q`/`S`/`D`, not WASD), mouse-wheel zoom, `TAB` back to editor, `ESC` quit.

## Architecture

`main.py` builds the pygame `screen` and hands it to `GameManager`, whose `run()` loop dispatches on `core.engine.gamestate.GameState` (`CREATOR` / `EXPLORATION` / `INTERACTION`). Each state object owns **its own inner pygame event loop** (`Creator.run()`, `Explorator.run()`, `GameManager.handle_interaction()`) rather than there being one shared frame loop — switching state means setting `self.state` and breaking out of the current inner `while` loop, which returns control to `GameManager.run()` to dispatch into the next state's loop.

Package layout (`core/`):
- `engine/` — state machine plumbing: `GameManager`, `GameState`, `Camera` (world↔screen coordinate/zoom transform), `RoomManager` (console-driven save/load/delete/list of rooms, via `input()`).
- `editor/` — the room editor (`Creator`, the `CREATOR` state): `ui.py` has `BorderManager` (singleton 9-slice panel renderer), `ToolPaletteUI`, `ObjectPalette` (the draggable object-type icon tray); `tools.py` has `ObjectTool` (drag state for placing an object from the palette onto the grid); `autotile.py` is the tile-logic core (see below).
- `world/` — the dungeon data model: `dungeon.py` (`Dungeon` composes a `TileMap` + `ObjectManager` + `WorldRenderer` + `SaveManager`; grid↔world coordinate conversion; `is_rect_walkable` collision check), `object_manager.py` (`ObjectManager` plus the `OBJECT_TYPES`/`OBJECT_LIST` registry of placeable object metadata — asset path, placement surface, footprint size, frame count), `entities.py` (`Player` — sprite-sheet animation keyed by direction, mirrors left-facing sprites from the right-facing frames, hitbox anchored at the feet; stub `NPC`/`Enemies` classes not yet wired up).
- `data/` — `ressources.py` (asset/tileset path resolution, tile metadata JSON loading, the `ROOMS_DIRECTORY` constant), `save_manager.py` (`SaveManager`, JSON room (de)serialization with a legacy-tile-format migration path).
- `rendering/` — `world_renderer.py` (`WorldRenderer`: draws the tile grid with a `(tile_index, zoom)` surface cache, placed objects, debug grid lines, and the spawn-preview marker).
- `explorator.py` (top-level, not in a subpackage) — the `EXPLORATION` state (`Explorator`): player movement/collision, camera follow.

Autotiling (`core/editor/autotile.py`), the core "logical grid" algorithm: cells are `EMPTY`/`FLOOR`/`WALL` ints. `build_walls()` does a two-pass pass over the grid — strip existing `WALL` cells back to `EMPTY`, then surround every `FLOOR` cell's empty neighbors (8-directional) with `WALL`. `resolve_sprite_grid()` then computes a 4-directional (`up`/`right`/`down`/`left`) neighbor bitmask string like `"0212"` per non-empty cell and looks up `(category, bitmask)` in `AUTOTILE_LOOKUP`, which is built at import time from `assets/tiles/tile_categories.json`, to pick the concrete sprite index.

### Mid-refactor state — known-broken wiring

The codebase was recently restructured from a flat `core/*.py` layout into the `engine/editor/world/data/rendering` subpackages above (see the many `D core/*.py` deletions in `git status`). Several cross-module references were not finished being updated and will raise `NameError`/`AttributeError` at runtime if that code path is exercised:
- `GameManager.initialize_world`/`initialize_character`/`initialize_camera`/`handle_exploration` reference `World`, `PNJManager`, `Character`, `InteractionUI` — none of these are imported or defined anywhere in the current tree.
- `Creator` (`core/editor/creator.py`) calls `self.editor.*` in several places (`_mouse_to_grid`, `_paint_at_mouse`, `run`) but never assigns `self.editor` in `__init__` — it likely should be `self.dungeon.tilemap` or similar.
- `WorldRenderer.render()` reads `self.tileset`, `self.sprite_grid`, `self.objects`, `self.height`/`self.width`, `self.tile_size`, `self.grid_to_world` — none of which are set on `WorldRenderer` itself; it looks like it was designed to be called with `Dungeon`/`TileMap` as `self` rather than as its own class.
- `ObjectManager.add_object` reads `self.logical_grid`/`self.width`/`self.height`, which don't exist on `ObjectManager` (they live on `TileMap`/`Dungeon`).
- `core/world/tilemap.py` is mostly commented-out design notes plus a re-export from `autotile.py`; the real `TileMap` implementation lives in `core/world/dungeon.py`, not there.
- `bin/grid.py` is a leftover/superseded standalone `DungeonGrid` prototype (predates the `Dungeon`/`TileMap`/`ObjectManager` split) and contains a dangling `ObjectPalette()` expression with no method body around it — don't treat it as the current data model.

Before assuming a class is fully wired up, check its actual current state rather than trusting these notes to stay accurate — this is very much in-progress code.
