"""INCI panel parser.

Phase 1.1: structure-only parser. Splits a raw INCI string into ordered
ingredient entries and flags annotations. Does NOT do CAS/EINECS lookup —
that lives in the lookup module (not yet built).
"""

import re


def parse_inci(inci_string: str) -> list[dict]:
    """Parse a raw INCI panel string into a list of structured ingredient entries.

    Returns a list of dicts with keys:
    - 'position': int (1-indexed order in panel)
    - 'inci_name': str (as-presented; first slash element if synonyms detected)
    - 'inci_normalized': str (uppercase, whitespace-collapsed, parens/asterisks stripped)
    - 'raw': str (original substring as it appeared, before stripping)
    - 'synonyms': list[str] (additional regional names from slash separation; [] otherwise)
    - 'notes': list[str] (any of: 'organic', 'CI_number', 'parenthetical',
      'slash_synonyms', 'may_contain')
    """
    if not inci_string or not inci_string.strip():
        return []

    # Newlines act as separators (panels often use line breaks instead of commas)
    s = re.sub(r"[\r\n]+", ",", inci_string)

    raw_tokens = _split_respecting_parens(s)

    entries: list[dict] = []
    position = 1
    may_contain_active = False

    for raw in raw_tokens:
        token = raw.strip()
        if not token:
            continue

        marker_match = re.match(
            r"^(may\s*contain|\+\s*/\s*-)\s*[:\-]?\s*",
            token,
            re.IGNORECASE,
        )
        if marker_match:
            may_contain_active = True
            token = token[marker_match.end():].strip()
            if not token:
                continue

        entries.append(_parse_token(raw, token, position, may_contain_active))
        position += 1

    return entries


def _parse_token(raw: str, token: str, position: int, may_contain: bool) -> dict:
    notes: list[str] = []
    synonyms: list[str] = []

    if may_contain:
        notes.append("may_contain")

    slash_parts = _split_slashes_outside_parens(token)
    if len(slash_parts) > 1:
        notes.append("slash_synonyms")
        inci_name = slash_parts[0].strip()
        synonyms = [p.strip() for p in slash_parts[1:] if p.strip()]
    else:
        inci_name = token

    if re.search(r"\*+\s*$", inci_name):
        notes.append("organic")

    # CI prefix + 4–6 digits; tolerates "CI 77891", "CI77891", "C.I. 77891"
    if re.match(r"^c\.?\s*i\.?\s*\d{4,6}", inci_name, re.IGNORECASE):
        notes.append("CI_number")

    if re.search(r"\([^)]*\)", inci_name):
        notes.append("parenthetical")

    normalized = re.sub(r"\s*\([^)]*\)\s*", " ", inci_name)
    normalized = normalized.replace("*", "")
    normalized = re.sub(r"\s+", " ", normalized).strip().upper()

    return {
        "position": position,
        "inci_name": inci_name,
        "inci_normalized": normalized,
        "raw": raw,
        "synonyms": synonyms,
        "notes": notes,
    }


def _split_respecting_parens(s: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in s:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            if depth > 0:
                depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def _split_slashes_outside_parens(s: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in s:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            if depth > 0:
                depth -= 1
            buf.append(ch)
        elif ch == "/" and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out
