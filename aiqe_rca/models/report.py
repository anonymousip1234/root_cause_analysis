"""Report output data models."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from aiqe_rca.models.alignment import AlignmentResult
from aiqe_rca.models.evidence import EvidenceElement
from aiqe_rca.models.gaps import DataGap
from aiqe_rca.models.hypothesis import Hypothesis


class ConfidenceLevel(str, Enum):
    """Qualitative confidence levels — no percentages or scores."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class ReportHeader(BaseModel):
    """Display fields at the top of the report."""

    part_process: str = "Not available from current inputs."
    defect_symptom: str = "Not available from current inputs."
    date_range: str = "Not available from current inputs."
    analysis_confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


class AnalysisResult(BaseModel):
    """Complete output of the deterministic engine pipeline (pre-report)."""

    evidence_elements: list[EvidenceElement]
    pre_ranking_hypotheses: list[Hypothesis] = Field(default_factory=list)
    hypotheses: list[Hypothesis]
    alignments: list[AlignmentResult]
    gaps: list[DataGap]
    confidence: ConfidenceLevel
    header: ReportHeader
    problem_statement: str


class ReportSection(BaseModel):
    """A single section of the rendered report."""

    title: str
    content: str  # Rendered text for this section


class ReportOutput(BaseModel):
    """Final report deliverable."""

    header: ReportHeader
    sections: list[ReportSection]
    evidence_trace_map: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Mapping: source filename -> list of report bullet IDs referencing it",
    )
    input_hash: str = Field(description="SHA-256 hash of all inputs")
    timestamp: str = Field(description="ISO 8601 timestamp of report generation")
    analysis_result: Optional[AnalysisResult] = Field(
        default=None, description="Full engine output for machine-readable JSON"
    )
