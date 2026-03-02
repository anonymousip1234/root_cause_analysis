"""Input hashing for auditability and replayability.

Produces a deterministic SHA-256 hash of all inputs (files + problem statement)
so that identical inputs can be verified to produce identical outputs.
"""

import hashlib


def compute_input_hash(
    problem_statement: str,
    files: dict[str, bytes],
) -> str:
    """Compute SHA-256 hash of all analysis inputs.

    Inputs are processed in a deterministic order:
    1. Problem statement (UTF-8 encoded)
    2. Files sorted by filename, each contributing filename + content

    Args:
        problem_statement: User-provided problem description.
        files: Mapping of filename -> file content bytes.

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    hasher = hashlib.sha256()

    # Hash problem statement
    hasher.update(problem_statement.encode("utf-8"))

    # Hash files in sorted order for determinism
    for filename in sorted(files.keys()):
        hasher.update(filename.encode("utf-8"))
        hasher.update(files[filename])

    return hasher.hexdigest()
