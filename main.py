"""Launch the dungeon editor. point d'entrée du programme"""

from __future__ import annotations
import sys
from pathlib import Path
import pygame
from core.game_manager import GameManager


# Allow "Run Python File" on core/main.py (script mode).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# === main.py ===



def main():
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    pygame.display.set_caption("DungeonArchitect")
    GameManager(screen).run()

if __name__ == "__main__":
    main()