# Benchmark Eval — Analysis (Run: 2026-04-23)

100-snippet benchmark comparing the Layer 1 rule-based tool against GPT-4o.
Source: `snippets.csv` → `run_benchmark.py` → `run_llm.py` → `score_benchmark.py`

---

## Overall binary metrics (flag vs clean)

| Metric    | Tool  | LLM   |
|-----------|-------|-------|
| Accuracy  | 0.870 | 0.960 |
| Precision | 0.897 | 0.957 |
| Recall    | 0.967 | 1.000 |
| F1        | 0.930 | 0.978 |
| TP        | 87    | 90    |
| FP        | 10    | 4     |
| FN        | 3     | 0     |
| TN        | 0     | 6     |

Tool–LLM agreement rate: **91/100 (91%)**

The tool's 0.93 F1 vs GPT-4o's 0.98 is a much narrower gap than you'd expect for a
regex + NER system vs a frontier LLM. But the failure modes are structurally different.

---

## Per-issue-type breakdown

| Flag type          | T-P  | T-R  | T-F1 | L-P  | L-R  | L-F1 | Gold N |
|--------------------|------|------|------|------|------|------|--------|
| causal_claim       | 0.89 | 0.47 | 0.62 | 0.92 | 0.71 | 0.80 | 17     |
| certainty_language | 0.77 | 0.83 | 0.80 | 0.89 | 0.67 | 0.76 | 12     |
| comparative_claim  | 0.77 | 0.69 | 0.73 | 1.00 | 0.63 | 0.78 | 49     |
| named_entity       | 0.25 | 0.71 | 0.37 | 0.33 | 0.57 | 0.42 | 7      |
| passive_attribution| 1.00 | 0.67 | 0.80 | 1.00 | 0.67 | 0.80 | 15     |
| quantitative_claim | 0.93 | 0.89 | 0.91 | 0.89 | 0.96 | 0.92 | 57     |
| temporal_claim     | 0.85 | 0.91 | 0.88 | 0.96 | 0.84 | 0.90 | 57     |
| trend_language     | 0.90 | 0.50 | 0.64 | 1.00 | 0.33 | 0.50 | 18     |
| vague_attribution  | 0.89 | 0.73 | 0.80 | 0.78 | 0.85 | 0.81 | 33     |

---

## Source category breakdown

| Category       | N  | Tool Acc | LLM Acc | T-FP | T-FN | L-FP | L-FN |
|----------------|----|----------|---------|------|------|------|------|
| ai             | 25 | 0.92     | 1.00    | 0    | 2    | 0    | 0    |
| edited         | 47 | 0.89     | 0.96    | 5    | 0    | 2    | 0    |
| pr             | 5  | 1.00     | 1.00    | 0    | 0    | 0    | 0    |
| wire/draft     | 22 | 0.77     | 0.91    | 5    | 0    | 2    | 0    |

---

## Tool false positives — all the same root cause

Every FP is a **clean, well-sourced sentence that happens to contain a date, count, or named entity.**

| ID  | Text (truncated)                                                  | Tool types fired               |
|-----|-------------------------------------------------------------------|-------------------------------|
| 091 | "…7-to-4 vote after nearly six hours of public testimony"        | quantitative_claim, temporal  |
| 092 | "…passed the bill 62-38 on Thursday…"                            | temporal_claim                |
| 093 | "The school opened in September 2018…"                            | temporal_claim, quantitative  |
| 094 | "Dr. Elena Vasquez…announced…at a press conference Tuesday"       | named_entity, temporal        |
| 095 | "The contract, signed in March 2021…"                             | temporal_claim                |
| 096 | "Federal prosecutors charged the company's CFO…last week"         | named_entity, comparative, temporal |
| 097 | "…capacity for 150 residents and a staff of 40…"                  | temporal_claim, quantitative  |
| 098 | "Senator Maria Cantwell introduced…citing a recent audit…"        | named_entity, temporal        |
| 099 | "The analysis was conducted by the Pew Research Center…"          | named_entity                  |
| 100 | "…repaired more than 40 miles of water main over the summer…"     | comparative_claim, temporal   |

**Root cause:** the tool has no concept of context. It fires the pattern regardless of whether
the surrounding sentence provides proper attribution. A vote count in a council vote is not a
quantitative risk. A named person announcing something is not a named entity risk.

**Fix signal:** a source-presence check — if a number or entity appears in a sentence that
also contains a fully-named institutional source (named ORG + named PERSON), suppress the flag
or downgrade priority. This would likely cut FPs by 50%+.

---

## Tool false negatives — all regex gaps

| ID  | Text                                                                          | Missed type(s)                         | Why the regex missed it |
|-----|-------------------------------------------------------------------------------|----------------------------------------|-------------------------|
| 022 | "The program **was found to have** disproportionately burdened…according to an internal review" | passive_attribution, vague_attribution | Regex requires `"it was found"` — drops the `"it"` and doesn't catch this construction |
| 068 | "The government's response…**was widely considered** too slow…"               | passive_attribution                    | `"widely considered"` without a trailing `"to"` doesn't match `"is/was widely considered to"` |
| 084 | "**Many economists argue** that rent control policies do more harm than good…" | vague_attribution, comparative, temporal | Regex catches `"many believe/say/argue"` but `"economists"` is a specific profession — the `many` precedes a noun, not a verb, so the pattern doesn't fire |

All three are fixable with regex additions. They're not fundamental gaps, just missing pattern shapes.

---

## Issue-type miss analysis

### Types the tool most often missed (within flagged rows)

| Type                | Missed N |
|---------------------|----------|
| comparative_claim   | 15       |
| trend_language      | 9        |
| causal_claim        | 9        |
| vague_attribution   | 9        |
| quantitative_claim  | 6        |
| temporal_claim      | 5        |
| passive_attribution | 5        |
| certainty_language  | 2        |
| named_entity        | 2        |

### Types the tool fired on but weren't in gold (noise by type)

| Type               | Extra N |
|--------------------|---------|
| named_entity       | 15      |
| comparative_claim  | 10      |
| temporal_claim     | 9       |
| quantitative_claim | 4       |
| certainty_language | 3       |
| vague_attribution  | 3       |

### Types the LLM most often missed

| Type                | Missed N |
|---------------------|----------|
| comparative_claim   | 18       |
| trend_language      | 12       |
| temporal_claim      | 9        |
| passive_attribution | 5        |
| causal_claim        | 5        |
| vague_attribution   | 5        |
| certainty_language  | 4        |
| named_entity        | 3        |
| quantitative_claim  | 2        |

### Types the LLM fired on but weren't in gold

| Type               | Extra N |
|--------------------|---------|
| named_entity       | 8       |
| vague_attribution  | 8       |
| quantitative_claim | 7       |
| temporal_claim     | 2       |

---

## Key findings by flag type

### `causal_claim` — tool recall 0.47, LLM recall 0.71
Both miss causal claims, but the tool misses nearly twice as many. The tool only fires on
explicit connective phrases (`"led to"`, `"caused"`, etc.). Implicit causation — `"driven by"`,
`"pricing out"`, `"affecting"` — goes undetected by both.

### `trend_language` — tool recall 0.50, LLM recall 0.33
The most interesting reversal: **the tool outperforms GPT-4o on recall here.** The tool has a
tight vocabulary of dramatic motion verbs. GPT-4o consistently under-flags `"rose sharply"`,
`"declined sharply"`, `"significantly worse"` — it appears to treat those as well-qualified
statements rather than unverified directional claims.

### `comparative_claim` — tool recall 0.69, LLM recall 0.63
Both are weak. The tool misses 15, the LLM misses 18. The missed cases tend to be softer
comparatives: `"roughly three times higher"`, `"more harm than good"`, `"long run"`. The
`"long run"` phrasing has no temporal regex match.

### `named_entity` — tool precision 0.25, LLM precision 0.33
Both have terrible precision. This is partly a **benchmark design problem**: named entity
flagging is almost always a FP in context because clean journalism routinely names people and
places. The tool fires on any named entity including fully-attributed clean sentences. The
category may need to be retired or scoped much more narrowly — only flag named entities when
attached to an unverified claim, not as a standalone signal.

### `passive_attribution` — both recall 0.67, both precision 1.00
When either system fires on passive attribution, it's right 100% of the time. But both miss a
third of cases. The missed constructions are actor-removed patterns without `"it"` as subject:
`"was found to"`, `"widely considered"`, `"expected to"`.

### `vague_attribution` — tool recall 0.73, LLM recall 0.85
LLM has a meaningful edge here because it reads semantically. The tool's regex requires specific
phrase shapes (`"experts say"`, `"many believe"`) and misses profession-as-collective-noun
patterns like `"economists argue"` and `"observers note"`.

---

## The 9 tool–LLM disagreements

The split is clean and diagnostic:

**3 rows the LLM got right, tool missed** — all passive/vague attribution requiring semantic reading:
- [022] `"was found to have"` — passive without `"it"`
- [068] `"widely considered"` — passive without `"to"`
- [084] `"Many economists argue"` — vague attribution with profession noun

**6 rows the tool flagged, LLM correctly left alone** — all clean sentences with incidental dates/entities:
- [093] School opening date
- [094] Named person making announcement
- [095] Contract signing date
- [096] Named institution filing charges
- [098] Named senator introducing legislation
- [099] Named research org citing named data sources

The LLM reads context; the tool reads patterns. The disagreements are not noise — they're a
clean map of each system's structural blind spot.

---

## Source category analysis

| Category       | Interpretation |
|----------------|----------------|
| AI-generated   | Easy for both — AI text uses explicit attribution phrases the tool's regex handles well |
| Edited journalism | Tool struggles more — edited copy varies phrasing more than the regex patterns expect |
| Wire/draft     | Worst for the tool (0.77 acc) — wire copy has formulaic patterns that trigger regex but are fine in context |
| PR             | Both perfect — PR copy is dense with superlatives and vague claims, easy to catch |

---

## Actionable takeaways

### Fix the tool's FP rate first
All 10 FPs are the same problem. A source-presence check in the flagging logic — suppress or
downgrade flags when a fully-named source (named ORG + named PERSON + clear attribution verb)
is present in the sentence — would likely cut tool FPs by half without harming recall.

### Add three regex patterns to close the FN gaps
1. `"(was|were|has been)\s+found\s+to"` — catches [022]
2. `"(is|was|were)\s+(widely\s+)?considered\s+(too|very|quite|an?)"` — catches [068]
3. `"\b(economists?|scientists?|doctors?|lawyers?|professors?)\s+argue"` — catches [084]

### Reconsider `named_entity` as a standalone flag
At 0.25 precision for the tool and 0.33 for the LLM, it adds more noise than signal. Consider
only firing named_entity flags when the entity is the sole attribution for a factual claim —
i.e., no other named org, no named data source present in the sentence.

### The LLM is not uniformly better
On `trend_language` the tool wins outright. On `comparative_claim` they're roughly tied and
both weak. The LLM's advantage is concentrated in semantic attribution reading. For production
use, a hybrid — tool regex as fast first pass, LLM only on borderline cases — would outperform
either alone.

### `comparative_claim` and `causal_claim` recall are the biggest open gaps for both systems
18 gold `comparative_claim` instances and 9 gold `causal_claim` instances were missed by the
LLM. These aren't just tool problems — they're genuinely hard. Implicit causation and soft
comparatives (`"more harm than good"`, `"increasingly unaffordable"`) require reading the full
sentence structure, not just surface patterns.
