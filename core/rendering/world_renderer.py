import pygame

from core.data.ressources import TILE_SIZE, load_tileset, get_tile_surface
from core.editor.autotile import EMPTY, DEFAULT_FLOOR_SPRITE
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

        for y, row in enumerate(dungeon.sprite_grid):
            for x, tile_index in enumerate(row):
                if tile_index < 0:
                    continue

                if (x, y) in doorway_cells:
                    tile_index = DEFAULT_FLOOR_SPRITE
                elif (x, y) in spawn_cells:
                    tile_index = self.SPAWN_FLOOR_SPRITE

                scaled = self._get_scaled_tile(tile_index, tile_px, columns)
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

    def _draw_objects(self, screen, dungeon, camera, hide_object_types=None, foreground_only=False, skip_foreground=False):
        hide_object_types = hide_object_types or ()
        tile_px, origin_x, origin_y = self._tile_grid_origin(dungeon, camera)

        for obj in dungeon.object_manager.objects:
            if obj["type"] in hide_object_types:
                continue

            is_foreground = dungeon.object_manager.is_foreground_object(obj)

            if foreground_only and not is_foreground:
                continue

            if skip_foreground and is_foreground:
                continue

            frames = self._get_object_frames(obj["type"], obj.get("variant"))
            frame_index = min(obj.get("frame", 0), len(frames) - 1)

            size_cells_x, size_cells_y = OBJECT_TYPES[obj["type"]]["size"]
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

            # Anchored to the footprint's left/bottom edge (not the origin cell's
            # center) so a multi-cell object like "wall" fills exactly the cells
            # it occupies instead of straddling half a tile into its neighbors.
            left_x = origin_x + obj["x"] * tile_px
            bottom_y = origin_y + (obj["y"] + size_cells_y) * tile_px

            screen.blit(scaled_sprite, (left_x, bottom_y - scaled_sprite.get_height()))

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
