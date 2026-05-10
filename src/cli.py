"""CLI entry point: INCI string in -> verified .docx out.

Usage:
    python -m src.cli "Water, Glycerin, ..." \\
        --output output/result.docx \\
        --product "Vitasana Body Wash" \\
        --client "Vitasana" \\
        --prepared-by "117 Holdings LLC" \\
        --purpose "EWG Verified submission support"
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from src.document import generate_document
from src.lookup import lookup_panel
from src.parser import parse_inci

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="src.cli",
        description="Generate a regulatory CAS reference .docx from an INCI panel.",
    )
    parser.add_argument(
        "inci",
        help="INCI panel string (comma- or newline-separated ingredients)",
    )
    parser.add_argument(
        "--output",
        help=(
            "Output .docx path. Defaults to "
            "output/cas-reference-<timestamp>.docx in the project root."
        ),
    )
    parser.add_argument("--product", help="Product name (e.g. 'Vitasana Body Wash')")
    parser.add_argument("--client", help="Client name (e.g. 'Vitasana')")
    parser.add_argument("--prepared-by", help="Prepared-by org (e.g. '117 Holdings LLC')")
    parser.add_argument("--purpose", help="Purpose of the document")

    args = parser.parse_args(argv)

    if args.output:
        output_path = args.output
    else:
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = str(DEFAULT_OUTPUT_DIR / f"cas-reference-{timestamp}.docx")

    metadata = {
        k: v
        for k, v in {
            "product_name": args.product,
            "client_name": args.client,
            "prepared_by": args.prepared_by,
            "purpose": args.purpose,
        }.items()
        if v
    }

    try:
        parsed = parse_inci(args.inci)
        results = lookup_panel(parsed)
        path = generate_document(results, output_path, metadata or None)
    except Exception as exc:  # last-resort guard so the CLI exits 1 cleanly
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    total = len(results)
    fully_verified = sum(1 for r in results if r.get("verified") is True)
    partial = sum(1 for r in results if r.get("source") == "cosing_partial")
    not_found = sum(1 for r in results if r.get("source") == "not_found")

    print(f"Total ingredients:                {total}")
    print(f"Fully verified (CAS confirmed):   {fully_verified}")
    print(f"Partial (CosIng entry, no CAS):   {partial}")
    print(f"Not found:                        {not_found}")
    print(f"Output: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
