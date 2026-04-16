# File Structure — Risk Highlight Tool

*Target structure for the full three-layer system. ✅ = exists and working. Build incrementally.*

---

```
risk-highlight-tool/
│
├── analysis/                          # Notebooks — logic lives here first
│   ├── layer1_copy_risk.ipynb         # ✅ Copy risk checker — 20 tests passing
│   ├── layer2_code_risk.ipynb         # ✅ Code risk checker — 29 tests passing, Python + R
│   ├── layer2_examples/               # ✅ Example scripts with known issues (risky + clean, Python + R)
│   │   ├── example_risky.py
│   │   ├── example_clean.py
│   │   └── example_risky.R
│   ├── layer3_notes_recall.ipynb      # Notes recall notebook — not started
│   └── archive/                       # Old or exploratory notebooks
│
├── risk_highlight/                    # Core Python package (future — extracted from notebooks)
│   ├── __init__.py
│   ├── layer1/
│   │   ├── flaggers.py                # flag_text(text) -> list[Flag]  ← main function
│   │   ├── patterns.py                # All regex, lexicons, spaCy Matcher rules
│   │   └── render.py                  # HTML highlight rendering
│   ├── layer2/
│   │   ├── flaggers.py                # flag_code(path) -> list[CodeFlag], find_decision_points()
│   │   ├── patterns.py                # AST rules, R regex patterns, sentinel values
│   │   └── scanner.py                 # scan_repo(path) -> dict[file, list[CodeFlag]]
│   └── layer3/
│       ├── indexer.py                 # Ingest docs → embed → store
│       └── retriever.py               # Query by claim text → return passages
│
├── ui/
│   ├── layer1_app.py                  # ✅ Streamlit copy risk checker — deployed
│   ├── layer2_app.py                  # ✅ Streamlit code risk checker — done
│   └── layer3_app.py                  # ✅ Streamlit notes recall — deployed (OpenAI embeddings)
│
├── evaluation/
│   ├── gold/
│   │   ├── layer1_gold.jsonl          # ✅ 30 labeled sentences — {text, flags:[{start,end,flag_type,priority}]}
│   │   ├── layer2_gold.jsonl          # Labeled code snippets with known issues (planned)
│   │   └── layer3_gold.jsonl          # claim → correct source passage pairs (planned)
│   └── run_eval.py                    # ✅ Precision / recall / F1 per flag type
│
├── docs/                              # ✅ Project documentation (moved from data/documentation/)
│   ├── HANDOFF.md                     # Claude Code handoff — read this first
│   ├── PROPOSAL.md                    # Architecture overview + decisions made
│   ├── FILE_STRUCTURE.md              # This file — target structure with build status
│   ├── LAYER2_FLAGS.md                # Complete flag taxonomy + decision points
│   ├── OPEN_QUESTIONS.md              # Outstanding decisions
│   ├── EVALUATION_PLAN_L1.md          # Eval methodology and gold set format
│   ├── AI_USE.md                      # Template: AI use log for data team
│   ├── AUDIT_TEMPLATE.md              # Template: audit checklist
│   └── VETTING_REQUEST.md             # Template: intake form for outside reporters
│
├── data/                              # Local only — gitignored (test docs, exports)
│   └── .gitignore                     # ignores everything except itself
│
├── scratch/                           # Throwaway experiments — gitignored
│   └── .gitkeep
│
├── tests/                             # Formal test suite (future)
│   ├── test_layer1.py
│   ├── test_layer2.py
│   └── test_layer3.py
│
├── pyproject.toml                     # ✅ Dependencies (uv-managed)
├── uv.lock                            # ✅ Locked dep graph — always commit
├── .gitignore
├── .python-version
└── README.md
```

---

## Key design decisions reflected in this structure

**Notebooks first, package second.**
Logic starts in `analysis/layerN.ipynb`. Once it works, it gets extracted into `risk_highlight/layerN/`. The Streamlit app and tests import from the package, not from notebooks.

**One core function per layer.**
- Layer 1: `flag_text(text: str) -> list[Flag]`
- Layer 2: `flag_code(path: str) -> list[CodeFlag]`
- Layer 3: `retrieve(query: str) -> list[Passage]`

Everything else is setup, rendering, or evaluation around those three functions.

**Patterns are data, not code.**
`patterns.py` in each layer holds the word lists, regex patterns, and spaCy Matcher rules as plain Python dicts/lists. This makes them easy to audit, extend, and version independently of logic.

**Evaluation is a first-class concern.**
`evaluation/gold/` holds the labeled test sets. `run_eval.py` runs the flaggers against them and prints precision/recall/F1 per flag type. This is how we know if a rule change helps or hurts.

---

## What does NOT belong in this repo

- Raw source data (PDFs, Google Docs exports, reporter notes) → local only, never committed
- ChromaDB vector store → local only, never committed
- `.env` → already gitignored
- `.venv/` → already gitignored
- Jupyter notebook outputs → already gitignored via `.gitignore`

---

## Build order

| Phase | Files | Status |
|---|---|---|
| 1 | `analysis/layer1_copy_risk.ipynb` | ✅ Done — 20 tests passing |
| 2 | `evaluation/gold/layer1_gold.jsonl` + `run_eval.py` | ✅ Done — F1 0.82 overall |
| 3 | `analysis/layer2_code_risk.ipynb` | ✅ Done — 29 tests passing, Python + R, repo scanner, decision points |
| 4 | `ui/layer1_app.py` (Streamlit) | ✅ Done — deployed at risk-highlight-tool.streamlit.app |
| 5 | `ui/layer3_app.py` (Streamlit, OpenAI embeddings) | ✅ Done — session-scoped, file upload, PDF/docx/txt/md |
| 6 | `ui/layer2_app.py` (Streamlit) | ✅ Done — tested, ready to deploy |
| 7 | `analysis/layer3_notes_recall.ipynb` | After Layer 2 UI |
| 8 | `risk_highlight/layer1/` (extract from notebook) | After Streamlit demos validated |
| 9 | `evaluation/gold/layer3_gold.jsonl` | After Layer 3 notebook |
