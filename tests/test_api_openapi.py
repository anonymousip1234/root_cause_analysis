"""OpenAPI regression tests for API request schemas."""

from aiqe_rca.api.main import app


def test_analyze_openapi_exposes_swagger_file_picker():
    """The analyze endpoint should expose a direct binary file field for Swagger UI."""
    schema = app.openapi()
    body = schema["components"]["schemas"]["Body_analyze_analyze_post"]
    props = body["properties"]

    assert "file" in props
    assert props["file"]["anyOf"][0]["format"] == "binary"
    assert "files" in props
    assert props["files"]["anyOf"][0]["items"]["format"] == "binary"
