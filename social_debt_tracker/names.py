"""Identity helpers for contact names.

Matching is accent-insensitive and case-insensitive. The key is a short hash of
the normalized name so Telegram callback buttons stay inside the 64-byte limit.
"""

from __future__ import annotations

import hashlib
import unicodedata

_KEY_LENGTH = 12


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_accents.casefold().split())


def contact_key(name: str) -> str:
    normalized = normalize_name(name)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:_KEY_LENGTH]
