"""Parser router — routes files to the correct parser based on extension."""

import logging
from pathlib import Path

from aiqe_rca.models.evidence import EvidenceElement

logger = logging.getLogger(__name__)
from aiqe_rca.parser.csv_parser import parse_csv
from aiqe_rca.parser.docx_parser import parse_docx
from aiqe_rca.parser.image_parser import parse_image
from aiqe_rca.parser.json_parser import parse_json
from aiqe_rca.parser.pdf_parser import parse_pdf
from aiqe_rca.parser.txt_parser import parse_txt
from aiqe_rca.parser.xlsx_parser import parse_xlsx

EXTENSION_MAP = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".xlsx": parse_xlsx,
    ".csv": parse_csv,
    ".txt": parse_txt,
    ".json": parse_json,
    ".jpg": parse_image,
    ".jpeg": parse_image,
    ".png": parse_image,
    ".bmp": parse_image,
    ".tiff": parse_image,
    ".tif": parse_image,
}

SUPPORTED_EXTENSIONS = set(EXTENSION_MAP.keys())


def parse_file(filename: str, content: bytes) -> list[EvidenceElement]:
    """Route a file to the appropriate parser based on its extension.

    Args:
        filename: Original filename (used for extension detection and source tracking).
        content: Raw file bytes.

    Returns:
        List of parsed evidence elements.

    Raises:
        ValueError: If the file extension is not supported.
    """
    ext = Path(filename).suffix.lower()

    if ext not in EXTENSION_MAP:
        raise ValueError(
            f"Unsupported file type: '{ext}'. "
            f"Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    parser_fn = EXTENSION_MAP[ext]
    return parser_fn(filename, content)


def parse_multiple_files(files: dict[str, bytes]) -> list[EvidenceElement]:
    """Parse multiple files and return all evidence elements.

    Individual file parse failures are logged and skipped — they must not
    abort the entire analysis pipeline (Rev-C §13 crash-path hardening).

    Args:
        files: Mapping of filename -> file content bytes.

    Returns:
        Combined list of evidence elements from all successfully parsed files.
    """
    all_elements: list[EvidenceElement] = []
    for filename, content in sorted(files.items()):  # sorted for determinism
        try:
            elements = parse_file(filename, content)
            # Sanitise: ensure text_content is never None (defensive guard)
            for e in elements:
                if e.text_content is None:
                    e.text_content = ""
            all_elements.extend(elements)
        except Exception:
            logger.exception(
                "File parsing failed for '%s' — skipping file, continuing pipeline.",
                filename,
            )
    return all_elements
