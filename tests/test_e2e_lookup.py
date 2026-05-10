"""End-to-end smoke test: parse + lookup on a real product panel.

Uses the real CosIng CSV at data/cosing.csv when present (falls back to the
6-row stub otherwise). PubChem is hit for real so the CosIng-partial ->
PubChem fallthrough path is exercised on actual data; LLM is disabled
(no API key in fixture) to keep the smoke test cheap and offline-from-
Anthropic. The test will need network for the PubChem leg.

Run with `pytest -s tests/test_e2e_lookup.py` to see the full result table.
"""

import pytest

import src.lookup as lookup_mod
from src.lookup import lookup_panel
from src.parser import parse_inci

VITASANA_PANEL = (
    "Water, Sodium Lauroyl Methyl Isethionate, Cocamidopropyl Betaine, "
    "Lauryl Glucoside, Aloe Barbadensis Leaf Juice*, Phenoxyethanol, "
    "Caprylyl Glycol, Ethylhexylglycerin"
)

COSING_SOURCES = ("cosing", "cosing_partial")


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Per-test SQLite cache; force CosIng index to reload from real disk."""
    monkeypatch.setattr(lookup_mod, "CACHE_PATH", tmp_path / "cache.db")
    monkeypatch.setattr(lookup_mod, "_cosing_cache", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield


def test_vitasana_panel_all_found_in_cosing(capsys):
    # No mocks: CosIng hits short-circuit before any external call; only the
    # cosing_partial fallthrough (Sodium Lauroyl Methyl Isethionate) actually
    # hits PubChem.
    parsed = parse_inci(VITASANA_PANEL)
    results = lookup_panel(parsed)

    in_cosing = [r for r in results if r.get("source") in COSING_SOURCES]
    fully_verified = [r for r in results if r.get("verified") is True]
    partials = [r for r in results if r.get("source") == "cosing_partial"]
    total = len(results)

    print("\n--- Vitasana panel results ---")
    print(
        f"{'#':<3} {'INCI Name':<42} {'CAS':<15} "
        f"{'EINECS':<25} {'Source':<16} {'Verified'}"
    )
    print("-" * 116)
    for r in results:
        print(
            f"{r['position']:<3} "
            f"{r['inci_name']:<42} "
            f"{(r.get('cas_number') or '-'):<15} "
            f"{(r.get('einecs_number') or '-'):<25} "
            f"{r['source']:<16} "
            f"{r['verified']}"
        )
    print(f"\nIn CosIng: {len(in_cosing)}/{total}")
    print(f"Fully verified (CAS present): {len(fully_verified)}/{total}")
    print(f"Partial (CosIng entry, CAS missing): {len(partials)}/{total}")
    for r in partials:
        print(f"  - {r['inci_name']}: {r.get('verification_note')}")

    assert len(in_cosing) == total, (
        f"Only {len(in_cosing)}/{total} ingredients found in CosIng "
        "(full or partial)"
    )
