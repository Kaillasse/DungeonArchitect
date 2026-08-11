import pygame

from core.data.ressources import TILE_SIZE, load_tileset, get_tile_surface, load_autotile_pack, load_tileset_region
from core.editor.autotile import EMPTY, WALL, DEFAULT_FLOOR_SPRITE, build_pack_lookup
from core.world.object_manager import OBJECT_TYPES, load_object_frames


class WorldRenderer:
    """Draws a Dungeon. Holds no world data — only pygame surface caches."""

    GRID_LINE_COLOR = (80, 80, 80)
    SPAWN_PREVIEW_COLOR = (0, 255, 0)
    LINK_INDICATOR_COLOR = (60, 220, 90)
    LINK_INDICATOR_RADIUS = 5

    # basictileset.png (6 cols x 5 rows, the only sheet load_tileset ever
    # resolves to -- no tileset.png exists) -- a ledge/edge tile drawn one
    # cell south of every non-empty cell whose south neighbor is EMPTY, only
    # while show_grid is True (F3 debug -- see render()'s "hide_border_cells"
    # too): a debug visualization of the logical grid's floor boundary, not
    # player-facing art, since a void cell is real, walkable-into terrain
    # (see Explorator._is_void/_attempt_fall) rather than a gap to visually
    # patch over.
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
        self._object_sprites = {}
        self._object_sprite_cache = {}
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

    def _get_object_frames(self, object_type, variant=None):
        cache_key = (object_type, variant)
        if cache_key not in self._object_sprites:
            self._object_sprites[cache_key] = load_object_frames(object_type, variant)
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

    def _get_tile_surface(self, dungeon, tile_index, pack_name, tile_px, columns):
        """Dispatches to a themed pack tile or the default interior tileset
        slice, depending on whether `pack_name` (dungeon.floor_theme/
        wall_theme for this cell's role -- see render()) is set. The single
        place render()'s tile-blit loop and its doorway/spawn overrides both
        go through, so the two can never resolve a cell differently."""
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

    def render(self, screen, dungeon, camera, spawn_preview=None, hide_object_types=None, show_link_indicators=False,
               skip_foreground_objects=False, show_grid=True, hide_border_cells=None):
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
        tile_px = round(tile_size * zoom)
        columns = self.tileset.get_width() // TILE_SIZE
        doorway_cells, spawn_cells, _pillars = self._get_objects_derived(dungeon)

        origin_x, origin_y = camera.world_to_screen(0, 0)
        origin_x, origin_y = round(origin_x), round(origin_y)

        # Viewport culling: only the cells that could actually land on
        # screen, instead of every cell in the room regardless of zoom/
        # camera position -- a small room this made no visible difference
        # for, but scales with room/viewport size instead of always being
        # O(width*height) per frame.
        x_start, x_end = self._visible_range(origin_x, tile_px, screen.get_width(), dungeon.width)
        y_start, y_end = self._visible_range(origin_y, tile_px, screen.get_height(), dungeon.height)

        for y in range(y_start, y_end):
            row = dungeon.sprite_grid[y]
            for x in range(x_start, x_end):
                tile_index = row[x]
                if tile_index < 0:
                    continue

                # A doorway/spawn override always renders as FLOOR-styled
                # art (see _footprint_cells' own docstring -- cosmetic only,
                # the logical cell underneath stays WALL) regardless of
                # which role's theme actually owns this cell, so both
                # branches force pack_name to the room's *floor* theme, not
                # whatever its own logical type would normally pick.
                if (x, y) in doorway_cells:
                    tile_index = self._floor_override_index(dungeon)
                    pack_name = dungeon.floor_theme
                elif (x, y) in spawn_cells:
                    if dungeon.floor_theme is not None:
                        tile_index = self._floor_override_index(dungeon)
                    else:
                        tile_index = self.SPAWN_FLOOR_SPRITE
                    pack_name = dungeon.floor_theme
                else:
                    is_wall_cell = dungeon.logical_grid[y][x] == WALL
                    pack_name = dungeon.wall_theme if is_wall_cell else dungeon.floor_theme

                scaled = self._get_tile_surface(dungeon, tile_index, pack_name, tile_px, columns)
                screen.blit(scaled, (origin_x + x * tile_px, origin_y + y * tile_px))

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

        if show_grid:
            hide_border_cells = hide_border_cells or ()
            ledge_source_cells = self._get_ledge_cells(dungeon)
            scaled_ledge = self._get_scaled_tile(self.BORDER_TILE_INDEX, tile_px, columns)
            for x, y in ledge_source_cells:
                if (x, y) in hide_border_cells:
                    continue
                south_y = y + 1
                screen.blit(scaled_ledge, (origin_x + x * tile_px, origin_y + south_y * tile_px))

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
        visually reads as blocking, not a wall texture peeking through)."""
        cells = set()
        for obj in dungeon.object_manager.objects:
            if not predicate(obj):
                continue
            size_x, size_y = OBJECT_TYPES[obj["type"]]["size"]
            for dx in range(size_x):
                for dy in range(size_y):
                    cells.add((obj["x"] + dx, obj["y"] + dy))
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
        EMPTY, off-grid counting as EMPTY) needing the debug south-border
        ledge tile (BORDER_TILE_INDEX) drawn one cell below it -- cached
        against dungeon.terrain_version instead of rescanned every frame
        (render()'s show_grid block used to be a full O(width*height) grid
        scan every call). Keyed by the SOURCE cell, not the drawn position,
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
        the same tile_px keeps objects glued to the grid at any zoom."""
        tile_px = round(dungeon.tile_size * camera.zoom)
        origin_x, origin_y = camera.world_to_screen(0, 0)
        return tile_px, round(origin_x), round(origin_y)

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

    def _draw_objects(self, screen, dungeon, camera, hide_object_types=None, foreground_only=False, skip_foreground=False):
        hide_object_types = hide_object_types or ()
        tile_px, origin_x, origin_y = self._tile_grid_origin(dungeon, camera)
        screen_w, screen_h = screen.get_width(), screen.get_height()

        for obj in dungeon.object_manager.objects:
            if obj["type"] in hide_object_types:
                continue

            config = OBJECT_TYPES[obj["type"]]
            size_cells_x, size_cells_y = config["size"]

            # Viewport culling -- an object's footprint depends only on its
            # position/size, never its frame/variant, so this can be
            # checked before touching the sprite cache (or loading frames
            # from disk on a cache miss) at all. Anchored to the
            # footprint's left/top edge, same as the blit position below
            # (left_x, top_y = origin_x + obj["x"]*tile_px, origin_y +
            # obj["y"]*tile_px -- scaled_sprite is always scaled to exactly
            # size_cells*tile_px, so this is the same position the old
            # bottom_y-then-subtract-height computation always landed on).
            left_x = origin_x + obj["x"] * tile_px
            top_y = origin_y + obj["y"] * tile_px
            if (
                left_x + size_cells_x * tile_px <= 0 or left_x >= screen_w
                or top_y + size_cells_y * tile_px <= 0 or top_y >= screen_h
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

            frames = self._get_object_frames(obj["type"], obj.get("variant"))
            frame_index = min(obj.get("frame", 0), len(frames) - 1)

            cache_key = (obj["type"], obj.get("variant"), frame_index, tile_px)
            scaled_sprite = self._object_sprite_cache.get(cache_key)
            if scaled_sprite is None:
                size = (size_cells_x * tile_px, size_cells_y * tile_px)
                scaled_sprite = pygame.transform.scale(frames[frame_index], size)
                if obj.get("variant") == "flip":
                    # Stairs only (Phase 6a): a single stairs.png asset,
                    # mirrored horizontally instead of shipping a second
                    # file, when ObjectManager._stairs_orientation found the
                    # floor it's facing to the west -- the cache key above
                    # already varies by variant, so the flipped surface is
                    # cached separately from the unflipped one for free.
                    scaled_sprite = pygame.transform.flip(scaled_sprite, True, False)
                self._object_sprite_cache[cache_key] = scaled_sprite

            if cell_modes is not None:
                self._draw_object_cells(
                    screen, scaled_sprite, cell_modes, size_cells_x, size_cells_y,
                    left_x, top_y, tile_px, foreground_only, skip_foreground,
                )
                continue

            screen.blit(scaled_sprite, (left_x, top_y))

    def _draw_object_cells(
        self, screen, scaled_sprite, cell_modes, size_cells_x, size_cells_y,
        left_x, top_y, tile_px, foreground_only, skip_foreground,
    ):
        """Splits one already-scaled object sprite into its individual
        size_cells_x x size_cells_y cell-sized pieces, each blitted
        separately (Surface.blit's `area` crops the source) so DIFFERENT
        cells of the SAME object can land in different render passes --
        "front" cells only in the foreground pass (after the player, like
        an L/R torch), "block"/"behind" cells only in the normal pass
        (before the player) -- matching the per-cell walkable+draw-order
        the sprite editor's multi-tile grid assigns (see
        core.world.object_manager.CELL_MODES/cell_mode). Neither filter
        active (Creator's single combined pass) draws every cell."""
        for row in range(size_cells_y):
            row_modes = cell_modes[row] if row < len(cell_modes) else ()
            for col in range(size_cells_x):
                mode = row_modes[col] if col < len(row_modes) else "behind"
                is_front = mode == "front"
                if foreground_only and not is_front:
                    continue
                if skip_foreground and is_front:
                    continue
                source_rect = pygame.Rect(col * tile_px, row * tile_px, tile_px, tile_px)
                dest = (left_x + col * tile_px, top_y + row * tile_px)
                screen.blit(scaled_sprite, dest, area=source_rect)

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

        tile_px, origin_x, origin_y = self._tile_grid_origin(dungeon, camera)

        cache_key = ("pillar", "top", 0, tile_px)
        sprite = self._object_sprite_cache.get(cache_key)
        if sprite is None:
            frames = self._get_object_frames("pillar", "top")
            sprite = pygame.transform.scale(frames[0], (tile_px, tile_px))
            self._object_sprite_cache[cache_key] = sprite

        for obj in pillars:
            top_x, top_y = obj["x"], obj["y"] - 1
            screen.blit(sprite, (origin_x + top_x * tile_px, origin_y + top_y * tile_px))

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
