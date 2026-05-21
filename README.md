# risk-highlight-tool

[![Tests](https://github.com/kastanis/risk-highlight-tool/actions/workflows/test.yml/badge.svg)](https://github.com/kastanis/risk-highlight-tool/actions/workflows/test.yml)

A suite of tools that surface risks in journalism copy and data analysis code before publication. Each layer targets a different stage of the reporting workflow.

## Layers

| Layer | What it checks | Status |
|---|---|---|
| **1 — Copy Risk** | Flags risk patterns in story text: vague sourcing, unsupported numbers, causal claims, certainty language | **Active development** |
| 2 — Code Risk | Static analysis of Python/R analysis scripts for data journalism mistakes | Backburner |
| 3 — Notes Recall | RAG over reporter notes — finds relevant passages for a given claim | Backburner |
| 4 — Editorial Judgment | LLM review: does the analysis actually support the story claim? | Backburner |
| 5 — Data Readiness | Checks a dataset for common quality issues before analysis begins | Backburner |

## Layer 1 — Copy Risk

Flags 9 risk pattern types in journalism copy using regex + n-gram fuzzy matching. No LLM in the flagging path — every flag is produced by a named, auditable rule. An optional AI second pass (GPT-4o) runs the same categories and logs disagreements to Supabase.

**Flag types:**

| Type | Priority | Example |
|---|---|---|
| `quantitative_claim` | High | `$4.2 million`, `27%`, `an estimated 400,000` |
| `vague_attribution` | High | `experts say`, `researchers found`, `economists argue` |
| `passive_attribution` | High | `it was reported that`, `was found to be` |
| `causal_claim` | High | `led to`, `caused`, `because of` |
| `agency_name` | High | `Customs and Border Patrol` (should be Protection), outdated agency names |
| `certainty_language` | Medium | `shows`, `proves`, `confirms` |
| `trend_language` | Medium | `surged`, `plummeted`, `rose sharply` |
| `comparative_claim` | Medium | `highest`, `more than`, `all-time` |
| `temporal_claim` | Medium | `last year`, `since 2019`, `historically` |

**Agency name checking:**
- 479 federal agencies loaded from `data/agencies/federal_agencies.yaml` (AP Stylebook canonicals)
- Tier 1 (54 major agencies) enabled by default; Tier 2 (425 agencies) opt-in via sidebar
- Fuzzy n-gram matching (2–8 word windows) catches misspellings and wrong-word substitutions
- Explicit regex patterns in `data/patterns/layer1_patterns.yaml` catch substitutions fuzzy matching can't (e.g. "Customs and Border Patrol")

**AI features (optional, require `OPENAI_API_KEY`):**
- **AI second pass** — GPT-4o runs the same 9 flag categories; disagreements logged to Supabase
- **Full AI review** — single-pass: identifies and web-searches all claims (figures, titles, dates, rankings). Best for static facts; political/time-sensitive claims may be unreliable
- **Fact checker** — verify a specific quantitative claim against web sources or a reporter-supplied URL

## Running locally

```bash
# Install dependencies
uv sync

# Copy env template and add keys (required for AI features)
cp .env.example .env
# OPENAI_API_KEY — required for AI second pass, Full AI review, fact checker
# SUPABASE_URL / SUPABASE_KEY — required for logging AI vs rule comparisons

# Layer 1 — Copy Risk Checker
uv run streamlit run ui/layer1_app.py

# Run evaluation against gold set
uv run python evaluation/run_eval.py

# Run tests
uv run pytest tests/
```

## Repo structure

```
risk_highlight/        # Core logic — layer1.py, ai_check.py, fact_check.py
ui/layer1_app.py       # Streamlit app
tests/                 # Layer 1 tests
evaluation/
  gold/                # Hand-labeled test set (layer1_gold.jsonl)
  benchmark/           # Benchmark scripts and results
data/
  agencies/            # federal_agencies.yaml — 479 agencies, AP style canonicals
  patterns/            # layer1_patterns.yaml — add patterns without code changes
docs/                  # PATTERN_SOURCES.md, EVALUATION_PLAN_L1.md, LAYER1_CHANGELOG.md
analysis/              # layer1_copy_risk.ipynb — exploratory analysis
```
