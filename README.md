# AIQE Phase 2 — Root Cause Analysis Engine

A deterministic root cause analysis engine for manufacturing quality investigations. The system uses rule-based logic for all reasoning and restricts LLM usage to language phrasing only.

## Core Principles

- **Deterministic**: Same inputs always produce identical outputs
- **No ML/LLM in reasoning**: API (ChatGPT/Grok) used strictly for language synthesis, not logic
- **Rule-based**: All hypothesis generation, evidence association, gap detection, and ranking is rule-based
- **Qualitative only**: Confidence is Low / Medium / High — no percentages, no scores exposed
- **Auditable**: SHA-256 input hashing + evidence trace maps for replayability

## Architecture

```
REST API (FastAPI)
  POST /api/analyze   GET /api/report/{id}   GET /api/health
        │
  ORCHESTRATOR (pipeline.py)
        │
  ┌─────┼─────────────────────────────────────┐
  │     │                                     │
  ▼     ▼         ▼          ▼          ▼     │
PARSER  EVIDENCE  HYPOTHESIS RANKING   REPORT │
        ASSOCIATOR BUILDER            GENERATOR
  │     (keyword   (rule     (net      (5 locked
  │     + embed)   based)    support)  sections)
  │                                     │
  │                               LANGUAGE LINT
  │                                     │
  │                              LLM SYNTHESIS
  │                              (phrasing only,
  │                               optional)
  └─────────────────────────────────────┘
```

## Prerequisites

- Python 3.12+
- [Poetry](https://python-poetry.org/) for dependency management
- Tesseract OCR (optional, for image parsing)

## Setup

```bash
# Clone and enter the project
cd root_cause_analysis

# Create virtual environment and install Poetry inside it
python3 -m venv .venv
source .venv/bin/activate
pip install poetry

# Install all dependencies
poetry install

# The embedding model (all-MiniLM-L6-v2) downloads automatically on first run
```

## Running the Server

```bash
source .venv/bin/activate
uvicorn aiqe_rca.api.main:app --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## API Endpoints

### `POST /api/analyze`

Run a root cause analysis on uploaded documents.

**Parameters:**
- `problem_statement` (form field, required): Problem description text
- `files` (file upload, required): One or more documents to analyze

**Supported file types:** PDF, DOCX, XLSX, CSV, TXT, JSON, JPG, PNG

**Example with curl:**
```bash
curl -X POST http://localhost:8000/api/analyze \
  -F "problem_statement=Intermittent bond failures with blistering near edges" \
  -F "files=@LabReport.docx" \
  -F "files=@SPC_Data.xlsx"
```

**Response:**
```json
{
  "report_id": "rca-abc123def456",
  "input_hash": "sha256...",
  "confidence": "Medium",
  "report_json": {
    "header": { ... },
    "sections": [ ... ],
    "evidence_trace_map": { ... }
  },
  "files": {
    "json": "/path/to/report.json",
    "html": "/path/to/report.html",
    "pdf": "/path/to/report.pdf"
  }
}
```

### `GET /api/report/{report_id}?format=json|html|pdf`

Retrieve a previously generated report.

### `GET /api/health`

Health check endpoint.

## Report Structure

Every report contains exactly 5 locked sections:

| # | Section | Description |
|---|---------|-------------|
| 1 | Executive Diagnostic Summary | High-level synthesis (max 2 paragraphs) |
| 2 | Most Likely Root Cause Hypotheses | 2–4 ranked hypotheses (Primary / Secondary / Conditional Amplifier) |
| 3 | Why AIQE Believes This | Supporting, contradicting, and gap evidence with source citations |
| 4 | Immediate Actions to Test | Investigation focus areas (guiding, not directive) |
| 5 | Analysis Confidence Statement | Qualitative confidence (Low / Medium / High) with rationale |

Reports are generated in three formats: **JSON** (machine-readable), **HTML**, and **PDF**.

## Engine Pipeline

The deterministic pipeline runs in this order:

1. **Parse** — Extract evidence elements from uploaded documents
2. **Build Hypotheses** — Rule-based matching against 8 domain failure templates (2–4 candidates)
3. **Associate Evidence** — Keyword overlap + fixed local embeddings (all-MiniLM-L6-v2, CPU-only)
4. **Classify Alignment** — Supporting / Contradicting / Indeterminate for each (hypothesis, evidence) pair
5. **Detect Gaps** — Check 5-category evidence schema (DR / PC / PV / DA / RC)
6. **Rank** — Primary / Secondary / Conditional Amplifier based on net support
7. **Assess Confidence** — Low / Medium / High (qualitative only)
8. **Generate Report** — 5 locked sections + language lint + fallback strings
9. **Audit** — SHA-256 input hash + evidence trace map

## Running Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

**Test suite includes:**
- 7 parser unit tests (CSV, TXT, JSON, determinism)
- 11 engine unit tests (hypothesis builder, alignment classifier, ranker, confidence, gap detector)
- 9 integration tests (Test Case 01 with real Lab Test Report)

**Key validations:**
- Determinism: same inputs produce identical outputs across multiple runs
- Hypothesis count: always 2–4
- Language lint: no disallowed wording in output
- Evidence trace map: source → evidence → report audit trail

## Project Structure

```
root_cause_analysis/
├── aiqe_rca/
│   ├── api/                    # FastAPI application
│   │   ├── main.py             # App entry point + lifespan
│   │   ├── routes.py           # API endpoints
│   │   └── schemas.py          # Request/response models
│   ├── parser/                 # Document parsers
│   │   ├── pdf_parser.py
│   │   ├── docx_parser.py
│   │   ├── xlsx_parser.py
│   │   ├── csv_parser.py
│   │   ├── txt_parser.py
│   │   ├── json_parser.py
│   │   ├── image_parser.py
│   │   └── router.py           # Routes files to correct parser
│   ├── engine/                 # Deterministic core engine
│   │   ├── pipeline.py         # Orchestrator
│   │   ├── hypothesis_builder.py
│   │   ├── evidence_associator.py
│   │   ├── alignment_classifier.py
│   │   ├── gap_detector.py
│   │   ├── ranker.py
│   │   └── confidence.py
│   ├── report/                 # Report generation
│   │   ├── generator.py        # 5-section report assembly
│   │   ├── language_lint.py    # Disallowed wording checker
│   │   ├── renderer.py         # HTML/PDF/JSON output
│   │   └── templates/
│   │       └── report.html     # Jinja2 report template
│   ├── synthesis/              # LLM phrasing (optional)
│   │   ├── llm_client.py
│   │   └── prompts/
│   ├── audit/                  # Auditability
│   │   ├── hasher.py           # SHA-256 input hashing
│   │   └── trace_map.py        # Evidence trace mapping
│   ├── models/                 # Pydantic data models
│   │   ├── evidence.py
│   │   ├── hypothesis.py
│   │   ├── alignment.py
│   │   ├── gaps.py
│   │   ├── report.py
│   │   └── audit.py
│   ├── rules/                  # Rule configuration
│   │   ├── domain_templates.yaml
│   │   ├── evidence_schema.yaml
│   │   └── language_rules.yaml
│   └── config.py               # Settings (pydantic-settings)
├── tests/
│   ├── test_parsers.py
│   ├── test_engine.py
│   └── test_01_integration.py
├── docs/                       # Reference documents
├── pyproject.toml
└── README.md
```

## Configuration

Configuration is managed via environment variables (prefix `AIQE_`) or a `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `AIQE_EMBEDDING_MODEL_NAME` | `sentence-transformers/all-MiniLM-L6-v2` | Pinned embedding model |
| `AIQE_EMBEDDING_DEVICE` | `cpu` | Device for embeddings (cpu only for determinism) |
| `AIQE_ASSOCIATION_THRESHOLD` | `0.18` | Evidence-to-hypothesis association threshold |
| `AIQE_MIN_HYPOTHESES` | `2` | Minimum hypothesis count |
| `AIQE_MAX_HYPOTHESES` | `4` | Maximum hypothesis count |
| `AIQE_LLM_ENABLED` | `false` | Enable LLM for language synthesis |
| `AIQE_LLM_API_KEY` | `""` | OpenAI API key (only if LLM enabled) |
| `AIQE_LLM_MODEL` | `gpt-4o-mini` | LLM model for synthesis |
| `AIQE_LLM_TEMPERATURE` | `0.0` | LLM temperature (must be 0 for determinism) |

## Behavior Rules

The engine enforces these non-negotiable rules (from the Phase 2 spec):

- Missing evidence is treated as a **diagnostic signal**, not an error
- Conflicts are **preserved**, never resolved — multiple hypotheses are maintained
- Weak data stays as weak evidence, never discarded
- Confidence is **qualitative only** — no percentages, no math exposed
- The system **never** declares a final root cause, recommends corrective actions, or assigns blame
- Language lint automatically checks output for directive verbs, absolutes, and scoring terms

## License

Proprietary — AIQE Phase 2
