# Layer 1 Pattern Sources

Sources for each hardcoded flag type and the YAML pattern registry.
Update this file whenever a pattern is added, modified, or removed.

---

## How to read this file

**Source tiers (in priority order):**
1. **Editorial** — observed directly in AI-assisted or AI-generated copy; primary source
2. **Journalism practice** — AP Stylebook, SPJ ethics code, verification handbooks, data journalism literature
3. **Academic (NLP/computation)** — peer-reviewed or arXiv papers on hedge detection, framing, bias
4. **Academic (journalism studies)** — content analysis, framing theory, media criticism

---

## Hardcoded flags (`REGEX_PATTERNS` + `_flag_spacy`)

### `quantitative_claim` — High

Hedged figures ("nearly 400,000") and bare specific numbers (27%, $3 million).

**Sources:**
- **Journalism practice** — AP Stylebook: numbers without attribution require sourcing; hedged figures ("about", "roughly") signal estimation, not confirmed data
- **Journalism practice** — Silverman, Craig. *Verification Handbook* (EJC, 2014). Ch. 3: verifying statistics is a primary fact-check task
- **Journalism practice** — Cairo, Alberto. *The Functional Art* (2013); Huff, Darrell. *How to Lie with Statistics* (1954) — both cover misrepresentation via hedged or unsourced figures
- **Editorial** — specific numbers (percentages, dollar amounts, large counts) are the most common sourcing gap in AI-assisted data stories

---

### `vague_attribution` — High

"Experts say", "officials said", "studies show", "according to sources".

**Sources:**
- **Journalism practice** — AP Stylebook, Anonymous sources section: unnamed sources require editorial justification; "experts say" without names is discouraged
- **Journalism practice** — SPJ Code of Ethics: "identify sources clearly" and "provide as much information as possible on sources' reliability"
- **Journalism practice** — Silverman. *Verification Handbook* (2014). Unattributed claims are a primary verification target
- **Academic (NLP)** — Recasens, Marta, et al. "Linguistic Models for Analyzing and Detecting Biased Language." ACL 2013. Identifies vague attribution as a framing device that obscures agency
- **Academic (NLP)** — Wiebe, Janyce, et al. "Annotating Expressions of Opinions and Emotions in Language." *Language Resources and Evaluation* 39.2-3 (2005). Source attribution is a core subjectivity signal

---

### `passive_attribution` — High

"It has been reported", "it is estimated", "it was found that".

**Sources:**
- **Journalism practice** — AP Stylebook, Passive voice guidance: passive constructions hide the actor responsible for a claim
- **Academic (NLP)** — Recasens et al. (ACL 2013) — passive constructions appear in the "framing bias" category where agent removal softens or obscures accountability
- **Academic (NLP)** — Rashkin, Hannah, et al. "Truth of Varying Shades: Analyzing Language in Fake News and Political Fact-Checking." EMNLP 2017. Passive attribution correlates with lower verifiability
- **Editorial** — common pattern in AI-generated text: LLMs use passive constructions to assert things without citing a source

---

### `causal_claim` — High

Causal connectives: "led to", "caused", "resulted in", "because of", "due to".

**Sources:**
- **Journalism practice** — Cairo. *The Functional Art* (2013); *How Charts Lie* (2019) — conflating correlation with causation is a primary data journalism error
- **Journalism practice** — Huff. *How to Lie with Statistics* (1954) — causal language without mechanism is a classic misrepresentation
- **Academic (journalism studies)** — Tankard, James W. "The Empirical Approach to the Study of Media Framing." *Framing Public Life* (2001). Causal framing is one of five primary journalistic frames
- **Editorial** — AI-generated text frequently asserts causation (policy "led to" outcome) without citing the study or mechanism

---

### `certainty_language` — Medium

Certainty verbs: "shows", "proves", "confirms", "demonstrates", "reveals", "establishes".

**Sources:**
- **Academic (NLP)** — Hyland, Ken. *Hedging in Scientific Research Articles* (1998). Defines hedging vs. boosting spectrum; certainty verbs are "boosters" that overclaim strength of evidence
- **Academic (NLP)** — Szarvas, György, et al. "Cross-Genre and Cross-Domain Detection of Semantic Uncertainty." *Computational Linguistics* 38.2 (2012). Certainty vs. uncertainty classification in scientific and news text
- **Academic (NLP)** — Medlock, Ben, and Ted Briscoe. "Weakly Supervised Learning for Hedge Classification in Scientific Literature." ACL 2007
- **Editorial** — verb list (`shows`, `proves`, `confirms`, `demonstrates`, `reveals`, `establishes`, `means`) reflects most common overstatement verbs seen in AI-generated summaries

---

### `trend_language` — Medium

Vivid directional verbs: "surged", "soared", "plummeted", "collapsed", "dropped sharply".

**Sources:**
- **Journalism practice** — Standard data journalism critique: magnitude language ("surged", "soared") without a baseline figure is unverifiable
- **Academic (journalism studies)** — Entman, Robert M. "Framing: Toward Clarification of a Fractured Paradigm." *Journal of Communication* 43.4 (1993). Salience framing via vivid verb choice
- **Academic (NLP)** — Lim, Siying, et al. "Annotating and Predicting Linguistic Uncertainty in News." ACL Findings 2023 — directional claims without magnitude are flagged as low-precision assertions
- **Editorial** — verb list is editorially constructed; covers the most common vivid trend verbs seen in AI-generated economic and policy copy

---

### `comparative_claim` — Medium

Superlatives ("highest", "lowest", "most"), "more than / less than", "all-time".

**Sources:**
- **Journalism practice** — Data journalism convention: comparative claims require a stated baseline (compared to what? over what period?)
- **Academic (statistics)** — Huff. *How to Lie with Statistics* (1954) — superlatives without context ("the highest rate") are a classic misleading framing
- **Academic (NLP)** — Comparative claim detection is a subtask in fact-checking research; see FEVER shared task (Thorne et al. 2018) — comparatives are among the hardest claims to verify
- **Editorial** — regex is editorially constructed; "highly unlikely/likely" added because AI-generated text uses these as false precision hedges

---

### `temporal_claim` — Medium

"Last year", "since 2018", "in recent years", "over the past decade", "historically".

**Sources:**
- **Journalism practice** — Standard verification practice: time references must be accurate and current; "recently" and "historically" are vague and require grounding
- **Journalism practice** — Silverman. *Verification Handbook* (2014). Date accuracy is a core verification check, especially for breaking news
- **Editorial** — regex is editorially constructed; the primary risk is stale copy reused without updating time references, which is common in AI-assisted drafts

---

### `named_entity` — Medium (via spaCy NER)

Named persons, organizations, places, groups, monetary amounts, counts, percentages, dates, times.

**Sources:**
- **NLP tooling** — spaCy `en_core_web_sm` NER model (Honnibal & Montani, 2017). Entity types: PERSON, ORG, GPE, NORP, MONEY, CARDINAL, PERCENT, DATE, TIME
- **Journalism practice** — Name accuracy and role accuracy are standard copy desk checks; NER surfaces all named entities for human review
- **Editorial** — MONEY, CARDINAL, PERCENT are promoted to `quantitative_claim` (High); DATE/TIME to `temporal_claim` (Medium); PERSON/ORG/GPE/NORP to `named_entity` (Medium)

---

## YAML pattern registry (`data/patterns/layer1_patterns.yaml`)

Patterns added here should follow the same source-documentation practice.
When activating a commented-out example or adding a new pattern, add a row to this table.

| Pattern (brief) | Flag type | Priority | Source tier | Source |
|---|---|---|---|---|
| *(none active yet)* | — | — | — | — |

### Commented-out examples in the YAML file

These are documented here for traceability. Activate them by moving above `patterns: []` in the YAML.

| Pattern | Flag type | Priority | Source |
|---|---|---|---|
| "it is worth noting / important to note" | `passive_attribution` | Medium | Editorial + AI detection research (Guo et al. 2023 "How Close is ChatGPT to Human Experts?") |
| "delve into / underscore / multifaceted" | `passive_attribution` | Medium | Editorial — LLM-specific lexical tells; see RAID benchmark (Peng et al. 2024, arXiv 2405.07940) |
| "a significant number / a large proportion" | `quantitative_claim` | High | Editorial — vague quantity slips past `vague_attribution` (no source verb required here) |
| "clearly / obviously / undoubtedly" | `certainty_language` | High | Academic — Hyland (1998) booster category; also Binoculars (Hans et al. 2024, arXiv 2401.12070) |
| "on one hand … on the other hand" | `comparative_claim` | Medium | Journalism practice — false balance framing; Columbia Journalism Review, Poynter AI coverage guidance |
| "this highlights / underscores the importance" | `passive_attribution` | Medium | Editorial + AI detection — structural filler common in LLM-generated prose; RAID benchmark |

---

## Key references (full citations)

- AP Stylebook. Current edition. apstylebook.com
- Cairo, Alberto. *The Functional Art*. New Riders, 2013.
- Cairo, Alberto. *How Charts Lie*. W.W. Norton, 2019.
- Entman, Robert M. "Framing: Toward Clarification of a Fractured Paradigm." *Journal of Communication* 43.4 (1993): 51–58.
- Hans, Abhimanyu, et al. "Binoculars: Zero-Shot Detection of LLM-Generated Text." arXiv 2401.12070, 2024.
- Huff, Darrell. *How to Lie with Statistics*. W.W. Norton, 1954.
- Hyland, Ken. *Hedging in Scientific Research Articles*. John Benjamins, 1998.
- Medlock, Ben, and Ted Briscoe. "Weakly Supervised Learning for Hedge Classification in Scientific Literature." ACL 2007.
- Peng, Liam, et al. "RAID: A Shared Benchmark for Robust Evaluation of Machine-Generated Text Detectors." arXiv 2405.07940, 2024.
- Rashkin, Hannah, et al. "Truth of Varying Shades: Analyzing Language in Fake News and Political Fact-Checking." EMNLP 2017.
- Recasens, Marta, et al. "Linguistic Models for Analyzing and Detecting Biased Language." ACL 2013.
- Silverman, Craig (ed.). *Verification Handbook*. European Journalism Centre, 2014. verificationhandbook.com
- SPJ Code of Ethics. spj.org/ethicscode.asp
- Szarvas, György, et al. "Cross-Genre and Cross-Domain Detection of Semantic Uncertainty." *Computational Linguistics* 38.2 (2012): 335–367.
- Tankard, James W. "The Empirical Approach to the Study of Media Framing." In *Framing Public Life*, ed. Reese et al. Erlbaum, 2001.
- Thorne, James, et al. "FEVER: A Large-scale Dataset for Fact Extraction and VERification." NAACL 2018.
- Wiebe, Janyce, et al. "Annotating Expressions of Opinions and Emotions in Language." *Language Resources and Evaluation* 39 (2005): 165–210.
