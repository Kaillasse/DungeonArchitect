"""SoundBoxPanelUI -- the sound counterpart to MechanicsPanelUI's own
"drop a card onto the panel, edit it" pattern (see that module's own
docstring for the Forge's version), reached in-world via a "boxbig"
object instead of a "Totem 3" -- same proximity-gated docked-panel shape
as the Forge/Generateur (see Creator._entity_in_range/its own
_sound_box_unlocked).

Confirmed with the user: sounds moved OUT of the Forge entirely into this
dedicated tool ("simplifier l'affichage dans la Forge") -- MechanicsPanelUI
still LOADS and passes through whatever sounds/pitch a card already has
(so its own Enregistrer can never silently wipe them), it just no longer
renders or lets the player edit them; this panel is the only place that
actually happens now. Everything else the Forge does (mechanics,
Proprietes/Dechirer/Coller, Cartes/butin) stays exactly where it was --
this panel is sounds-only, nothing more.

Deliberately simpler than the Forge: fixed size, no scrolling (the
worst-case row count -- an enemy's 5 states + place/destroy = 7 -- fits
comfortably without it), no resizing, no giant-card backing (a plain
BorderManager panel, like ChestPanelUI/RolePanelUI). The row/pitch-slider
UI itself is otherwise a straight port of what MechanicsPanelUI's own
Sons section used to render/handle.
"""

import random

import pygame

from core.ui.widgets import BorderManager
from core.ui.fonts import get_font
from core.world.object_manager import (
    OBJECT_TYPES, ITEM_DEFINITIONS, ENEMY_ANIMATIONS, mob_kind as _mob_kind,
    update_type_mechanics, update_item_overrides, update_item, is_builtin_item,
)
from core.data.sound_manager import SoundManager, list_available_sound_files


class SoundBoxPanelUI:
    STANDARD_WIDTH = 420
    STANDARD_HEIGHT = 420

    SOUND_ROW_HEIGHT = 30
    # A sound row gains this much extra height when its pitch slider is
    # showing (see _sound_row_height's own MechanicsPanelUI ancestor) --
    # the slider draws on its own line right below the file picker/Jouer
    # row, not squeezed onto it.
    PITCH_ROW_HEIGHT = 26
    PITCH_SLIDER_MIN = 0.5
    PITCH_SLIDER_MAX = 2.0
    DEFAULT_PITCH_RANGE = [0.85, 1.15]

    CARD_TEXT_COLOR = (20, 20, 20)
    CARD_TEXT_MUTED_COLOR = (70, 70, 70)

    _SOUND_LABEL_OVERRIDES = {
        "use": "Utilisation", "place": "Pose", "destroy": "Casse",
        "throw": "Lancer", "interact": "Interaction",
        "idle": "Repos", "movement": "Mouvement", "move": "Mouvement",
        "attack": "Attaque", "damaged": "Touche", "death": "Mort",
    }

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.width = self.STANDARD_WIDTH
        self.height = self.STANDARD_HEIGHT

        self.border = BorderManager()
        self.font = get_font("button", 18, bold=True)
        self.title_font = get_font("title", 18, bold=True)
        self.small_font = get_font("button", 13)

        self.type_id = None
        self.item_id = None
        self.name = ""
        # "object"/"item"/"mob"/"pnj" -- just enough of MechanicsPanelUI's
        # own card_kind concept to know which sound slots apply (see
        # _sound_slot_keys), never the full mechanics-editing state.
        self.card_kind = None
        self.mob_states = ()
        self.interactable = False
        self.throwable_enabled = False
        self.status_text = ""

        # Sons -- {"use"/"place"/"destroy"/...: "filename.wav"|None}, same
        # generic vocabulary as core.data.cards.Card.sounds/object_manager's
        # "sounds" mechanics field. _available_sound_files is scanned once
        # per panel lifetime, not re-globbed per frame.
        self.card_sounds = {}
        self._available_sound_files = list_available_sound_files()
        self._sound_rects = {}

        # Pitch -- {key: True/False} whether random-pitch is on for that
        # sound slot, {key: [min, max]} its range when it is. Only
        # meaningful for a key that also has a real sound assigned.
        self.pitch_enabled = {}
        self.pitch_range = {}
        self._pitch_rects = {}
        self._pitch_dragging = None  # (key, "lo"/"hi") or None

        self._save_rect = None
        self._clear_rect = None
        self._layout()

    def contains(self, pos):
        return pygame.Rect(self.x, self.y, self.width, self.height).collidepoint(pos)

    def move(self, dx, dy):
        self.x += dx
        self.y += dy
        self._layout()

    def open(self, card_id):
        """Loads just enough of `card_id` to know which sound slots apply
        (card_kind/mob_states/interactable/throwable_enabled -- the exact
        same rule MechanicsPanelUI's own _sound_slot_keys used to derive
        from its full edit state) plus its current sounds/pitch. Stays
        empty for anything that isn't a real OBJECT_TYPES/ITEM_DEFINITIONS
        id (a room or property card has no sounds concept at all)."""
        item_def = ITEM_DEFINITIONS.get(card_id)
        if item_def is not None:
            self.item_id = card_id
            self.type_id = None
            self.name = item_def.get("name", card_id)
            self.card_kind = "item"
            self.mob_states = ()
            self.interactable = False
            self.throwable_enabled = "throwable" in item_def.get("capabilities", {})
            self._load_sounds(item_def.get("sounds", {}))
            self._load_pitch(item_def.get("sound_pitch", {}))
            self.status_text = ""
            return

        config = OBJECT_TYPES.get(card_id)
        if config is None:
            return
        self.type_id = card_id
        self.item_id = None
        self.name = config.get("name", card_id)
        self.throwable_enabled = False

        is_pnj = bool(config.get("entity_pack"))
        is_mob = bool(config.get("mob")) and not is_pnj
        if is_mob:
            self.card_kind = "mob"
            kind = _mob_kind(card_id)
            self.mob_states = ENEMY_ANIMATIONS if kind == "enemy" else ("idle", "move")
            self.interactable = False
        elif is_pnj:
            self.card_kind = "pnj"
            self.mob_states = ()
            self.interactable = False
        else:
            self.card_kind = "object"
            self.mob_states = ()
            self.interactable = config.get("interactable", False)
        self._load_sounds(config.get("sounds", {}))
        self._load_pitch(config.get("sound_pitch", {}))
        self.status_text = ""

    def clear(self):
        """"Vider" -- returns to the empty placeholder state without
        touching disk, same spirit as MechanicsPanelUI's own."""
        self.type_id = None
        self.item_id = None
        self.name = ""
        self.status_text = ""

    def _sound_slot_keys(self):
        """Every sound row that applies to the currently loaded card --
        one slot per ACTION the card can actually trigger. Verbatim copy
        of MechanicsPanelUI's own rule (see that method's own docstring
        for the full per-kind reasoning), just reading this panel's own
        slimmer load() state instead of the Forge's full edit state."""
        if self.card_kind == "item":
            keys = ["use"]
            if self.throwable_enabled:
                keys.append("throw")
            return keys
        if self.card_kind == "mob":
            return list(self.mob_states) + ["place", "destroy"]
        if self.card_kind == "pnj":
            return ["use", "place", "destroy"]
        if self.card_kind == "object":
            keys = ["place", "destroy"]
            if self.interactable or OBJECT_TYPES.get(self.type_id, {}).get("linkable"):
                keys.append("interact")
            return keys
        return []

    def _sound_slot_label(self, key):
        return "Son : " + self._SOUND_LABEL_OVERRIDES.get(key, key.replace("_", " ").title())

    def _load_sounds(self, sounds):
        self.card_sounds = dict(sounds)

    def _cycle_sound(self, key, step):
        options = [None] + self._available_sound_files
        current = self.card_sounds.get(key)
        index = options.index(current) if current in options else 0
        self.card_sounds[key] = options[(index + step) % len(options)]

    def _load_pitch(self, sound_pitch):
        self.pitch_enabled = {key: True for key in sound_pitch}
        self.pitch_range = {key: list(value) for key, value in sound_pitch.items()}

    def _toggle_pitch(self, key):
        """Flips random-pitch on/off for `key` -- newly enabling it seeds
        DEFAULT_PITCH_RANGE rather than a degenerate [x, x]."""
        self.pitch_enabled[key] = not self.pitch_enabled.get(key, False)
        if self.pitch_enabled[key] and key not in self.pitch_range:
            self.pitch_range[key] = list(self.DEFAULT_PITCH_RANGE)

    def _pitch_value_to_x(self, track, value):
        span = self.PITCH_SLIDER_MAX - self.PITCH_SLIDER_MIN
        frac = max(0.0, min(1.0, (value - self.PITCH_SLIDER_MIN) / span))
        return track.x + frac * track.width

    def _pitch_x_to_value(self, track, x):
        frac = max(0.0, min(1.0, (x - track.x) / max(1, track.width)))
        return self.PITCH_SLIDER_MIN + frac * (self.PITCH_SLIDER_MAX - self.PITCH_SLIDER_MIN)

    def _sound_row_height(self, key):
        height = self.SOUND_ROW_HEIGHT
        if self.card_sounds.get(key) and self.pitch_enabled.get(key):
            height += self.PITCH_ROW_HEIGHT
        return height

    def _try_save(self):
        """"Enregistrer" -- persists ONLY sounds/sound_pitch, passing
        every OTHER mechanics field straight through unchanged from the
        card's own current live state (this panel never tracks or edits
        any of them -- that's still entirely the Forge's job). Same
        update_type_mechanics/update_item_overrides/update_item entry
        points MechanicsPanelUI's own Enregistrer uses, just a narrower
        slice of what actually changes. Returns the saved id on success
        (Creator just refreshes the Collection, same "plain string"
        contract MechanicsPanelUI's own _try_save already established),
        None on failure."""
        entry = OBJECT_TYPES.get(self.type_id) if self.type_id is not None else ITEM_DEFINITIONS.get(self.item_id)
        if entry is None:
            return None
        sounds = {key: path for key, path in self.card_sounds.items() if path}
        sound_pitch = {
            key: self.pitch_range[key] for key in sounds
            if self.pitch_enabled.get(key) and key in self.pitch_range
        }
        try:
            if self.item_id is not None:
                if is_builtin_item(self.item_id):
                    update_item_overrides(
                        self.item_id, entry.get("capabilities", {}), entry.get("effects", []),
                        sounds, sound_pitch, entry.get("loot_cards"),
                    )
                else:
                    update_item(
                        self.item_id, entry.get("name"), entry.get("slot"), entry.get("icon_path"),
                        entry.get("icon_rect"),
                        capabilities=entry.get("capabilities", {}), effects=entry.get("effects", []),
                        sounds=sounds, sound_pitch=sound_pitch, loot_cards=entry.get("loot_cards"),
                    )
            else:
                update_type_mechanics(
                    self.type_id,
                    blocks_movement=entry.get("blocks_movement", False),
                    cell_modes=entry.get("cell_modes"),
                    interactable=entry.get("interactable", False),
                    lockable=bool(entry.get("blocks_until_open")),
                    capabilities=entry.get("capabilities", {}),
                    stats=entry.get("stats"),
                    effects=entry.get("effects", []),
                    sounds=sounds,
                    sound_pitch=sound_pitch,
                    loot_cards=entry.get("loot_cards"),
                )
        except ValueError as exc:
            self.status_text = str(exc)
            return None
        self.status_text = f"Sons de '{self.name}' mis a jour."
        return self.item_id if self.item_id is not None else self.type_id

    def _layout(self):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        content_x = self.x + 20
        content_width = self.width - 40
        self._clear_rect = pygame.Rect(panel_rect.right - 90, panel_rect.y + 12, 70, 28)
        self._save_rect = pygame.Rect(content_x, self.y + self.height - 56, content_width, 40)

        cursor = self.y + 60
        row_h = self.SOUND_ROW_HEIGHT - 6
        label_w, btn_w, name_w, play_w, pitch_w, gap = 90, 20, 90, 44, 44, 5
        self._sound_rects = {}
        self._pitch_rects = {}
        for key in self._sound_slot_keys():
            ry = cursor
            lx = content_x + label_w + gap
            prev_rect = pygame.Rect(lx, ry, btn_w, row_h)
            name_rect = pygame.Rect(prev_rect.right + gap, ry, name_w, row_h)
            next_rect = pygame.Rect(name_rect.right + gap, ry, btn_w, row_h)
            play_rect = pygame.Rect(next_rect.right + gap, ry, play_w, row_h)
            pitch_toggle_rect = pygame.Rect(play_rect.right + gap, ry, pitch_w, row_h)
            self._sound_rects[key] = {
                "label": pygame.Rect(content_x, ry, label_w, row_h),
                "prev": prev_rect, "name": name_rect, "next": next_rect, "play": play_rect,
                "pitch_toggle": pitch_toggle_rect,
            }
            if self.card_sounds.get(key) and self.pitch_enabled.get(key):
                slider_y = cursor + self.SOUND_ROW_HEIGHT + 6
                track = pygame.Rect(content_x + 46, slider_y, content_width - 46 - 96, 12)
                lo_value, hi_value = self.pitch_range.get(key, self.DEFAULT_PITCH_RANGE)
                lo_x = self._pitch_value_to_x(track, lo_value)
                hi_x = self._pitch_value_to_x(track, hi_value)
                self._pitch_rects[key] = {
                    "track": track,
                    "lo": pygame.Rect(lo_x - 5, track.centery - 8, 10, 16),
                    "hi": pygame.Rect(hi_x - 5, track.centery - 8, 10, 16),
                }
            else:
                self._pitch_rects.pop(key, None)
            cursor += self._sound_row_height(key)

    def handle_event(self, event):
        """Returns the saved card_id once Enregistrer succeeds (Creator
        just refreshes the Collection on that, same "plain string, no
        tear/fuse bookkeeping" contract as MechanicsPanelUI's own
        Enregistrer -- this panel has no Dechirer/Coller/loot concept at
        all). None otherwise."""
        self._layout()
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self._clear_rect.collidepoint(event.pos):
            self.clear()
            return None

        # A pitch slider handle drag, same multi-event shape as
        # MechanicsPanelUI's own version -- (key, "lo"/"hi") identifies
        # which row/handle. Dragging "lo" past "hi" (or vice versa) clamps
        # against the OTHER handle's current value rather than crossing
        # it, so the range can never invert.
        if self._pitch_dragging is not None:
            key, handle = self._pitch_dragging
            if event.type == pygame.MOUSEMOTION:
                rects = self._pitch_rects.get(key)
                current = self.pitch_range.get(key, list(self.DEFAULT_PITCH_RANGE))
                if rects is not None:
                    value = self._pitch_x_to_value(rects["track"], event.pos[0])
                    if handle == "lo":
                        current[0] = min(value, current[1])
                    else:
                        current[1] = max(value, current[0])
                    self.pitch_range[key] = current
                return None
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._pitch_dragging = None
                return None

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        if self._save_rect.collidepoint(event.pos):
            return self._try_save()

        for key in self._sound_slot_keys():
            rects = self._sound_rects.get(key)
            if rects is None:
                continue
            if rects["prev"].collidepoint(event.pos):
                self._cycle_sound(key, -1)
                return None
            if rects["next"].collidepoint(event.pos):
                self._cycle_sound(key, 1)
                return None
            if rects["play"].collidepoint(event.pos):
                filename = self.card_sounds.get(key)
                if filename:
                    pitch = None
                    if self.pitch_enabled.get(key):
                        lo, hi = sorted(self.pitch_range.get(key, self.DEFAULT_PITCH_RANGE))
                        if hi > lo:
                            pitch = random.uniform(lo, hi)
                    SoundManager().play_path(filename, pitch=pitch)
                return None
            if self.card_sounds.get(key) and rects["pitch_toggle"].collidepoint(event.pos):
                self._toggle_pitch(key)
                return None
            pitch_rects = self._pitch_rects.get(key)
            if pitch_rects is not None:
                if pitch_rects["lo"].collidepoint(event.pos):
                    self._pitch_dragging = (key, "lo")
                    return None
                if pitch_rects["hi"].collidepoint(event.pos):
                    self._pitch_dragging = (key, "hi")
                    return None
                if pitch_rects["track"].collidepoint(event.pos):
                    # A click on the track itself (not precisely on either
                    # handle) jumps the NEAREST handle there and starts
                    # dragging it from there.
                    value = self._pitch_x_to_value(pitch_rects["track"], event.pos[0])
                    lo, hi = self.pitch_range.get(key, self.DEFAULT_PITCH_RANGE)
                    handle = "lo" if abs(value - lo) <= abs(value - hi) else "hi"
                    current = self.pitch_range.setdefault(key, list(self.DEFAULT_PITCH_RANGE))
                    if handle == "lo":
                        current[0] = min(value, current[1])
                    else:
                        current[1] = max(value, current[0])
                    self._pitch_dragging = (key, handle)
                    return None
        return None

    def render(self, screen):
        panel_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        self.border.draw(screen, panel_rect)

        if self.type_id is None and self.item_id is None:
            hint = self.small_font.render("Glisse une carte ici pour regler ses sons", True, (150, 150, 150))
            screen.blit(hint, (self.x + 20, self.y + 16))
            return

        self._layout()
        title = self.title_font.render(f"Sound Box -- {self.name}", True, self.CARD_TEXT_COLOR)
        screen.blit(title, (self.x + 20, self.y + 16))
        self.border.draw_centered_label(screen, self._clear_rect, self.small_font, "Vider")

        self._render_sounds(screen)

        self.border.draw_centered_label(screen, self._save_rect, self.font, "Enregistrer")
        if self.status_text:
            status_surface = self.small_font.render(self.status_text, True, self.CARD_TEXT_MUTED_COLOR)
            screen.blit(status_surface, (self.x + 20, self._save_rect.y - 20))

    def _render_sounds(self, screen):
        """One row per _sound_slot_keys entry, each a filename cycled from
        _available_sound_files (< / > buttons, "Aucun" at the None end), a
        Jouer button that previews it immediately via SoundManager.
        play_path (through the row's own pitch range if enabled), and --
        only once a real file is assigned -- a "Pitch" toggle. Once
        toggled on, a second line renders the double-handle range slider
        (see _render_pitch_slider). Straight port of MechanicsPanelUI's
        own version."""
        for key in self._sound_slot_keys():
            rects = self._sound_rects.get(key)
            if rects is None:
                continue
            label = self.small_font.render(self._sound_slot_label(key), True, self.CARD_TEXT_COLOR)
            screen.blit(label, (rects["label"].x, rects["label"].y + 4))
            self.border.draw_centered_label(screen, rects["prev"], self.small_font, "<")
            self.border.draw_centered_label(screen, rects["next"], self.small_font, ">")
            current = self.card_sounds.get(key)
            display = current if current else "Aucun"
            if len(display) > 12:
                display = display[:10] + "..."
            name_surface = self.small_font.render(display, True, self.CARD_TEXT_COLOR)
            screen.blit(name_surface, (rects["name"].x + 4, rects["name"].y + 4))
            self.border.draw_centered_label(screen, rects["play"], self.small_font, "Jouer")
            if current:
                pitch_label = "[x] Pitch" if self.pitch_enabled.get(key) else "[ ] Pitch"
                self.border.draw_centered_label(screen, rects["pitch_toggle"], self.small_font, pitch_label)

            pitch_rects = self._pitch_rects.get(key)
            if pitch_rects is not None:
                self._render_pitch_slider(screen, key, pitch_rects)

    def _render_pitch_slider(self, screen, key, rects):
        track = rects["track"]
        pygame.draw.rect(screen, (40, 40, 46), track, border_radius=4)
        lo, hi = self.pitch_range.get(key, self.DEFAULT_PITCH_RANGE)
        lo_x = self._pitch_value_to_x(track, lo)
        hi_x = self._pitch_value_to_x(track, hi)
        pygame.draw.rect(
            screen, (110, 150, 190), pygame.Rect(lo_x, track.y, max(1, hi_x - lo_x), track.height),
        )
        for handle in ("lo", "hi"):
            pygame.draw.rect(screen, (220, 220, 220), rects[handle], border_radius=2)
        readout = self.small_font.render(f"x{lo:.2f} - x{hi:.2f}", True, self.CARD_TEXT_COLOR)
        screen.blit(readout, (track.right + 8, track.centery - readout.get_height() / 2))
