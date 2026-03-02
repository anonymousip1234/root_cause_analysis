"""Image parser using OCR (pytesseract + Pillow)."""

import io
import uuid

from aiqe_rca.models.evidence import EvidenceElement, SourceType


def parse_image(filename: str, content: bytes) -> list[EvidenceElement]:
    """Parse an image file (JPG/PNG) into evidence elements via OCR.

    Falls back gracefully if pytesseract/tesseract is not available.
    """
    elements: list[EvidenceElement] = []

    try:
        from PIL import Image
        import pytesseract

        image = Image.open(io.BytesIO(content))
        text = pytesseract.image_to_string(image).strip()

        if text and len(text) >= 10:
            elements.append(
                EvidenceElement(
                    id=f"E-{uuid.uuid5(uuid.NAMESPACE_DNS, f'{filename}-ocr')}",
                    source=filename,
                    source_type=SourceType.IMAGE,
                    text_content=text,
                    page_ref="OCR extraction",
                )
            )
        else:
            # Image present but no readable text extracted
            elements.append(
                EvidenceElement(
                    id=f"E-{uuid.uuid5(uuid.NAMESPACE_DNS, f'{filename}-img-ref')}",
                    source=filename,
                    source_type=SourceType.IMAGE,
                    text_content=f"Image file provided: {filename}. Unable to extract reliably from current inputs.",
                    page_ref="image reference",
                )
            )
    except Exception:
        # Tesseract not installed or image unreadable — graceful fallback
        elements.append(
            EvidenceElement(
                id=f"E-{uuid.uuid5(uuid.NAMESPACE_DNS, f'{filename}-img-fallback')}",
                source=filename,
                source_type=SourceType.IMAGE,
                text_content=f"Image file provided: {filename}. Unable to extract reliably from current inputs.",
                page_ref="image reference (OCR unavailable)",
            )
        )

    return elements
