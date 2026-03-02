"""CSV file parser."""

import csv
import io
import uuid

from aiqe_rca.models.evidence import EvidenceElement, SourceType


def parse_csv(filename: str, content: bytes) -> list[EvidenceElement]:
    """Parse a CSV file into evidence elements.

    Uses first row as headers. Each data row becomes one evidence element.
    """
    elements: list[EvidenceElement] = []
    counter = 0

    text = content.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    if len(rows) < 2:
        return elements

    headers = [h.strip() if h.strip() else f"Col{i+1}" for i, h in enumerate(rows[0])]

    for row_idx, row in enumerate(rows[1:], start=2):
        parts = []
        for col_idx, cell_val in enumerate(row):
            if cell_val and cell_val.strip():
                header = headers[col_idx] if col_idx < len(headers) else f"Col{col_idx+1}"
                parts.append(f"{header}: {cell_val.strip()}")
        row_text = "; ".join(parts)
        if len(row_text) < 10:
            continue
        counter += 1
        elements.append(
            EvidenceElement(
                id=f"E-{uuid.uuid5(uuid.NAMESPACE_DNS, f'{filename}-r{row_idx}')}",
                source=filename,
                source_type=SourceType.CSV,
                text_content=row_text,
                page_ref=f"row {row_idx}",
            )
        )

    return elements
