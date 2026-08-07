"""Per-profile "home" room: a hub the player boots straight into (see
Menu._redirect_to_home), with Explo<->Creator switching driven by zoom
level instead of TAB while it's the active room (see Creator._is_home_room
/ Explorator._check_home_zoom_switch). This is the item that stayed
labeled "Phase 6c" in CLAUDE.md's original scope after 6b/6c were
redefined -- see the Roadmap's "Multiplayer refactor" section."""

from __future__ import annotations

from core.data.profile_manager import _sanitize_name
from core.data.ressources import ROOMS_DIRECTORY
from core.world.dungeon import Dungeon

HOME_ROOM_PREFIX = "home_"

# Camera's default zoom range is 0.5..4.0 (geometric mid ~1.41); both
# Creator's and Explorator's cameras start at zoom=1.0, already safely
# inside the Creator band below, so entering home for the very first time
# needs no explicit zoom seed. The gap between the two thresholds is a
# dead zone so a single wheel notch (Camera.zoom_at steps by x1.2/x0.8)
# can't flip the state back and forth right at a boundary.
ZOOM_ENTER_EXPLORATION = 1.6  # crossing at/above this while in Creator -> switch to Exploration
ZOOM_ENTER_CREATOR = 1.2  # crossing at/below this while in Exploration -> switch to Creator


def home_room_name(player_name: str) -> str:
    return f"{HOME_ROOM_PREFIX}{_sanitize_name(player_name)}"


def ensure_home_room(player_name: str) -> str:
    """Creates <player>'s home room on disk if it doesn't exist yet -- a
    blank Dungeon, the same starting state "+ Nouvelle salle" (RoomPanelUI's
    own new-room flow) leaves a room in -- so home is immediately visible
    in list_rooms()/RoomBrowser like any other saved room instead of only
    materializing once the player happens to hit Sauvegarder. Returns the
    room name either way."""
    name = home_room_name(player_name)
    path = ROOMS_DIRECTORY / f"{name}.json"
    if not path.exists():
        Dungeon().save_to_json(name)
    return name


def wants_exploration(zoom: float) -> bool:
    return zoom >= ZOOM_ENTER_EXPLORATION


def wants_creator(zoom: float) -> bool:
    return zoom <= ZOOM_ENTER_CREATOR
