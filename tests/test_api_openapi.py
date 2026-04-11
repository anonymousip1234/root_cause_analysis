"""OpenAPI and API regression tests for multipart upload handling."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aiqe_rca.api.main import app


def test_analyze_openapi_exposes_swagger_file_picker():
    """The analyze endpoint should expose a files array with binary upload for Swagger UI."""
    schema = app.openapi()
    body = schema["paths"]["/analyze"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]
    props = body["properties"]

    assert "files" in props
    assert props["files"]["items"]["format"] == "binary"
    assert props["files"]["type"] == "array"
    assert "problem_statement" in props


def test_analyze_accepts_files_field_upload():
    """Multipart uploads using the documented files field should succeed."""
    client = TestClient(app)

    response = client.post(
        "/analyze",
        data={"problem_statement": "Intermittent chatter marks with coolant flow variation."},
        files=[
            (
                "files",
                (
                    "notes.txt",
                    b"Coolant flow was inconsistent during failing lots. Spindle speed remained within limits.",
                    "text/plain",
                ),
            )
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert "reasoning_artifact" in payload["report_json"]


def test_analyze_accepts_legacy_file_field_upload():
    """The endpoint should also tolerate legacy clients that still send file instead of files."""
    client = TestClient(app)

    response = client.post(
        "/analyze",
        data={"problem_statement": "Intermittent chatter marks with coolant flow variation."},
        files=[
            (
                "file",
                (
                    "notes.txt",
                    b"Coolant flow was inconsistent during failing lots. Spindle speed remained within limits.",
                    "text/plain",
                ),
            )
        ],
    )

    assert response.status_code == 200
