from src.parser import parse_inci


def test_empty_input():
    assert parse_inci("") == []
    assert parse_inci("   ") == []
    assert parse_inci("\n\n") == []


def test_simple_comma_list():
    result = parse_inci("Aqua, Glycerin, Tocopherol")
    assert len(result) == 3
    assert result[0]["position"] == 1
    assert result[0]["inci_name"] == "Aqua"
    assert result[0]["inci_normalized"] == "AQUA"
    assert result[0]["notes"] == []
    assert result[0]["synonyms"] == []
    assert result[2]["position"] == 3
    assert result[2]["inci_name"] == "Tocopherol"


def test_position_is_1_indexed():
    result = parse_inci("A, B, C")
    assert [e["position"] for e in result] == [1, 2, 3]


def test_organic_asterisk_preserved_in_inci_name():
    result = parse_inci("Aloe Barbadensis Leaf Juice*")
    assert len(result) == 1
    entry = result[0]
    assert entry["inci_name"] == "Aloe Barbadensis Leaf Juice*"
    assert entry["inci_normalized"] == "ALOE BARBADENSIS LEAF JUICE"
    assert "organic" in entry["notes"]


def test_slash_synonyms_canonical_first():
    result = parse_inci("Aqua/Water/Eau")
    assert len(result) == 1
    entry = result[0]
    assert entry["inci_name"] == "Aqua"
    assert entry["inci_normalized"] == "AQUA"
    assert entry["synonyms"] == ["Water", "Eau"]
    assert "slash_synonyms" in entry["notes"]


def test_slash_synonyms_with_spaces_around_slash():
    result = parse_inci("Aqua / Water / Eau")
    assert len(result) == 1
    assert result[0]["inci_name"] == "Aqua"
    assert result[0]["synonyms"] == ["Water", "Eau"]
    assert "slash_synonyms" in result[0]["notes"]


def test_parenthetical_preserved_in_inci_name():
    result = parse_inci("Parfum (Fragrance)")
    assert len(result) == 1
    entry = result[0]
    assert entry["inci_name"] == "Parfum (Fragrance)"
    assert entry["inci_normalized"] == "PARFUM"
    assert "parenthetical" in entry["notes"]


def test_ci_number_with_space():
    result = parse_inci("CI 77891")
    assert len(result) == 1
    assert result[0]["inci_normalized"] == "CI 77891"
    assert "CI_number" in result[0]["notes"]


def test_ci_number_no_space():
    result = parse_inci("CI77891")
    assert "CI_number" in result[0]["notes"]


def test_ci_number_dotted_form():
    result = parse_inci("C.I. 77891")
    assert "CI_number" in result[0]["notes"]


def test_ci_number_does_not_match_word_starting_with_ci():
    # 'Cinnamomum' should not be flagged as CI_number
    result = parse_inci("Cinnamomum Cassia Extract")
    assert "CI_number" not in result[0]["notes"]


def test_may_contain_marker_propagates_to_subsequent_tokens():
    result = parse_inci("Aqua, Glycerin, May Contain: CI 77891, CI 77491")
    assert len(result) == 4
    assert "may_contain" not in result[0]["notes"]
    assert "may_contain" not in result[1]["notes"]
    assert result[2]["inci_name"] == "CI 77891"
    assert "may_contain" in result[2]["notes"]
    assert "CI_number" in result[2]["notes"]
    assert "may_contain" in result[3]["notes"]


def test_plus_minus_marker():
    result = parse_inci("Aqua, +/- CI 77891")
    assert len(result) == 2
    assert "may_contain" not in result[0]["notes"]
    assert "may_contain" in result[1]["notes"]
    assert result[1]["inci_name"] == "CI 77891"


def test_may_contain_as_standalone_token():
    result = parse_inci("Aqua, May Contain:, CI 77891")
    # marker token alone produces no entry but flips the flag
    assert len(result) == 2
    assert result[0]["inci_name"] == "Aqua"
    assert "may_contain" not in result[0]["notes"]
    assert result[1]["inci_name"] == "CI 77891"
    assert "may_contain" in result[1]["notes"]


def test_parens_with_internal_comma_not_split():
    result = parse_inci("Tocopherol (Vitamin E, Antioxidant), Aqua")
    assert len(result) == 2
    assert result[0]["inci_name"] == "Tocopherol (Vitamin E, Antioxidant)"
    assert result[1]["inci_name"] == "Aqua"


def test_newlines_as_separators():
    result = parse_inci("Aqua\nGlycerin\nTocopherol")
    assert [e["inci_name"] for e in result] == ["Aqua", "Glycerin", "Tocopherol"]


def test_mixed_newlines_and_commas():
    result = parse_inci("Aqua,\nGlycerin,\nTocopherol")
    assert [e["inci_name"] for e in result] == ["Aqua", "Glycerin", "Tocopherol"]


def test_trailing_comma_ignored():
    result = parse_inci("Aqua, Glycerin,")
    assert len(result) == 2


def test_consecutive_commas_skipped():
    result = parse_inci("Aqua,, Glycerin")
    assert len(result) == 2


def test_raw_preserves_pre_strip_substring():
    result = parse_inci("  Aqua  ,  Glycerin  ")
    assert result[0]["raw"] == "  Aqua  "
    assert result[0]["inci_name"] == "Aqua"
    assert result[1]["raw"] == "  Glycerin  "


def test_realistic_panel():
    panel = (
        "Aqua/Water/Eau, Glycerin, Cetearyl Alcohol, Tocopherol, "
        "Aloe Barbadensis Leaf Juice*, Parfum (Fragrance), "
        "Phenoxyethanol, May Contain: CI 77891, CI 77491"
    )
    result = parse_inci(panel)
    assert len(result) == 9

    aqua = result[0]
    assert aqua["inci_name"] == "Aqua"
    assert aqua["synonyms"] == ["Water", "Eau"]
    assert "slash_synonyms" in aqua["notes"]

    aloe = result[4]
    assert aloe["inci_name"] == "Aloe Barbadensis Leaf Juice*"
    assert aloe["inci_normalized"] == "ALOE BARBADENSIS LEAF JUICE"
    assert "organic" in aloe["notes"]

    parfum = result[5]
    assert parfum["inci_name"] == "Parfum (Fragrance)"
    assert parfum["inci_normalized"] == "PARFUM"
    assert "parenthetical" in parfum["notes"]

    ci_first = result[7]
    assert ci_first["inci_name"] == "CI 77891"
    assert "CI_number" in ci_first["notes"]
    assert "may_contain" in ci_first["notes"]

    ci_second = result[8]
    assert ci_second["inci_name"] == "CI 77491"
    assert "may_contain" in ci_second["notes"]


def test_synonyms_default_empty_when_no_slash():
    result = parse_inci("Glycerin")
    assert result[0]["synonyms"] == []
