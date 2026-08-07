"""Multiplayer panel (M toggles, home only -- see Explorator.run()'s
event loop): browse sessions discovered on the LAN and host or join one,
or -- once connected -- show status and a way to disconnect. A thin UI
shell around Explorator.start_hosting/join_session/stop_networking, which
own all the actual networking; this class just lays out buttons and a
live discovery list. Lives alongside inventory_ui.py as Explorator-only
overlay UI, same "not shared with Creator" separation."""

from __future__ import annotations

import pygame

from core.ui.widgets import BorderManager
from core.network.discovery import SessionBrowser


class MultiplayerPanelUI:

    ROW_HEIGHT = 34
    ROW_SPACING = 6
    PANEL_WIDTH = 380

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.border = BorderManager()
        self.title_font = pygame.font.SysFont("arial", 20)
        self.font = pygame.font.SysFont("arial", 16)
        self.small_font = pygame.font.SysFont("arial", 13)

        self.is_open = False
        self._browser = None  # discovery.SessionBrowser, only while open and not connected
        self.status_text = ""

    def open(self):
        self.is_open = True
        self.status_text = ""

    def close(self):
        self.is_open = False
        self._stop_browsing()

    def _stop_browsing(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def update(self, connected):
        """Call once a frame while open -- polls discovery only while not
        already connected (browsing is moot once you're already in a
        session; closes the socket the moment that stops being true so it
        doesn't linger bound for no reason)."""
        if not self.is_open:
            return
        if connected:
            self._stop_browsing()
            return
        if self._browser is None:
            self._browser = SessionBrowser()
        self._browser.poll()

    def _entries(self):
        return self._browser.entries() if self._browser is not None else []

    # -- layout --

    def _host_rect(self):
        return pygame.Rect(self.x, self.y + 34, self.PANEL_WIDTH, self.ROW_HEIGHT)

    def _status_rect(self):
        return pygame.Rect(self.x, self.y + 34, self.PANEL_WIDTH, self.ROW_HEIGHT)

    def _disconnect_rect(self):
        return pygame.Rect(self.x, self.y + 34 + self.ROW_HEIGHT + 10, self.PANEL_WIDTH, self.ROW_HEIGHT)

    def _entry_rect(self, index):
        top = self._host_rect().bottom + 14
        return pygame.Rect(self.x, top + index * (self.ROW_HEIGHT + self.ROW_SPACING), self.PANEL_WIDTH, self.ROW_HEIGHT)

    def _bottom_content_y(self, connected, entry_count):
        if connected:
            return self._disconnect_rect().bottom
        if entry_count:
            return self._entry_rect(entry_count - 1).bottom
        return self._host_rect().bottom + 24

    def _close_rect(self, connected, entry_count):
        return pygame.Rect(self.x, self._bottom_content_y(connected, entry_count) + 12, self.PANEL_WIDTH, 32)

    def panel_height(self, connected, entry_count):
        return self._close_rect(connected, entry_count).bottom - self.y

    def contains(self, pos, connected):
        if not self.is_open:
            return False
        rect = pygame.Rect(self.x, self.y, self.PANEL_WIDTH, self.panel_height(connected, len(self._entries())))
        return rect.collidepoint(pos)

    # -- interaction --

    def handle_event(self, event, explorator):
        """Directly drives Explorator's hosting/join/disconnect methods
        (rather than returning an action for a caller to interpret, like
        GeneratorPanelUI/RoomPanelUI do) -- this panel has no meaning
        decoupled from a live Explorator to act on, unlike those, which
        are also usable from Creator's static preview. Returns "connected"
        (start_hosting/join_session just succeeded -- game_manager.
        network_client is now set) or "disconnected" (stop_networking was
        just called -- game_manager.explorator is now a brand-new
        instance) so the caller's own run()/run_networked() loop can react
        the way it needs to (stop looping and let GameManager's dispatch
        pick up the change) -- this panel has no access to that loop's own
        `running` local to do it itself. None otherwise (e.g. Fermer, or a
        connection attempt that just failed and updated status_text)."""
        if not self.is_open or event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        connected = explorator.game_manager.network_client is not None

        if connected:
            if self._disconnect_rect().collidepoint(event.pos):
                explorator.stop_networking()
                self.close()
                return "disconnected"
            elif self._close_rect(True, 0).collidepoint(event.pos):
                self.close()
            return None

        if self._host_rect().collidepoint(event.pos):
            client, error = explorator.start_hosting()
            self.status_text = error or ""
            if client is not None:
                self.close()  # let the freshly-loaded world show through unobstructed
                return "connected"
            return None

        entries = self._entries()
        for index, (ip, port, name, room_kind, room_name) in enumerate(entries):
            if self._entry_rect(index).collidepoint(event.pos):
                client, error = explorator.join_session(ip, port)
                self.status_text = error or ""
                if client is not None:
                    self.close()
                    return "connected"
                return None

        if self._close_rect(False, len(entries)).collidepoint(event.pos):
            self.close()
        return None

    # -- rendering --

    def render(self, screen, explorator):
        if not self.is_open:
            return

        connected = explorator.game_manager.network_client is not None
        title = self.title_font.render("Multijoueur", True, (255, 255, 255))
        screen.blit(title, (self.x, self.y))

        if connected:
            hosting = explorator.game_manager._game_server is not None
            if hosting:
                status = f"Vous hebergez sur le port {explorator.game_manager._game_server._server_socket.getsockname()[1]} -- {len(explorator.players)} joueur(s) connecte(s)."
            else:
                status = f"Connecte -- {len(explorator.players)} joueur(s) dans la partie."
            self.border.draw_centered_label(screen, self._status_rect(), self.font, status)
            self.border.draw_centered_label(screen, self._disconnect_rect(), self.font, "Deconnecter")
            self.border.draw_centered_label(screen, self._close_rect(True, 0), self.font, "Fermer")
            return

        self.border.draw_centered_label(screen, self._host_rect(), self.font, "Heberger cette partie")

        entries = self._entries()
        if not entries:
            hint = self.small_font.render("Recherche de parties sur le reseau local...", True, (180, 180, 180))
            screen.blit(hint, (self.x, self._host_rect().bottom + 14))
        for index, (ip, port, name, room_kind, room_name) in enumerate(entries):
            rect = self._entry_rect(index)
            label = f"Rejoindre {name} ({room_name})"
            self.border.draw_centered_label(screen, rect, self.font, label)

        self.border.draw_centered_label(screen, self._close_rect(False, len(entries)), self.font, "Fermer")

        if self.status_text:
            status_surface = self.small_font.render(self.status_text, True, (255, 140, 140))
            screen.blit(status_surface, (self.x, self._close_rect(False, len(entries)).bottom + 6))
