# Layer 1 — Scores Log

Benchmark: `evaluation/benchmark/snippets.csv` (100 rows)
LLM baseline: GPT-4o, temperature 0 (run once, held fixed across tool iterations)

---

## Scores log

| Date       | Change                                                        | Tool Acc | Tool P | Tool R | Tool F1 | FP | FN |
|------------|---------------------------------------------------------------|----------|--------|--------|---------|----|----|
| 2026-04-23 | Baseline                                                      | 0.870    | 0.897  | 0.967  | 0.930   | 10 |  3 |
| 2026-04-23 | +2 passive_attribution patterns; +profession-noun vague_attribution; remove named_entity | 0.910 | 0.909 | 1.000 | 0.952 | 9 | 0 |

LLM (GPT-4o) baseline for reference: Acc 0.960 / P 0.957 / R 1.000 / F1 0.978 / FP 4 / FN 0

---

## Change log

### 2026-04-23 — iteration 1

**Changes made:**
- `passive_attribution` regex: added `\b(?:was|were|has\s+been)\s+found\s+to\b` — catches "was found to have" without leading "it"
- `passive_attribution` regex: added `\b(?:is|was|were)\s+(?:widely\s+)?considered\s+(?:too|very|quite|an?\s+\w+|the\s+\w+)` — catches "widely considered too slow"
- `vague_attribution` regex: added `\b(?:economists?|doctors?|lawyers?|professors?|historians?|sociologists?|psychologists?)\s+(?:say|said|argue|argued|warn|warned|suggest|suggested|claim|claimed)\b` — catches "Many economists argue"
- `named_entity` removed from `NER_RULES` and `FLAG_COLORS` — was producing noise (0.25 precision) without meaningful signal for data journalism use case

**Effect:**
- Recall: 0.967 → 1.000 (all 3 FNs resolved)
- Precision: 0.897 → 0.909 (slight improvement — named_entity removal reduced FPs by 1)
- F1: 0.930 → 0.952
- FN: 3 → 0
- FP: 10 → 9
- `passive_attribution` F1: 0.80 → 0.89
- `vague_attribution` F1: 0.80 → 0.84

**Remaining FPs (9):** all in true-negative rows — tool fires on dates and counts in clean,
well-sourced sentences. Root cause is context blindness, not pattern error. Next step is a
source-presence suppression check.

---

## Per-issue-type history

| Flag type           | Baseline F1 | After iter 1 | Delta |
|---------------------|-------------|--------------|-------|
| causal_claim        | 0.62        | 0.62         | —     |
| certainty_language  | 0.80        | 0.80         | —     |
| comparative_claim   | 0.73        | 0.73         | —     |
| named_entity        | 0.37        | removed      | —     |
| passive_attribution | 0.80        | 0.89         | +0.09 |
| quantitative_claim  | 0.91        | 0.91         | —     |
| temporal_claim      | 0.88        | 0.88         | —     |
| trend_language      | 0.64        | 0.64         | —     |
| vague_attribution   | 0.80        | 0.84         | +0.04 |

---

## Next candidates (in recommended order)

1. **Source-presence suppression for FPs** — 9 remaining FPs are all clean sentences with dates/counts/named sources. If a sentence contains a fully-named ORG or PERSON as the attribution subject, suppress `temporal_claim` and `quantitative_claim` flags. High-risk change — do carefully and verify against all 90 TP rows.

2. **`causal_claim` recall (current: 0.47)** — tool misses implicit causation: "driven by", "pricing out", "affecting". Additive regex, lower risk.

3. **`trend_language` recall (current: 0.50)** — misses "increasingly unaffordable", "growing gap". Additive regex, lower risk.

4. **`comparative_claim` recall (current: 0.69)** — misses "more harm than good", "long run". Additive regex, lower risk.
