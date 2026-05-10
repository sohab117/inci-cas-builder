"""CAS lookup layer.

Phase 1.2: resolves a parsed INCI entry to CAS + EINECS + function via a
priority chain — local CosIng CSV → PubChem REST → Claude LLM. SQLite cache
sits in front of the chain; not_found results are not cached so subsequent
runs can retry as data sources improve.

Phase 1.2.6: refined `verified` semantic. `verified=True` requires both an
authoritative source (CosIng/PubChem) AND a non-empty cas_number. CosIng
entries with empty CAS get source='cosing_partial' and a verification_note,
so the .docx output flags them for manual review instead of showing false
confidence.

Phase 1.2.7: when CosIng has an entry but no CAS (the partial case), the
chain falls through to PubChem and then LLM in pursuit of a CAS. CosIng's
function and EINECS are preserved across fallthroughs (CosIng remains
authoritative for those fields even when its CAS is missing). The
verification_note records the path taken so the .docx surfaces the gap.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
COSING_PATH = DATA_DIR / "cosing.csv"
COSING_STUB_PATH = DATA_DIR / "cosing_stub.csv"
CACHE_PATH = DATA_DIR / "lookup_cache.db"

PUBCHEM_URL_TEMPLATE = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/synonyms/JSON"
)
PUBCHEM_TIMEOUT_SECONDS = 10

LLM_MODEL = "claude-opus-4-7"
LLM_MAX_TOKENS = 500

_CAS_PATTERN = re.compile(r"^\d{2,7}-\d{2}-\d$")

_cosing_cache: dict[str, dict] | None = None


PARTIAL_NOTE = "CosIng entry exists but CAS field is empty in source data"
PUBCHEM_FILL_NOTE = (
    "CAS resolved via PubChem; CosIng entry exists but its CAS field is empty"
)
LLM_FILL_NOTE = "CAS LLM-inferred; not in CosIng or PubChem"


def lookup_ingredient(parsed_entry: dict) -> dict:
    """Resolve one parsed INCI entry to a fully populated ingredient record.

    Output dict contains parser keys plus:
        cas_number, einecs_number, function: str | None
        function_full: str | None — alias of function preserving the original
            CosIng list (the document layer simplifies for display)
        verified: bool — True only when source is authoritative AND cas_number set
        source: 'cosing' | 'cosing_partial' | 'pubchem' | 'llm' | 'not_found'
        verification_note: str | None — explains the source path when CosIng was
            partial and a fallback filled in (or when nothing did)

    A CosIng partial hit (entry present, CAS empty) does NOT short-circuit the
    chain — PubChem and LLM are still tried for a CAS. CosIng's function and
    EINECS are preserved if either fills the CAS.
    """
    result = _resolve_chain(parsed_entry)
    result["function_full"] = result.get("function")
    return result


def _resolve_chain(parsed_entry: dict) -> dict:
    """Run the cache -> CosIng -> PubChem -> LLM chain and return the result dict
    (without the function_full alias — that's added by lookup_ingredient)."""
    out = dict(parsed_entry)
    out.update(
        cas_number=None,
        einecs_number=None,
        function=None,
        verified=False,
        source="not_found",
        verification_note=None,
    )

    normalized = (parsed_entry.get("inci_normalized") or "").strip().upper()
    if not normalized:
        return out

    cached = _cache_get(normalized)
    if cached is not None:
        out.update(cached)
        return out

    cosing_key, cosing_hit = _cosing_with_slash_retry(parsed_entry, normalized)

    # Full CosIng hit: short-circuit.
    if cosing_hit is not None and cosing_hit.get("cas_number"):
        result = {
            **cosing_hit,
            "verified": True,
            "source": "cosing",
            "verification_note": None,
        }
        _cache_result(normalized, cosing_key, result)
        out.update(result)
        return out

    # At this point cosing_hit is None (no CosIng entry) or partial (entry
    # exists but CAS is empty). In both cases we try PubChem next; the only
    # difference is whether we preserve CosIng's function/EINECS on success.
    inci_name = parsed_entry.get("inci_name", "")
    pubchem_cas = _pubchem_lookup(inci_name)
    if pubchem_cas is not None:
        if cosing_hit is not None:
            result = {
                "cas_number": pubchem_cas,
                "einecs_number": cosing_hit.get("einecs_number"),
                "function": cosing_hit.get("function"),
                "verified": True,
                "source": "pubchem",
                "verification_note": PUBCHEM_FILL_NOTE,
            }
        else:
            result = {
                "cas_number": pubchem_cas,
                "einecs_number": None,
                "function": None,
                "verified": True,
                "source": "pubchem",
                "verification_note": None,
            }
        _cache_result(normalized, cosing_key, result)
        out.update(result)
        return out

    llm_data = _llm_lookup(inci_name)
    if llm_data is not None:
        if cosing_hit is not None:
            result = {
                "cas_number": llm_data.get("cas_number"),
                "einecs_number": (
                    cosing_hit.get("einecs_number") or llm_data.get("einecs_number")
                ),
                "function": (
                    cosing_hit.get("function") or llm_data.get("function")
                ),
                "verified": False,
                "source": "llm",
                "verification_note": LLM_FILL_NOTE,
            }
        else:
            result = {
                "cas_number": llm_data.get("cas_number"),
                "einecs_number": llm_data.get("einecs_number"),
                "function": llm_data.get("function"),
                "verified": False,
                "source": "llm",
                "verification_note": None,
            }
        _cache_result(normalized, cosing_key, result)
        out.update(result)
        return out

    # Last resort: nothing produced a CAS. If CosIng at least had the entry,
    # surface its function/EINECS with the partial diagnostic.
    if cosing_hit is not None:
        result = {
            **cosing_hit,
            "verified": False,
            "source": "cosing_partial",
            "verification_note": PARTIAL_NOTE,
        }
        _cache_result(normalized, cosing_key, result)
        out.update(result)
        return out

    return out


def _cache_result(normalized: str, cosing_key: str, result: dict) -> None:
    """Cache under the canonical key, plus the rejoined CosIng key when
    that's how we matched, so future lookups by either form short-circuit."""
    _cache_put(normalized, result)
    if cosing_key != normalized:
        _cache_put(cosing_key, result)


def lookup_panel(parsed_entries: list[dict]) -> list[dict]:
    """Apply lookup_ingredient to every entry in a parsed panel."""
    return [lookup_ingredient(e) for e in parsed_entries]


def _cosing_with_slash_retry(
    parsed_entry: dict, normalized: str
) -> tuple[str, dict | None]:
    """Try canonical key first; if `slash_synonyms` flagged, retry rejoined form.

    Returns (key_used, cosing_row_or_None). `key_used` is the rejoined form when
    that's how we matched, so the caller can write a second cache entry under
    the rejoined key in addition to the canonical one.
    """
    direct = _cosing_lookup(normalized)
    if direct is not None:
        return normalized, direct

    if "slash_synonyms" not in (parsed_entry.get("notes") or []):
        return normalized, None

    parts = [parsed_entry.get("inci_name", "")] + (parsed_entry.get("synonyms") or [])
    rejoined = "/".join(p.strip() for p in parts if p.strip()).upper()
    if rejoined == normalized or not rejoined:
        return normalized, None

    rejoined_hit = _cosing_lookup(rejoined)
    if rejoined_hit is not None:
        return rejoined, rejoined_hit
    return normalized, None


def _cosing_lookup(name: str) -> dict | None:
    return _get_cosing_index().get(name.upper().strip())


def _get_cosing_index() -> dict[str, dict]:
    global _cosing_cache
    if _cosing_cache is None:
        path = COSING_PATH if COSING_PATH.exists() else COSING_STUB_PATH
        _cosing_cache = _load_cosing_index(path)
    return _cosing_cache


def _load_cosing_index(path: Path) -> dict[str, dict]:
    index: dict[str, dict] = {}
    if not path.exists():
        return index
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row.get("inci_name") or "").upper().strip()
            if not key:
                continue
            index[key] = {
                "cas_number": (row.get("cas_number") or "").strip() or None,
                "einecs_number": (row.get("einecs_number") or "").strip() or None,
                "function": (row.get("function") or "").strip() or None,
            }
    return index


def _pubchem_lookup(name: str) -> str | None:
    if not name:
        return None
    url = PUBCHEM_URL_TEMPLATE.format(name=quote(name))
    try:
        resp = requests.get(url, timeout=PUBCHEM_TIMEOUT_SECONDS)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    info_list = data.get("InformationList", {}).get("Information", [])
    if not info_list:
        return None
    for syn in info_list[0].get("Synonym", []):
        if isinstance(syn, str) and _CAS_PATTERN.match(syn):
            return syn
    return None


def _llm_lookup(name: str) -> dict | None:
    if not name:
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    prompt = (
        f"You are a regulatory chemistry assistant for the cosmetic industry. "
        f"For the INCI ingredient '{name}', return its CAS Registry Number, "
        f"EINECS (EC) number, and primary cosmetic function.\n\n"
        f"This is for regulatory documentation. Only return values that are "
        f"definitively associated with this exact INCI name. If you are uncertain "
        f"about any field, return null for that field rather than guessing. Do not "
        f"infer values from similar-sounding ingredients."
    )

    schema = {
        "type": "object",
        "properties": {
            "cas_number": {"type": ["string", "null"]},
            "einecs_number": {"type": ["string", "null"]},
            "function": {"type": ["string", "null"]},
        },
        "required": ["cas_number", "einecs_number", "function"],
        "additionalProperties": False,
    }

    try:
        response = Anthropic(api_key=api_key).messages.create(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except Exception:
        return None

    text = next(
        (b.text for b in response.content if getattr(b, "type", None) == "text"),
        None,
    )
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not data.get("cas_number"):
        return None
    return {
        "cas_number": data.get("cas_number"),
        "einecs_number": data.get("einecs_number"),
        "function": data.get("function"),
    }


def _cache_conn() -> sqlite3.Connection:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cache (
            inci_normalized TEXT PRIMARY KEY,
            cas_number TEXT,
            einecs_number TEXT,
            function TEXT,
            verified INTEGER,
            source TEXT,
            verification_note TEXT,
            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Migrate older databases that were created before verification_note existed.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(cache)").fetchall()}
    if "verification_note" not in cols:
        conn.execute("ALTER TABLE cache ADD COLUMN verification_note TEXT")
    return conn


def _cache_get(key: str) -> dict | None:
    conn = _cache_conn()
    try:
        row = conn.execute(
            "SELECT cas_number, einecs_number, function, verified, source, "
            "verification_note FROM cache WHERE inci_normalized = ?",
            (key,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "cas_number": row[0],
        "einecs_number": row[1],
        "function": row[2],
        "verified": bool(row[3]),
        "source": row[4],
        "verification_note": row[5],
    }


def _cache_put(key: str, result: dict) -> None:
    conn = _cache_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO cache "
            "(inci_normalized, cas_number, einecs_number, function, verified, "
            "source, verification_note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                result.get("cas_number"),
                result.get("einecs_number"),
                result.get("function"),
                int(bool(result.get("verified"))),
                result.get("source"),
                result.get("verification_note"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


if os.environ.get("LOOKUP_DEBUG") == "1":
    import random as _random

    _idx = _get_cosing_index()
    _src = COSING_PATH if COSING_PATH.exists() else COSING_STUB_PATH
    print(f"[lookup] CosIng loaded: {len(_idx)} rows from {_src}")
    if _idx:
        for _name, _row in _random.sample(list(_idx.items()), min(5, len(_idx))):
            print(
                f"  {_name!r} -> CAS={_row['cas_number']!r} "
                f"EINECS={_row['einecs_number']!r} "
                f"Function={_row['function']!r}"
            )
