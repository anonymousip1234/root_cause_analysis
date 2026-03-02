"""API request/response Pydantic models."""

from pydantic import BaseModel, Field


class AnalyzeResponse(BaseModel):
    """Response from the /analyze endpoint."""

    report_id: str
    input_hash: str
    confidence: str
    report_json: dict
    files: dict[str, str] = Field(
        default_factory=dict,
        description="Paths to generated report files (json, html, pdf)",
    )


class HealthResponse(BaseModel):
    """Response from the /health endpoint."""

    status: str = "ok"
    version: str = "0.1.0"
    engine: str = "AIQE Phase 2 — Deterministic RCA Engine"


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: str = ""
