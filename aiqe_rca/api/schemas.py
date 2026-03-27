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


class FeedbackRequest(BaseModel):
    """Request body for submitting feedback."""

    comment: str = Field(..., max_length=2000, description="Feedback comment")


class FeedbackResponse(BaseModel):
    """Response after feedback submission."""

    feedback_id: str
    admin_notified: bool


class EmailReportRequest(BaseModel):
    """Request body for emailing a report."""

    recipient_emails: list[str] = Field(..., min_length=1, description="Email addresses to send the report to")
    subject: str = Field(default="", description="Custom email subject (optional)")
    message: str = Field(default="", description="Optional message body to include")
    format: str = Field(default="pdf", description="Report format to attach: pdf or html")
