"""Unit tests for src/document.py — .docx generation."""

from docx import Document
from docx.oxml.ns import qn

from src.document import generate_document


def _entry(
    position,
    inci_name,
    synonyms=None,
    function=None,
    cas_number=None,
    einecs_number=None,
    verified=False,
    source="not_found",
    verification_note=None,
):
    """Build a lookup-style entry dict for tests."""
    return {
        "position": position,
        "inci_name": inci_name,
        "inci_normalized": inci_name.upper(),
        "raw": inci_name,
        "synonyms": synonyms or [],
        "notes": [],
        "function": function,
        "cas_number": cas_number,
        "einecs_number": einecs_number,
        "verified": verified,
        "source": source,
        "verification_note": verification_note,
    }


def _cell_fill(cell):
    """Return the hex fill color of a table cell, or None."""
    tcPr = cell._tc.tcPr
    if tcPr is None:
        return None
    shd = tcPr.find(qn("w:shd"))
    if shd is None:
        return None
    return shd.get(qn("w:fill"))


def _find_data_table(doc):
    """The document has exactly one table (the ingredient table). Return it."""
    assert len(doc.tables) == 1, f"expected 1 table, found {len(doc.tables)}"
    return doc.tables[0]


def test_generates_valid_docx_that_reopens(tmp_path):
    out = tmp_path / "out.docx"
    entries = [_entry(1, "Water", cas_number="7732-18-5", verified=True, source="cosing")]

    returned = generate_document(entries, str(out))

    assert returned == str(out)
    assert out.exists() and out.stat().st_size > 0
    # Reopens without raising
    Document(str(out))


def test_table_has_7_columns_and_correct_row_count(tmp_path):
    out = tmp_path / "out.docx"
    entries = [
        _entry(1, "Water", cas_number="7732-18-5", verified=True, source="cosing"),
        _entry(2, "Glycerin", cas_number="56-81-5", verified=True, source="cosing"),
        _entry(3, "Tocopherol", verified=False, source="not_found"),
    ]

    generate_document(entries, str(out))
    doc = Document(str(out))
    table = _find_data_table(doc)

    assert len(table.columns) == 7
    # 1 header row + 3 data rows
    assert len(table.rows) == 4

    header_texts = [c.text.strip() for c in table.rows[0].cells]
    expected = [
        "#",
        "INCI Name",
        "Common Name / Function",
        "CAS Number",
        "EINECS",
        "Trade Name / Source",
        "Verified",
    ]
    assert header_texts == expected


def test_header_metadata_appears_in_document(tmp_path):
    out = tmp_path / "out.docx"
    entries = [_entry(1, "Water", cas_number="7732-18-5", verified=True, source="cosing")]
    metadata = {
        "product_name": "Vitasana Body Wash",
        "client_name": "Vitasana",
        "prepared_by": "117 Holdings LLC",
        "purpose": "EWG Verified submission support",
        "date": "2026-05-09",
    }

    generate_document(entries, str(out), metadata)
    doc = Document(str(out))

    # All metadata strings should appear somewhere in the body paragraphs
    body_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Vitasana Body Wash" in body_text
    assert "Vitasana" in body_text
    assert "117 Holdings LLC" in body_text
    assert "EWG Verified submission support" in body_text
    assert "2026-05-09" in body_text


def test_unverified_rows_have_different_shading_than_verified_rows(tmp_path):
    out = tmp_path / "out.docx"
    entries = [
        _entry(1, "Water", cas_number="7732-18-5", verified=True, source="cosing"),
        _entry(2, "Mystery", verified=False, source="not_found"),
    ]

    generate_document(entries, str(out))
    doc = Document(str(out))
    table = _find_data_table(doc)

    verified_row_fill = _cell_fill(table.rows[1].cells[0])
    unverified_row_fill = _cell_fill(table.rows[2].cells[0])
    assert verified_row_fill != unverified_row_fill, (
        f"verified and unverified rows have same shading "
        f"({verified_row_fill!r} == {unverified_row_fill!r})"
    )


def test_verification_notes_render_as_footnotes(tmp_path):
    out = tmp_path / "out.docx"
    entries = [
        _entry(1, "Water", cas_number="7732-18-5", verified=True, source="cosing"),
        _entry(
            2,
            "Sodium Lauroyl Methyl Isethionate",
            function="Cleansing",
            verified=False,
            source="cosing_partial",
            verification_note="CosIng entry exists but CAS field is empty in source data",
        ),
    ]

    generate_document(entries, str(out))
    doc = Document(str(out))
    table = _find_data_table(doc)

    # Verified column on row 2 (index 2) should have a superscript reference run
    verified_cell = table.rows[2].cells[6]
    superscript_runs = [
        r for p in verified_cell.paragraphs for r in p.runs if r.font.superscript
    ]
    assert len(superscript_runs) >= 1, "no superscript footnote ref in unverified row"

    # Body paragraphs after the table should contain the note text
    body_text = "\n".join(p.text for p in doc.paragraphs)
    assert "CosIng entry exists but CAS field is empty in source data" in body_text


def test_synonyms_render_as_italic_second_line_under_inci_name(tmp_path):
    out = tmp_path / "out.docx"
    entries = [
        _entry(
            1,
            "Aqua",
            synonyms=["Water", "Eau"],
            cas_number="7732-18-5",
            verified=True,
            source="cosing",
        ),
    ]

    generate_document(entries, str(out))
    doc = Document(str(out))
    table = _find_data_table(doc)

    inci_cell = table.rows[1].cells[1]
    paragraphs = inci_cell.paragraphs
    assert len(paragraphs) >= 2, (
        f"expected INCI cell with synonyms to have ≥2 paragraphs, got {len(paragraphs)}"
    )
    # First paragraph: canonical name
    assert "Aqua" in paragraphs[0].text
    # Second paragraph: synonyms in italic
    second_text = paragraphs[1].text
    assert "Water" in second_text and "Eau" in second_text
    assert any(r.italic for r in paragraphs[1].runs), (
        "synonyms line should be italic"
    )
