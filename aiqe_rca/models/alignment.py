"""Alignment classification data models."""

from enum import Enum

from pydantic import BaseModel, Field


class AlignmentLabel(str, Enum):
    """Evidence-to-hypothesis relationship classification."""

    SUPPORTING = "supporting"
    WEAKENING = "weakening"
    CONTRADICTING = "contradictory"
    INDETERMINATE = "indeterminate"


class AlignmentResult(BaseModel):
    """Classification of the relationship between a hypothesis and an evidence element."""

    hypothesis_id: str
    evidence_id: str
    classification: AlignmentLabel
    rationale: str = Field(description="Short explanation of why this classification was assigned")
