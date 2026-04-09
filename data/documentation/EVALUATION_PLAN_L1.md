# Evaluation Plan — Layer 1 Copy Risk Checker

*How we know if the tool is working, getting better, or getting worse.*

**Last updated:** 2026-04-08
**Tool version:** Layer 1 notebook, 9 flag types, 33 unit tests passing

---

## What we are measuring

The tool flags risk patterns in text. A good tool:
- Catches the things that deserve a second look (**recall**)
- Doesn't flood the journalist with noise (**precision**)
- Behaves consistently — same input, same flags (**determinism**, already guaranteed by design)
- Improves when rules are tuned, without regressing elsewhere (**regression safety**)

We are **not** measuring whether the tool is "right" in an absolute sense. A flag is correct if a reasonable data journalist would agree the span deserves a second look, not if the claim turns out to be false.

---

## Metrics

For each flag type:

| Metric | Definition |
|---|---|
| **Precision** | Of all flags raised, what fraction were genuine risks? |
| **Recall** | Of all genuine risks in the text, what fraction were caught? |
| **F1** | Harmonic mean of precision and recall — single summary number per flag type |
| **False positive rate** | Flags raised on spans that don't warrant review |
| **Miss rate** | Genuine risks not caught |

**Target:** High recall on `quantitative_claim`, `vague_attribution`, `causal_claim`. Reasonable precision across all types. The cost of a miss is higher than the cost of a false positive — but a tool that flags everything is useless.

---

## Gold standard

A labeled test set of real journalism sentences — the ground truth the metrics are calculated against.

### Format

JSONL file at `evaluation/gold/layer1_gold.jsonl`. One record per sentence or short passage:

```json
{
  "id": "001",
  "source": "ProPublica — eviction story 2024",
  "text": "Evictions rose sharply in Los Angeles, increasing by 27%, which shows the new policy hurt renters.",
  "flags": [
    {"start": 9,  "end": 21, "flag_type": "trend_language",      "priority": "Medium"},
    {"start": 46, "end": 49, "flag_type": "quantitative_claim",   "priority": "High"},
    {"start": 57, "end": 62, "flag_type": "certainty_language",   "priority": "Medium"},
    {"start": 57, "end": 96, "flag_type": "causal_claim",         "priority": "High"},
    {"start": 23, "end": 34, "flag_type": "named_entity",         "priority": "Medium"}
  ],
  "notes": "Classic data journalism risk sentence — multiple overlapping flag types"
}
```

Fields:
- `id` — unique identifier
- `source` — where the sentence came from (for provenance)
- `text` — the exact input string
- `flags` — hand-labeled spans: character offsets, flag type, priority
- `notes` — optional annotator notes on edge cases or ambiguity

### Size targets

| Phase | Target | Purpose |
|---|---|---|
| **v1 (now)** | 30–50 sentences | Enough to catch obvious failures and false positive patterns |
| **v2** | 100–150 sentences | Enough for per-flag-type F1 to be meaningful |
| **v3** | 200+ sentences | Robust evaluation across story types and domains |

Start small. 30 well-chosen sentences are more valuable than 200 random ones.

### Sources for the gold set

In rough order of priority:

1. **Real data journalism copy** — pull sentences from published AP, ProPublica, NYT data stories that contain known risk patterns. Best signal because it's the actual domain.
2. **Known AI-generated summaries** — outputs from ChatGPT/Claude prompted to summarize data findings. High density of flags, good stress test.
3. **Constructed examples** — sentences written specifically to test edge cases (e.g., a causal claim with no connective word, a number with no percent sign).
4. **Negative examples** — clean sentences with no flags, to measure false positive rate.

Aim for roughly equal numbers of each flag type represented. Include at least 10 negative examples (no flags expected).

---

## Annotation process

Who labels the gold set and how.

### Labeler
At minimum: one data journalist with editing experience. Ideally two labelers independently, then reconcile disagreements — this surfaces ambiguous cases that become test edge cases.

### Instructions for labelers

> For each sentence: identify every span that a data journalist should verify before publication. For each span, assign the most specific flag type from this list: `quantitative_claim`, `vague_attribution`, `causal_claim`, `certainty_language`, `trend_language`, `comparative_claim`, `temporal_claim`, `named_entity`.
>
> A span is correct to flag if a reasonable data journalist would want to check it — not if it turns out to be wrong.
>
> Mark `start` and `end` as character offsets into the sentence (0-indexed). Use the exact matched text — don't extend the span beyond the triggering phrase.

### Inter-annotator agreement
If using two labelers: calculate Cohen's Kappa per flag type. Flag types with Kappa < 0.6 are ambiguous and need clearer rule definitions before the evaluation is meaningful.

---

## Evaluation script

`evaluation/run_eval.py` — runs the tool against the gold set and prints results.

### What it outputs

```
Flag type             Precision  Recall     F1         TP   FP   FN
────────────────────────────────────────────────────────────────────
quantitative_claim    0.91       0.88       0.89       44   4    6
vague_attribution     0.87       0.92       0.89       23   3    2
causal_claim          0.78       0.83       0.80       20   6    4
certainty_language    0.82       0.71       0.76       17   4    7
trend_language        0.93       0.89       0.91       25   2    3
comparative_claim     0.76       0.80       0.78       20   6    5
temporal_claim        0.88       0.91       0.89       31   4    3
named_entity          0.71       0.94       0.81       48   20   3
────────────────────────────────────────────────────────────────────
OVERALL               0.84       0.87       0.85

False positive examples (sample):
  [named_entity] "U.S." — well-known entity, not a risk in context
  [comparative_claim] "first" — ordinal used in narrative, not a comparison

Miss examples (sample):
  [causal_claim] "The rent increases pushed families out" — no connective word
```

### Running it

```bash
uv run python evaluation/run_eval.py
```

---

## Evaluation cadence

| When | What |
|---|---|
| After any change to `REGEX_PATTERNS` or `CERTAINTY_VERBS` | Run eval, check no flag type regresses by more than 5 F1 points |
| After adding a new flag type | Add at least 5 gold examples for the new type before claiming it works |
| Before moving to Streamlit | Full eval pass, results logged |
| Before any public demo | Full eval pass, known failure modes documented |

---

## Known failure modes (current)

Tracked here so they're visible and can be addressed systematically.

| Failure mode | Flag type | Example | Status |
|---|---|---|---|
| Well-known entities over-flagged | `named_entity` | "U.S.", "the Fed" | Open — suppression list planned |
| Implied causation missed | `causal_claim` | "The rent increases pushed families out" | Open — no connective word |
| Superlatives in narrative context | `comparative_claim` | "the first time we met" | Open — false positive |
| Normalized numbers missed | `quantitative_claim` | "a dozen", "hundreds of" | Open |
| No gold examples for new flags | `passive_attribution`, `quantitative_claim` (hedged) | "it was found that", "roughly $72,000" | Open — add 5+ examples per type to gold set |

---

## What good looks like

A tool the data team trusts enough to run on every story before publication, without feeling like it cries wolf. That means:

- **Precision above 0.80** on every flag type — fewer than 1 in 5 flags is noise
- **Recall above 0.85** on High-priority flag types — nearly all quantitative claims, vague attributions, and causal claims caught
- **No single flag type dominating** — if `named_entity` fires 10x more than everything else, it's drowning the signal
