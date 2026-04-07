"""API routes for the AIQE RCA Engine."""

import base64
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from aiqe_rca.api.schemas import (
    AnalyzeResponse,
    EmailReportRequest,
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
)
from aiqe_rca.audit.hasher import compute_input_hash
from aiqe_rca.audit.trace_map import build_audit_record
from aiqe_rca.config import aws_settings, settings
from aiqe_rca.engine.pipeline import run_analysis
from aiqe_rca.parser.router import SUPPORTED_EXTENSIONS
from aiqe_rca.report.generator import generate_report
from aiqe_rca.report.renderer import render_json, save_report

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    problem_statement: Annotated[
        str,
        Form(..., description="Problem description text"),
    ],
    files: Annotated[
        list[UploadFile],
        File(description="Documents to analyze. Upload one or more files (PDF, DOCX, XLSX, CSV, TXT, JSON, JPG, PNG)."),
    ],
):
    """Run a root cause analysis on uploaded documents.

    Accepts multiple files (PDF, DOCX, XLSX, CSV, TXT, JSON, JPG, PNG)
    and a problem statement. Returns a deterministic diagnostic report.
    """
    uploaded_files: list[UploadFile] = [f for f in files if f.filename]

    # Validate files
    if not uploaded_files:
        raise HTTPException(status_code=400, detail="At least one file is required.")

    # Read file contents
    file_contents: dict[str, bytes] = {}
    for f in uploaded_files:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
            )
        content = await f.read()
        file_contents[f.filename] = content

    if not file_contents:
        raise HTTPException(status_code=400, detail="No valid files provided.")

    # Compute input hash
    input_hash = compute_input_hash(problem_statement, file_contents)
    timestamp = datetime.now(timezone.utc).isoformat()
    report_id = f"rca-{uuid.uuid5(uuid.NAMESPACE_DNS, input_hash).hex[:12]}"

    # Run deterministic analysis pipeline
    try:
        analysis_result = run_analysis(problem_statement, file_contents)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Analysis engine error: {str(e)}",
        )

    # Generate report
    report = generate_report(analysis_result, input_hash, timestamp)

    # Save report files
    try:
        file_paths = save_report(report, report_id)
        paths_str = {fmt: str(p) for fmt, p in file_paths.items()}
    except Exception:
        paths_str = {}

    # Build audit record
    audit_record = build_audit_record(report, sorted(file_contents.keys()))

    # Save audit record
    audit_dir = settings.reports_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / f"{report_id}_audit.json"
    audit_path.write_text(
        audit_record.model_dump_json(indent=2), encoding="utf-8"
    )

    # Parse report JSON for response
    report_json_str = render_json(report)
    report_json_dict = json.loads(report_json_str)

    return AnalyzeResponse(
        report_id=report_id,
        input_hash=input_hash,
        confidence=analysis_result.confidence.value,
        report_json=report_json_dict,
        files=paths_str,
    )


@router.get("/report/{report_id}")
async def get_report(report_id: str, format: str = "json"):
    """Retrieve a previously generated report by ID.

    Args:
        report_id: The report identifier returned from /analyze.
        format: Output format — "json", "html", or "pdf".
    """
    reports_dir = settings.reports_dir

    if format == "json":
        path = reports_dir / f"{report_id}.json"
    elif format == "html":
        path = reports_dir / f"{report_id}.html"
    elif format == "pdf":
        path = reports_dir / f"{report_id}.pdf"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")

    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found.")

    if format == "pdf":
        from fastapi.responses import FileResponse

        return FileResponse(path, media_type="application/pdf", filename=f"{report_id}.pdf")
    elif format == "html":
        from fastapi.responses import HTMLResponse

        return HTMLResponse(content=path.read_text(encoding="utf-8"))
    else:
        return json.loads(path.read_text(encoding="utf-8"))


def _send_email(to_addresses: list[str], subject: str, body: str, attachments: list[tuple[str, bytes]] | None = None):
    """Send an email via SendGrid API. Raises on failure."""
    import httpx

    msg = {
        "personalizations": [{"to": [{"email": addr} for addr in to_addresses]}],
        "from": {"email": aws_settings.sendgrid_from_email},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }

    if attachments:
        msg["attachments"] = [
            {
                "content": base64.b64encode(file_bytes).decode("ascii"),
                "filename": filename,
                "type": "application/pdf" if filename.endswith(".pdf") else "text/html",
                "disposition": "attachment",
            }
            for filename, file_bytes in attachments
        ]

    resp = httpx.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {aws_settings.sendgrid_api_key}",
            "Content-Type": "application/json",
        },
        json=msg,
        timeout=30,
    )
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"SendGrid error {resp.status_code}: {resp.text}")


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(feedback: FeedbackRequest):
    """Submit general feedback and notify admin via email."""
    feedback_id = f"fb-{uuid.uuid4().hex[:12]}"
    feedback_record = {
        "feedback_id": feedback_id,
        "comment": feedback.comment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    feedback_dir = settings.reports_dir / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    feedback_path = feedback_dir / f"{feedback_id}.json"
    feedback_path.write_text(json.dumps(feedback_record, indent=2), encoding="utf-8")

    # Email admins if SendGrid is configured
    admin_notified = False
    admin_emails = [
        e.strip() for e in aws_settings.sendgrid_to_email.split(",") if e.strip()
    ]
    if aws_settings.sendgrid_api_key and aws_settings.sendgrid_from_email and admin_emails:
        try:
            _send_email(
                to_addresses=admin_emails,
                subject=f"AIQE Feedback: {feedback_id}",
                body=(
                    f"Comment:\n{feedback.comment}\n\n"
                    f"Timestamp: {feedback_record['timestamp']}"
                ),
            )
            admin_notified = True
        except Exception:
            logger.exception("SendGrid send failed for feedback %s", feedback_id)

    return FeedbackResponse(
        feedback_id=feedback_id,
        admin_notified=admin_notified,
    )


@router.post("/report/{report_id}/email")
async def email_report(report_id: str, req: EmailReportRequest):
    """Send a generated report to recipients via email (SMTP).

    Attaches the report as PDF or HTML.
    """
    if not aws_settings.sendgrid_api_key or not aws_settings.sendgrid_from_email:
        raise HTTPException(
            status_code=503,
            detail="Email not configured. Set SENDGRID_API_KEY and SENDGRID_FROM_EMAIL in environment.",
        )

    # Resolve the report file
    ext = "pdf" if req.format == "pdf" else "html"
    report_path = settings.reports_dir / f"{report_id}.{ext}"
    if not report_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Report '{report_id}' not found in {ext} format.",
        )

    subject = req.subject or f"AIQE Root Cause Analysis Report — {report_id}"
    body_text = req.message or "Please find the attached AIQE RCA report."

    try:
        _send_email(
            to_addresses=req.recipient_emails,
            subject=subject,
            body=body_text,
            attachments=[(f"{report_id}.{ext}", report_path.read_bytes())],
        )
    except Exception as e:
        logger.exception("SendGrid send failed for report %s", report_id)
        raise HTTPException(status_code=502, detail=f"Email delivery failed: {e}")

    return {
        "status": "sent",
        "report_id": report_id,
        "recipients": req.recipient_emails,
        "format": ext,
    }
