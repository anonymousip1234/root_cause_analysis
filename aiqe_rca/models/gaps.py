"""Data gap detection models."""

from enum import Enum

from pydantic import BaseModel, Field

from aiqe_rca.models.evidence import EvidenceCategory


class GapSeverity(str, Enum):
    """Severity of missing evidence."""

    CRITICAL = "critical"  # Entire category missing
    MODERATE = "moderate"  # Category present but incomplete
    MINOR = "minor"  # Category present, minor sub-area missing


class DataGap(BaseModel):
    """A detected gap in the evidence — expected but missing or incomplete data."""

    category: EvidenceCategory
    description: str = Field(description="Short label describing what is missing")
    severity: GapSeverity
    affects_hypotheses: list[str] = Field(
        default_factory=list,
        description="IDs of hypotheses materially affected by this gap",
    )
