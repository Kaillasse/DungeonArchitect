"""Centralized font loading -- the single place every panel/widget in the
project should get a pygame.font.Font from, instead of each one calling
pygame.font.SysFont("arial", ...) on its own (44 such calls across 18
files, found 2026-08-19 while preparing this). Three roles, matching what
the user wants to visually separate: "title" (panel headers), "button"
(clickable labels), "text" (everything else -- body copy, hints, detail
lines).

Each role maps to ONE font file, assets/ui/<role>.ttf (or .otf, tried
second) -- drop a file in under that name and every caller picks it up
automatically, nothing else to change. Until a role's file exists, get_font
falls back to pygame.font.SysFont("arial", size, bold=bold) -- the exact
same font every call site already uses today -- so switching a call site
to this module is a no-op visually until the real files are actually in
place. That's deliberate: the migration of existing call sites can happen
NOW, safely, before the user has even picked which fonts to use.

Migrating an existing call site: replace
    pygame.font.SysFont("arial", 15)
with
    core.ui.fonts.get_font("text", 15)
(or "title"/"button", whichever role that particular font is actually
used for -- a judgment call per call site, not a blind rename, since
today's self.font is routinely used for BOTH button labels and plain text
within the same panel)."""

import pygame

from core.data.ressources import PROJECT_ROOT

FONT_DIR = PROJECT_ROOT / "assets" / "ui"

# Filename stem (no extension) expected for each role. Tries ROLE.ttf,
# then ROLE.otf, in that order -- both are real pygame.font.Font-loadable
# formats, ttf is just the more common one to find for free/Google-Fonts-
# style faces.
_ROLE_FILENAMES = {
    "title": "title",
    "button": "button",
    "text": "text",
}

# TEMPORARY (2026-08-19, confirmed with the user): title.ttf/button.ttf --
# the first 2 free fonts picked -- render worse (too big/ugly) than
# text.ttf, so every role routes through text.ttf for now regardless of
# what it's actually tagged as. Every call site's own role ("title"/
# "button"/"text") is untouched either way -- flip this back to False
# once better title/button fonts are chosen, nothing else needs
# re-migrating.
_FORCE_TEXT_FONT = True

# Also 2026-08-19: text.ttf itself renders noticeably smaller than Arial
# used to at the same nominal pixel size (a property of that particular
# font file's own metrics, not something any call site's requested size
# got changed to cause -- see get_font's own docstring). User confirmed
# the first +30% pass on "text" alone read better and asked for +50% on
# everything next, now that every role resolves to the same text.ttf file
# anyway (see _FORCE_TEXT_FONT) -- so this is a flat default rather than
# a per-role table. Bump _SIZE_SCALE_DEFAULT directly for further
# across-the-board tuning.
_SIZE_SCALE_DEFAULT = 1.5
_SIZE_SCALE = {}

# (role, size, bold) -> Font. A Font is tied to one exact pixel size at
# load time (unlike a CSS-style scalable font), so every distinct size a
# caller asks for gets its own cached instance -- still just one disk
# read/parse per (role, size) actually used, not one per render() call.
_cache = {}


def _resolve_path(role):
    if _FORCE_TEXT_FONT:
        role = "text"
    stem = _ROLE_FILENAMES.get(role)
    if stem is None:
        return None
    for ext in (".ttf", ".otf"):
        candidate = FONT_DIR / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def get_font(role, size, bold=False):
    """A pygame.font.Font for `role` ("title"/"button"/"text") at `size`
    pixels (see _SIZE_SCALE for why the actual loaded size can differ from
    what's passed in), cached per (role, size, bold). Falls back to
    pygame.font.SysFont("arial", size, bold=bold) -- today's look,
    unchanged -- for any role whose own assets/ui/<role>.ttf|.otf file
    doesn't exist yet (or, while _FORCE_TEXT_FONT is set, if text.ttf
    itself doesn't exist). Never raises for an unknown role -- falls back
    the same way a missing file does, so a typo'd role name degrades
    quietly instead of crashing whatever panel just tried to render."""
    scaled_size = max(1, round(size * _SIZE_SCALE.get(role, _SIZE_SCALE_DEFAULT)))
    key = (role, scaled_size, bold)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    path = _resolve_path(role)
    if path is not None:
        font = pygame.font.Font(str(path), scaled_size)
        font.set_bold(bold)
    else:
        font = pygame.font.SysFont("arial", scaled_size, bold=bold)

    _cache[key] = font
    return font


def clear_cache():
    """Drops every cached Font -- call after dropping a new/replacement
    file into assets/ui/ (e.g. from the in-app font-picker this is meant
    to eventually support) so the next get_font() call for that role
    re-resolves the path and loads the new file instead of keeping
    whatever was cached from before, including the SysFont fallback if a
    role's file didn't exist yet the first time it was requested."""
    _cache.clear()
