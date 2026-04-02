# Canonical Test 1 Validation

Date: 2026-04-02

## Input Set

- Problem statement: intermittent rubber-to-metal bond failures with blistering near edges, no recorded cure-time or cure-temperature changes, mostly Line 2 / 2nd shift.
- Documents:
  - `docs/Test01_LabTestReport.docx`
  - `docs/Test01_PFMEA.pdf`

## Expected Canonical Behaviors

- Primary contributor ranks as upstream surface / adhesive condition variation.
- Secondary contributor ranks as geometry-driven adhesive coverage variability.
- Environmental exposure / storage conditions are treated as an amplifier.
- Cure variation and press/tool variation are explicitly weakened.
- Evidence relationships are explicitly tagged as `supporting`, `weakening`, `contradicting`, or `indeterminate`.
- Contradictions and confidence-limiting gaps are surfaced explicitly.
- Overall confidence is `Medium`.
- Output is deterministic and stateless across repeated runs.

## Actual Result

- Primary contributor: `Upstream Surface / Adhesive Condition Variation`
- Secondary contributor: `Adhesive Coverage Variability at Geometry-Challenged Regions`
- Conditional amplifier: `Environmental Exposure / Storage Conditions`
- Deprioritized alternative: `Process Parameter Variation`
- Confidence: `Medium`

## Explicitly Surfaced False-Lead Weakening

- Stable cure parameters weaken a primary cure-variation explanation because the defect remains intermittent across lots.
- Multi-tool and multi-lot occurrence weakens a press, cavity, or equipment-only explanation.

## Explicitly Surfaced Gaps

- Adhesive handling variability is referenced, but lot-by-lot exposure time or open-container duration is not directly logged.
- Storage / staging conditions appear relevant, but there is no direct lot-level tracking of dwell time or location before molding.
- Environmental humidity exposure is plausible from the inputs, but no direct humidity or ambient-condition monitoring data was provided.
- Adhesive coverage verification is limited to visual checks; quantitative coverage or thickness confirmation is not available.

## Determinism / Statelessness Checks

- `pytest` suite result: `33 passed`
- Canonical Test 1 integration assertions verify repeated-run determinism.
- Machine-readable report JSON includes:
  - `analysis.stateless_execution.isolated_per_request = true`
  - `analysis.stateless_execution.shared_request_context = false`
- Evidence association now falls back to deterministic offline lexical matching when the local embedding model is unavailable, so no network state or model-download behavior is required for a canonical run.

## Generated Output Artifacts

- JSON: `reports/canonical-test01-824897da97e4.json`
- HTML: `reports/canonical-test01-824897da97e4.html`

## Environment Note

- PDF generation was not produced on this machine because WeasyPrint's native dependency `libgobject-2.0-0` is not installed in the Windows environment.
- JSON and HTML outputs were generated successfully, and report saving now degrades gracefully when PDF-native libraries are unavailable.
