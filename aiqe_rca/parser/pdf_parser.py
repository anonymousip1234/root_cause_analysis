"""PDF document parser using pdfplumber."""

import io
import uuid

import pdfplumber

from aiqe_rca.models.evidence import EvidenceElement, SourceType


def parse_pdf(filename: str, content: bytes) -> list[EvidenceElement]:
    """Parse a PDF file into evidence elements.

    Extracts text page-by-page, splitting into paragraph-level elements.
    Also extracts table content if present.
    """
    elements: list[EvidenceElement] = []
    counter = 0

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            # Extract text paragraphs
            text = page.extract_text()
            if text:
                paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
                for para in paragraphs:
                    if len(para) < 10:
                        continue
                    counter += 1
                    elements.append(
                        EvidenceElement(
                            id=f"E-{uuid.uuid5(uuid.NAMESPACE_DNS, f'{filename}-p{page_num}-{counter}')}",
                            source=filename,
                            source_type=SourceType.PDF,
                            text_content=para,
                            page_ref=f"p.{page_num}",
                        )
                    )

            # Extract tables
            tables = page.extract_tables()
            for table_idx, table in enumerate(tables):
                if not table or len(table) < 2:
                    continue
                headers = table[0] if table[0] else []
                for row_idx, row in enumerate(table[1:], start=1):
                    row_text_parts = []
                    for col_idx, cell in enumerate(row):
                        if cell:
                            header = headers[col_idx] if col_idx < len(headers) and headers[col_idx] else f"Col{col_idx+1}"
                            row_text_parts.append(f"{header}: {cell}")
                    row_text = "; ".join(row_text_parts)
                    if len(row_text) < 10:
                        continue
                    counter += 1
                    elements.append(
                        EvidenceElement(
                            id=f"E-{uuid.uuid5(uuid.NAMESPACE_DNS, f'{filename}-p{page_num}-t{table_idx}-r{row_idx}')}",
                            source=filename,
                            source_type=SourceType.PDF,
                            text_content=row_text,
                            page_ref=f"p.{page_num} table {table_idx+1} row {row_idx}",
                        )
                    )

    return elements
