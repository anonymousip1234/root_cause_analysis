"""JSON file parser."""

import json
import uuid

from aiqe_rca.models.evidence import EvidenceElement, SourceType


def _flatten_json(obj: object, prefix: str = "") -> list[str]:
    """Recursively flatten a JSON object into key: value strings."""
    results: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            new_prefix = f"{prefix}.{key}" if prefix else key
            results.extend(_flatten_json(value, new_prefix))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            new_prefix = f"{prefix}[{idx}]"
            results.extend(_flatten_json(item, new_prefix))
    else:
        val_str = str(obj).strip()
        if val_str:
            results.append(f"{prefix}: {val_str}")
    return results


def parse_json(filename: str, content: bytes) -> list[EvidenceElement]:
    """Parse a JSON file into evidence elements.

    Flattens the JSON structure and groups related fields into evidence elements.
    """
    elements: list[EvidenceElement] = []
    text = content.decode("utf-8", errors="replace")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return elements

    if isinstance(data, list):
        # Array of records — each record becomes an evidence element
        for idx, record in enumerate(data):
            flat = _flatten_json(record)
            record_text = "; ".join(flat)
            if len(record_text) < 10:
                continue
            elements.append(
                EvidenceElement(
                    id=f"E-{uuid.uuid5(uuid.NAMESPACE_DNS, f'{filename}-rec-{idx}')}",
                    source=filename,
                    source_type=SourceType.JSON,
                    text_content=record_text,
                    page_ref=f"record [{idx}]",
                )
            )
    elif isinstance(data, dict):
        # Single object — flatten into one evidence element
        flat = _flatten_json(data)
        full_text = "; ".join(flat)
        if len(full_text) >= 10:
            elements.append(
                EvidenceElement(
                    id=f"E-{uuid.uuid5(uuid.NAMESPACE_DNS, f'{filename}-root')}",
                    source=filename,
                    source_type=SourceType.JSON,
                    text_content=full_text,
                    page_ref="root object",
                )
            )

    return elements
