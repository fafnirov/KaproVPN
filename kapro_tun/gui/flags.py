"""Country code / flag-emoji helpers for config cards and pickers.

Most VPN providers prefix server names with a 2-letter country code —
"NL Server · VLESS ...", "RU SPB · trojan", "[DE] Frankfurt".
We pluck that prefix and render the corresponding Unicode flag.

If we can't find a country code in the name, falls back to "" — the UI
just shows the name without a flag, no harm done.

(No live geoip lookup: it'd cost an HTTP call per config every time the
picker opens, and the name-based heuristic is right >95% of the time
for share-URL formats people actually use.)
"""
from __future__ import annotations

import re
from functools import lru_cache

from ..core.parser import ProxyConfig


# Match leading 2-letter uppercase code, optionally preceded by a flag emoji
# that some providers already embed. Stops at space / dash / underscore / dot.
_LEADING_CC = re.compile(r"^[☀-➿\U0001F1E6-\U0001F1FF\s]*([A-Z]{2})[\s\-_.,/|]")
# Or in brackets: [RU], (DE)
_BRACKET_CC = re.compile(r"[\[\(]([A-Z]{2})[\]\)]")


@lru_cache(maxsize=128)
def country_code(name: str) -> str:
    """Return the 2-letter ISO country code parsed from a config name, or ''."""
    if not name:
        return ""
    m = _LEADING_CC.match(name)
    if m:
        return m.group(1)
    m = _BRACKET_CC.search(name)
    if m:
        return m.group(1)
    return ""


@lru_cache(maxsize=128)
def code_to_flag(code: str) -> str:
    """ISO 2-letter code → Unicode flag emoji ('NL' → 🇳🇱).

    Returns '' if the code isn't two ASCII letters.
    """
    code = (code or "").upper()
    if len(code) != 2 or not code.isalpha() or not code.isascii():
        return ""
    base = ord("\U0001F1E6")  # REGIONAL INDICATOR SYMBOL LETTER A
    return chr(base + ord(code[0]) - ord("A")) + chr(base + ord(code[1]) - ord("A"))


def flag_for_config(cfg: ProxyConfig) -> str:
    """Best-effort flag emoji for a saved config; '' if undetermined."""
    return code_to_flag(country_code(cfg.name))


def prefix_with_flag(cfg: ProxyConfig, name: str = None) -> str:
    """Prepend `<flag>  ` to the given name (defaults to cfg.name)."""
    name = name if name is not None else cfg.name
    flag = flag_for_config(cfg)
    return f"{flag}  {name}" if flag else name
