"""Deterministic Uzbek name normalization and matching service."""

from __future__ import annotations

import re

CYRILLIC_TO_LATIN: dict[str, str] = {
    "А": "A", "а": "a",
    "Б": "B", "б": "b",
    "В": "V", "в": "v",
    "Г": "G", "г": "g",
    "Д": "D", "д": "d",
    "Е": "E", "е": "e",
    "Ё": "Yo", "ё": "yo",
    "Ж": "J", "ж": "j",
    "З": "Z", "з": "z",
    "И": "I", "и": "i",
    "Й": "Y", "й": "y",
    "К": "K", "к": "k",
    "Л": "L", "л": "l",
    "М": "M", "м": "m",
    "Н": "N", "н": "n",
    "О": "O", "о": "o",
    "П": "P", "п": "p",
    "Р": "R", "р": "r",
    "С": "S", "с": "s",
    "Т": "T", "т": "t",
    "У": "U", "у": "u",
    "Ф": "F", "ф": "f",
    "Х": "X", "х": "x",
    "Ц": "Ts", "ц": "ts",
    "Ч": "Ch", "ч": "ch",
    "Ш": "Sh", "ш": "sh",
    "Щ": "Sh", "щ": "sh",
    "Ъ": "", "ъ": "",
    "Ы": "I", "ы": "i",
    "Ь": "", "ь": "",
    "Э": "E", "э": "e",
    "Ю": "Yu", "ю": "yu",
    "Я": "Ya", "я": "ya",
    "Ғ": "G", "ғ": "g",
    "Қ": "K", "қ": "k",
    "Ҳ": "H", "ҳ": "h",
    "Ў": "O", "ў": "o",
}


def transliterate_cyrillic(text: str) -> str:
    """Convert Cyrillic characters to Uzbek Latin equivalents."""
    return "".join(CYRILLIC_TO_LATIN.get(char, char) for char in text)


def normalize_token(token: str) -> str:
    """Normalize a single name token with Uzbek orthographic equivalences."""
    if token.startswith("ye"):
        token = "e" + token[2:]

    token = token.replace("kh", "h")
    token = token.replace("x", "h")
    token = token.replace("š", "sh")
    token = token.replace("č", "ch")
    token = token.replace("ts", "c")

    return token


def normalize_name_to_tokens(name: str) -> set[str]:
    """Convert a name string into a normalized set of tokens."""
    lat = transliterate_cyrillic(name)
    lowered = lat.lower()

    # Normalize o' / g' variants
    lowered = re.sub(r"o['’ʻ`ó]", "o", lowered)
    lowered = re.sub(r"g['’ʻ`]", "g", lowered)

    # Replace punctuation (. , ' ’ ʻ ` -) with spaces
    lowered = re.sub(r"[.,'’ʻ`\-]", " ", lowered)

    raw_tokens = lowered.split()
    normalized = set()
    for tok in raw_tokens:
        norm = normalize_token(tok)
        if norm:
            normalized.add(norm)

    return normalized


def token_matches(typed_tok: str, sheet_tok: str) -> bool:
    """Check if a typed token matches a sheet token."""
    if typed_tok == sheet_tok:
        return True
    # Stem / prefix matching for Uzbek name variations (e.g. Ismat vs Ismatjon, Jasur vs Jasurbek, Xasanov vs Xasanova)
    if len(typed_tok) >= 3 and len(sheet_tok) >= 3:
        if typed_tok.startswith(sheet_tok) or sheet_tok.startswith(typed_tok):
            return True
    return False


def names_match(typed: str, sheet_name: str) -> bool:
    """Compare typed name against sheet record name using set inclusion rules.

    - Requires at least 2 tokens in the typed string.
    - Every typed token must match at least one sheet name token.
    - Deterministic only (no fuzzy matching).
    """
    typed_tokens = normalize_name_to_tokens(typed)
    sheet_tokens = normalize_name_to_tokens(sheet_name)

    if len(typed_tokens) < 2:
        return False

    for t_tok in typed_tokens:
        if not any(token_matches(t_tok, s_tok) for s_tok in sheet_tokens):
            return False

    return True
