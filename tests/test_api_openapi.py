"""OpenAPI regression tests for API request schemas."""

from aiqe_rca.api.main import app


def test_analyze_openapi_exposes_swagger_file_picker():
    """The analyze endpoint should expose a files array with binary upload for Swagger UI."""
    schema = app.openapi()
    body = schema["components"]["schemas"]["Body_analyze_analyze_post"]
    props = body["properties"]

    assert "files" in props
    assert props["files"]["items"]["format"] == "binary"
    assert props["files"]["type"] == "array"
    assert "problem_statement" in props
