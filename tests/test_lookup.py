from pathlib import Path

import pytest

import src.lookup as lookup_mod
from src.lookup import lookup_ingredient, lookup_panel

STUB_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "cosing_stub.csv"


@pytest.fixture(autouse=True)
def isolated_lookup_state(tmp_path, monkeypatch):
    """Force tests to use the stub CSV and a per-test SQLite cache."""
    monkeypatch.setattr(lookup_mod, "COSING_PATH", tmp_path / "no-real-cosing.csv")
    monkeypatch.setattr(lookup_mod, "COSING_STUB_PATH", STUB_CSV_PATH)
    monkeypatch.setattr(lookup_mod, "CACHE_PATH", tmp_path / "cache.db")
    monkeypatch.setattr(lookup_mod, "_cosing_cache", None)
    yield


def _entry(inci_name: str, normalized: str = None, synonyms=None, notes=None) -> dict:
    return {
        "position": 1,
        "inci_name": inci_name,
        "inci_normalized": normalized if normalized is not None else inci_name.upper(),
        "raw": inci_name,
        "synonyms": synonyms or [],
        "notes": notes or [],
    }


def test_cosing_hit_returns_water_data():
    result = lookup_ingredient(_entry("Water"))
    assert result["cas_number"] == "7732-18-5"
    assert result["einecs_number"] == "231-791-2"
    assert result["function"] == "Solvent"
    assert result["verified"] is True
    assert result["source"] == "cosing"
    # Parser fields preserved
    assert result["inci_name"] == "Water"
    assert result["position"] == 1


def test_cosing_entry_with_empty_cas_is_partial(mocker, monkeypatch):
    """CosIng partial + PubChem 404 + LLM unavailable -> source='cosing_partial'.
    Verification note still explains the CosIng gap."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    pubchem_404 = mocker.MagicMock(status_code=404)
    mocker.patch("src.lookup.requests.get", return_value=pubchem_404)

    result = lookup_ingredient(_entry("Sodium Lauroyl Methyl Isethionate"))

    assert result["source"] == "cosing_partial"
    assert result["verified"] is False
    assert result["cas_number"] is None
    assert result["einecs_number"] is None
    assert result["function"] == "Cleansing"
    assert result["verification_note"] is not None
    assert "CosIng" in result["verification_note"]


def test_cosing_partial_fills_cas_via_pubchem(mocker):
    """CosIng partial + PubChem hit -> source='pubchem', verified=True,
    CosIng function/EINECS preserved, note explains the gap."""
    pubchem_resp = mocker.MagicMock(status_code=200)
    pubchem_resp.json.return_value = {
        "InformationList": {
            "Information": [{"Synonym": ["Some Trade Name", "65104-92-3"]}]
        }
    }
    mocker.patch("src.lookup.requests.get", return_value=pubchem_resp)
    anthropic_mock = mocker.patch("src.lookup.Anthropic")

    result = lookup_ingredient(_entry("Sodium Lauroyl Methyl Isethionate"))

    assert result["source"] == "pubchem"
    assert result["verified"] is True
    assert result["cas_number"] == "65104-92-3"
    # CosIng metadata preserved (function from CosIng, EINECS empty in stub -> None)
    assert result["function"] == "Cleansing"
    assert result["einecs_number"] is None
    assert result["verification_note"] is not None
    assert "PubChem" in result["verification_note"]
    assert "CosIng" in result["verification_note"]
    anthropic_mock.assert_not_called()


def test_cosing_partial_falls_through_to_llm_when_pubchem_misses(mocker, monkeypatch):
    """CosIng partial + PubChem 404 + LLM hit -> source='llm', verified=False,
    CosIng function preserved, note explains both gaps."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    pubchem_404 = mocker.MagicMock(status_code=404)
    mocker.patch("src.lookup.requests.get", return_value=pubchem_404)

    text_block = mocker.MagicMock(type="text")
    text_block.text = (
        '{"cas_number": "12345-67-8", '
        '"einecs_number": null, '
        '"function": "Surfactant"}'
    )
    fake_message = mocker.MagicMock(content=[text_block])
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = fake_message
    mocker.patch("src.lookup.Anthropic", return_value=fake_client)

    result = lookup_ingredient(_entry("Sodium Lauroyl Methyl Isethionate"))

    assert result["source"] == "llm"
    assert result["verified"] is False
    assert result["cas_number"] == "12345-67-8"
    # CosIng's "Cleansing" wins over LLM's "Surfactant"
    assert result["function"] == "Cleansing"
    assert result["verification_note"] is not None
    assert "LLM" in result["verification_note"]


def test_cosing_full_hit_has_no_verification_note():
    """Sanity: a full CosIng hit (CAS present) carries verification_note=None."""
    result = lookup_ingredient(_entry("Water"))
    assert result["verified"] is True
    assert result["source"] == "cosing"
    assert result["verification_note"] is None


def test_pubchem_fallback_when_cosing_misses(mocker):
    pubchem_resp = mocker.MagicMock(status_code=200)
    pubchem_resp.json.return_value = {
        "InformationList": {
            "Information": [{"Synonym": ["Vitamin E", "alpha-Tocopherol", "59-02-9"]}]
        }
    }
    mocker.patch("src.lookup.requests.get", return_value=pubchem_resp)
    anthropic_mock = mocker.patch("src.lookup.Anthropic")

    result = lookup_ingredient(_entry("Tocopherol"))
    assert result["cas_number"] == "59-02-9"
    assert result["einecs_number"] is None
    assert result["function"] is None
    assert result["verified"] is True
    assert result["source"] == "pubchem"
    anthropic_mock.assert_not_called()


def test_llm_fallback_when_cosing_and_pubchem_miss(mocker, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    pubchem_resp = mocker.MagicMock(status_code=404)
    mocker.patch("src.lookup.requests.get", return_value=pubchem_resp)

    text_block = mocker.MagicMock(type="text")
    text_block.text = (
        '{"cas_number": "12345-67-8", '
        '"einecs_number": "999-999-9", '
        '"function": "Mystery Function"}'
    )
    fake_message = mocker.MagicMock(content=[text_block])
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = fake_message
    mocker.patch("src.lookup.Anthropic", return_value=fake_client)

    result = lookup_ingredient(_entry("Obscuram Esoterica"))
    assert result["cas_number"] == "12345-67-8"
    assert result["einecs_number"] == "999-999-9"
    assert result["function"] == "Mystery Function"
    assert result["verified"] is False
    assert result["source"] == "llm"


def test_not_found_when_all_sources_fail(mocker, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    pubchem_resp = mocker.MagicMock(status_code=404)
    mocker.patch("src.lookup.requests.get", return_value=pubchem_resp)

    text_block = mocker.MagicMock(type="text")
    text_block.text = (
        '{"cas_number": null, "einecs_number": null, "function": null}'
    )
    fake_message = mocker.MagicMock(content=[text_block])
    fake_client = mocker.MagicMock()
    fake_client.messages.create.return_value = fake_message
    mocker.patch("src.lookup.Anthropic", return_value=fake_client)

    result = lookup_ingredient(_entry("Completely Unknown Ingredient X"))
    assert result["cas_number"] is None
    assert result["einecs_number"] is None
    assert result["function"] is None
    assert result["verified"] is False
    assert result["source"] == "not_found"


def test_cache_hit_skips_external_calls(mocker):
    """First call hits PubChem; second call must not."""
    pubchem_resp = mocker.MagicMock(status_code=200)
    pubchem_resp.json.return_value = {
        "InformationList": {"Information": [{"Synonym": ["59-02-9"]}]}
    }
    pubchem_mock = mocker.patch("src.lookup.requests.get", return_value=pubchem_resp)

    entry = _entry("Tocopherol")
    first = lookup_ingredient(entry)
    assert first["source"] == "pubchem"
    assert first["cas_number"] == "59-02-9"
    assert pubchem_mock.call_count == 1

    second = lookup_ingredient(entry)
    assert second["source"] == "pubchem"
    assert second["cas_number"] == "59-02-9"
    assert pubchem_mock.call_count == 1


def test_slash_synonym_retry_hits_compound_inci_name(mocker):
    """`Caprylic` + synonym `Capric Triglyceride` should rejoin to hit CosIng."""
    pubchem_mock = mocker.patch("src.lookup.requests.get")
    anthropic_mock = mocker.patch("src.lookup.Anthropic")

    entry = _entry(
        "Caprylic",
        normalized="CAPRYLIC",
        synonyms=["Capric Triglyceride"],
        notes=["slash_synonyms"],
    )
    result = lookup_ingredient(entry)

    assert result["source"] == "cosing"
    assert result["cas_number"] == "73398-61-5"
    assert result["function"] == "Emollient"
    pubchem_mock.assert_not_called()
    anthropic_mock.assert_not_called()


def test_slash_synonym_second_lookup_hits_cache(mocker):
    """Regression: slash-rejoined hits must cache under canonical key too,
    so the second call short-circuits without re-running CosIng."""
    spy = mocker.spy(lookup_mod, "_cosing_lookup")
    entry = _entry(
        "Caprylic",
        normalized="CAPRYLIC",
        synonyms=["Capric Triglyceride"],
        notes=["slash_synonyms"],
    )

    first = lookup_ingredient(entry)
    assert first["source"] == "cosing"
    assert first["cas_number"] == "73398-61-5"
    calls_after_first = spy.call_count
    assert calls_after_first >= 1, "CosIng should have been queried on first call"

    second = lookup_ingredient(entry)
    assert second["source"] == "cosing"
    assert second["cas_number"] == "73398-61-5"
    assert spy.call_count == calls_after_first, (
        "CosIng was re-queried on second call; cache should have short-circuited"
    )


def test_lookup_panel_resolves_full_list(mocker):
    pubchem_mock = mocker.patch("src.lookup.requests.get")
    entries = [
        _entry("Water"),
        _entry("Glycerin"),
        _entry("Phenoxyethanol"),
    ]
    results = lookup_panel(entries)

    assert [r["cas_number"] for r in results] == [
        "7732-18-5",
        "56-81-5",
        "122-99-6",
    ]
    assert all(r["source"] == "cosing" for r in results)
    pubchem_mock.assert_not_called()
