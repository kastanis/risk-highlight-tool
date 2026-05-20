# risk-highlight-tool

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

Flags 8 risk pattern types in journalism copy using regex + spaCy NER. No LLM in the flagging path — every flag is produced by a named, auditable rule.

**Flag types:**

| Type | Priority | Example |
|---|---|---|
| `quantitative_claim` | High | `$4.2 million`, `27%`, `an estimated 400,000` |
| `vague_attribution` | High | `experts say`, `researchers found`, `economists argue` |
| `passive_attribution` | High | `it was reported that`, `was found to be` |
| `causal_claim` | High | `led to`, `caused`, `because of` |
| `certainty_language` | Medium | `shows`, `proves`, `confirms` |
| `trend_language` | Medium | `surged`, `plummeted`, `rose sharply` |
| `comparative_claim` | Medium | `highest`, `more than`, `all-time` |
| `temporal_claim` | Medium | `last year`, `since 2019`, `historically` |

## Running locally

```bash
# Install dependencies
uv sync

# Layer 1 — Copy Risk Checker
uv run streamlit run ui/layer1_app.py

# Run evaluation against gold set
uv run python evaluation/run_eval.py

# Run tests
uv run pytest tests/
```

Requires `OPENAI_API_KEY` in `.env` for Layer 3 (notes recall) only.

## Repo structure

```
risk_highlight/        # Shared flagging logic (single source of truth)
ui/                    # Streamlit apps, one per layer
tests/                 # Smoke tests for Layer 1
evaluation/
  gold/                # Hand-labeled test sets
  benchmark/           # Benchmark scripts and snippets
data/patterns/         # YAML pattern registry (extend Layer 1 without code changes)
docs/                  # Active reference docs
analysis/              # Exploratory notebooks
```
