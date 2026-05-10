"""Convert the official CosIng CSV export to our internal schema.

Source format (EU Commission, archived 2020-12-30):
    Lines 1-9: metadata (sep=,, "File creation date", blank lines, "Inventory of...")
    Line 10:   header — COSING Ref No, INCI name, INN name, Ph. Eur. Name,
               CAS No, EC No, Chem/IUPAC Name / Description, Restriction,
               Function, Update Date
    Line 11+:  data rows (multi-line entries possible — use csv module)

Output schema (data/cosing.csv):
    inci_name, cas_number, einecs_number, function

Field cleanup:
    - INCI name: strip whitespace, uppercase (lookup keys are uppercase)
    - CAS No: strip; if multi-valued ("123-45-6, 789-01-2") take first valid;
              "-" / blank become empty (lookup module turns empty into None)
    - EC No: strip; "-" / blank become empty
    - Function: strip + Title Case for consistency with stub display values

Usage:
    python scripts/convert_cosing.py <input.csv> <output.csv>

Defaults: /tmp/cosing_raw.csv → data/cosing.csv
"""

import csv
import re
import sys
from pathlib import Path

CAS_PATTERN = re.compile(r"\d{2,7}-\d{2}-\d")

DEFAULT_INPUT = Path("/tmp/cosing_raw.csv")
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "data" / "cosing.csv"

OUTPUT_HEADER = ["inci_name", "cas_number", "einecs_number", "function"]


def _clean_placeholder(value: str) -> str:
    """Strip whitespace; treat '-' or empty as empty string."""
    v = (value or "").strip()
    return "" if v in {"", "-"} else v


def _first_cas(value: str) -> str:
    """Pull the first valid CAS pattern from a possibly multi-valued cell."""
    cleaned = _clean_placeholder(value)
    if not cleaned:
        return ""
    match = CAS_PATTERN.search(cleaned)
    return match.group(0) if match else ""


def _find_header_row(path: Path) -> int:
    """Return the 0-indexed line number of the CSV header."""
    with open(path, encoding="utf-8", newline="") as f:
        for i, line in enumerate(f):
            if line.startswith("COSING Ref No,"):
                return i
    raise ValueError(f"No CosIng header row found in {path}")


def convert(input_path: Path, output_path: Path) -> tuple[int, int]:
    """Convert CosIng CSV to our schema. Returns (rows_in, rows_out)."""
    header_line = _find_header_row(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows_in = 0
    rows_out = 0
    with open(input_path, encoding="utf-8", newline="") as src:
        # Skip metadata rows
        for _ in range(header_line):
            src.readline()
        reader = csv.DictReader(src)

        with open(output_path, "w", encoding="utf-8", newline="") as dst:
            writer = csv.DictWriter(dst, fieldnames=OUTPUT_HEADER)
            writer.writeheader()

            for row in reader:
                rows_in += 1
                inci = (row.get("INCI name") or "").strip().upper()
                if not inci:
                    continue
                writer.writerow(
                    {
                        "inci_name": inci,
                        "cas_number": _first_cas(row.get("CAS No", "")),
                        "einecs_number": _clean_placeholder(row.get("EC No", "")),
                        "function": _clean_placeholder(row.get("Function", "")).title(),
                    }
                )
                rows_out += 1

    return rows_in, rows_out


def main() -> int:
    args = sys.argv[1:]
    src = Path(args[0]) if len(args) >= 1 else DEFAULT_INPUT
    dst = Path(args[1]) if len(args) >= 2 else DEFAULT_OUTPUT

    if not src.exists():
        print(f"Input file not found: {src}", file=sys.stderr)
        return 1

    rows_in, rows_out = convert(src, dst)
    print(f"CosIng converted: {rows_in} source rows -> {rows_out} output rows")
    print(f"Output: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
