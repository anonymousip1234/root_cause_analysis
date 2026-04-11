"""Report renderer — produces HTML, PDF, and JSON from ReportOutput."""

import base64
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from aiqe_rca.config import settings
from aiqe_rca.models.report import ReportOutput

_LOGO_PATH = Path(__file__).parent / "templates" / "logo.jpg"


def _get_jinja_env() -> Environment:
    """Get Jinja2 environment pointing to report templates."""
    templates_dir = settings.report_templates_dir
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=True,
    )


def _logo_data_uri() -> str:
    """Return the AIQE logo as a base64 data URI for embedding in HTML."""
    if _LOGO_PATH.exists():
        b64 = base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    return ""


def render_html(report: ReportOutput) -> str:
    """Render the report as HTML string using the structured template."""
    env = _get_jinja_env()
    template = env.get_template("report.html")

    logo = _logo_data_uri()
    problem_stmt = ""
    if report.analysis_result:
        problem_stmt = report.analysis_result.problem_statement

    # Get structured template data if available (set by generator)
    tdata = getattr(report, "_template_data", None)

    if tdata:
        return template.render(
            header=report.header,
            logo_data_uri=logo,
            problem_statement=problem_stmt,
            executive_summary_paragraphs=tdata["executive_summary_paragraphs"],
            hypotheses=tdata["hypotheses"],
            why_bullets=tdata["why_bullets"],
            actions_intro=tdata["actions_intro"],
            action_items=tdata["action_items"],
            confidence_statement=tdata["confidence_statement"],
            input_hash=report.input_hash,
            timestamp=report.timestamp,
        )
    else:
        # Fallback: render from flat section content
        exec_paragraphs = report.sections[0].content.split("\n\n") if report.sections else []
        return template.render(
            header=report.header,
            logo_data_uri=logo,
            problem_statement=problem_stmt,
            executive_summary_paragraphs=exec_paragraphs,
            hypotheses=[],
            why_bullets=[],
            actions_intro="",
            action_items=[],
            confidence_statement=report.sections[4].content if len(report.sections) > 4 else "",
            input_hash=report.input_hash,
            timestamp=report.timestamp,
        )


def render_pdf(report: ReportOutput, output_path: Path) -> Path:
    """Render the report as a PDF file."""
    from weasyprint import HTML

    html_content = render_html(report)
    HTML(string=html_content).write_pdf(str(output_path))
    return output_path


def render_json(report: ReportOutput) -> str:
    """Render the report as machine-readable JSON."""
    tdata = getattr(report, "_template_data", {}) or {}
    reasoning_artifact = tdata.get("reasoning_artifact", {})
    analysis = None
    if report.analysis_result:
        analysis = {
            "hypotheses": tdata.get("hypotheses", []),
            "evidence_relationships": tdata.get("relationship_entries", []),
            "contradictions": tdata.get("contradictions", []),
            "gaps": tdata.get("gaps", []),
            "confidence": report.analysis_result.confidence.value,
            "stateless_execution": {
                "isolated_per_request": True,
                "shared_request_context": False,
                "deterministic_input_hash": report.input_hash,
                "confirmation": tdata.get(
                    "stateless_confirmation",
                    "This run used only current input. No prior context reused.",
                ),
            },
        }
    report_dict = {
        "header": {
            "part_process": report.header.part_process,
            "defect_symptom": report.header.defect_symptom,
            "date_range": report.header.date_range,
            "analysis_confidence": report.header.analysis_confidence.value,
        },
        "sections": [
            {"title": s.title, "content": s.content} for s in report.sections
        ],
        "analysis": analysis,
        "reasoning_artifact": reasoning_artifact,
        "evidence_trace_map": report.evidence_trace_map,
        "input_hash": report.input_hash,
        "timestamp": report.timestamp,
    }
    return json.dumps(report_dict, indent=2, ensure_ascii=False)


def save_report(
    report: ReportOutput,
    report_id: str,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Save report in all formats (JSON, HTML, PDF)."""
    out_dir = output_dir or settings.reports_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}

    json_path = out_dir / f"{report_id}.json"
    json_path.write_text(render_json(report), encoding="utf-8")
    paths["json"] = json_path

    html_path = out_dir / f"{report_id}.html"
    html_path.write_text(render_html(report), encoding="utf-8")
    paths["html"] = html_path

    pdf_path = out_dir / f"{report_id}.pdf"
    try:
        render_pdf(report, pdf_path)
        paths["pdf"] = pdf_path
    except Exception:
        # HTML/JSON remain valid deliverables even if native PDF dependencies
        # are unavailable on the host environment.
        pass

    return paths
