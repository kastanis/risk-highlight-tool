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
