"""Evidence trace map — maps source documents to report output.

Provides an audit trail: source file → evidence elements → report sections
where each piece of evidence is referenced.
"""

from aiqe_rca.models.audit import AuditRecord, TraceEntry
from aiqe_rca.models.report import ReportOutput


def build_trace_map(report: ReportOutput) -> list[TraceEntry]:
    """Build a trace map from the report's evidence trace map.

    For each source file, identifies which evidence elements were extracted
    and which report sections reference them.

    Args:
        report: The generated report with evidence_trace_map populated.

    Returns:
        List of TraceEntry objects for the audit record.
    """
    entries: list[TraceEntry] = []

    for source_file, evidence_ids in sorted(report.evidence_trace_map.items()):
        # Find which sections reference these evidence IDs
        report_refs: list[str] = []
        for section in report.sections:
            for eid in evidence_ids:
                if eid in section.content:
                    report_refs.append(f"{section.title}:{eid}")

        entries.append(
            TraceEntry(
                source_file=source_file,
                evidence_ids=evidence_ids,
                report_references=report_refs,
            )
        )

    return entries


def build_audit_record(
    report: ReportOutput,
    file_manifest: list[str],
) -> AuditRecord:
    """Build a complete audit record for the analysis.

    Args:
        report: The generated report.
        file_manifest: Ordered list of input filenames.

    Returns:
        AuditRecord with hash, timestamp, trace map, and manifest.
    """
    trace_map = build_trace_map(report)

    return AuditRecord(
        input_hash=report.input_hash,
        timestamp=report.timestamp,
        trace_map=trace_map,
        file_manifest=file_manifest,
    )
