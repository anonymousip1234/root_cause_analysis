"""Evidence element data models."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EvidenceCategory(str, Enum):
    """5-category evidence schema for gap detection."""

    DESIGN_REQUIREMENTS = "DR"  # DFMEA, specs, drawings
    PROCESS_CONTROL = "PC"  # Control plan, work instructions
    PERFORMANCE_VARIATION = "PV"  # SPC, yield trends
    DETECTION_AUDIT = "DA"  # Inspection plans, audit results
    RESPONSE_CORRECTIVE = "RC"  # Containment, rework response
    UNCATEGORIZED = "UN"


class SourceType(str, Enum):
    """Type of source document."""

    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    CSV = "csv"
    TXT = "txt"
    JSON = "json"
    IMAGE = "image"


class EvidenceElement(BaseModel):
    """A discrete piece of evidence extracted from an uploaded document."""

    id: str = Field(description="Unique evidence element ID (e.g., E001)")
    source: str = Field(description="Source filename")
    source_type: SourceType
    text_content: str = Field(description="Extracted text content or description")
    category: EvidenceCategory = EvidenceCategory.UNCATEGORIZED
    page_ref: Optional[str] = Field(
        default=None, description="Page, row, or table reference within source"
    )

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EvidenceElement):
            return False
        return self.id == other.id
