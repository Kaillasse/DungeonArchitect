"""Wire protocol for the client/server transport layer (multiplayer Phase 3):
newline-delimited JSON over a TCP socket, one message per line -- the
thinnest layer that can carry "type" + freeform fields. No auth, no framing
beyond the newline, no schema versioning -- see CLAUDE.md's Phase 3 section
for why (trusted small co-op deployment, transport-layer scope only).

Client -> server: "join" (name), "input" (one player's InputState, plus any
one-shot actions buffered since the last send), "pvp_toggle" (F4 -- must be
server-authoritative since it gates real damage).

Server -> client: "welcome" (assigned player_id + which room/donjon to load
locally), "snapshot" (every tick -- see build_snapshot), "leave" (a session
disconnected)."""

from __future__ import annotations

import json

from core.engine.input import InputState

MSG_JOIN = "join"
MSG_INPUT = "input"
MSG_PVP_TOGGLE = "pvp_toggle"

MSG_WELCOME = "welcome"
MSG_SNAPSHOT = "snapshot"
MSG_LEAVE = "leave"


def encode(msg_type: str, **fields) -> bytes:
    """One JSON object + newline, ready to write to a socket file."""
    return encode_dict({"type": msg_type, **fields})


def encode_dict(payload: dict) -> bytes:
    """Same framing as encode(), for a dict already carrying its own "type"
    key (build_snapshot's return value) -- avoids stripping it back out just
    to hand it to encode(msg_type, **fields) instead."""
    return (json.dumps(payload) + "\n").encode("utf-8")


def decode(line) -> dict:
    """Parses one previously-encode()'d line (str or bytes -- sockets in
    this codebase are read in binary mode) back into its dict -- callers
    switch on payload["type"]."""
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    return json.loads(line)


def input_state_to_fields(input_state: InputState) -> dict:
    return {
        "move_x": input_state.move_direction.x,
        "move_y": input_state.move_direction.y,
        "running": input_state.running,
        "requested_actions": list(input_state.requested_actions),
    }


def input_state_from_fields(fields: dict) -> InputState:
    import pygame

    return InputState(
        move_direction=pygame.Vector2(fields.get("move_x", 0.0), fields.get("move_y", 0.0)),
        running=bool(fields.get("running", False)),
        requested_actions=tuple(fields.get("requested_actions", ())),
    )


def _iter_dungeons(explorator):
    """(room_ref, dungeon) for every room a full-state snapshot needs to
    cover -- None (single-room mode) or every room in the assembly (not just
    the active floor: Explorator.render already draws floors below/above
    tinted, so their live entity/object state matters too, see
    DungeonAssembly.render). Simplest-correct choice for a small dungeon --
    see CLAUDE.md's flagged Phase 3 simplifications."""
    if explorator.assembly is not None:
        for room in explorator.assembly.rooms:
            yield room.index, room.dungeon
    else:
        yield None, explorator.dungeon


def build_snapshot(explorator, tick: int, terrain_versions: dict) -> dict:
    """Full authoritative world state for one server tick. `terrain_versions`
    is the server's own {room_ref: last_sent_version} bookkeeping -- mutated
    in place; a room whose Dungeon.terrain_version has advanced since the
    last call gets its raw grids included this tick (destroy_area is rare,
    so this stays cheap in practice) so a client can just assign them
    locally instead of replaying the destruction algorithm."""
    players = []
    for session in explorator.players.values():
        player = session.player
        players.append({
            "id": session.player_id,
            "x": player.position.x, "y": player.position.y,
            "direction": player.direction,
            "animation": player.animation,
            "action": player.action,
            "frame": player.frame,
            "health": player.health,
        })

    animals, enemies, pickups, objects, dynamites, explosions, terrain = [], [], [], [], [], [], []

    for room_ref, dungeon in _iter_dungeons(explorator):
        for animal in dungeon.animal_manager.animals:
            animals.append({
                "id": id(animal), "room": room_ref, "animal_type": animal.animal_type,
                "x": animal.position.x, "y": animal.position.y, "state": animal.state,
                "dir_x": animal.direction.x, "dir_y": animal.direction.y,
                "flip": animal.flip, "frame": animal.frame, "health": animal.health,
            })

        for enemy in dungeon.enemy_manager.enemies:
            enemies.append({
                "id": id(enemy), "room": room_ref, "enemy_type": enemy.enemy_type,
                "x": enemy.position.x, "y": enemy.position.y, "state": enemy.state,
                "dir_x": enemy.direction.x, "dir_y": enemy.direction.y,
                "flip": enemy.flip, "frame": enemy.frame,
                "health": enemy.health, "alive": enemy.alive,
            })

        for pickup in dungeon.pickup_manager.pickups:
            pickups.append({
                "id": id(pickup), "room": room_ref, "kind": "currency",
                "currency_type": pickup.currency_type,
                "x": pickup.position.x, "y": pickup.position.y,
                "state": pickup.state, "frame": pickup.frame,
            })
        for item_pickup in dungeon.pickup_manager.item_pickups:
            pickups.append({
                "id": id(item_pickup), "room": room_ref, "kind": "item",
                "item_id": item_pickup.item.item_id, "slot": item_pickup.slot,
                "x": item_pickup.position.x, "y": item_pickup.position.y,
            })

        for index, obj in enumerate(dungeon.object_manager.objects):
            objects.append({
                "room": room_ref, "index": index,
                "activated": obj.get("activated", False),
                "open": obj.get("open", False),
                "frame": obj.get("frame", 0),
            })

        for dynamite in dungeon.projectile_manager.dynamites:
            dynamites.append({
                "id": id(dynamite), "room": room_ref,
                "x": dynamite.position.x, "y": dynamite.position.y, "frame": dynamite.frame,
            })
        for explosion in dungeon.projectile_manager.explosions:
            explosions.append({
                "id": id(explosion), "room": room_ref,
                "x": explosion.position.x, "y": explosion.position.y, "frame": explosion.frame,
            })

        if terrain_versions.get(room_ref) != dungeon.terrain_version:
            terrain_versions[room_ref] = dungeon.terrain_version
            terrain.append({
                "room": room_ref,
                "logical_grid": dungeon.logical_grid,
                "sprite_grid": dungeon.sprite_grid,
            })

    return {
        "type": MSG_SNAPSHOT, "tick": tick,
        "pvp_enabled": explorator.pvp_enabled, "victory": explorator.victory,
        "game_over": explorator.game_manager.state.name != "EXPLORATION",
        "players": players, "animals": animals, "enemies": enemies,
        "pickups": pickups, "objects": objects,
        "dynamites": dynamites, "explosions": explosions,
        "terrain": terrain,
    }
