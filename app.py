"""AIQE RCA Engine — FastAPI application."""

import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from aiqe_rca.audit.hasher import compute_input_hash
from aiqe_rca.config import aws_settings
from aiqe_rca.engine.pipeline import run_analysis
from aiqe_rca.report.generator import generate_report
from aiqe_rca.report.renderer import render_html, render_json

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AIQE Root Cause Analysis Engine",
    version="0.1.0",
    description="Deterministic root cause analysis from uploaded quality documents.",
)

ALLOWED_EXTENSIONS = {".docx", ".pdf", ".xlsx", ".csv", ".txt"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB per file


def _get_s3_client():
    """Create an S3 client from configured credentials."""
    if not aws_settings.aws_access_key_id or not aws_settings.aws_s3_bucket:
        return None
    return boto3.client(
        "s3",
        aws_access_key_id=aws_settings.aws_access_key_id,
        aws_secret_access_key=aws_settings.aws_secret_access_key,
        region_name=aws_settings.aws_region,
    )


def _upload_to_s3(content: bytes, key: str, content_type: str) -> str | None:
    """Upload bytes to S3 and return a presigned download URL (1-hour expiry)."""
    client = _get_s3_client()
    if not client:
        return None
    try:
        client.put_object(
            Bucket=aws_settings.aws_s3_bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": aws_settings.aws_s3_bucket, "Key": key},
            ExpiresIn=3600,
        )
        return url
    except ClientError:
        logger.exception("S3 upload failed for key=%s", key)
        return None


def _validate_files(files: list[UploadFile]) -> None:
    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{ext}'. Allowed: {ALLOWED_EXTENSIONS}",
            )


@app.get("/health")
async def health():
    s3_ok = _get_s3_client() is not None
    return {"status": "ok", "s3_configured": s3_ok}


@app.post("/analyze")
async def analyze(
    problem_statement: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
    output_format: Annotated[str, Form()] = "json",
):
    """Run RCA analysis on uploaded documents.

    Args:
        problem_statement: Description of the quality problem.
        files: One or more quality documents (.docx, .pdf, .xlsx, .csv).
        output_format: Response format — "json", "html", or "pdf".

    Returns:
        Analysis report in the requested format.
        If S3 is configured, also uploads PDF/HTML and returns download URLs.
    """
    if not problem_statement.strip():
        raise HTTPException(status_code=400, detail="problem_statement is required.")

    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required.")

    _validate_files(files)

    # Read uploaded files into memory
    file_map: dict[str, bytes] = {}
    for f in files:
        content = await f.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File '{f.filename}' exceeds {MAX_FILE_SIZE // (1024*1024)}MB limit.",
            )
        file_map[f.filename] = content

    # Run pipeline
    try:
        result = run_analysis(problem_statement, file_map)
    except Exception:
        logger.exception("Pipeline failed")
        raise HTTPException(status_code=500, detail="Analysis pipeline failed.")

    input_hash = compute_input_hash(problem_statement, file_map)
    timestamp = datetime.now(timezone.utc).isoformat()
    report = generate_report(result, input_hash, timestamp)
    report_id = f"rca_{input_hash[:12]}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    # Generate PDF bytes (used for both direct return and S3 upload)
    html_content = render_html(report)
    from weasyprint import HTML
    pdf_buf = io.BytesIO()
    HTML(string=html_content).write_pdf(pdf_buf)
    pdf_bytes = pdf_buf.getvalue()

    # Upload to S3 if configured
    s3_urls = {}
    pdf_url = _upload_to_s3(pdf_bytes, f"reports/{report_id}.pdf", "application/pdf")
    if pdf_url:
        s3_urls["pdf"] = pdf_url
    html_url = _upload_to_s3(
        html_content.encode("utf-8"), f"reports/{report_id}.html", "text/html"
    )
    if html_url:
        s3_urls["html"] = html_url
    json_str = render_json(report)
    json_url = _upload_to_s3(
        json_str.encode("utf-8"), f"reports/{report_id}.json", "application/json"
    )
    if json_url:
        s3_urls["json"] = json_url

    # Return in requested format
    if output_format == "pdf":
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={report_id}.pdf"},
        )

    if output_format == "html":
        return StreamingResponse(
            io.BytesIO(html_content.encode("utf-8")),
            media_type="text/html",
        )

    # Default: JSON
    return JSONResponse(content={
        "report_id": report_id,
        "input_hash": input_hash,
        "timestamp": timestamp,
        "header": {
            "part_process": report.header.part_process,
            "defect_symptom": report.header.defect_symptom,
            "date_range": report.header.date_range,
            "analysis_confidence": report.header.analysis_confidence.value,
        },
        "sections": [
            {"title": s.title, "content": s.content} for s in report.sections
        ],
        "evidence_trace_map": report.evidence_trace_map,
        "s3_urls": s3_urls,
    })
