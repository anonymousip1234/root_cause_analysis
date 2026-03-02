"""API routes for the AIQE RCA Engine."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from aiqe_rca.api.schemas import AnalyzeResponse, ErrorResponse, HealthResponse
from aiqe_rca.audit.hasher import compute_input_hash
from aiqe_rca.audit.trace_map import build_audit_record
from aiqe_rca.config import settings
from aiqe_rca.engine.pipeline import run_analysis
from aiqe_rca.parser.router import SUPPORTED_EXTENSIONS
from aiqe_rca.report.generator import generate_report
from aiqe_rca.report.renderer import render_json, save_report

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
