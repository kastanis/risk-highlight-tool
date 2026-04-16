# Handoff — Risk Highlight Tool

*For Claude Code. Read this before touching any file.*

**Last updated:** 2026-04-16
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
| Layer 3 | Notes recall (RAG) | `ui/layer3_app.py` | ✅ Done — deployed on Streamlit Cloud |
| UI — Layer 1 | Streamlit copy risk checker | `ui/layer1_app.py` | ✅ Done — deployed at risk-highlight-tool.streamlit.app |
| UI — Layer 2 | Streamlit code risk checker | `ui/layer2_app.py` | ✅ Done — tested against all 3 example scripts |
| Analysis — Layer 3 | Notes recall notebook | `analysis/layer3_notes_recall.ipynb` | ❌ Not started |

**Next task:** Deploy `ui/layer2_app.py` to Streamlit Cloud, then build `analysis/layer3_notes_recall.ipynb`.

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
`no_null_before_aggregation`, `geocoding_unverified`, `projection_not_set`,
`percentage_without_base`, `small_denominator_risk`, `hardcoded_geo_count`

Medium-priority: `no_dtype_check`, `encoding_not_set`, `excel_date_risk`,
`no_category_check`, `join_on_string`, `hardcoded_path`

**Removed flags (too noisy):** `mean_without_median`, `no_value_range_check`,
`magic_number`, `pct_change_without_base_note`

### 13 decision point types

`filter_threshold`, `unit_of_analysis`, `join_type`, `stat_test_choice`,
`exclusion_filter`, `date_cutoff`, `rate_denominator`, `time_period`,
`deduplication`, `column_selection`, `smoothing_choice`, `imputation`,
(stat_test_choice covers both Python scipy and R t.test/lm/glm/chisq.test)

### Known limitations

**Polars support:** The flagging patterns were built for pandas (Python) and base R / tidyverse.
Scripts using Polars will produce false positives — primarily `no_null_before_aggregation`
firing on `.agg()` chains where Polars handles nulls differently. Polars support is deferred
to a future pass. Document any Polars scripts as out-of-scope for Layer 2 until then.

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

## Layer 3 — Notes Recall

### What it does

Upload reporter notes (PDF, .docx, .txt, .md), paste a claim, get back the most relevant
passages. RAG over uploaded documents using OpenAI embeddings. Session-scoped: index lives
in browser memory and is cleared when the tab closes.

**Privacy note:** Text is sent to OpenAI for embedding only — not stored or used for training.
For notes that must stay fully local, see the commented-out `sentence-transformers` + `chromadb`
stack in `pyproject.toml`.

### Stack

```python
openai              # text-embedding-3-small — fast, cheap, no local download
python-dotenv       # .env loading for local dev
pdfplumber          # PDF text extraction (page-aware)
python-docx         # .docx extraction
streamlit           # UI + session state
```

### Core functions (`ui/layer3_app.py`)

```python
@dataclass
class Chunk:
    text: str
    filename: str
    page: int           # 0 = unknown (docx, txt)
    embedding: list[float] = field(default_factory=list)

embed_chunks(chunks: list[Chunk], client: OpenAI) -> list[Chunk]
    # Batch embed in one API call (up to 2048 inputs)

search(query_embedding, index, top_k=5) -> list[tuple[Chunk, float]]
    # Cosine similarity, returns top_k sorted by score
```

### Key constants

```python
EMBED_MODEL   = "text-embedding-3-small"
CHUNK_SIZE    = 400   # characters
CHUNK_OVERLAP = 80
TOP_K         = 5
```

### Deployment

- **Local:** `uv run streamlit run ui/layer3_app.py` — needs `OPENAI_API_KEY` in `.env`
- **Streamlit Cloud:** add `OPENAI_API_KEY` to App → Settings → Secrets

### Still to build

- `analysis/layer3_notes_recall.ipynb` — exploration notebook with eval and iteration
- `evaluation/gold/layer3_gold.jsonl` — claim → correct passage pairs for recall eval
- Google Drive ingestion (deferred — see `pyproject.toml` comments)

---

## Streamlit UI

### Layer 1 app (`ui/layer1_app.py`) — done

Deployed at: https://risk-highlight-tool.streamlit.app

Logic (flag_text, FLAG_COLORS, render_html) is inlined in the app — not imported from the notebook.
If the notebook logic changes, keep the app in sync manually until the `risk_highlight` package
extraction is done (Phase 6 in FILE_STRUCTURE.md).

### Layer 2 app (`ui/layer2_app.py`) — done

All Layer 2 logic inlined (same pattern as Layer 1 — no imports from notebook).

```
Layout:
- Sidebar: file uploader (.py / .R) + checkbox filters (High/Medium groups) + About
- Main: summary badges (N High, N Medium, N Decision pts)
- Tab 1 "Risk Flags": legend + summary table + annotated source view
- Tab 2 "Decision Points": checklist table (line, category, code snippet, reviewer question)
- Session state: cached by filename:hash(source) — re-runs only on file change
```

**Tested against:**
- `example_risky.py` → 37 flags (16 types), 9 decision points
- `example_clean.py` → 0 High flags
- `example_risky.R` → 30 flags (16 types)

**Run locally:** `uv run streamlit run ui/layer2_app.py`
**Deploy:** Add new app on Streamlit Cloud pointing at `ui/layer2_app.py` (same repo, no secrets needed)

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
├── ui/
│   ├── layer1_app.py                ✅ Streamlit copy risk checker (deployed)
│   └── layer3_app.py                ✅ Streamlit notes recall (OpenAI embeddings)
├── docs/
│   ├── HANDOFF.md                   This file
│   ├── PROPOSAL.md                  Architecture overview
│   ├── FILE_STRUCTURE.md            Target repo structure with build status
│   ├── LAYER2_FLAGS.md              Complete flag taxonomy + decision points
│   ├── OPEN_QUESTIONS.md            Outstanding decisions
│   ├── EVALUATION_PLAN_L1.md        Eval methodology and gold set format
│   ├── AI_USE.md                    Template: AI use log for data team
│   ├── AUDIT_TEMPLATE.md            Template: audit checklist
│   └── VETTING_REQUEST.md           Template: intake form for outside reporters
├── data/                            (gitignored) — local test docs only
├── scratch/                         (gitignored) — throwaway experiments
├── pyproject.toml                   Dependencies (uv-managed)
├── uv.lock                          Locked dep graph — commit this
└── .gitignore
```

---

## Environment

```bash
# Install deps and activate
uv sync

# Run Layer 1 eval
uv run python evaluation/run_eval.py
uv run python evaluation/run_eval.py --verbose

# Run Layer 1 Streamlit app
uv run streamlit run ui/layer1_app.py

# Run Layer 3 Streamlit app (needs OPENAI_API_KEY in .env)
uv run streamlit run ui/layer3_app.py

# Open notebooks
uv run jupyter lab

# Run Layer 2 inline tests (run the test cell in the notebook)
# Or execute the notebook:
cd analysis && uv run jupyter nbconvert --to notebook --execute layer2_code_risk.ipynb
```

spaCy model is installed via `pyproject.toml` — `uv sync` handles it.
If running manually: `uv run python -m spacy download en_core_web_sm`

Layer 3 requires `OPENAI_API_KEY` in `.env` for local dev, or in Streamlit Cloud secrets for deployment.

---

## Key decisions — do not relitigate these

- **No LLM in the flagging logic.** Every flag is a named rule. LLM fallback is deferred to v2.
- **Color by flag type, not priority.** Priority is shown in the table, not the highlight color.
- **Deduplication is per flag type only.** Two different flag types on the same span are both kept.
- **No quote flag.** Removed — not specific enough to data journalism risk.
- **All layers independent.** Each works standalone. Integration comes later.
- **Open source only for Layers 1 + 2.** spaCy (MIT), stdlib — no proprietary APIs in flagging logic.
- **Layer 3 uses OpenAI embeddings for the deployed version.** Local-only stack (sentence-transformers + ChromaDB) is stubbed in `pyproject.toml` comments for teams with strict data policies. Text goes to OpenAI only for embedding, not storage or training.
- **`_code_only()` in every window check.** Comments with flag keywords cause false negatives without this.

---

## Open questions (see `OPEN_QUESTIONS.md` for detail)

- Q1: Suppression list for well-known named entities (U.S., Iran, the Fed)
- Q2: `trend_language` recall — expanded (now 0.75); 2 FNs remain
- Q3: R checker coverage gap — regex window vs. investing in `rpy2`?
- Q4: Decision point noise — 10–20 per script, is that useful for editors?
- Q5: `.ipynb` support for Layer 2 — extract cells via `nbformat` first?
- Q6: Layer 2 gold set — needed before claiming Layer 2 "works"

## Future: Layer 4 — Editorial Judgment Tool

Full scope document: `docs/LAYER4_SCOPE.md`

One-line summary: Takes a story draft + analysis script, uses Claude to produce
a 7-section editorial memo answering "does this analysis support what the story claims?"
First layer to use an LLM in the core reasoning path. Stateless — one API call per review.
Estimated build: 1–2 sessions once Layer 2 is deployed.
