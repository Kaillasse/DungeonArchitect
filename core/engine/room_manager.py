
from core.world.dungeon import Dungeon
from core.data.ressources import ROOMS_DIRECTORY

class RoomManager:

    def __init__(self, grid: Dungeon):
        self.rooms = grid
        self.grid = grid
        self.current_room = None

    def scan(self):
        rooms = sorted(ROOMS_DIRECTORY.glob("*.json"))
        return [room.stem for room in rooms]

    def save_room(self):

        print("\n===== ENREGISTRER UNE SALLE =====")
        name = input("Nom de la salle : ").strip()

        if not name:
            print("Nom invalide.")
            return

        self.grid.save_to_json(name)
        self.current_room = name

        print(f"Salle '{name}' enregistrée.")

    def load_room(self):

        print("\n===== CHARGER UNE SALLE =====")

        rooms = self.scan()

        if not rooms:
            print("Aucune salle enregistrée.")
            return

        print("Salles disponibles :")
        for room in rooms:
            print(" -", room)

        name = input("Salle à charger : ").strip()

        if name not in rooms:
            print("Salle introuvable.")
            return

        self.grid.load_from_json(name)
        self.current_room = name

        print(f"Salle '{name}' chargée.")

    def delete_room(self):

        print("\n===== SUPPRIMER UNE SALLE =====")

        rooms = self.scan()

        if not rooms:
            print("Aucune salle enregistrée.")
            return

        print("Salles disponibles :")
        for room in rooms:
            print(" -", room)

        name = input("Salle à supprimer : ").strip()

        if name not in rooms:
            print("Salle introuvable.")
            return

        path = ROOMS_DIRECTORY / f"{name}.json"
        path.unlink()

        if self.current_room == name:
            self.current_room = None

        print(f"Salle '{name}' supprimée.")

    def list_rooms(self):

        rooms = self.scan()

        print("\n===== SALLES DISPONIBLES =====")

        if not rooms:
            print("(aucune)")
            return

        for room in rooms:
            marker = " <- courante" if room == self.current_room else ""
            print(f"- {room}{marker}")