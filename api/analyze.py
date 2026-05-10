"""POST /api/analyze — wraps the engine for the web frontend.

Accepts an INCI string (+ optional document metadata), runs parse_inci ->
lookup_panel -> generate_document, and returns the per-ingredient results,
a summary, and the .docx as base64. Document storage is intentionally
client-side: Vercel serverless functions don't share memory across
invocations, so persisting documents server-side would require Redis or
blob storage. For now the bytes ride along in the response so the
frontend can save/download directly.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException

from lib.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    AnalyzeSummary,
    IngredientResult,
)
from src.document import generate_document, simplify_function
from src.lookup import lookup_panel
from src.parser import parse_inci

app = FastAPI()


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    if not request.inci_string.strip():
        raise HTTPException(status_code=400, detail="inci_string cannot be empty")

    parsed = parse_inci(request.inci_string)
    if not parsed:
        raise HTTPException(
            status_code=400,
            detail="No ingredients parsed from inci_string",
        )

    results = lookup_panel(parsed)

    metadata_dict = (
        request.metadata.model_dump(exclude_none=True) if request.metadata else None
    )

    doc_bytes = _render_docx_to_bytes(results, metadata_dict)
    document_base64 = base64.b64encode(doc_bytes).decode("ascii")

    summary = AnalyzeSummary(
        total=len(results),
        fully_verified=sum(1 for r in results if r.get("verified") is True),
        partial=sum(1 for r in results if r.get("source") == "cosing_partial"),
        not_found=sum(1 for r in results if r.get("source") == "not_found"),
    )

    ingredients = [
        IngredientResult.model_validate(_with_simplified_function(r))
        for r in results
    ]

    return AnalyzeResponse(
        ingredients=ingredients,
        summary=summary,
        document_base64=document_base64,
    )


def _with_simplified_function(result: dict) -> dict:
    """Replace `function` with the concise category for API consumers, and
    keep the original CosIng list under `function_full`. Both are None when
    the engine had no function data at all."""
    full = result.get("function")
    if full:
        simplified = simplify_function(full, result.get("inci_name") or "")
    else:
        simplified = None
    return {**result, "function": simplified, "function_full": full}


def _render_docx_to_bytes(results: list[dict], metadata: dict | None) -> bytes:
    """generate_document writes to a path; spool through /tmp and read back.
    Vercel functions get a writable /tmp by default."""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        generate_document(results, tmp_path, metadata)
        return Path(tmp_path).read_bytes()
    finally:
        Path(tmp_path).unlink(missing_ok=True)
