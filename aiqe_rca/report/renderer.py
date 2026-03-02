"""Report renderer — produces HTML, PDF, and JSON from ReportOutput."""

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from aiqe_rca.config import settings
from aiqe_rca.models.report import ReportOutput


def _get_jinja_env() -> Environment:
    """Get Jinja2 environment pointing to report templates."""
    templates_dir = settings.report_templates_dir
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=True,
    )


def render_html(report: ReportOutput) -> str:
    """Render the report as HTML string using the structured template."""
    env = _get_jinja_env()
    template = env.get_template("report.html")

    # Get structured template data if available (set by generator)
    tdata = getattr(report, "_template_data", None)

    if tdata:
        return template.render(
            header=report.header,
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
    render_pdf(report, pdf_path)
    paths["pdf"] = pdf_path

    return paths
