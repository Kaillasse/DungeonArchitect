"""Per-profile "home" room: a hub the player boots straight into
(Menu._redirect_to_home), with Explo<->Creator switching driven by zoom
level instead of TAB while it's the active room (Creator._is_home_room /
Explorator._check_home_zoom_switch)."""

from __future__ import annotations

from core.data.profile_manager import _sanitize_name
from core.data.ressources import rooms_directory
from core.world.dungeon import Dungeon

HOME_ROOM_PREFIX = "home_"

# Camera's default zoom range is 0.5..4.0; both Creator's and Explorator's
# cameras start at zoom=1.0, already inside the Creator band below. The gap
# between the two thresholds is a dead zone so a single wheel notch
# (Camera.zoom_at steps x1.2/x0.8) can't flip state back and forth at a boundary.
ZOOM_ENTER_EXPLORATION = 1.6  # crossing at/above this while in Creator -> switch to Exploration
ZOOM_ENTER_CREATOR = 1.2  # crossing at/below this while in Exploration -> switch to Creator


def home_room_name(player_name: str) -> str:
    return f"{HOME_ROOM_PREFIX}{_sanitize_name(player_name)}"


def ensure_home_room(player_name: str) -> str:
    """Creates <player>'s home room on disk if it doesn't exist yet -- a
    blank Dungeon, same as "+ Nouvelle salle" leaves a room in -- so home is
    immediately visible in list_rooms()/RoomBrowser instead of only
    materializing once the player hits Sauvegarder. Returns the room name either way."""
    name = home_room_name(player_name)
    path = rooms_directory() / f"{name}.json"
    if not path.exists():
        Dungeon().save_to_json(name)
    return name


def wants_exploration(zoom: float) -> bool:
    return zoom >= ZOOM_ENTER_EXPLORATION


def wants_creator(zoom: float) -> bool:
    return zoom <= ZOOM_ENTER_CREATOR
