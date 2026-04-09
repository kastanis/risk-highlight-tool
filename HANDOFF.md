# Handoff — Risk Highlight Tool

*For Claude Code. Read this before touching any file.*

**Last updated:** 2026-04-09
**Repo:** `/Users/akastanis/Git_work/risk-highlight-tool`
**Run environment:** `uv run` — always prefix Python commands with `uv run`

---

## What this project is

A suite of three independent tools for surfacing risk in data journalism work.
The mental model is **Grammarly for editorial risk**: flag what deserves a second look,
never decide truth, never rewrite anything.

**Core principle:** Every flag is explainable by a named rule. No LLM judgment in the flagging logic.

---

## Status at handoff

| Layer | What | File | Status |
|---|---|---|---|
| Layer 1 | Copy risk checker | `analysis/layer1_copy_risk.ipynb` | ✅ Done — 20 tests passing |
| Layer 1 | Evaluation | `evaluation/gold/layer1_gold.jsonl` + `evaluation/run_eval.py` | ✅ Done — 30 sentences labeled |
| Layer 2 | Code risk checker | `analysis/layer2_code_risk.ipynb` | ✅ Done — 29 tests passing |
| Layer 2 | Example scripts | `analysis/layer2_examples/` | ✅ Done |
| Layer 3 | Notes recall (RAG) | `analysis/layer3_notes_recall.ipynb` | ❌ Not started |
| UI | Streamlit apps | `ui/layer1_app.py`, `ui/layer2_app.py` | ❌ Not started |

**Next task:** Build `ui/layer1_app.py` — Streamlit app for Layer 1.

---

## Layer 1 — Copy Risk Checker

### What it does

Flags risk patterns in journalism prose or AI-generated text. Static analysis only —
no LLM calls, fully deterministic.

### Core function

```python
# analysis/layer1_copy_risk.ipynb
flag_text(text: str) -> list[Flag]
```

Returns `Flag` objects with: `start`, `end`, `text`, `flag_type`, `priority`, `reason`

### 9 flag types and colors

```python
FLAG_COLORS = {
    "quantitative_claim":  "#74c0fc",  # blue    — "27%", "$4.2 million"; hedged variant: "roughly $72,000"
    "vague_attribution":   "#ff6b6b",  # red     — "experts say", "studies show", "advocates say"
    "passive_attribution": "#f783ac",  # rose    — "it was found that", "it is estimated", "widely believed to"
    "causal_claim":        "#ff922b",  # orange  — "led to", "caused", "due to"
    "certainty_language":  "#ffd43b",  # yellow  — "shows", "proves", "confirms"
    "trend_language":      "#63e6be",  # teal    — "surged", "plummeted", "significantly worse"
    "comparative_claim":   "#a9e34b",  # green   — "highest", "more than", "at all-time"
    "temporal_claim":      "#ffa8a8",  # pink    — "since 2020", "last year", "April 7"
    "named_entity":        "#dee2e6",  # grey    — PERSON, ORG, GPE, NORP via spaCy NER
}
```

**`quantitative_claim` has two reasons** depending on whether the number is hedged:
- Precise: `"Specific number — source needed"` → triggered by `27%`, `$4.2 million`
- Hedged: `"Hedged figure — does the reporter have the exact number?"` → triggered by `roughly $72,000`, `nearly half`, `approximately 400 jobs`

The hedged pattern is listed first in `REGEX_PATTERNS` so it wins deduplication when both match the same span.

### Architecture: two tiers

**Tier 1 — regex (`REGEX_PATTERNS` list):** `quantitative_claim`, `vague_attribution`,
`trend_language`, `comparative_claim`, `temporal_claim`

**Tier 2 — spaCy NER + patterns:**
- `causal_claim` — phrase match against PDTB causal connectives list
- `certainty_language` — lemma match (`token.pos_ == "VERB"`) for: shows, proves, confirms, demonstrates, reveals
- `named_entity` — spaCy NER labels PERSON, ORG, GPE, NORP → named_entity; MONEY, CARDINAL, PERCENT → quantitative_claim; DATE, TIME → temporal_claim

**Deduplication:** Same `flag_type` overlapping spans collapse to the first. Different types on
the same span are **both kept** — shown in the table, resolved for inline rendering with dotted
underline + `+N` superscript.

### Layer 1 eval results (current)

```
Flag type             Precision  Recall     F1
─────────────────────────────────────────────
causal_claim               1.00    1.00   1.00
certainty_language         0.83    1.00   0.91
quantitative_claim         1.00    0.93   0.96
temporal_claim             0.78    0.93   0.85
trend_language             1.00    0.75   0.86
vague_attribution          1.00    0.88   0.93
comparative_claim          0.67    0.57   0.62
named_entity               0.40    0.40   0.40
─────────────────────────────────────────────
OVERALL                    0.83    0.81   0.82
```

**Known weak spots** (documented in `OPEN_QUESTIONS.md`):
- `trend_language` recall 0.75 — 2 FNs remain in gold set
- `vague_attribution` recall 0.88 — 1 FN remains in gold set
- `named_entity` precision 0.40 — over-flags "ZIP", "Tuesday", proper adjectives
- `passive_attribution` — new flag type, no gold examples yet; add to gold set before claiming it works
- `quantitative_claim` hedged variant — no gold examples yet; fires correctly in spot checks

Run eval: `uv run python evaluation/run_eval.py` (or `--verbose` for FP/FN examples)

---

## Layer 2 — Code Risk Checker

### What it does

Static analysis of `.py` and `.R` scripts. No code execution. Two outputs:
1. **Risk flags** — things that may be wrong (for the data team)
2. **Decision points** — methodology choices needing editorial sign-off (for editors)

### Core functions

```python
# analysis/layer2_code_risk.ipynb

flag_code(path: str | Path) -> list[CodeFlag]
# Dispatches to PythonFlagger (AST) or flag_r() (regex) based on file suffix

scan_repo(repo_path, extensions=(".py", ".r")) -> dict[str, list[CodeFlag]]
# Recursively scan a directory — returns {filepath: [CodeFlag]}

find_decision_points(source: str) -> list[DecisionPoint]
# Separate pass — detects methodology choices, not bugs
```

### `CodeFlag` dataclass

```python
@dataclass
class CodeFlag:
    line: int       # 1-indexed
    col: int        # 0-indexed
    end_line: int
    code: str       # exact source text of flagged line
    flag_type: str
    priority: str   # "High" or "Medium"
    reason: str
    language: str   # "python" or "r"
```

### Python detection: AST + regex hybrid

**AST (`PythonFlagger(ast.NodeVisitor)`):**
- `visit_Call` — catches: `read_csv`/`read_excel` (load checks), `merge`/`join` (join checks), aggregation functions, geocoding calls, spatial joins
- `visit_Assign` — catches: `astype(int/float)` on ZIP columns (`zip_as_numeric`)
- `visit_Compare` — catches: `== 0.05` comparator (`hardcoded_threshold`)
- `run_post_checks()` — whole-file pass after AST walk: `_check_loads()`, `_check_merges()`, `_check_aggregations()`, `_check_regex_passes()`

**Critical implementation detail — `_code_only(line)`:**
Strip inline comments before pattern matching. Without this, flag keywords in comments
(e.g. `# no na check`) trigger false negatives in proximity windows. Every window check
must use `_code_only()`.

**Critical implementation detail — load window:**
`_check_loads()` builds a per-load window that **stops at the next load line** (`all_load_lines`).
Without this, a check for `isna` after load line 9 picks up `isna` from the window of load line 15,
producing false negatives.

**R detection:** Line-by-line regex only (no R AST available from Python). Same flag types,
same priorities. Window proximity checks via `_r_has_nearby()`.

### 20 risk flag types

Full taxonomy with AP checklist references: `data/documentation/LAYER2_FLAGS.md`

High-priority: `no_shape_check`, `no_na_check`, `zip_as_numeric`, `total_row_risk`,
`sentinel_value_risk`, `no_join_count_check`, `no_unmatched_check`, `hardcoded_threshold`,
`no_null_before_aggregation`, `geocoding_unverified`, `projection_not_set`

Medium-priority: `no_dtype_check`, `encoding_not_set`, `excel_date_risk`,
`no_value_range_check`, `no_category_check`, `join_on_string`, `magic_number`,
`mean_without_median`, `pct_change_without_base_note`, `hardcoded_geo_count`

### 10 decision point types

`filter_threshold`, `unit_of_analysis`, `join_type`, `stat_test_choice`,
`exclusion_filter`, `date_cutoff`, `rate_denominator`, `time_period`,
`deduplication`, `column_selection`

Full taxonomy: `data/documentation/LAYER2_FLAGS.md` § Decision points

### Test scripts

```
analysis/layer2_examples/
├── example_risky.py   — 16 flag types should fire, 9 decision points
├── example_clean.py   — 0 High flags (5 Medium acceptable)
└── example_risky.R    — 12 flag types should fire
```

Tests run inline in the notebook. 29/29 passing at handoff.

---

## Layer 3 — Notes Recall (not started)

### What it will do

Given a claim from Layer 1 output, retrieve the passage in reporter notes most likely
to be the source. RAG over local documents — no external API calls.

### Planned stack

```python
# All local — no data leaves the machine (hard requirement: reporter notes are sensitive)
sentence-transformers   # local embeddings
chromadb                # local vector store
pdfplumber              # PDF text extraction
google-api-python-client  # Google Drive ingestion (optional)
```

### Core functions (to build)

```python
index_documents(folder: Path) -> None   # embed and store in ChromaDB
retrieve(query: str, top_k: int = 3) -> list[Passage]  # semantic search
```

### Dependencies to uncomment in `pyproject.toml`

```toml
"sentence-transformers"
"chromadb"
"pdfplumber"
```

---

## Streamlit UI (not started)

### Layer 1 app (`ui/layer1_app.py`) — build this next

```
Layout:
- Left: text area for paste input
- Right: colored inline highlight output (reuse render_html() from notebook)
- Below: flag table — flag_type | priority | matched text | reason
- Sidebar: flag type legend with color swatches
```

Key: `render_html()` already exists in the notebook — extract it and import.
The Streamlit app should be a thin wrapper around `flag_text()`, not duplicate logic.

### Layer 2 app (`ui/layer2_app.py`) — after Layer 1 UI

```
Layout:
- File upload widget (or path text input for local use)
- Tabs: "Risk Flags" | "Decision Points"
- Risk tab: annotated source view (reuse render_flags() from notebook)
- Decision tab: checklist table (reuse render_decision_points() from notebook)
- Sidebar: repo scan — file list with High flag counts
```

---

## Repo structure

```
risk-highlight-tool/
├── analysis/
│   ├── layer1_copy_risk.ipynb       ✅ Core logic + tests
│   ├── layer2_code_risk.ipynb       ✅ Core logic + tests
│   └── layer2_examples/             ✅ Test scripts
│       ├── example_risky.py
│       ├── example_clean.py
│       └── example_risky.R
├── evaluation/
│   ├── gold/layer1_gold.jsonl       ✅ 30 labeled sentences
│   └── run_eval.py                  ✅ Precision/recall/F1 per flag type
├── data/documentation/
│   ├── PROPOSAL.md                  Architecture overview
│   ├── FILE_STRUCTURE.md            Target repo structure with build status
│   ├── LAYER2_FLAGS.md              Complete flag taxonomy + decision points
│   ├── OPEN_QUESTIONS.md            Outstanding decisions
│   ├── EVALUATION_PLAN_L1.md        Eval methodology and gold set format
│   ├── AI_USE.md                    Template: AI use log for data team
│   └── VETTING_REQUEST.md           Template: intake form for outside reporters
├── ui/                              (empty — to build)
├── pyproject.toml                   Dependencies
└── HANDOFF.md                       This file
```

---

## Environment

```bash
# Install deps and activate
uv sync

# Run Layer 1 eval
uv run python evaluation/run_eval.py
uv run python evaluation/run_eval.py --verbose

# Open notebooks
uv run jupyter lab

# Run Layer 2 inline tests (run the test cell in the notebook)
# Or execute the notebook:
cd analysis && uv run jupyter nbconvert --to notebook --execute layer2_code_risk.ipynb
```

spaCy model required for Layer 1:
```bash
uv run python -m spacy download en_core_web_sm
```

---

## Key decisions — do not relitigate these

- **No LLM in the flagging logic.** Every flag is a named rule. LLM fallback is deferred to v2.
- **Color by flag type, not priority.** Priority is shown in the table, not the highlight color.
- **Deduplication is per flag type only.** Two different flag types on the same span are both kept.
- **No quote flag.** Removed — not specific enough to data journalism risk.
- **All layers independent.** Each works standalone. Integration comes later.
- **Open source only.** spaCy (MIT), textacy (Apache 2.0), stdlib — no proprietary APIs.
- **Local only for Layer 3.** Reporter notes never leave the machine.
- **`_code_only()` in every window check.** Comments with flag keywords cause false negatives without this.

---

## Open questions (see `OPEN_QUESTIONS.md` for detail)

- Q1: Suppression list for well-known named entities (U.S., Iran, the Fed)
- Q2: `trend_language` recall — expanded (now 0.75); 2 FNs remain
- Q3: R checker coverage gap — regex window vs. investing in `rpy2`?
- Q4: Decision point noise — 10–20 per script, is that useful for editors?
- Q5: `.ipynb` support for Layer 2 — extract cells via `nbformat` first?
- Q6: Layer 2 gold set — needed before claiming Layer 2 "works"
