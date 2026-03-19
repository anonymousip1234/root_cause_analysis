"""API routes for the AIQE RCA Engine."""

import json
import logging
import smtplib
import uuid
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

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
    problem_statement: str = Form(..., description="Problem description text"),
    files: list[UploadFile] = File(..., description="Documents to analyze"),
):
    """Run a root cause analysis on uploaded documents.

    Accepts multiple files (PDF, DOCX, XLSX, CSV, TXT, JSON, JPG, PNG)
    and a problem statement. Returns a deterministic diagnostic report.
    """
    # Validate files
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required.")

    # Read file contents
    file_contents: dict[str, bytes] = {}
    for f in files:
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


def _send_smtp_email(to_addresses: list[str], subject: str, body: str, attachments: list[tuple[str, bytes]] | None = None):
    """Send an email via SMTP. Raises smtplib.SMTPException on failure."""
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = aws_settings.smtp_sender_email
    msg["To"] = ", ".join(to_addresses)
    msg.attach(MIMEText(body, "plain"))

    for filename, file_bytes in (attachments or []):
        attachment = MIMEApplication(file_bytes)
        attachment.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(attachment)

    with smtplib.SMTP(aws_settings.smtp_host, aws_settings.smtp_port) as server:
        server.starttls()
        server.login(aws_settings.smtp_sender_email, aws_settings.smtp_sender_password)
        server.sendmail(aws_settings.smtp_sender_email, to_addresses, msg.as_string())


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(feedback: FeedbackRequest):
    """Submit feedback for a report and notify admin via email."""
    # Verify the report exists
    report_path = settings.reports_dir / f"{feedback.report_id}.json"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail=f"Report '{feedback.report_id}' not found.")

    # Save feedback to disk
    feedback_id = f"fb-{uuid.uuid4().hex[:12]}"
    feedback_record = {
        "feedback_id": feedback_id,
        "report_id": feedback.report_id,
        "rating": feedback.rating,
        "comment": feedback.comment,
        "submitted_by": feedback.submitted_by,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    feedback_dir = settings.reports_dir / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    feedback_path = feedback_dir / f"{feedback_id}.json"
    feedback_path.write_text(json.dumps(feedback_record, indent=2), encoding="utf-8")

    # Email admins if SMTP is configured
    admin_notified = False
    admin_emails = [
        e.strip() for e in aws_settings.smtp_admin_emails.split(",") if e.strip()
    ]
    if aws_settings.smtp_sender_email and aws_settings.smtp_sender_password and admin_emails:
        try:
            _send_smtp_email(
                to_addresses=admin_emails,
                subject=f"AIQE Feedback: {feedback.report_id} — Rating {feedback.rating}/5",
                body=(
                    f"Report ID: {feedback.report_id}\n"
                    f"Rating: {feedback.rating}/5\n"
                    f"Submitted by: {feedback.submitted_by or 'Anonymous'}\n\n"
                    f"Comment:\n{feedback.comment or '(no comment)'}\n\n"
                    f"Timestamp: {feedback_record['timestamp']}"
                ),
            )
            admin_notified = True
        except smtplib.SMTPException:
            logger.exception("SMTP send failed for feedback %s", feedback_id)

    return FeedbackResponse(
        feedback_id=feedback_id,
        report_id=feedback.report_id,
        admin_notified=admin_notified,
    )


@router.post("/report/{report_id}/email")
async def email_report(report_id: str, req: EmailReportRequest):
    """Send a generated report to recipients via email (SMTP).

    Attaches the report as PDF or HTML.
    """
    if not aws_settings.smtp_sender_email or not aws_settings.smtp_sender_password:
        raise HTTPException(
            status_code=503,
            detail="Email not configured. Set SMTP_SENDER_EMAIL and SMTP_SENDER_PASSWORD in environment.",
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
        _send_smtp_email(
            to_addresses=req.recipient_emails,
            subject=subject,
            body=body_text,
            attachments=[(f"{report_id}.{ext}", report_path.read_bytes())],
        )
    except smtplib.SMTPException as e:
        logger.exception("SMTP send failed for report %s", report_id)
        raise HTTPException(status_code=502, detail=f"Email delivery failed: {e}")

    return {
        "status": "sent",
        "report_id": report_id,
        "recipients": req.recipient_emails,
        "format": ext,
    }
