"""Pydantic request/response models for the FastAPI surface.

These mirror the engine's lookup_panel result shape (with the parser fields
flattened in) plus a base64-encoded .docx for inline download. Vercel
serverless functions don't share memory between invocations, so we don't
keep server-side document state — the bytes ride out in the response.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AnalyzeRequestMetadata(BaseModel):
    product_name: str | None = None
    client_name: str | None = None
    prepared_by: str | None = None
    purpose: str | None = None
    date: str | None = None


class AnalyzeRequest(BaseModel):
    inci_string: str
    metadata: AnalyzeRequestMetadata | None = None


class IngredientResult(BaseModel):
    """A single ingredient row. Tolerates extra parser fields on input."""

    model_config = ConfigDict(extra="ignore")

    position: int
    inci_name: str
    inci_normalized: str
    synonyms: list[str] = []
    function: str | None = None
    function_full: str | None = None
    cas_number: str | None = None
    einecs_number: str | None = None
    verified: bool = False
    verification_note: str | None = None
    source: str = "not_found"


class AnalyzeSummary(BaseModel):
    total: int
    fully_verified: int
    partial: int
    not_found: int


class AnalyzeResponse(BaseModel):
    ingredients: list[IngredientResult]
    summary: AnalyzeSummary
    document_base64: str
