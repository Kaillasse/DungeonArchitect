"""Multiplayer panel (M toggles, home only -- see Explorator.run()'s
event loop): browse sessions discovered on the LAN, join a manually-typed
address (host across a different network -- LAN UDP broadcast discovery
can never reach that), or host, or -- once connected -- show status and a
way to disconnect. A thin UI shell around Explorator.start_hosting/
join_session/stop_networking, which own all the actual networking; this
class just lays out buttons/a text field and a live discovery list. Lives
alongside inventory_ui.py as Explorator-only overlay UI, same "not shared
with Creator" separation.

No name-based ("type my friend's pseudo") discovery across different
networks: that needs a rendezvous/matchmaking server both sides can reach
over the public internet (the host registers a name -> address there, the
joiner looks it up) -- this project has no such server, hence the manual
IP[:port]/hostname field instead. A DDNS hostname (e.g. myname.duckdns.org)
typed into that same field gets you the closest thing to "a name" without
new infrastructure -- socket resolution already handles a hostname exactly
like a literal IP, no code difference."""

from __future__ import annotations

import pygame

from core.ui.widgets import BorderManager, TextInputBox
from core.network.discovery import SessionBrowser


def _parse_address(value):
    """"host" or "host:port" (host: a dotted IP or a resolvable hostname,
    e.g. a DDNS name -- socket.connect resolves either identically, no
    special-casing needed) -> (host, port), port defaulting to
    core.network.server.DEFAULT_PORT when omitted. None if empty or the
    port half isn't a plain integer. Deferred import of DEFAULT_PORT --
    core.network.server imports core.exploration.explorator at module
    scope, and this module is imported BY explorator.py, so a top-level
    import here would cycle (same reasoning NetworkSessionMixin's own
    start_hosting/join_session already follow)."""
    value = value.strip()
    if not value:
        return None
    if ":" in value:
        host, _, port_str = value.rpartition(":")
        if not host or not port_str.isdigit():
            return None
        return host, int(port_str)
    from core.network.server import DEFAULT_PORT
    return value, DEFAULT_PORT


class MultiplayerPanelUI:

    ROW_HEIGHT = 34
    ROW_SPACING = 6
    PANEL_WIDTH = 380
    ADDRESS_BUTTON_WIDTH = 110

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

        address_rect = self._manual_address_rect()
        self._address_input = TextInputBox(
            address_rect.x, address_rect.y, address_rect.width, address_rect.height, max_length=64,
        )

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

    def _top_rect(self):
        """The panel's first row -- "Heberger cette partie" when not connected,
        the connection status line when connected. Never both at once (see
        handle_event/render, each branches on `connected` first), so one rect
        serves both roles instead of two geometrically-identical methods."""
        return pygame.Rect(self.x, self.y + 34, self.PANEL_WIDTH, self.ROW_HEIGHT)

    def _disconnect_rect(self):
        return pygame.Rect(self.x, self.y + 34 + self.ROW_HEIGHT + 10, self.PANEL_WIDTH, self.ROW_HEIGHT)

    def _manual_address_hint_pos(self):
        return (self.x, self._top_rect().bottom + 10)

    def _manual_address_rect(self):
        """The typed IP[:port]/hostname field -- sits right below "Heberger"
        (and its own small_font hint label, see render), above the
        LAN-discovered entries. Only meaningful while not connected (see
        render/handle_event)."""
        width = self.PANEL_WIDTH - self.ADDRESS_BUTTON_WIDTH - 8
        return pygame.Rect(self.x, self._top_rect().bottom + 26, width, self.ROW_HEIGHT)

    def _manual_join_button_rect(self):
        address_rect = self._manual_address_rect()
        return pygame.Rect(address_rect.right + 8, address_rect.y, self.ADDRESS_BUTTON_WIDTH, self.ROW_HEIGHT)

    def _entries_top(self):
        return self._manual_address_rect().bottom + 14

    def _entry_rect(self, index):
        top = self._entries_top()
        return pygame.Rect(self.x, top + index * (self.ROW_HEIGHT + self.ROW_SPACING), self.PANEL_WIDTH, self.ROW_HEIGHT)

    def _bottom_content_y(self, connected, entry_count):
        if connected:
            return self._disconnect_rect().bottom
        if entry_count:
            return self._entry_rect(entry_count - 1).bottom
        return self._entries_top()

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

    def _attempt_manual_join(self, explorator):
        """Shared by the "Rejoindre" button and pressing Enter in the
        address field. Returns "connected" on success (same contract as
        handle_event), None otherwise -- status_text is set either way so
        the caller doesn't need to distinguish "bad address" from
        "connection failed" itself."""
        address = _parse_address(self._address_input.value)
        if address is None:
            self.status_text = "Adresse invalide -- attendu IP[:port] ou hote[:port]."
            return None
        client, error = explorator.join_session(*address)
        self.status_text = error or ""
        if client is not None:
            self.close()
            return "connected"
        return None

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
        connection attempt that just failed and updated status_text).

        The caller is expected to intercept K_ESCAPE (closes the whole
        panel) before this ever sees it -- see Explorator.run()/
        run_networked()'s own event loop -- so any KEYDOWN reaching here is
        routed straight into the address field, exactly like the in-game
        chat input's own "no separate focus click needed" shape."""
        if not self.is_open:
            return None

        connected = explorator.game_manager.network_client is not None

        if event.type == pygame.KEYDOWN:
            if connected:
                return None
            confirmed = self._address_input.handle_event(event)
            if confirmed:
                return self._attempt_manual_join(explorator)
            return None

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        if connected:
            if self._disconnect_rect().collidepoint(event.pos):
                explorator.stop_networking()
                self.close()
                return "disconnected"
            elif self._close_rect(True, 0).collidepoint(event.pos):
                self.close()
            return None

        if self._top_rect().collidepoint(event.pos):
            client, error = explorator.start_hosting()
            self.status_text = error or ""
            if client is not None:
                self.close()  # let the freshly-loaded world show through unobstructed
                return "connected"
            return None

        if self._manual_join_button_rect().collidepoint(event.pos):
            return self._attempt_manual_join(explorator)

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
            self.border.draw_centered_label(screen, self._top_rect(), self.font, status)
            self.border.draw_centered_label(screen, self._disconnect_rect(), self.font, "Deconnecter")
            self.border.draw_centered_label(screen, self._close_rect(True, 0), self.font, "Fermer")
            return

        self.border.draw_centered_label(screen, self._top_rect(), self.font, "Heberger cette partie")

        # Manual address -- the only way to reach a host on a different
        # network (LAN discovery below can never see it, see class
        # docstring). A DDNS hostname works here too, not just a raw IP.
        hint = self.small_font.render("Adresse de l'hote (IP[:port] ou nom d'hote) :", True, (180, 180, 180))
        screen.blit(hint, self._manual_address_hint_pos())
        self._address_input.render(screen)
        self.border.draw_centered_label(screen, self._manual_join_button_rect(), self.font, "Rejoindre")

        entries = self._entries()
        if not entries:
            hint = self.small_font.render("Recherche de parties sur le reseau local...", True, (180, 180, 180))
            screen.blit(hint, (self.x, self._entries_top()))
        for index, (ip, port, name, room_kind, room_name) in enumerate(entries):
            rect = self._entry_rect(index)
            label = f"Rejoindre {name} ({room_name})"
            self.border.draw_centered_label(screen, rect, self.font, label)

        self.border.draw_centered_label(screen, self._close_rect(False, len(entries)), self.font, "Fermer")

        if self.status_text:
            status_surface = self.small_font.render(self.status_text, True, (255, 140, 140))
            screen.blit(status_surface, (self.x, self._close_rect(False, len(entries)).bottom + 6))
