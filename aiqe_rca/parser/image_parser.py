"""Image parser using OCR (pytesseract + Pillow).

When OCR is unavailable or extracts no readable text, the parser enriches
the fallback evidence element with signal words extracted from the filename
so the element can still participate in evidence association and classification.
"""

import io
import re
import uuid
from pathlib import Path

from aiqe_rca.models.evidence import EvidenceElement, SourceType


def _extract_filename_signals(filename: str) -> list[str]:
    """Extract meaningful signal words from the image filename."""
    stem = Path(filename).stem.lower()
    # Split on common separators
    words = re.split(r"[_\-\s.]+", stem)
    # Filter trivial / non-informative tokens
    stopwords = {
        "img", "image", "photo", "pic", "picture", "file", "scan",
        "jpeg", "jpg", "png", "bmp", "tiff", "tif",
        "001", "002", "003", "0001", "temp", "copy", "new",
    }
    return [w for w in words if len(w) >= 4 and w not in stopwords]


def _build_fallback_text(filename: str) -> str:
    """Build enriched fallback evidence text from filename signals."""
    signals = _extract_filename_signals(filename)
    if signals:
        signal_context = f"Filename signals: {', '.join(signals)}."
    else:
        signal_context = ""
    parts = [
        f"Visual observation submitted: {filename}.",
        signal_context,
        "Image provided for analysis — no text content extracted.",
    ]
    return " ".join(p for p in parts if p)


def parse_image(filename: str, content: bytes) -> list[EvidenceElement]:
    """Parse an image file (JPG/PNG) into evidence elements via OCR.

    Falls back gracefully if pytesseract/tesseract is not available.
    Even when OCR fails, produces an evidence element enriched with
    filename-derived signals so the image can participate in classification.
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
            # OCR ran but found nothing readable — enrich with filename signals
            elements.append(
                EvidenceElement(
                    id=f"E-{uuid.uuid5(uuid.NAMESPACE_DNS, f'{filename}-img-ref')}",
                    source=filename,
                    source_type=SourceType.IMAGE,
                    text_content=_build_fallback_text(filename),
                    page_ref="image reference",
                )
            )
    except Exception:
        # Tesseract not installed or image unreadable — graceful fallback with filename signals
        elements.append(
            EvidenceElement(
                id=f"E-{uuid.uuid5(uuid.NAMESPACE_DNS, f'{filename}-img-fallback')}",
                source=filename,
                source_type=SourceType.IMAGE,
                text_content=_build_fallback_text(filename),
                page_ref="image reference (OCR unavailable)",
            )
        )

    return elements
