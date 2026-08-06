"""Launch the dungeon editor. point d'entrée du programme"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path
import pygame
from core.engine.game_manager import GameManager
from core.data.settings import load_settings


# Allow "Run Python File" on core/main.py (script mode).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# === main.py ===

DEFAULT_PORT = 5555


def parse_args():
    """No flags at all is today's fully local game, byte-for-byte -- both
    --server and --connect are strictly opt-in (multiplayer Phase 3)."""
    parser = argparse.ArgumentParser(description="Dungeon Architect")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--server", action="store_true", help="Run a headless authoritative server (no window)")
    mode.add_argument("--connect", metavar="HOST:PORT", help="Connect to a running server as a network client")

    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Server: port to listen on (default {DEFAULT_PORT})")
    room_source = parser.add_mutually_exclusive_group()
    room_source.add_argument("--room", help="Server: room to host, from assets/rooms")
    room_source.add_argument("--donjon", help="Server: donjon to host, from assets/donjons")
    parser.add_argument("--name", default="player", help="Client: display name sent to the server on join")

    args = parser.parse_args()
    if args.server and not (args.room or args.donjon):
        parser.error("--server requires --room NAME or --donjon NAME")
    return args


def run_local():
    pygame.init()
    settings = load_settings()
    size, flags = settings.display_mode()
    screen = pygame.display.set_mode(size, flags)
    pygame.display.set_caption("DungeonArchitect")
    GameManager(screen, settings).run()


def run_server(args):
    from core.network.server import GameServer

    server = GameServer(args.port, room=args.room, donjon=args.donjon)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[server] shutting down")


def run_client(args):
    from core.network.client import NetworkClient
    from core.engine.gamestate import GameState

    host, _, port_str = args.connect.partition(":")
    port = int(port_str) if port_str else DEFAULT_PORT

    pygame.init()
    settings = load_settings()
    size, flags = settings.display_mode()
    screen = pygame.display.set_mode(size, flags)
    pygame.display.set_caption("DungeonArchitect")

    game_manager = GameManager(screen, settings)
    game_manager.state = GameState.EXPLORATION
    explorator = game_manager.explorator

    client = NetworkClient(host, port, name=args.name)
    try:
        welcome = client.wait_for_welcome()
    except TimeoutError as exc:
        print(f"[client] {exc}")
        client.close()
        return

    if welcome["room_kind"] == "donjon":
        explorator.open_donjon(welcome["room_name"])
    else:
        explorator.open_room(welcome["room_name"])
    explorator.adopt_local_player_id(welcome["player_id"])

    try:
        explorator.run_networked(client)
    finally:
        client.close()


def main():
    args = parse_args()

    if args.server:
        run_server(args)
    elif args.connect:
        run_client(args)
    else:
        run_local()


if __name__ == "__main__":
    main()
