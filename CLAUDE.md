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
- `menu.py`, `explorator.py`, `ui.py` (top-level, not in a subpackage) — `Menu` (the `MENU` state: title screen with Editeur/Explorer/Parametres/Quitter, routes to `CREATOR`/`EXPLORATION`; `ESC` from either gameplay state now returns here instead of quitting — only the menu itself quits the program), `Explorator` (the `EXPLORATION` state: player movement/collision, camera follow), `ui.py` (`BorderManager`, the shared 9-slice panel renderer used by both the editor UI and `Menu`).

Autotiling (`core/editor/autotile.py`), the core "logical grid" algorithm: cells are `EMPTY`/`FLOOR`/`WALL` ints. `build_walls()` does a two-pass pass over the grid — strip existing `WALL` cells back to `EMPTY`, then surround every `FLOOR` cell's empty neighbors (8-directional) with `WALL`. `resolve_sprite_grid()` then computes a 4-directional (`up`/`right`/`down`/`left`) neighbor bitmask string like `"0212"` per non-empty cell and looks up `(category, bitmask)` in `AUTOTILE_LOOKUP`, which is built at import time from `assets/tiles/tile_categories.json`, to pick the concrete sprite index.

## Roadmap

**Object placement rules — done:**
- `ObjectManager.add_object` now reads `OBJECT_TYPES[type]["placement"]` (`"floor"` or `"wall"`) instead of hardcoding `FLOOR` for every type — this also fixed a real bug where `torch` (wall-only) could never actually be placed.
- `Dungeon.paint_cell` calls `object_manager.prune_invalid()` after every edit, which drops any placed object whose cell no longer matches its placement rule — so erasing a floor destroys the `gate`/`wall`/`button`/`vase`/`spawn` sitting on it, and erasing the floor that generated a wall segment destroys any `torch` mounted there too.
- `spawn` is excluded from rendering during exploration: `WorldRenderer.render(..., hide_object_types=...)`, with `Explorator` passing `{"spawn"}`. `Creator` passes nothing, so it still shows in the editor.
- `torch` gets an L/R wall-mount variant chosen at placement time (`ObjectManager._wall_variant`): floor immediately to the wall's left → `R`, floor immediately to the wall's right → `L`, no adjacent floor on either side (the common straight-wall case) → the plain front-facing sprite. Stored as an optional `"variant"` key on the object dict (additive — old saves without it still load).

**Not yet implemented — needs a design decision before starting:** button/gate/wall dynamic linkage. Stepping on a `button` should trigger its own animation plus a *specific* linked `gate`/`wall` object's open animation, and make that cell walkable. This needs:
- a way to associate a button with the gate(s)/wall(s) it opens (explicit link stored at placement time? nearest matching object in the room? something else?) — no such concept exists yet, and it changes the save format (an additive field, same as `torch`'s `variant`, but worth agreeing on the shape first)
- a runtime-toggleable walkable state, since `logical_grid` today only encodes static `EMPTY`/`FLOOR`/`WALL` with no notion of a cell becoming walkable/unwalkable at runtime without rebuilding the autotile grid

**Procedural room-to-room generation** (further out, not started): detect a room's entry/exit points (via its `gate`/`wall` objects), then propose or procedurally place adjacent rooms whose own entry/exit objects match type-for-type. Overlap at a junction should be resolved by shifting the new room ±1 floor/layer (multi-floor dungeons, not just single rooms) rather than by moving tiles within a floor. When floors are stacked, the player standing below an occupied floor above them should be able to see through to it (a rendering concern — `WorldRenderer` currently renders exactly one `Dungeon`'s grid, with no concept of multiple stacked floors at all).
