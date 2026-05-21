# Open Questions — Risk Highlight Tool

*Decisions still needed. Answered questions moved to PROPOSAL.md § Decisions made.*

---

## Layer 1 — Copy Risk Checker

**Q1. Suppression list for well-known entities**
Named entities like "U.S.", "Iran", "the Fed" are flagged as `named_entity` (grey) but rarely need
verification in standard data journalism. Should there be a configurable suppression list of
entities to skip, or is the grey low-salience flag acceptable noise?

**Q2. Trend language and vague attribution recall — partially resolved**
`trend_language` F1 improved from 0.67 → 0.86 (recall 0.50 → 0.75) by adding
`significantly worse/better`, `dramatic drop/decline`, `dramatically dropped/worsened`.
`vague_attribution` F1 improved from 0.77 → 0.93 (recall 0.62 → 0.88) by adding
`advocates?` noun and `found/find/finds` verbs. 2 FNs remain in `trend_language`,
1 FN in `vague_attribution` — address when gold set is expanded to v2 (100+ sentences).

---

## Layer 2 — Code Risk Checker

**Q3. R coverage gap**
The R checker is regex-based (no AST). `no_shape_check` and `no_na_check` detection
depends on window proximity to load lines — works well for linear scripts, degrades
for scripts where load and checks are separated by many lines. Accept this limitation
or invest in a Python-side R parser (e.g. `rpy2`)?

**Q4. Decision points — noise level**
The decision point detector fires on any `groupby()`, any filter threshold, any join type.
In a typical analysis script this produces 10–20 entries. Is that useful signal for an editor,
or too much to act on? Consider: only surface decision points that also have a risk flag on
the same line?

**Q5. `.ipynb` support**
The current `flag_code()` handles `.py` and `.R` only. Jupyter notebooks (`.ipynb`) need
cell extraction via `nbformat` before analysis. High value since most analysts work in notebooks.
Add as next Layer 2 feature?

**Q6. Layer 2 gold set**
No labeled evaluation set exists for Layer 2 yet. Do you have annotated notebooks with known
issues, or should we construct synthetic examples and label them?

---

## Layer 3 — Notes Recall

**Q7. Chunk size tuning**
`CHUNK_SIZE = 400` characters was chosen without systematic testing. Shorter chunks (200–250)
may improve precision for dense documents; longer chunks (600–800) may improve recall for
narrative prose. Should be tuned against a labeled `layer3_gold.jsonl` set once that exists.

**Q8. Top-K threshold**
Results are returned for all top-5 regardless of score. A match score below ~0.35 is likely
noise. Should there be a minimum score cutoff, or a UI warning when the best match is weak?

**Q9. Local-only version for sensitive newsrooms**
The deployed app sends text to OpenAI. For reporters with strict data policies (embargoed material,
source protection), a fully local version using `sentence-transformers` + ChromaDB is stubbed in
`pyproject.toml`. Activate when needed — local model download is ~80MB, first-run slow on CPU.

**Q10. Multi-file deduplication**
If the same passage appears verbatim in two uploaded documents, both will surface in results.
Should duplicate passages be collapsed, or is showing both occurrences useful (e.g., same quote
in interview notes and a PDF)?

---

## Deferred (not blocking)

**D1. Tier 3 LLM fallback (Layer 1)**
Keeping tool 100% rule-based for v1. Revisit after eval reveals what rules consistently miss:
- implied causation (causal claim with no connective word)
- normative-as-fact (opinion framed as conclusion)

**D2. Browser/editor plugin**
Architecture is ready (thin FastAPI wrapper around `flag_text()`).
Build after Streamlit demo validates the UX.

**D3. SQL support (Layer 2)**
`sqlfluff` is the right base. Custom rules needed for: `SELECT *`, missing `WHERE` clauses
on aggregations, implicit type casting. Scope after Python + R are solid.
