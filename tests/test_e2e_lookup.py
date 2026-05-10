"""End-to-end smoke test: parse + lookup on a real product panel.

Uses the real CosIng CSV at data/cosing.csv when present (falls back to the
6-row stub otherwise). External fallbacks (PubChem, LLM) are mocked off so
the test runs hermetically — only CosIng coverage is being measured.

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

MIN_COSING_COVERAGE = 0.5


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Per-test SQLite cache; force CosIng index to reload from real disk."""
    monkeypatch.setattr(lookup_mod, "CACHE_PATH", tmp_path / "cache.db")
    monkeypatch.setattr(lookup_mod, "_cosing_cache", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield


def test_vitasana_panel_at_least_half_resolved_by_cosing(mocker, capsys):
    pubchem_404 = mocker.MagicMock(status_code=404)
    mocker.patch("src.lookup.requests.get", return_value=pubchem_404)

    parsed = parse_inci(VITASANA_PANEL)
    results = lookup_panel(parsed)

    cosing_verified = sum(
        1
        for r in results
        if r.get("source") == "cosing" and r.get("verified") is True
    )
    total = len(results)

    print("\n--- Vitasana panel results ---")
    print(
        f"{'#':<3} {'INCI Name':<42} {'CAS':<15} "
        f"{'EINECS':<25} {'Source':<10} {'Verified'}"
    )
    print("-" * 110)
    for r in results:
        print(
            f"{r['position']:<3} "
            f"{r['inci_name']:<42} "
            f"{(r.get('cas_number') or '-'):<15} "
            f"{(r.get('einecs_number') or '-'):<25} "
            f"{r['source']:<10} "
            f"{r['verified']}"
        )
    pct = 100 * cosing_verified // total if total else 0
    print(f"\nCosIng-verified: {cosing_verified}/{total} ({pct}%)")

    assert cosing_verified / total >= MIN_COSING_COVERAGE, (
        f"Only {cosing_verified}/{total} ingredients resolved from CosIng — "
        f"weak coverage for this panel ({pct}% < "
        f"{int(MIN_COSING_COVERAGE * 100)}% threshold)"
    )
