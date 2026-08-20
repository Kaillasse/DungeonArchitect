import pygame

from core.data.ressources import TILE_SIZE, load_tileset, get_tile_surface, load_autotile_pack, load_tileset_region
from core.editor.autotile import EMPTY, WALL, DEFAULT_FLOOR_SPRITE, DEFAULT_WALL_SPRITE, build_pack_lookup
from core.world.object_manager import OBJECT_TYPES, load_object_frames


class WorldRenderer:
    """Draws a Dungeon. Holds no world data — only pygame surface caches."""

    GRID_LINE_COLOR = (80, 80, 80)
    SPAWN_PREVIEW_COLOR = (0, 255, 0)
    LINK_INDICATOR_COLOR = (60, 220, 90)
    LINK_INDICATOR_RADIUS = 5

    # basictileset.png (6 cols x 5 rows, the only sheet load_tileset ever
    # resolves to -- no tileset.png exists) -- a ledge/edge tile drawn one
    # cell south of every non-empty cell whose south neighbor is EMPTY,
    # gated by show_border (see render()/_render_border) rather than
    # show_grid (F3 debug lines only) -- player-facing, marking the real
    # floor boundary a void cell drop actually is (see
    # Explorator._is_void/_attempt_fall), not just a debug aid. hide_border_cells
    # (render()'s own param, see DungeonAssembly._border_cells_by_room)
    # suppresses this at a room-to-room border-merge seam, where the "south
    # neighbor" is secretly real floor belonging to another room, not void.
    BORDER_TILE_INDEX = 25

    # basictileset.png frame 20 -- the decorated floor tile drawn under a
    # placed "spawn" object instead of whatever the autotiler would
    # otherwise resolve there (Phase 6a), same "override this cell's tile
    # index before blitting" pattern _doorway_cells already uses for
    # gate/wall/cave_entrance.
    SPAWN_FLOOR_SPRITE = 20

    def __init__(self):
        self.tileset = load_tileset()
        self._tile_cache = {}
        self._pack_tile_cache = {}
        # Native (unscaled, TILE_SIZE-px), zoom-independent tile caches used
        # by the terrain composite path -- see _get_native_tile/
        # _get_pack_tile_native and render()'s own comment on why the floor/
        # wall grid composites at a fixed native resolution instead of
        # scaling each tile to the current (possibly continuously changing)
        # zoom. Never invalidated by a zoom change at all, unlike
        # _tile_cache/_pack_tile_cache above (still used by _render_border's
        # own, still per-tile-rounded, ledge pass).
        self._native_tile_cache = {}
        self._pack_tile_native_cache = {}
        # Same native/zoom-independent idea, for the object-composite path
        # (_draw_objects/_draw_pillar_tops) -- see _get_object_sprite_native.
        self._object_sprite_native_cache = {}
        self._pillar_top_native = None
        self._object_sprites = {}
        # (doorway_cells, spawn_cells, pillars), cached against the
        # objects_version they were computed from -- see
        # _get_objects_derived. A WorldRenderer is always owned 1:1 by
        # exactly one Dungeon (constructed once in Dungeon.__init__, never
        # shared across dungeons), so a bare instance attribute is safe
        # here, no dict keyed by dungeon needed.
        self._objects_cache = None
        # set of (x, y) source cells needing the debug south-border ledge
        # tile drawn one cell below them, cached against terrain_version --
        # see _get_ledge_cells.
        self._ledge_cache = None

    def _get_object_frames(self, object_type, variant=None, direction=None):
        cache_key = (object_type, variant, direction)
        if cache_key not in self._object_sprites:
            self._object_sprites[cache_key] = load_object_frames(object_type, variant, direction)
        return self._object_sprites[cache_key]

    def _get_scaled_tile(self, tile_index, tile_px, columns):
        # Keyed on tile_px (already the rounded pixel size that fully
        # determines the scaled output), not the raw zoom float -- Camera.
        # zoom_at's *1.2/0.8 steps rarely land on the exact same float twice,
        # so keying on zoom made this cache grow unboundedly across a
        # zoom-in/zoom-out session instead of being reused. tile_px collapses
        # every zoom that rounds to the same pixel size onto one entry.
        cache_key = (tile_index, tile_px)
        if cache_key not in self._tile_cache:
            tile_surface = get_tile_surface(self.tileset, tile_index, tile_size=TILE_SIZE, columns=columns)
            self._tile_cache[cache_key] = pygame.transform.scale(tile_surface, (tile_px, tile_px))
        return self._tile_cache[cache_key]

    def _get_pack_tile_surface(self, pack_name, tile_index, tile_px):
        """The scaled surface for tile `tile_index` of autotile pack
        `pack_name` (see core.data.ressources.save_autotile_pack) -- unlike
        _get_scaled_tile, never invalidated by a bitmask/default/variant_of
        edit (core.data.ressources.update_autotile_pack_tile never touches
        a tile's own `rect`, so the cropped image itself never goes stale;
        only build_pack_lookup's *choice* of which index to use can change,
        which is why that cache has its own separate mtime invalidation).
        A blank tile if the pack or index no longer resolves (e.g. deleted
        mid-session) instead of raising, same defensive spirit as
        get_tile_surface's own out-of-bounds branch."""
        cache_key = (pack_name, tile_index, tile_px)
        if cache_key not in self._pack_tile_cache:
            payload = load_autotile_pack(pack_name)
            tiles = payload.get("tiles", []) if payload else []
            if payload is None or not (0 <= tile_index < len(tiles)):
                surface = pygame.Surface((tile_px, tile_px), pygame.SRCALPHA)
            else:
                region = load_tileset_region(payload["tileset"], tiles[tile_index]["rect"])
                surface = pygame.transform.scale(region, (tile_px, tile_px))
            self._pack_tile_cache[cache_key] = surface
        return self._pack_tile_cache[cache_key]

    def _get_native_tile(self, tile_index, columns):
        """Unscaled (native TILE_SIZE-px) tile surface, cached by tile_index
        alone -- see _composite_tile_grid for why the terrain grid composites
        at this fixed native size instead of scaling each tile to the
        current zoom. Zoom-independent, so unlike _get_scaled_tile this
        cache is never invalidated by a zoom change at all."""
        if tile_index not in self._native_tile_cache:
            self._native_tile_cache[tile_index] = get_tile_surface(
                self.tileset, tile_index, tile_size=TILE_SIZE, columns=columns,
            )
        return self._native_tile_cache[tile_index]

    def _get_pack_tile_native(self, pack_name, tile_index):
        """Native-size counterpart to _get_pack_tile_surface -- same source
        region, scaled once to the fixed TILE_SIZE composite pitch instead
        of to the current zoom's tile_px. See _get_native_tile's own
        docstring; same invalidation story as _get_pack_tile_surface
        (never invalidated by a bitmask/variant edit, only by the tileset
        region itself changing, which core.data.ressources never does to
        an existing pack entry)."""
        cache_key = (pack_name, tile_index)
        if cache_key not in self._pack_tile_native_cache:
            payload = load_autotile_pack(pack_name)
            tiles = payload.get("tiles", []) if payload else []
            if payload is None or not (0 <= tile_index < len(tiles)):
                surface = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
            else:
                region = load_tileset_region(payload["tileset"], tiles[tile_index]["rect"])
                surface = pygame.transform.scale(region, (TILE_SIZE, TILE_SIZE))
            self._pack_tile_native_cache[cache_key] = surface
        return self._pack_tile_native_cache[cache_key]

    def _get_tile_surface_native(self, tile_index, pack_name, columns):
        if pack_name is not None:
            return self._get_pack_tile_native(pack_name, tile_index)
        return self._get_native_tile(tile_index, columns)

    def _get_tile_surface(self, dungeon, tile_index, pack_name, tile_px, columns):
        """Dispatches to a themed pack tile or the default interior tileset
        slice, depending on whether `pack_name` (that cell's own
        dungeon.theme_grid entry, or dungeon.floor_theme for a doorway/spawn
        cosmetic override -- see render()) is set. The single place
        render()'s tile-blit loop and its doorway/spawn overrides both go
        through, so the two can never resolve a cell differently."""
        if pack_name is not None:
            return self._get_pack_tile_surface(pack_name, tile_index, tile_px)
        return self._get_scaled_tile(tile_index, tile_px, columns)

    def _floor_override_index(self, dungeon):
        """The tile_index doorway/spawn cell overrides fall back to --
        DEFAULT_FLOOR_SPRITE (an interior tileset index) when the room has
        no floor theme, exactly as before; the theme's own default tile
        when it does, since DEFAULT_FLOOR_SPRITE means nothing in a themed
        pack's own index space."""
        if dungeon.floor_theme is not None:
            _lookup, default_index, _variants = build_pack_lookup(dungeon.floor_theme)
            return default_index
        return DEFAULT_FLOOR_SPRITE

    def get_theme_preview_surface(self, pack_name, role, size_px):
        """A small square surface showing the tile a given brush (pack_name,
        or None for the built-in interior tileset) would paint right now --
        `role` ("floor"/"wall") only matters when pack_name is None, to pick
        DEFAULT_FLOOR_SPRITE vs DEFAULT_WALL_SPRITE. Used by ToolPaletteUI's
        Sol/Mur buttons so the player can see which tileset is active before
        painting, without needing to reopen AutotileThemePanelUI. Reuses
        _get_pack_tile_surface/_get_scaled_tile's own caches -- same tiny
        surfaces render() already produces at other zoom levels, just one
        more (pack_name, tile_index, size_px) cache entry."""
        if pack_name is not None:
            _lookup, default_index, _variants = build_pack_lookup(pack_name)
            return self._get_pack_tile_surface(pack_name, default_index, size_px)
        tile_index = DEFAULT_FLOOR_SPRITE if role == "floor" else DEFAULT_WALL_SPRITE
        columns = self.tileset.get_width() // TILE_SIZE
        return self._get_scaled_tile(tile_index, size_px, columns)

    def render(self, screen, dungeon, camera, spawn_preview=None, hide_object_types=None, show_link_indicators=False,
               skip_foreground_objects=False, show_grid=True, show_border=True, hide_border_cells=None):
        zoom = camera.zoom
        tile_size = dungeon.tile_size
        # Snapped to a whole pixel count -- see _get_scaled_tile: every tile
        # texture at this zoom is exactly tile_px wide/tall. If we instead
        # positioned each tile with camera.world_to_screen's raw float and
        # let pygame.blit truncate that per tile, consecutive tiles would
        # step by floor(tile_px) some of the time and ceil(tile_px) other
        # times (whenever the true fractional-pixel position crosses an
        # integer boundary) while the texture itself always stays the same
        # rounded width -- a 1px gap flickers in wherever the step exceeded
        # the texture's width. That's the "irregular grid that isn't there
        # at min/max zoom" bug: min/max zoom happen to land on an exact
        # integer tile_px (e.g. 32*0.5, 32*4), so there was nothing to round
        # in the first place; every other zoom level (reached via
        # Camera.zoom_at's *1.2/0.8 steps) doesn't. Deriving every tile's
        # screen position from one shared, already-rounded origin plus an
        # integer multiple of this same tile_px guarantees adjacent tiles
        # are always exactly contiguous, no matter the zoom.
        #
        # tile_px/origin both come from _tile_grid_origin -- see its own
        # docstring for why origin must be derived from tile_px's rounded
        # scale rather than camera.world_to_screen's raw one. Still used
        # below for viewport culling and by everything BUT the terrain grid
        # itself (_composite_tile_grid renders that with its own,
        # non-per-tile-rounded scheme -- see its own docstring).
        tile_px, origin_x, origin_y = self._tile_grid_origin(dungeon, camera)
        columns = self.tileset.get_width() // TILE_SIZE
        doorway_cells, spawn_cells, _pillars = self._get_objects_derived(dungeon)

        # Viewport culling: only the cells that could actually land on
        # screen, instead of every cell in the room regardless of zoom/
        # camera position -- a small room this made no visible difference
        # for, but scales with room/viewport size instead of always being
        # O(width*height) per frame.
        x_start, x_end = self._visible_range(origin_x, tile_px, screen.get_width(), dungeon.width)
        y_start, y_end = self._visible_range(origin_y, tile_px, screen.get_height(), dungeon.height)

        self._composite_tile_grid(
            screen, dungeon, camera, columns, doorway_cells, spawn_cells,
            x_start, x_end, y_start, y_end,
        )

        self._draw_objects(
            screen, dungeon, camera,
            hide_object_types=hide_object_types,
            skip_foreground=skip_foreground_objects,
        )
        if not skip_foreground_objects:
            # Creator's single-pass preview (no player to interleave) --
            # Explorator instead defers this to render_foreground_objects(),
            # called after it draws the player, so a pillar's decorative top
            # ends up in front of them too.
            self._draw_pillar_tops(screen, dungeon, camera, hide_object_types=hide_object_types)

        if show_border:
            self._render_border(screen, dungeon, camera, hide_border_cells=hide_border_cells)

        if show_grid:
            for gy in range(dungeon.height + 1):
                world_y = gy * tile_size
                p1 = camera.world_to_screen(0, world_y)
                p2 = camera.world_to_screen(dungeon.width * tile_size, world_y)
                pygame.draw.line(screen, self.GRID_LINE_COLOR, p1, p2)

            for gx in range(dungeon.width + 1):
                world_x = gx * tile_size
                p1 = camera.world_to_screen(world_x, 0)
                p2 = camera.world_to_screen(world_x, dungeon.height * tile_size)
                pygame.draw.line(screen, self.GRID_LINE_COLOR, p1, p2)

        if spawn_preview is not None:
            gx, gy = spawn_preview
            wx, wy = dungeon.grid_to_world(gx, gy)
            sx, sy = camera.world_to_screen(wx, wy)

            pygame.draw.circle(
                screen,
                self.SPAWN_PREVIEW_COLOR,
                (int(sx), int(sy)),
                int(tile_size * zoom / 4),
                2,
            )

        if show_link_indicators:
            self._draw_link_indicators(screen, dungeon, camera)

    def _composite_tile_grid(
        self, screen, dungeon, camera, columns, doorway_cells, spawn_cells, x_start, x_end, y_start, y_end,
    ):
        """Draws the floor/wall grid for [x_start, x_end) x [y_start, y_end)
        as ONE continuously-scaled image instead of many individually
        pixel-rounded tile blits (see render()'s own long comment on
        tile_px for the original gap-flicker problem that rounding fixed).

        Every visible tile is first composited at its fixed NATIVE size
        (TILE_SIZE, unscaled -- always exactly contiguous with its
        neighbors, nothing to round) onto one offscreen surface, which is
        then scaled ONCE using the camera's raw, continuous zoom and
        blitted at a single screen position. Rounding only happens twice
        per frame here (the composite's overall pixel size, and its one
        blit position) instead of once per visible tile -- so position
        error is bounded to about half a pixel, total, rather than about
        half a pixel PER CELL multiplied by that cell's distance from the
        camera's corner. That distance-amplified error (a tile 20 cells
        out could be off by ~10px) is what made the whole world visibly
        tremble while the co-op shared camera's zoom-to-fit eased
        continuously for about a second on every zoom change -- worse the
        farther apart the players (and so the more zoomed out, wider-area
        the shared view) were. Fixed 2026-08-18; see _tile_grid_origin's
        own docstring for a smaller, earlier fix along the same lines that
        wasn't sufficient by itself.

        Placed OBJECTS (walls-as-decoration, doors, chests...) still use
        the older per-object tile_px scheme (_draw_objects) -- terrain is
        the dominant visual mass, so it's fixed first; objects are a
        smaller, sparser follow-up if they turn out to still be
        noticeable."""
        if x_end <= x_start or y_end <= y_start:
            return

        composite_w = (x_end - x_start) * TILE_SIZE
        composite_h = (y_end - y_start) * TILE_SIZE
        composite = pygame.Surface((composite_w, composite_h), pygame.SRCALPHA)

        for y in range(y_start, y_end):
            row = dungeon.sprite_grid[y]
            for x in range(x_start, x_end):
                tile_index = row[x]
                if tile_index < 0:
                    continue

                # See render()'s previous version of this same override
                # logic for the full doorway/spawn-cosmetic-override
                # reasoning -- unchanged, just now filling the composite
                # instead of blitting straight to screen.
                if (x, y) in doorway_cells and dungeon.logical_grid[y][x] == WALL:
                    tile_index = self._floor_override_index(dungeon)
                    pack_name = dungeon.floor_theme
                elif (x, y) in spawn_cells:
                    if dungeon.floor_theme is not None:
                        tile_index = self._floor_override_index(dungeon)
                    else:
                        tile_index = self.SPAWN_FLOOR_SPRITE
                    pack_name = dungeon.floor_theme
                else:
                    pack_name = dungeon.theme_grid[y][x]

                tile_surface = self._get_tile_surface_native(tile_index, pack_name, columns)
                composite.blit(tile_surface, ((x - x_start) * TILE_SIZE, (y - y_start) * TILE_SIZE))

        # dungeon.tile_size / TILE_SIZE recovers WORLD_SCALE (16px source
        # art rendered at 2x) without importing it separately -- consistent
        # with how tile_px = round(dungeon.tile_size * zoom) already folds
        # it in elsewhere in this file.
        effective_scale = camera.zoom * (dungeon.tile_size / TILE_SIZE)
        target_w = max(1, round(composite_w * effective_scale))
        target_h = max(1, round(composite_h * effective_scale))
        scaled = pygame.transform.scale(composite, (target_w, target_h))

        dest_x, dest_y = camera.world_to_screen(x_start * dungeon.tile_size, y_start * dungeon.tile_size)
        screen.blit(scaled, (round(dest_x), round(dest_y)))

    def _render_border(self, screen, dungeon, camera, hide_border_cells=None):
        """The south-edge ledge tile (see BORDER_TILE_INDEX's own docstring)
        -- player-facing now, not just an F3 debug aid, so both render()
        (single-room Creator/Explorator draw) and DungeonAssembly._render_floor
        (via the public render_border() below, see its own docstring for why
        that's a SEPARATE pass rather than just calling this from inside
        render()) can call it independently of show_grid, which now only
        gates the literal debug grid LINES."""
        # Composited natively then scaled+blitted once -- same reasoning as
        # _composite_tile_grid/_draw_objects/_draw_pillar_tops (2026-08-18):
        # per-tile rounded positioning amplified into visible trembling,
        # proportional to distance from the camera, during a continuously
        # changing zoom. Bounding box over only the VISIBLE ledge cells
        # (not the whole viewport, not the whole dungeon) -- a long south
        # wall can span a wide area, but it's still capped by the screen-
        # bounded visible range, same as every other composite pass here.
        tile_px, origin_x, origin_y = self._tile_grid_origin(dungeon, camera)
        columns = self.tileset.get_width() // TILE_SIZE
        x_start, x_end = self._visible_range(origin_x, tile_px, screen.get_width(), dungeon.width)
        y_start, y_end = self._visible_range(origin_y, tile_px, screen.get_height(), dungeon.height)
        if x_end <= x_start or y_end <= y_start:
            return

        hide_border_cells = hide_border_cells or ()
        ledge_source_cells = self._get_ledge_cells(dungeon)

        visible_ledges = [
            (x, y + 1) for x, y in ledge_source_cells
            if (x, y) not in hide_border_cells and x_start <= x < x_end and y_start <= y + 1 < y_end
        ]
        if not visible_ledges:
            return

        min_x = min(x for x, _ in visible_ledges)
        max_x = max(x for x, _ in visible_ledges)
        min_y = min(y for _, y in visible_ledges)
        max_y = max(y for _, y in visible_ledges)

        composite_w = (max_x - min_x + 1) * TILE_SIZE
        composite_h = (max_y - min_y + 1) * TILE_SIZE
        composite = pygame.Surface((composite_w, composite_h), pygame.SRCALPHA)

        native_ledge = self._get_native_tile(self.BORDER_TILE_INDEX, columns)
        for x, south_y in visible_ledges:
            composite.blit(native_ledge, ((x - min_x) * TILE_SIZE, (south_y - min_y) * TILE_SIZE))

        effective_scale = camera.zoom * (dungeon.tile_size / TILE_SIZE)
        target_w = max(1, round(composite_w * effective_scale))
        target_h = max(1, round(composite_h * effective_scale))
        scaled = pygame.transform.scale(composite, (target_w, target_h))
        dest_x, dest_y = camera.world_to_screen(min_x * dungeon.tile_size, min_y * dungeon.tile_size)
        screen.blit(scaled, (round(dest_x), round(dest_y)))

    def render_border(self, screen, dungeon, camera, hide_border_cells=None):
        """Public entry point for a SEPARATE border-only pass -- see
        DungeonAssembly._render_floor, which now draws every room's own
        floor/objects (show_border=False) in one full loop BEFORE calling
        this for every room in a second loop. That ordering is the actual
        fix for a real glitch: a room whose south edge glues to another
        room via a border merge (see core.world.assembly._border_edges) has
        no way to know, from its own local grid alone, that its southern
        neighbor cell is secretly real floor belonging to the OTHER room,
        not void -- _border_cells_by_room already computes and hides
        exactly those cells, but drawing this as a guaranteed-last pass
        (never interleaved with any room's floor) means even a seam this
        filter somehow missed would still end up painted OVER by real floor
        rather than on top of it, instead of depending on happening to
        iterate rooms in exactly the right order."""
        self._render_border(screen, dungeon, camera, hide_border_cells=hide_border_cells)

    @staticmethod
    def _footprint_cells(dungeon, predicate):
        """Every cell covered by the footprint of each placed object matching
        `predicate(obj)` -- shared by _doorway_cells (gate/wall/cave_entrance/
        big_entrance) and _spawn_cells ("spawn"), both used the same way:
        override this cell's tile index before blitting instead of whatever
        the autotiler resolved there. A gate/wall can only ever be placed on
        a WALL cell that already reads as a clean doorway
        (ObjectManager.is_valid_doorway), so its mere presence is enough --
        no need to re-validate the shape here. Drawing FLOOR under it instead
        of the underlying WALL sprite is purely cosmetic (the logical_grid
        cell stays WALL, so autotiling/doorway-validity/the procedural
        assembler are untouched) -- it just stops the player from feeling
        like they're walking into solid wall texture when the gate/wall
        itself is open (or even closed, since the door sprite is what
        visually reads as blocking, not a wall texture peeking through).

        The actual footprint math is ObjectManager._footprint_cells_of's --
        reused here instead of re-deriving OBJECT_TYPES[...]["size"] and the
        dx/dy loop a second time, so there's only one place that needs to
        get "which cells does this object's footprint cover" right."""
        object_manager = dungeon.object_manager
        cells = set()
        for obj in object_manager.objects:
            if not predicate(obj):
                continue
            cells.update(object_manager._footprint_cells_of(obj))
        return cells

    @classmethod
    def _doorway_cells(cls, dungeon):
        return cls._footprint_cells(dungeon, lambda obj: OBJECT_TYPES[obj["type"]]["placement"] == "doorway")

    @classmethod
    def _spawn_cells(cls, dungeon):
        return cls._footprint_cells(dungeon, lambda obj: obj["type"] == "spawn")

    def _get_objects_derived(self, dungeon):
        """(doorway_cells, spawn_cells, pillars), recomputed only when
        dungeon.object_manager.objects_version has actually changed --
        render() used to rebuild doorway/spawn cells from scratch (a full
        scan of every placed object) every single frame, and
        _draw_pillar_tops did its own separate full scan for pillars alone,
        even though objects change rarely (a paint/erase/move/prune, not
        per-frame). Folded into one cache since all three share the exact
        same invalidation signal. Same versioned-cache shape as
        DungeonAssembly._border_cells_by_room's use of terrain_version --
        objects_version is the object-list equivalent."""
        version = dungeon.object_manager.objects_version
        cached = self._objects_cache
        if cached is not None and cached[0] == version:
            return cached[1], cached[2], cached[3]

        doorway_cells = self._doorway_cells(dungeon)
        spawn_cells = self._spawn_cells(dungeon)
        pillars = [obj for obj in dungeon.object_manager.objects if obj["type"] == "pillar"]
        self._objects_cache = (version, doorway_cells, spawn_cells, pillars)
        return doorway_cells, spawn_cells, pillars

    def _get_ledge_cells(self, dungeon):
        """Every (x, y) SOURCE cell (a non-empty cell whose south neighbor is
        EMPTY, off-grid counting as EMPTY) needing the south-border ledge
        tile (BORDER_TILE_INDEX) drawn one cell below it -- cached against
        dungeon.terrain_version instead of rescanned every frame
        (_render_border used to be a full O(width*height) grid scan every
        call). Keyed by the SOURCE cell, not the drawn position,
        to match hide_border_cells' own coordinate convention
        (DungeonAssembly._south_seam_cells collects source floor cells, not
        the cell below them). terrain_version is bumped by both Dungeon.
        paint_cell (Creator painting/erasing) and destroy_area (exploration-
        time destruction), so a hole freshly carved into a room -- by either
        -- shows its own ledge on the very next render instead of only ever
        reflecting whatever the grid looked like when this was first cached."""
        version = dungeon.terrain_version
        cached = self._ledge_cache
        if cached is not None and cached[0] == version:
            return cached[1]

        cells = set()
        for y, row in enumerate(dungeon.logical_grid):
            for x, cell in enumerate(row):
                if cell == EMPTY:
                    continue
                south_y = y + 1
                if south_y >= dungeon.height or dungeon.logical_grid[south_y][x] == EMPTY:
                    cells.add((x, y))
        self._ledge_cache = (version, cells)
        return cells

    def render_foreground_objects(self, screen, dungeon, camera, hide_object_types=None):
        """Objects ObjectManager.is_foreground_object() flags (e.g. an L/R torch), plus every pillar's decorative top -- call this after drawing the player sprite."""
        self._draw_objects(screen, dungeon, camera, hide_object_types=hide_object_types, foreground_only=True)
        self._draw_pillar_tops(screen, dungeon, camera, hide_object_types=hide_object_types)

    @staticmethod
    def _tile_grid_origin(dungeon, camera):
        """(tile_px, origin_x, origin_y) shared by every tile/object blit in
        a render pass -- see render()'s own comment on tile_px for why this
        matters: positioning each object independently via camera.world_to_
        screen's raw float (as this used to do) let an object drift up to a
        pixel off the floor grid beneath it at non-integer zoom, since the
        tile grid itself is already snapped to this same origin+tile_px
        scheme but a lone per-object call wasn't. Deriving every position
        from one shared, already-rounded origin plus an integer multiple of
        the same tile_px keeps objects glued to the grid at any zoom.

        origin is derived from tile_px's own effective (rounded) scale --
        tile_px / dungeon.tile_size -- NOT camera.world_to_screen's raw
        camera.zoom (fixed 2026-08-18: it used to be). Mixing the two meant
        a cell's actual rendered offset was origin(raw zoom) + index *
        tile_px(rounded zoom): the gap between "raw" and "rounded" zoom is
        at most 0.5 tile_px, but that gap gets multiplied by the cell
        index, so a tile 20 cells from the origin could sit up to ~10px
        off from where continuous, unrounded math would put it -- and
        that error swings through its full range every time zoom moves by
        one whole tile_px step. Static zoom (manual mouse-wheel, one step
        then still) made this a single imperceptible snap; the co-op
        shared camera's zoom-to-fit (Explorator._update_shared_camera)
        eases zoom continuously for about a second, sweeping through that
        error dozens of times a second -- which is what actually read as
        the world trembling/juddering during a zoom transition (entities
        never showed it: core.world.entities draws them from raw
        camera.zoom throughout, with nothing else to be inconsistent
        with). Deriving origin from the SAME rounded scale as tile_px
        makes the two always agree, so the only motion left when tile_px
        ticks by one is the real, single-pixel-per-cell rescale a zoom
        step actually is -- no added wobble on top of it.

        Rescales camera.world_to_screen(0, 0)'s own raw-zoom answer by
        (effective_zoom / camera.zoom) rather than reaching into camera.x/
        camera.y directly -- core.world.assembly's _OffsetCamera/
        _ZoomOnlyCamera (multi-room rendering) only implement zoom/
        world_to_screen, no x/y, and world_to_screen(0, 0) is always some
        fixed reference point R transformed as (0 - R) * zoom for every
        camera shape actually used here, so multiplying by the zoom ratio
        is equivalent to redoing that same transform at effective_zoom
        instead, for any of them."""
        zoom = camera.zoom
        tile_px = round(dungeon.tile_size * zoom)
        effective_zoom = tile_px / dungeon.tile_size
        raw_origin_x, raw_origin_y = camera.world_to_screen(0, 0)
        scale_ratio = effective_zoom / zoom
        origin_x = round(raw_origin_x * scale_ratio)
        origin_y = round(raw_origin_y * scale_ratio)
        return tile_px, origin_x, origin_y

    @staticmethod
    def _visible_range(origin, tile_px, screen_extent, count):
        """[start, end) grid indices along one axis whose tile could touch
        the visible [0, screen_extent) screen span -- cell i draws at
        origin + i*tile_px (see _tile_grid_origin), so this is just that
        formula solved for i, clamped to [0, count] and padded by one tile
        on each side so a partially-visible edge tile is never dropped.
        Used by render()'s tile-grid loop and _draw_objects to skip work
        for cells/objects nowhere near the camera instead of walking the
        entire grid/object list every frame regardless of what a room's
        size actually is -- previously O(width*height) unconditionally, no
        matter the zoom level or room size."""
        start = max(0, (0 - origin) // tile_px - 1)
        end = min(count, (screen_extent - origin) // tile_px + 2)
        return start, end

    def _get_object_sprite_native(self, obj_type, variant, direction, frame_index, size_cells_x, size_cells_y):
        """Unscaled-to-zoom (TILE_SIZE-per-cell) object sprite, cached by
        (type, variant, direction, frame, footprint size) -- the object
        composite path's counterpart to _get_native_tile/_get_pack_tile_
        native. See _draw_objects for why objects composite at this fixed
        native resolution and get scaled once, continuously, instead of
        each being individually scaled/rounded to the current zoom (that
        was the exact same distance-amplified trembling the terrain grid
        had, just for placed objects -- fixed 2026-08-18, same day as
        terrain, once it turned out to be MORE noticeable once terrain
        stopped moving relative to it). `direction` (NPC_DIRECTIONS, or
        None) selects one frame_rects entry out of a type's own
        `directions` mapping -- see load_object_frames -- orthogonal to
        `variant` (torch-style alternate assets), never both at once in
        practice."""
        cache_key = (obj_type, variant, direction, frame_index, size_cells_x, size_cells_y)
        if cache_key not in self._object_sprite_native_cache:
            frames = self._get_object_frames(obj_type, variant, direction)
            frame_index = min(frame_index, len(frames) - 1)
            size = (size_cells_x * TILE_SIZE, size_cells_y * TILE_SIZE)
            sprite = pygame.transform.scale(frames[frame_index], size)
            if variant == "flip":
                # Stairs only (Phase 6a): a single stairs.png asset,
                # mirrored horizontally instead of shipping a second file --
                # the cache key already varies by variant, so the flipped
                # surface is cached separately from the unflipped one.
                sprite = pygame.transform.flip(sprite, True, False)
            self._object_sprite_native_cache[cache_key] = sprite
        return self._object_sprite_native_cache[cache_key]

    def _draw_objects(self, screen, dungeon, camera, hide_object_types=None, foreground_only=False, skip_foreground=False):
        """Composites every visible placed object onto one native-resolution
        offscreen surface (same TILE_SIZE-per-cell pitch _composite_tile_grid
        uses for terrain), then scales that whole surface once, continuously,
        and blits it in a single call -- see _composite_tile_grid's own
        docstring for the full reasoning (distance-from-camera-amplified
        rounding error during a continuously-changing zoom). Objects used to
        each be individually scaled/positioned via origin + cell_index *
        tile_px (a per-object rounding, same shape of bug the terrain grid
        had); doing that per object instead of once for the whole visible
        set was strictly worse, not better, since there are usually MANY
        objects across a room's whole visible span."""
        hide_object_types = hide_object_types or ()
        tile_px, origin_x, origin_y = self._tile_grid_origin(dungeon, camera)
        x_start, x_end = self._visible_range(origin_x, tile_px, screen.get_width(), dungeon.width)
        y_start, y_end = self._visible_range(origin_y, tile_px, screen.get_height(), dungeon.height)
        if x_end <= x_start or y_end <= y_start:
            return

        composite_w = (x_end - x_start) * TILE_SIZE
        composite_h = (y_end - y_start) * TILE_SIZE
        composite = pygame.Surface((composite_w, composite_h), pygame.SRCALPHA)
        drew_anything = False

        for obj in dungeon.object_manager.objects:
            if obj["type"] in hide_object_types:
                continue

            config = OBJECT_TYPES[obj["type"]]
            size_cells_x, size_cells_y = config["size"]

            # Viewport culling in CELL space against the same [x_start,
            # x_end) x [y_start, y_end) window terrain uses -- an object's
            # footprint depends only on its position/size, never its
            # frame/variant, so this is checked before touching the sprite
            # cache (or loading frames from disk on a cache miss) at all.
            if (
                obj["x"] + size_cells_x <= x_start or obj["x"] >= x_end
                or obj["y"] + size_cells_y <= y_start or obj["y"] >= y_end
            ):
                continue

            # A custom type with per-cell "cell_modes" (see
            # object_manager.CELL_MODES/cell_mode) decides front/back PER
            # CELL below instead of through this single whole-object check
            # -- skip the early foreground_only/skip_foreground filter here
            # entirely for those, since a single object can straddle both
            # passes at once.
            cell_modes = config.get("cell_modes")

            if cell_modes is None:
                is_foreground = dungeon.object_manager.is_foreground_object(obj)
                if foreground_only and not is_foreground:
                    continue
                if skip_foreground and is_foreground:
                    continue

            frames = self._get_object_frames(obj["type"], obj.get("variant"), obj.get("direction"))
            frame_index = min(obj.get("frame", 0), len(frames) - 1)
            native_sprite = self._get_object_sprite_native(
                obj["type"], obj.get("variant"), obj.get("direction"), frame_index, size_cells_x, size_cells_y,
            )

            local_x = (obj["x"] - x_start) * TILE_SIZE
            local_y = (obj["y"] - y_start) * TILE_SIZE

            if cell_modes is not None:
                self._composite_object_cells(
                    composite, native_sprite, cell_modes, size_cells_x, size_cells_y,
                    local_x, local_y, foreground_only, skip_foreground,
                )
            else:
                composite.blit(native_sprite, (local_x, local_y))
            drew_anything = True

        if not drew_anything:
            return

        effective_scale = camera.zoom * (dungeon.tile_size / TILE_SIZE)
        target_w = max(1, round(composite_w * effective_scale))
        target_h = max(1, round(composite_h * effective_scale))
        scaled = pygame.transform.scale(composite, (target_w, target_h))
        dest_x, dest_y = camera.world_to_screen(x_start * dungeon.tile_size, y_start * dungeon.tile_size)
        screen.blit(scaled, (round(dest_x), round(dest_y)))

    def _composite_object_cells(
        self, composite, native_sprite, cell_modes, size_cells_x, size_cells_y,
        local_x, local_y, foreground_only, skip_foreground,
    ):
        """Native-composite counterpart to the old _draw_object_cells:
        splits one already-native-scaled object sprite into its individual
        TILE_SIZE-sized cell pieces onto `composite` at LOCAL (composite-
        relative) coordinates, instead of directly onto the screen at
        absolute (tile_px-scaled) ones. Same per-cell front/behind/block
        filtering as before -- "front" cells only in the foreground pass
        (after the player, like an L/R torch), "block"/"behind" cells only
        in the normal pass (before the player), matching the sprite
        editor's multi-tile grid (core.world.object_manager.CELL_MODES/
        cell_mode). Neither filter active (Creator's single combined pass)
        draws every cell."""
        for row in range(size_cells_y):
            row_modes = cell_modes[row] if row < len(cell_modes) else ()
            for col in range(size_cells_x):
                mode = row_modes[col] if col < len(row_modes) else "behind"
                is_front = mode == "front"
                if foreground_only and not is_front:
                    continue
                if skip_foreground and is_front:
                    continue
                source_rect = pygame.Rect(col * TILE_SIZE, row * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                dest = (local_x + col * TILE_SIZE, local_y + row * TILE_SIZE)
                composite.blit(native_sprite, dest, area=source_rect)

    def _draw_pillar_tops(self, screen, dungeon, camera, hide_object_types=None):
        """Every pillar's decorative top half, one cell north of wherever
        that pillar object currently is (Phase 6a polish -- see
        OBJECT_TYPES["pillar"]): purely a rendering detail, not a second
        object, so it always follows its base automatically and can never
        be independently moved/erased/orphaned. Always drawn, regardless of
        what else occupies that cell -- same "always wins" foreground
        treatment an L/R torch already gets, with no exception (an earlier
        version skipped entry-exit cells; the user asked to drop that)."""
        hide_object_types = hide_object_types or ()
        if "pillar" in hide_object_types:
            return

        _doorway_cells, _spawn_cells, pillars = self._get_objects_derived(dungeon)
        if not pillars:
            return

        # Composited natively (like _draw_objects/_composite_tile_grid) then
        # scaled+blitted once -- tight bounding box around only the VISIBLE
        # pillar tops (not the whole viewport, and not the whole dungeon):
        # pillars are typically sparse, so a full-viewport composite would
        # be wasteful, but a bounding box over every pillar in a large room
        # regardless of visibility could span the whole room. Filtering to
        # visible ones first keeps this both small and safe.
        tile_px, origin_x, origin_y = self._tile_grid_origin(dungeon, camera)
        x_start, x_end = self._visible_range(origin_x, tile_px, screen.get_width(), dungeon.width)
        y_start, y_end = self._visible_range(origin_y, tile_px, screen.get_height(), dungeon.height)

        visible_tops = [
            (obj["x"], obj["y"] - 1) for obj in pillars
            if x_start <= obj["x"] < x_end and y_start <= obj["y"] - 1 < y_end
        ]
        if not visible_tops:
            return

        min_x = min(x for x, _ in visible_tops)
        max_x = max(x for x, _ in visible_tops)
        min_y = min(y for _, y in visible_tops)
        max_y = max(y for _, y in visible_tops)

        composite_w = (max_x - min_x + 1) * TILE_SIZE
        composite_h = (max_y - min_y + 1) * TILE_SIZE
        composite = pygame.Surface((composite_w, composite_h), pygame.SRCALPHA)

        native_sprite = self._get_pillar_top_native()
        for top_x, top_y in visible_tops:
            composite.blit(native_sprite, ((top_x - min_x) * TILE_SIZE, (top_y - min_y) * TILE_SIZE))

        effective_scale = camera.zoom * (dungeon.tile_size / TILE_SIZE)
        target_w = max(1, round(composite_w * effective_scale))
        target_h = max(1, round(composite_h * effective_scale))
        scaled = pygame.transform.scale(composite, (target_w, target_h))
        dest_x, dest_y = camera.world_to_screen(min_x * dungeon.tile_size, min_y * dungeon.tile_size)
        screen.blit(scaled, (round(dest_x), round(dest_y)))

    def _get_pillar_top_native(self):
        if self._pillar_top_native is None:
            frames = self._get_object_frames("pillar", "top")
            self._pillar_top_native = pygame.transform.scale(frames[0], (TILE_SIZE, TILE_SIZE))
        return self._pillar_top_native

    def _draw_link_indicators(self, screen, dungeon, camera):
        for obj in dungeon.object_manager.objects:
            # Also shown for E/S types that aren't "linkable" (cave_entrance/
            # big_entrance never button-link to anything, so their own
            # `links` list -- read below -- always stays empty, drawing just
            # a bare dot with no lines) -- this is what gives them a
            # right-clickable target for RolePanelUI (see Creator), same dot
            # gate/wall's own link-drag already uses.
            if not (dungeon.object_manager.is_linkable(obj["type"]) or dungeon.object_manager.is_es_type(obj["type"])):
                continue

            sx, sy = camera.world_to_screen(*dungeon.object_indicator_position(obj))

            for link_target in obj.get("links", []):
                lsx, lsy = camera.world_to_screen(*dungeon.object_indicator_position(link_target))
                pygame.draw.line(screen, self.LINK_INDICATOR_COLOR, (sx, sy), (lsx, lsy), 2)

            pygame.draw.circle(screen, self.LINK_INDICATOR_COLOR, (int(sx), int(sy)), self.LINK_INDICATOR_RADIUS)
