"""Local account system: a pseudo + password gate that decides which
account's data (see core.data.ressources.set_active_account -- rooms/
donjons live per-account from here on) a session can access. Not a
security-grade system -- this is a single local machine, no network
identity yet (see the multiplayer pseudo+tag directory discussed
separately, still unbuilt) -- but a password is still never stored in
plain text, since that's cheap to get right regardless of threat model.

One account = one file, assets/accounts/<pseudo>.json (credentials only --
the account's own DATA directory is assets/accounts/<pseudo>/, a sibling,
see ressources.account_directory). Mirrors core.data.profile_manager's own
"stateless converter, tolerant load" shape."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from pathlib import Path

from core.data.ressources import ACCOUNTS_DIRECTORY

_SAFE_PSEUDO_RE = re.compile(r"[^A-Za-z0-9_-]+")
MAX_PSEUDO_LENGTH = 32
# High enough to be a real cost for brute-forcing, low enough not to make
# login feel slow on ordinary hardware -- same ballpark Django/most modern
# defaults use for PBKDF2-SHA256.
_PBKDF2_ITERATIONS = 260_000


class AccountError(ValueError):
    """Raised by create_account for a bad pseudo/password/already-taken
    pseudo -- a ValueError subclass so existing `except ValueError` callers
    (if any ever wrap this) keep working, but callers can also catch this
    specifically."""


def _sanitize_pseudo(pseudo) -> str:
    """Restricts a pseudo to [a-z0-9_-], capped in length -- same convention
    as profile_manager._sanitize_name/room_manager._sanitize_room_name,
    since a pseudo is also used directly as a filename and, via
    ressources.account_directory, a directory name. Lowercased so "Thib"
    and "thib" are always the same account -- NTFS/APFS hide this on a
    single Windows/Mac dev machine (both resolve to the same file/directory
    already), but the raw-cased version would silently split into two
    accounts on a case-sensitive filesystem (Linux) or once account listing
    ever compares pseudos as plain strings."""
    return _SAFE_PSEUDO_RE.sub("_", str(pseudo or "").strip().lower())[:MAX_PSEUDO_LENGTH]


def _account_path(pseudo: str) -> Path:
    return ACCOUNTS_DIRECTORY / f"{_sanitize_pseudo(pseudo)}.json"


def _hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt_hex = salt_hex or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), _PBKDF2_ITERATIONS,
    )
    return salt_hex, digest.hex()


def account_exists(pseudo: str) -> bool:
    return _account_path(pseudo).exists()


def create_account(pseudo: str, password: str) -> str:
    """Creates a brand-new account. Raises AccountError (never writes
    anything) if the sanitized pseudo is empty, the password is empty, or
    the pseudo is already taken. Returns the sanitized pseudo on success --
    the caller (Menu) still needs to call ressources.set_active_account
    with it and ressources.apply_starter_pack_to_account to seed its rooms
    directory."""
    safe_pseudo = _sanitize_pseudo(pseudo)
    if not safe_pseudo:
        raise AccountError("Pseudo invalide.")
    if not password:
        raise AccountError("Mot de passe requis.")
    if account_exists(safe_pseudo):
        raise AccountError("Ce pseudo est deja pris.")

    salt_hex, password_hash = _hash_password(password)
    payload = {"version": 1, "pseudo": safe_pseudo, "salt": salt_hex, "password_hash": password_hash}
    with _account_path(safe_pseudo).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return safe_pseudo


def verify_login(pseudo: str, password: str) -> str | None:
    """The sanitized pseudo on a correct password, None on an unknown
    pseudo, a corrupt account file, or a wrong password -- deliberately the
    same None for all three (no "pseudo doesn't exist" vs "wrong password"
    distinction surfaced to the caller), so a login screen can't be used to
    enumerate which pseudos are already registered."""
    path = _account_path(pseudo)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None

    salt_hex = payload.get("salt")
    expected_hash = payload.get("password_hash")
    if not salt_hex or not expected_hash:
        return None

    _, actual_hash = _hash_password(password, salt_hex)
    if not hmac.compare_digest(actual_hash, expected_hash):
        return None
    return payload.get("pseudo") or _sanitize_pseudo(pseudo)
