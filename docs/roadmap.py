"""Generate AIQE Phase 2 Roadmap PDF"""
import markdown
from weasyprint import HTML

md_content = """
# AIQE Phase 2 — Root Cause Analysis Engine: Build Roadmap

---

## Decisions Locked

| Decision | Choice |
|----------|--------|
| Report structure | 5 sections (Test Case format) |
| Deliverable | Engine + REST API (no frontend UI) |
| Evidence matching | Fixed local embeddings + keyword rules |
| Tech stack | Python (FastAPI) |

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                    REST API (FastAPI)                 │
│         /analyze   /health   /report/{id}            │
└──────────────────┬───────────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────────┐
│              ORCHESTRATOR (pipeline.py)               │
│  Coordinates the deterministic flow, step by step    │
└──┬────────┬────────┬────────┬────────┬───────────────┘
   │        │        │        │        │
   ▼        ▼        ▼        ▼        ▼
┌──────┐┌───────┐┌───────┐┌───────┐┌───────────────┐
│PARSER││EVIDENCE││HYPOTHE││RANKING││REPORT         │
│      ││ASSOC.  ││SIS    ││       ││GENERATOR      │
│docx  ││keyword ││builder││net    ││JSON + HTML/PDF│
│pdf   ││+ embed ││rule   ││support││+ evidence     │
│xlsx  ││+ rules ││based  ││+ gaps ││  trace map    │
│csv   ││        ││2-4    ││→label ││               │
│images││        ││       ││       ││               │
└──────┘└───────┘└───────┘└───────┘└───────────────┘
                                          │
                                    ┌─────▼──────┐
                                    │ LANGUAGE    │
                                    │ SYNTHESIS   │
                                    │ (LLM API)   │
                                    │ phrasing    │
                                    │ only        │
                                    └────────────┘
```

---

## Document Analysis Summary

### Doc 1: Appendix A — Internal Evidence Handling
Defines the internal (non-user-facing) data model. Every uploaded input becomes a discrete evidence item
with: source type, context, temporal relevance, signals, limitations. Evidence is classified as
Supporting / Contradictory / Inconclusive / Not Observable. Missing docs are diagnostic signals, not errors.
The system must never score, learn, optimize, or expose internals.

### Doc 2: Behavior Rules (Detailed)
8 non-negotiable rules:

- Missing evidence = diagnostic signal, never block execution
- Conflicts are preserved, never resolved
- Weak data stays as weak evidence, never discarded
- Always 2–4 hypotheses (never 1, never >4)
- Confidence is qualitative only (Low/Medium/High) — no percentages, no math
- Deterministic: same input = same output, no randomness, no learning
- Absolute prohibitions: no learning, no tuning, no equations, no declaring "final root cause", no corrective action recommendations, no blame
- Acceptance test: a Quality Engineer understands what to investigate next without being told what to do

### Doc 3: Dev Doc JS Final (THE CORE SPEC)
The single source of truth. Defines:

- **4 locked report sections**: Executive Diagnostic Summary, Contributing Hypotheses, Evidence Alignment & Contradictions, Investigation Focus
- **Header fields**: Part/Process, Defect/Symptom, Date Range, Analysis Confidence
- **Per-section rules**: exact allowed/disallowed language, length limits, fallback strings
- **Inputs**: PDF/DOCX/XLSX/CSV/TXT/JSON docs, images (JPG/PNG), user problem statement
- **Outputs**: Rendered report (HTML/PDF), machine-readable JSON, evidence trace map
- **Language lint**: automated check for disallowed wording before finalization

### Doc 4: Dev Clarification (THE LOGIC SPEC)
Answers the critical question of how deterministic logic works without ML:

1. **Evidence Association** — parse docs into evidence elements, compute keyword/semantic similarity to hypotheses, attach above threshold
2. **Alignment vs Contradiction** — rule-based classification (Supporting/Contradicting/Indeterminate) with short rationale
3. **Data Gap Identification** — generic evidence schema (Design/Requirements, Process/Control, Performance/Variation, Detection/Audit, Response/Corrective) checked against uploaded docs
4. **Missing Data Detection** — mechanical check for required vs optional fields
5. **Hypothesis Ranking** — net support (supporting - contradicting) + gap severity mapped to Primary / Secondary / Conditional Amplifier
6. **3 full test cases** with inputs and expected outputs

### Doc 5: Test01 Expected Output
The gold standard output for Test Case 01 — a rubber-to-metal bond failure scenario. Shows exactly what the
5-section report should look like.

### Doc 6: Test01 Lab Test Report
Sample input document for Test Case 01 — a lab report on transmission seal bond integrity with thermal
cycling results, blistering observations, and storage time correlation.

---

## Module Breakdown

### Module 1 — Document Parser (parser/)
- Ingests: PDF, DOCX, XLSX, CSV, TXT, JSON, JPG/PNG
- Outputs: list of evidence elements, each with: id, source (filename + page/row), text_content, category tag (DR/PC/PV/DA/RC)
- Image handling: OCR (Tesseract) or description extraction
- Libraries: python-docx, pdfplumber, openpyxl, Pillow, pytesseract

### Module 2 — Evidence Associator (engine/evidence_associator.py)
- Takes: parsed evidence elements + generated hypotheses
- Uses: keyword overlap + domain phrase matching + fixed local embedding (pinned all-MiniLM-L6-v2)
- Outputs: for each hypothesis, a list of associated evidence elements
- Determinism guarantee: pinned model version, no random seed, CPU-only inference

### Module 3 — Alignment & Contradiction Classifier (engine/alignment_classifier.py)
- For each (hypothesis, evidence) pair, classifies: Supporting / Contradicting / Indeterminate
- Plus a short rationale string
- Rule-based keyword/context checks + embedding similarity direction
- No LLM involvement

### Module 4 — Hypothesis Builder (engine/hypothesis_builder.py)
- Generates 2–4 candidate hypotheses from: problem description, evidence clusters, domain rule templates
- Rule-based: pattern matching against known failure mode templates
- Each hypothesis: ID, short description, associated process step/component

### Module 5 — Data Gap Detector (engine/gap_detector.py)
- Generic evidence schema with 5 categories: DR, PC, PV, DA, RC
- Checks which categories are present/missing/partial
- Outputs: list of gap labels with short descriptions

### Module 6 — Hypothesis Ranker (engine/ranker.py)
- Internally computes net_support = count(supporting) - count(contradicting) + gap_severity
- Maps to: Primary / Secondary / Conditional Amplifier
- Same inputs → same ordering, every time

### Module 7 — Confidence Assessor (engine/confidence.py)
- Qualitative only: Low / Medium / High
- Based on: evidence coverage, contradiction severity, gap count

### Module 8 — Report Generator (report/generator.py)
- 5 locked sections: Executive Diagnostic Summary, Most Likely Root Cause Hypotheses, Why AIQE Believes This, Immediate Actions to Test, Analysis Confidence Statement
- Outputs: structured JSON + rendered HTML/PDF + evidence trace map
- Includes language lint and fallback strings

### Module 9 — Language Synthesis (synthesis/llm_client.py)
- Thin wrapper around ChatGPT/Grok API
- Called only by the report generator for phrasing
- temperature=0, fixed system prompt

### Module 10 — Auditability (audit/)
- Input hash (SHA-256), timestamp, evidence trace map, replayability

---

## Build Phases

### Phase A — Foundation (Week 1–2)

| # | Task | Output |
|---|------|--------|
| A1 | Project scaffolding (FastAPI, folder structure, config, deps) | Runnable skeleton |
| A2 | Document parser — PDF, DOCX, XLSX, CSV, TXT, JSON | Parsed evidence elements |
| A3 | Image handler — OCR/text extraction from JPG/PNG | Image evidence elements |
| A4 | Evidence element data model + internal schema | Pydantic models |

### Phase B — Core Engine (Week 3–5)

| # | Task | Output |
|---|------|--------|
| B1 | Domain rule templates (manufacturing RCA failure patterns) | Rule config files (YAML/JSON) |
| B2 | Hypothesis builder (rule-based, 2–4 candidates) | Hypothesis generation |
| B3 | Evidence associator (keyword + embedding matching) | Evidence-to-hypothesis links |
| B4 | Alignment/contradiction classifier | Supporting/Contradicting/Indeterminate labels |
| B5 | Data gap detector (5-category schema) | Gap list per analysis |
| B6 | Hypothesis ranker (Primary/Secondary/Conditional Amplifier) | Ranked hypothesis list |
| B7 | Confidence assessor (Low/Medium/High) | Qualitative confidence label |
| B8 | Determinism validation — same input 10x, assert identical | Determinism proof |

### Phase C — Report & Synthesis (Week 6–7)

| # | Task | Output |
|---|------|--------|
| C1 | Report generator — JSON output (5 sections + header) | Machine-readable report |
| C2 | Language lint engine (disallowed wording checker) | Automated lint pass/fail |
| C3 | LLM synthesis wrapper (temperature=0, constrained prompts) | Polished section text |
| C4 | HTML/PDF report renderer | Human-readable report |
| C5 | Evidence trace map generator | Source → bullet audit trail |
| C6 | Fallback string handling | Graceful degradation |

### Phase D — API & Auditability (Week 8)

| # | Task | Output |
|---|------|--------|
| D1 | FastAPI endpoints: POST /analyze, GET /report/{id}, GET /health | Working REST API |
| D2 | File upload handling (multipart) | All supported formats |
| D3 | Input hashing + timestamp + storage | Replayable audit records |
| D4 | API error handling + validation | Clean error responses |

### Phase E — Testing & Validation (Week 9–10)

| # | Task | Output |
|---|------|--------|
| E1 | Test Case 01 — Contradictory Evidence (rubber-to-metal bond) | Pass/Fail |
| E2 | Test Case 02 — Sparse Data / No PFMEA | Pass/Fail |
| E3 | Test Case 03 — Conflicting Signals / Intermittent Issue | Pass/Fail |
| E4 | Tests 04–08 (remaining test cases) | Pass/Fail |
| E5 | Determinism regression (all inputs 3x, assert identical) | Determinism certified |
| E6 | Language lint validation across all outputs | No disallowed language |
| E7 | Edge cases: empty inputs, single doc, all gaps, all contradictions | Robust handling |

---

## Folder Structure

```
root_cause_analysis/
├── api/
│   ├── main.py
│   ├── routes.py
│   └── schemas.py
├── parser/
│   ├── pdf_parser.py
│   ├── docx_parser.py
│   ├── xlsx_parser.py
│   ├── csv_parser.py
│   ├── image_parser.py
│   └── parser_router.py
├── engine/
│   ├── pipeline.py
│   ├── hypothesis_builder.py
│   ├── evidence_associator.py
│   ├── alignment_classifier.py
│   ├── gap_detector.py
│   ├── ranker.py
│   └── confidence.py
├── synthesis/
│   ├── llm_client.py
│   └── prompts/
├── report/
│   ├── generator.py
│   ├── language_lint.py
│   ├── renderer.py
│   └── templates/
├── audit/
│   ├── hasher.py
│   └── trace_map.py
├── rules/
│   ├── domain_templates.yaml
│   ├── evidence_schema.yaml
│   └── language_rules.yaml
├── models/
│   └── embedding/
├── tests/
│   ├── test_01/
│   ├── test_02/
│   ├── test_03/
│   └── ...
├── config.py
├── requirements.txt
└── README.md
```

---

## Key Dependencies

| Package | Purpose |
|---------|---------|
| fastapi + uvicorn | REST API |
| python-docx | DOCX parsing |
| pdfplumber | PDF parsing |
| openpyxl | XLSX parsing |
| pytesseract + Pillow | Image OCR |
| sentence-transformers | Fixed local embeddings (all-MiniLM-L6-v2) |
| pydantic | Data models + validation |
| weasyprint or xhtml2pdf | HTML to PDF rendering |
| pyyaml | Rule config loading |
| openai or httpx | LLM API calls (synthesis only) |
| pytest | Test suite |

---

## Risk Flags

| Risk | Mitigation |
|------|------------|
| Embedding model updates break determinism | Pin exact model version + hash, store locally |
| LLM phrasing introduces disallowed language | Language lint runs after synthesis, reject + re-request if fails |
| Image OCR quality varies | Fallback: "Unable to extract reliably from current inputs." |

---

*Generated: 2026-02-25 | AIQE Phase 2 Root Cause Analysis Engine*
"""

html_content = markdown.markdown(md_content, extensions=["tables", "fenced_code"])

full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{
    size: A4;
    margin: 20mm 18mm;
  }}
  body {{
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 11px;
    line-height: 1.5;
    color: #1a1a1a;
    max-width: 100%;
  }}
  h1 {{
    font-size: 22px;
    color: #0d1b2a;
    border-bottom: 3px solid #0d47a1;
    padding-bottom: 8px;
    margin-top: 0;
  }}
  h2 {{
    font-size: 16px;
    color: #0d47a1;
    border-bottom: 1px solid #ccc;
    padding-bottom: 4px;
    margin-top: 24px;
    page-break-after: avoid;
  }}
  h3 {{
    font-size: 13px;
    color: #1565c0;
    margin-top: 16px;
    page-break-after: avoid;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
    font-size: 10px;
  }}
  th {{
    background-color: #0d47a1;
    color: white;
    padding: 6px 8px;
    text-align: left;
    font-weight: 600;
  }}
  td {{
    padding: 5px 8px;
    border: 1px solid #ddd;
  }}
  tr:nth-child(even) {{
    background-color: #f5f7fa;
  }}
  code {{
    background-color: #f0f0f0;
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 10px;
  }}
  pre {{
    background-color: #1a1a2e;
    color: #e0e0e0;
    padding: 14px;
    border-radius: 6px;
    font-size: 9px;
    line-height: 1.4;
    overflow-x: auto;
    white-space: pre;
    page-break-inside: avoid;
  }}
  pre code {{
    background: none;
    padding: 0;
    color: #e0e0e0;
    font-size: 9px;
  }}
  ul {{
    padding-left: 20px;
  }}
  li {{
    margin-bottom: 3px;
  }}
  strong {{
    color: #0d1b2a;
  }}
  hr {{
    border: none;
    border-top: 1px solid #ddd;
    margin: 16px 0;
  }}
  p {{
    margin: 6px 0;
  }}
</style>
</head>
<body>
{html_content}
</body>
</html>"""

output_path = "/home/swapnonilmukherjee/projects/root_cause_analysis/AIQE_Phase2_Roadmap.pdf"
HTML(string=full_html).write_pdf(output_path)
print(f"PDF generated: {output_path}")
