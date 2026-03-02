"""Tests for document parsers."""

import json

from aiqe_rca.parser.csv_parser import parse_csv
from aiqe_rca.parser.json_parser import parse_json
from aiqe_rca.parser.txt_parser import parse_txt


def test_txt_parser_splits_paragraphs():
    content = b"First paragraph with enough text to pass.\n\nSecond paragraph with enough text to pass."
    elements = parse_txt("test.txt", content)
    assert len(elements) == 2
    assert elements[0].source == "test.txt"
    assert "First paragraph" in elements[0].text_content


def test_txt_parser_skips_short():
    content = b"Hi\n\nThis is a longer paragraph that should be included."
    elements = parse_txt("test.txt", content)
    assert len(elements) == 1
    assert "longer paragraph" in elements[0].text_content


def test_csv_parser_basic():
    content = b"Name,Value,Status\nCure Temp,180C,In Control\nCure Time,45min,Out of Spec"
    elements = parse_csv("data.csv", content)
    assert len(elements) == 2
    assert "Cure Temp" in elements[0].text_content
    assert "data.csv" == elements[0].source


def test_csv_parser_deterministic():
    content = b"A,B\nValue1,Value2\nValue3,Value4"
    run1 = parse_csv("test.csv", content)
    run2 = parse_csv("test.csv", content)
    assert [e.id for e in run1] == [e.id for e in run2]


def test_json_parser_array():
    data = [
        {"parameter": "temperature", "value": 180, "status": "in control"},
        {"parameter": "pressure", "value": 5.2, "status": "out of spec"},
    ]
    content = json.dumps(data).encode("utf-8")
    elements = parse_json("data.json", content)
    assert len(elements) == 2
    assert "temperature" in elements[0].text_content


def test_json_parser_object():
    data = {"report": "Lab test results", "finding": "Blistering observed at edges"}
    content = json.dumps(data).encode("utf-8")
    elements = parse_json("report.json", content)
    assert len(elements) == 1
    assert "Blistering" in elements[0].text_content


def test_parser_determinism():
    """Same inputs must always produce same outputs (IDs, order)."""
    content = b"Col1,Col2\nAlpha test data row,Beta test data row\nGamma test data row,Delta test data row"
    results = []
    for _ in range(5):
        elements = parse_csv("determinism.csv", content)
        results.append([e.id for e in elements])
    assert all(r == results[0] for r in results)
