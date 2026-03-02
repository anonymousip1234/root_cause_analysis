"""Plain text file parser."""

import uuid

from aiqe_rca.models.evidence import EvidenceElement, SourceType


def parse_txt(filename: str, content: bytes) -> list[EvidenceElement]:
    """Parse a plain text file into evidence elements.

    Splits on double-newlines into paragraphs. Each paragraph becomes an evidence element.
    """
    elements: list[EvidenceElement] = []
    text = content.decode("utf-8", errors="replace")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    for idx, para in enumerate(paragraphs, start=1):
        if len(para) < 10:
            continue
        elements.append(
            EvidenceElement(
                id=f"E-{uuid.uuid5(uuid.NAMESPACE_DNS, f'{filename}-para-{idx}')}",
                source=filename,
                source_type=SourceType.TXT,
                text_content=para,
                page_ref=f"paragraph {idx}",
            )
        )

    return elements
