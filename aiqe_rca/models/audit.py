"""Audit and traceability models."""

from pydantic import BaseModel, Field


class TraceEntry(BaseModel):
    """Maps a source document to evidence elements to report bullets."""

    source_file: str
    evidence_ids: list[str] = Field(default_factory=list)
    report_references: list[str] = Field(
        default_factory=list,
        description="Section + bullet identifiers where this evidence appears",
    )


class AuditRecord(BaseModel):
    """Audit trail for replayability and verification."""

    input_hash: str = Field(description="SHA-256 of all input files + problem statement")
    timestamp: str = Field(description="ISO 8601 timestamp")
    trace_map: list[TraceEntry] = Field(default_factory=list)
    file_manifest: list[str] = Field(
        default_factory=list, description="Ordered list of input filenames"
    )
