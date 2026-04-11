# Phase-2 Production Validation

Date: 2026-04-11

## Scope

This validation pass covered:

- deterministic, input-driven hypothesis generation
- explicit evidence tagging with `supporting`, `weakening`, `contradictory`, and `indeterminate`
- contradiction-aware ranking and deprioritization
- separate reasoning artifact output
- stateless execution confirmation
- multipart `/analyze` upload behavior in Swagger-compatible form

## Environment Notes

- Python environment used: `env\Scripts\python.exe`
- `pytest` was not installed in the active environment, so verification was executed through direct module compilation and runtime checks with `fastapi.testclient.TestClient`
- PDF generation is still optional at runtime because `WeasyPrint` native dependencies are not available on this host; JSON and HTML reports are generated successfully

## Verification Steps

1. Syntax validation

Command:

```powershell
env\Scripts\python.exe -m compileall aiqe_rca tests
```

Observed result:

- all updated application and test modules compiled successfully

2. OpenAPI multipart schema validation

Checked the generated schema for `/analyze` and confirmed:

- request content type is `multipart/form-data`
- `problem_statement` is present
- `files` is present
- `files.items.format == binary`

3. API upload validation

Executed `/analyze` with:

- documented field name `files`
- legacy-compatible field name `file`

Observed result:

- `files` upload request returned HTTP `200`
- `file` upload request returned HTTP `200`

4. Deterministic reasoning validation

Input used:

- Problem statement: `Intermittent chatter marks on finished shafts. Spindle speed stayed stable while coolant flow varied between lots.`
- Files:
  - `observations_01.txt`
  - `observations_02.txt`

Observed engine result:

- Primary: `coolant flow`
- Secondary: `coolant delivery fluctuated`
- Conditional amplifier: `chatter marks`
- Deprioritized alternative: `spindle speed`
- Confidence: `Medium`

Observed contradiction handling:

- `spindle speed` was explicitly tagged contradictory because the evidence states it remained within limits
- contradicted hypothesis was not allowed to rank as Primary

Observed artifact completeness:

- `pre_ranking_hypotheses`
- `evidence_classification_table`
- `contradiction_log`
- `gap_log`
- `prioritization_summary`
- `stateless_confirmation`

Observed stateless confirmation:

```text
This run used only current input. No prior context reused.
```

## Output Files

Generated report output from the validated two-file request:

- JSON: [rca-6cb36d576d69.json](/c:/Devlopment/Projects/AIQE/rca/root_cause_analysis/reports/rca-6cb36d576d69.json)
- HTML: [rca-6cb36d576d69.html](/c:/Devlopment/Projects/AIQE/rca/root_cause_analysis/reports/rca-6cb36d576d69.html)

## Output Excerpt

Section: `Most Likely Root Cause Hypotheses`

```text
Primary Contributor: coolant flow (gap severity=0) - Current input repeatedly references coolant flow in connection with the reported issue.
Secondary Contributor: coolant delivery fluctuated (gap severity=0) - Current input repeatedly references coolant delivery fluctuated in connection with the reported issue.
Conditional Amplifier: chatter marks (gap severity=1) - Current input repeatedly references chatter marks in connection with the reported issue.
Deprioritized Alternative: spindle speed (gap severity=3) - Current input repeatedly references spindle speed in connection with the reported issue.
```

## Production-Grade Changes Confirmed

- `/analyze` no longer relies on FastAPI body coercion for uploaded files; it parses multipart form data directly and still documents the `files` upload field explicitly for Swagger
- hypothesis generation no longer uses domain templates or prior canonical vocabulary
- evidence tagging is now explicit per evidence-hypothesis pair
- contradiction counts now penalize ranking and block contradicted Primaries when non-contradicted alternatives exist
- reasoning artifact is now returned as a separate top-level output object instead of being embedded inside the report narrative
- report generation now validates that hypothesis names and artifact hypothesis terms are traceable to current input before returning output
