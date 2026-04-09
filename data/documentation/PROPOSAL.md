# Risk Highlight Tool — Architecture Proposal

*Working document. Last updated: 2026-04-09. Layer 1 and Layer 2 notebooks built and tested.*

---

## What this is

A suite of three independent tools for surfacing risk in data journalism work — not to decide truth, not to rewrite copy, not to fix code. Only to highlight what deserves a second look.

The mental model is **Grammarly for editorial risk**: underline the span, name the risk type, let the journalist decide what to do.

---

## Core principle

> The tool does not decide if something is true or false.
> It surfaces patterns that are risky to leave unverified.
> Every flag is explainable by a named rule, not a model's judgment.

---

## Three tools (independent, connectable later)

---

### Layer 1 — Copy Risk Checker

**Input:** Pasted journalism prose or AI-generated text (summary, article draft, research memo)

**Output:** Inline span annotations — each flagged phrase gets:
- `flag_type` — what kind of risk it is
- `priority` — High / Medium / Low
- `reason` — one-line plain English explanation
- `matched_text` — the exact phrase that triggered the flag

**What it does NOT do:**
- Declare claims true or false
- Rewrite or suggest alternative copy
- Score the article as "good" or "bad"
- Make editorial judgments

#### Flag taxonomy

Tier 1 — Pure regex / lexicon (fully deterministic, no model):

| Flag type | Color | Example trigger | Priority |
|---|---|---|---|
| `quantitative_claim` | Blue | "27%", "$4.2 million", "50 wallets", "8.8 cents" | High |
| `quantitative_claim` (hedged) | Blue | "roughly $72,000", "nearly half", "approximately 400 jobs" — same type, different reason: "Hedged figure — does the reporter have the exact number?" | High |
| `vague_attribution` | Red | "experts say", "studies show", "sources say", "advocates say", "Researchers found" | High |
| `passive_attribution` | Rose | "it was found that", "it has been reported", "it is estimated that", "is widely believed to" — actor removed entirely | High |
| `trend_language` | Teal | "rose sharply", "escalated sharply", "plummeted", "significantly worse", "dramatic drop" | Medium |
| `comparative_claim` | Green | "more than", "highest", "highly unlikely", "best", "worst" | Medium |
| `temporal_claim` | Pink | "since 2020", "last year", "in recent years", "historically" | Medium |

Tier 2 — spaCy NER + syntactic patterns (still fully deterministic):

| Flag type | Color | Detection method | Priority |
|---|---|---|---|
| `causal_claim` | Orange | Phrase match: PDTB causal connectives — "led to", "caused", "resulted in", "due to", "triggered", "drove" | High |
| `quantitative_claim` | Blue | spaCy NER: MONEY, CARDINAL, PERCENT — catches numbers regex misses (e.g. "50 wallets", "8.8 cents") | High |
| `temporal_claim` | Pink | spaCy NER: DATE, TIME — catches specific timestamps (e.g. "6:30 pm ET", "April 7 around 2 pm") | Medium |
| `certainty_language` | Yellow | Token lemma match: "shows", "proves", "confirms", "demonstrates", "reveals" (as VERB, not hedged) | Medium |
| `named_entity` | Grey | spaCy NER: PERSON, ORG, GPE, NORP — verify name, title, and attributed claims | Medium |

**Rendering:** Colors are by flag type (not priority). Hover any highlight for flag type, priority, and reason. Table view shows all flags including overlapping spans.

**Multi-flag spans:** When multiple flag types overlap the same span, the inline view shows the highest-priority color with a dotted underline and `+` superscript. Hovering lists all flags at that position (`MULTIPLE FLAGS — vague_attribution [High] | certainty_language [Medium]`). The table always shows every flag independently.

**Known limitation — suppression list:** Well-known geopolitical entities (U.S., Iran, etc.) are flagged as `named_entity` but may not warrant review in every context. A configurable suppression list is a planned enhancement.

Tier 3 — LLM fallback (not yet built, optional):

| Flag type | Why LLM needed |
|---|---|
| `implied_causation` | Causal claim with no connective word (narrative implication) |
| `summary_overreach` | "This shows..." / "This means..." wrapping a complex finding |
| `normative_as_fact` | Opinion presented as conclusion without hedge |

#### Examples

**Original test case:**
```
Evictions rose sharply in Los Angeles, increasing by 27%, which shows the new policy hurt renters.
```
```
"rose sharply"                      → trend_language      [Medium]
"27%"                               → quantitative_claim  [High]
"shows"                             → certainty_language  [Medium]
"the new policy hurt renters"       → causal_claim        [High]
"Los Angeles"                       → named_entity        [Medium]
```

**Real-world test (Polymarket story):**
```
...50 newly created wallets...at around 6:30 pm ET on Wednesday...
created on April 7 around 2 pm ET...placed roughly $72,000...at an average price
of 8.8 cents...rhetoric had escalated sharply...highly unlikely...
```
```
"50 newly created wallets"          → quantitative_claim  [High]   (CARDINAL NER)
"6:30 pm ET on Wednesday"           → temporal_claim      [Medium]  (TIME NER)
"April 7 around 2 pm ET"            → temporal_claim      [Medium]  (DATE NER)
"$72,000"                           → quantitative_claim  [High]
"8.8 cents"                         → quantitative_claim  [High]
"escalated sharply"                 → trend_language      [Medium]
"highly unlikely"                   → comparative_claim   [Medium]
"$2.1 million"                      → quantitative_claim  [High]
"a whole civilization will die..."  → quote               [High]
```

#### Open source building blocks (researched)

| Tool | Role | Rule-based? | Span offsets? | Maintained? |
|---|---|---|---|---|
| **spaCy** | NER, dependency parse, POS tagging | Mostly | Yes | Yes (2025) |
| **spaCy Matcher / PhraseMatcher** | Core engine — custom flag rules | Yes | Yes (native) | Yes |
| **textacy** | `subject_verb_object_triples()`, `direct_quotations()` — returns spaCy Spans with `.start_char`/`.end_char` | Yes (dep parse) | Yes | Yes (2025) |
| **medspaCy / ConText** | Uncertainty/negation detection; clinical origin but domain-agnostic algorithm — retarget with journalism patterns | Yes | Yes (entity spans) | Yes (2025) |
| **negspaCy** | Negation detection (Negex algorithm) | Yes | Yes | Moderate (2023) |
| **ClaimBuster** | Reference only — sentence-level check-worthiness score. API only, political text, model-based. Not usable as a library. | No | No | Research-active |
| **FactCC** | Reference only — factual consistency vs. source doc. Archived 2021. | No | No | Archived |

**Key finding:** No production library exists for causal connective detection or journalism-specific hedge detection. These must be built with spaCy `DependencyMatcher` + custom connective word lists (drawn from Penn Discourse Treebank connective taxonomy). No journalism organization (AP, Reuters, NYT, ProPublica) has released an NLP claim-detection library.

#### Build path

1. ~~**Notebook** (`analysis/layer1_copy_risk.ipynb`)~~ ✅ **Done** — `flag_text(text) -> list[Flag]`, 20 passing tests, colored HTML output with type legend
2. ~~**Evaluation gold set** (`evaluation/gold/layer1_gold.jsonl` + `run_eval.py`)~~ ✅ **Done** — 30 labeled sentences, precision/recall/F1 per flag type (overall F1 0.82)
3. **Streamlit app** (`ui/layer1_app.py`) — paste text, see colored inline highlights, sidebar flag table
4. **Browser/editor plugin** (later) — thin FastAPI wrapper; Chrome extension or ProseMirror plugin

#### Dependencies installed
- `spacy>=3.8.14` + `en_core_web_sm` model
- `textacy>=0.13.0`

---

### Layer 2 — Code Risk Checker

**Input:** `.py` or `.R` files (data journalism analysis scripts). Point at a single file or a full repo directory.

**Output:** Two views per file:
- **Risk flags** — line-level annotations for things that may be wrong (missing checks, bad practices)
- **Decision points** — methodological choices that need editorial sign-off (filter thresholds, join types, stat test selection)

**What it does NOT do:**
- Fix the code
- Re-run the analysis
- Judge whether the analysis is correct

#### Flag taxonomy (full list in `LAYER2_FLAGS.md`)

20 flag types across 6 categories: Import/Load, Column/Value, Joins, Statistical Analysis, Geographies, and a separate Decision Points layer. See [LAYER2_FLAGS.md](LAYER2_FLAGS.md) for the complete taxonomy with AP checklist references.

Key High-priority flags:

| Flag type | Example trigger | Language |
|---|---|---|
| `no_shape_check` | `read_csv()` with no `len()`/`.shape` afterward | Python/R |
| `no_na_check` | Load or merge with no `.isna()`/`is.na()` check | Python/R |
| `zip_as_numeric` | ZIP column cast to `int` or `float` | Python/R |
| `no_join_count_check` | `merge()` with no row count before/after | Python/R |
| `no_unmatched_check` | Left/outer join with no anti-join check | Python/R |
| `hardcoded_threshold` | `p < 0.05` with no comment | Python/R |
| `no_null_before_aggregation` | `.sum()`/`.mean()` with no prior null handling | Python/R |
| `sentinel_value_risk` | `!= -99` or `!= -999` in a numeric column | Python/R |
| `total_row_risk` | `"Total"` string in a column used for aggregation | Python/R |
| `percentage_without_base` | `/ len(df) * 100` with no denominator printed | Python/R |

Decision point categories: `filter_threshold`, `unit_of_analysis`, `join_type`, `stat_test_choice`, `exclusion_filter`, `date_cutoff`, `rate_denominator`, `time_period`, `deduplication`.

#### Two outputs, two audiences

- **Risk flags** → data team technical review. Catches bugs and omissions before the data team reads the code.
- **Decision points** → editor or senior reporter. Surfaces methodology choices that affect the story — filter basis, join type, stat test assumptions.

#### Open source building blocks

| Tool | Role | Maintained? |
|---|---|---|
| **ast** (stdlib) | Python AST parser — detects call patterns, hardcoded literals, merge keys | Yes |
| **re** (stdlib) | R analysis via line-level regex (no R AST available from Python) | Yes |
| **lintr** | R static analysis (future: feed results into Layer 2) | Yes |
| **sqlfluff** | SQL linter with plugin system (SQL support planned) | Yes (2025) |

#### Build path

1. ~~**Notebook** (`analysis/layer2_code_risk.ipynb`)~~ ✅ **Done** — `flag_code(path) -> list[CodeFlag]`, 29 tests passing, annotated HTML output, repo scanner, decision point detector
2. **CLI tool** (`risk-check-code myanalysis.py`) — prints annotated report to terminal
3. **Streamlit app** (`ui/layer2_app.py`) — upload file or paste path, see annotated output

---

### Layer 3 — Source/Notes Recall

**Input:** Reporter notes and source documents (Google Drive, PDFs, local files)

**Output:** Given a claim or phrase, returns the passage(s) in reporter notes that are most likely the source — with document name and excerpt.

**What it does NOT do:**
- Verify the claim is accurate
- Edit or summarize notes
- Replace the reporter's judgment about sources

#### Use case

Layer 1 flags: `"27% increase in evictions"` → `quantitative_claim [High]`

Reporter asks Layer 3: *"Where does this number come from?"*

Layer 3 returns: *"Closest match: city_housing_report_2024.pdf, page 4 — 'Eviction filings increased 27.3% year over year...'"*

#### Open source building blocks (researched)

| Tool | Role | Maintained? |
|---|---|---|
| **sentence-transformers** | Local embedding models — no data sent externally | Yes (2025) |
| **ChromaDB** | Local vector store — no cloud required | Yes (2025) |
| **pdfplumber** | PDF text extraction with layout awareness | Yes |
| **google-api-python-client** | Google Drive / Docs ingestion | Yes |
| **watchdog** | File system watcher to auto-index new documents | Yes |

**Data sensitivity:** All embeddings stay local. Nothing sent to external APIs. This is a hard requirement given sensitivity of reporter notes.

#### Build path

1. **Notebook** (`analysis/layer3_notes_recall.ipynb`) — index a folder of docs, run semantic search queries
2. **Streamlit app** (later) — upload docs, query by claim text
3. **Integration** (later) — Layer 1 flag → auto-query Layer 3

---

## Evaluation

Each tool needs to be measurable. Without evaluation, there's no way to know if rule changes help or hurt.

### Layer 1 evaluation

**Approach:** Build a labeled test set of journalism sentences.

- **Gold standard:** 100–200 journalism sentences, hand-labeled with flag types and spans
- **Sources:** AP style guide examples, ProPublica data stories, known problematic AI summaries
- **Metrics:**
  - Precision — of flags raised, how many were real risks?
  - Recall — of real risks, how many did we catch?
  - F1 per flag type — which rules are working?
  - False positive rate — is it over-flagging?
- **Format:** simple JSONL file — `{text, flags: [{start, end, flag_type, priority}]}`
- **Tool:** notebook or pytest fixture that runs the flagging function against the gold set

Key tension to measure: **precision vs. recall tradeoff**. A tool that flags everything is useless noise. A tool that misses causal claims is dangerous. The target is high recall on High-priority flags, reasonable precision overall.

### Layer 2 evaluation

- Gold standard: annotated notebooks with known methodological issues
- Metrics: same precision/recall per flag type
- Bonus: check against notebooks that produced published corrections (known errors)

### Layer 3 evaluation

- Gold standard: claim → correct source passage pairs from real reporting
- Metric: top-1 and top-3 retrieval accuracy (did the right document appear in results?)
- Metric: mean reciprocal rank (MRR)

---

## Decisions made

- **Prototype output:** Notebook HTML first (`IPython.display.HTML`), then Streamlit ✅
- **Color scheme:** By flag type (not priority) — more actionable for journalists ✅
- **Quote flag removed** — not relevant for data journalism checks; quotes are a general editorial concern, not a data risk ✅
- **Causal + certainty overlap:** Both flags kept — different editorial concerns, both surfaced in table ✅
- **Layer 3 data sensitivity:** Local-only embeddings confirmed ✅
- **Tier 3 (LLM fallback):** Deferred — keeping tool 100% rule-based for v1 ✅
- **Layer 2 language priority:** Python first (AST), R second (regex), SQL later ✅
- **All tools independent:** Each layer works standalone, connectable later ✅
- **Open source only:** spaCy (MIT), textacy (Apache 2.0), all stdlib — no proprietary models or external APIs ✅

## Open decisions (see OPEN_QUESTIONS.md)

- Suppression list for well-known entities (U.S., major countries, etc.)
- Evaluation gold set source — existing labeled data or build from public sources?

---

## Build order

| Phase | Files | Status |
|---|---|---|
| 1 | `analysis/layer1_copy_risk.ipynb` | ✅ Done — 20 tests passing |
| 2 | `evaluation/gold/layer1_gold.jsonl` + `run_eval.py` | ✅ Done — 30 sentences, F1 0.79 overall |
| 3 | `analysis/layer2_code_risk.ipynb` | ✅ Done — 29 tests passing, Python + R, repo scanner, decision points |
| 4 | `ui/layer1_app.py` (Streamlit) | Next |
| 5 | `ui/layer2_app.py` (Streamlit) | After Layer 1 UI |
| 6 | `analysis/layer3_notes_recall.ipynb` | After Layer 2 ships |
