"""Generate the regulatory CAS reference .docx from looked-up panel entries.

Phase 1.3: takes the list returned by `lookup_panel()` and produces a
Vitasana-style Word document with a 7-column ingredient table, header
metadata, footnotes for verification gaps, and a confidentiality footer.
"""

from __future__ import annotations

from datetime import date as _date
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

# Palette
HEADER_FILL = "D5E8F0"  # subtle blue for header row
UNVERIFIED_FILL = "FFF3CD"  # light yellow for verified=N rows

DASH = "—"

COLUMN_HEADERS = [
    "#",
    "INCI Name",
    "Common Name / Function",
    "CAS Number",
    "EINECS",
    "Trade Name / Source",
    "Verified",
]

DEFAULT_NOTE = (
    "Note: Rows marked N in the Verified column require confirmation against "
    "supplier SDS or alternative sources before regulatory submission."
)


def generate_document(
    parsed_entries: list[dict],
    output_path: str,
    metadata: dict | None = None,
) -> str:
    """Render parsed+looked-up entries to a .docx file. Returns the path."""
    metadata = metadata or {}
    product_name = metadata.get("product_name") or "Cosmetic Product"
    client_name = metadata.get("client_name") or ""
    prepared_by = metadata.get("prepared_by") or ""
    purpose = metadata.get("purpose") or ""
    doc_date = metadata.get("date") or _date.today().strftime("%Y-%m-%d")

    doc = Document()

    _write_header(doc, product_name, prepared_by, client_name, doc_date, purpose)

    footnotes = _FootnoteLedger()
    _write_table(doc, parsed_entries, footnotes)

    _write_footnotes_section(doc, footnotes)
    _write_confidentiality(doc, prepared_by)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    return output_path


# ---------------------------------------------------------------------------
# Document sections
# ---------------------------------------------------------------------------


def _write_header(doc, product_name, prepared_by, client_name, doc_date, purpose):
    title = doc.add_heading(f"{product_name} {DASH} CAS Number Reference", level=1)
    for run in title.runs:
        run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)

    meta_parts: list[str] = []
    if prepared_by:
        meta_parts.append(f"Prepared by: {prepared_by}")
    if client_name:
        meta_parts.append(f"Client: {client_name}")
    meta_parts.append(f"Date: {doc_date}")
    doc.add_paragraph("  |  ".join(meta_parts))

    if purpose:
        doc.add_paragraph(f"Purpose: {purpose}")

    note = doc.add_paragraph()
    note.paragraph_format.left_indent = Pt(18)
    bold_label = note.add_run("Note: ")
    bold_label.bold = True
    note.add_run(DEFAULT_NOTE.removeprefix("Note: "))


def _write_table(doc, entries, footnotes):
    table = doc.add_table(rows=1, cols=len(COLUMN_HEADERS))
    table.style = "Table Grid"

    header_row = table.rows[0]
    for i, header in enumerate(COLUMN_HEADERS):
        cell = header_row.cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(header)
        run.bold = True
        _shade_cell(cell, HEADER_FILL)

    for entry in entries:
        row = table.add_row()
        _write_data_row(row, entry, footnotes)


def _write_data_row(row, entry, footnotes):
    cells = row.cells

    cells[0].text = str(entry.get("position", ""))

    # INCI Name (+ italic synonyms line if present)
    inci_cell = cells[1]
    inci_cell.text = ""
    inci_cell.paragraphs[0].add_run(entry.get("inci_name") or "")
    synonyms = entry.get("synonyms") or []
    if synonyms:
        synonym_para = inci_cell.add_paragraph()
        joined = " / ".join([entry.get("inci_name") or ""] + synonyms)
        run = synonym_para.add_run(joined)
        run.italic = True

    cells[2].text = entry.get("function") or ""
    cells[3].text = entry.get("cas_number") or DASH
    cells[4].text = entry.get("einecs_number") or DASH
    cells[5].text = ""  # Trade Name / Source — supplied later

    # Verified column with optional superscript footnote ref
    verified_cell = cells[6]
    verified_cell.text = ""
    verified_para = verified_cell.paragraphs[0]
    verified = bool(entry.get("verified"))
    label = verified_para.add_run("Y" if verified else "N")
    label.bold = True

    note = entry.get("verification_note")
    if note:
        ref = verified_para.add_run(str(footnotes.ref(note)))
        ref.font.superscript = True

    if not verified:
        for cell in cells:
            _shade_cell(cell, UNVERIFIED_FILL)


def _write_footnotes_section(doc, footnotes):
    if not footnotes:
        return
    doc.add_paragraph()
    for num, text in footnotes.ordered():
        para = doc.add_paragraph()
        ref = para.add_run(str(num))
        ref.font.superscript = True
        body = para.add_run(" " + text)
        body.italic = True


def _write_confidentiality(doc, prepared_by):
    para = doc.add_paragraph()
    suffix = f" | {prepared_by}" if prepared_by else ""
    run = para.add_run(
        f"Confidential {DASH} For Internal and Regulatory Use Only{suffix}"
    )
    run.italic = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FootnoteLedger:
    """Collects unique verification_note strings and assigns 1-indexed numbers."""

    def __init__(self) -> None:
        self._notes: dict[str, int] = {}

    def __bool__(self) -> bool:
        return bool(self._notes)

    def ref(self, note: str) -> int:
        if note not in self._notes:
            self._notes[note] = len(self._notes) + 1
        return self._notes[note]

    def ordered(self) -> list[tuple[int, str]]:
        return sorted(((n, t) for t, n in self._notes.items()), key=lambda x: x[0])


def _shade_cell(cell, hex_color: str) -> None:
    """Apply a background fill to a table cell via OXML."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)
