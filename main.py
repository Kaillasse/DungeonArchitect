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
# No more --server/--connect flags: hosting/joining a multiplayer session
# now happens in-game, from the player's own home (M key, see
# core.exploration.multiplayer_ui.MultiplayerPanelUI and
# Explorator.start_hosting/join_session) instead of a separate CLI launch
# mode -- GameServer/NetworkClient/run_networked are unchanged underneath,
# just driven from there now instead of from here.
#
# --give-card is a different kind of CLI flag from those retired ones: it's
# not a launch mode, just a one-shot local dev/test utility that mutates a
# saved Profile's card_collection (see core.data.cards/core.data.
# profile_manager) directly on disk, no game session or pygame window
# involved at all -- see _apply_give_card below.


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Dungeon Architect")
    parser.add_argument(
        "--give-card", metavar="CARD_ID", default=None,
        help="Ajoute des exemplaires d'une carte au profil local (test), sans lancer le jeu.",
    )
    parser.add_argument(
        "--give-all-cards", action="store_true",
        help="Ajoute des exemplaires de CHAQUE carte connue au profil local (test de toute la collection), sans lancer le jeu.",
    )
    parser.add_argument(
        "--admingod", action="store_true",
        help="Donne au profil local une collection complete et illimitee (le stock affiche ne baisse jamais en jeu), sans lancer le jeu.",
    )
    parser.add_argument("--count", type=int, default=1, help="Nombre d'exemplaires a donner par carte (defaut 1).")
    parser.add_argument(
        "--player", default=None,
        help="Nom du profil cible (defaut : local_player_name des reglages sauvegardes).",
    )
    return parser


def _apply_give_card(args):
    """Mutates a Profile's card_collection directly via ProfileManager/
    CardManager -- neither has any real pygame dependency (see the Card
    system plan's own exploration notes), so this never needs pygame.init()
    or a display, unlike every other path through main()."""
    from core.data.cards import CardManager
    from core.data.profile_manager import ProfileManager

    player = args.player or load_settings().local_player_name
    if not player:
        print("Aucun joueur local configure -- passe --player <nom>.")
        return

    card = CardManager().load(args.give_card)
    if card is None:
        print(f"Carte inconnue : {args.give_card}")
        return

    manager = ProfileManager()
    profile = manager.load(player)
    profile.card_collection[args.give_card] = profile.card_collection.get(args.give_card, 0) + args.count
    manager.save(profile)
    print(f"{player} possede maintenant {profile.card_collection[args.give_card]}x {card.name} ({args.give_card}).")


def _apply_give_all_cards(args):
    """Same idea as _apply_give_card, but every card CardManager knows
    about at once -- meant for quickly getting a full test collection
    (place/verify every card type) instead of calling --give-card once per
    id by hand."""
    from core.data.cards import CardManager
    from core.data.profile_manager import ProfileManager

    player = args.player or load_settings().local_player_name
    if not player:
        print("Aucun joueur local configure -- passe --player <nom>.")
        return

    manager = ProfileManager()
    profile = manager.load(player)
    card_manager = CardManager()
    card_ids = card_manager.list_known_card_ids()
    for card_id in card_ids:
        profile.card_collection[card_id] = profile.card_collection.get(card_id, 0) + args.count
    manager.save(profile)
    print(f"{player} a recu {args.count}x chacune des {len(card_ids)} cartes connues.")


def _apply_admingod(args):
    """Same shape as _apply_give_all_cards, plus a persisted Profile.admingod
    flag that Creator's card-consumption gates and CardPanelUI's own
    display check to bypass card_collection entirely (see
    core.data.profile_manager.ADMINGOD_STOCK's own comment) -- the seeded
    count here is mostly cosmetic (so a fresh save already reads as
    "basically infinite" instead of 0 before the profile is ever touched
    in-game), the actual never-runs-out guarantee comes from that bypass,
    not from the number being large."""
    from core.data.cards import CardManager
    from core.data.profile_manager import ProfileManager, ADMINGOD_STOCK

    player = args.player or load_settings().local_player_name
    if not player:
        print("Aucun joueur local configure -- passe --player <nom>.")
        return

    manager = ProfileManager()
    profile = manager.load(player)
    card_manager = CardManager()
    card_ids = card_manager.list_known_card_ids()
    for card_id in card_ids:
        profile.card_collection[card_id] = ADMINGOD_STOCK
    profile.admingod = True
    manager.save(profile)
    print(f"{player} est desormais en admingod : {len(card_ids)} cartes, stock illimite.")


def main():
    args = build_arg_parser().parse_args()

    if args.admingod:
        _apply_admingod(args)
        return

    if args.give_all_cards:
        _apply_give_all_cards(args)
        return

    if args.give_card is not None:
        _apply_give_card(args)
        return

    pygame.init()
    settings = load_settings()
    size, flags = settings.display_mode()
    screen = pygame.display.set_mode(size, flags)
    pygame.display.set_caption("DungeonArchitect")
    GameManager(screen, settings).run()


if __name__ == "__main__":
    main()
