# Layer 4 — Editorial Judgment Tool
## Scope document (not yet built)

*Last updated: 2026-04-16*

---

## What problem this solves

Layers 1 and 2 check **copy** and **code** independently against named rules.
Neither can answer the question that matters most in pre-publication review:

> "Does this analysis actually support what the story claims?"

Layer 4 takes both — a story draft and an analysis script — and uses an LLM to reason
about the gap between them. It produces a structured editorial memo, not a verdict.

**The tool does not decide if the story is right or wrong.**
It replaces the first 20 minutes of a data editor's review: surfacing the questions
a good editor would ask before the story goes to a senior editor or legal.

---

## How it differs from Layers 1–3

| Layer | Input | What it checks | Method |
|---|---|---|---|
| 1 | Story copy | Risk language in prose | Deterministic regex + spaCy |
| 2 | Analysis script | Technical mistakes in code | Deterministic AST + regex |
| 3 | Reporter notes | "Did the reporter have this?" | RAG over uploaded docs |
| **4** | **Story draft + analysis script** | **Does the analysis support the claim?** | **LLM reasoning** |

Layer 4 is the only layer that uses an LLM in the core reasoning path.
It is appropriate here because the task requires reading comprehension —
understanding what the story claims and whether the code produces it.

---

## Inputs

**Required:**
- Analysis script (`.py` or `.R`) — uploaded or pasted
- Story claim — either pasted headline + lede, or full draft

**Optional (improves output quality):**
- Layer 2 flag output — prepopulated if the user ran Layer 2 first
- Data source description — e.g. "ACS 5-year estimates, 2019–2023"

---

## Output: The Editorial Memo

A structured 7-section plain-English memo. Designed to be pasted into Slack,
attached to a CMS ticket, or used as a pre-publication checklist.

### Section structure

**1. Central claim**
One sentence: what is the story's main statistical assertion?
*Example: "The story claims that home-based child care workers over 50 make up the majority of the workforce in 38 states."*

**2. What the code produces**
Does the code produce a number or finding that matches that claim?
Flag any mismatch between the claim's framing and what the analysis actually computes.
*Example: "The code computes weighted percentage over 50 by state using IPUMS ACS 5-year estimates. The claim appears consistent with the output of `pct_over_50` in `state_grouped`."*

**3. Population and universe**
Who is included in the analysis? Who is excluded?
Is the population used in the code consistent with the population named in the story?
*Example: "Analysis covers OCC2010 code 4600 (child care workers) and IND1990 codes 862/863/761 filtered to self-employed workers. The story says 'home-based child care workers' — verify this definition matches the population claim."*

**4. Time coverage**
What period does the data cover? Is the final period complete?
Are year-over-year comparisons based on the same period each year?
*Example: "Code uses ACS 5-year 2024 sample (covers approximately 2019–2023). If the story says '2024 data,' clarify that this is a 5-year rolling estimate, not a single-year snapshot."*

**5. Comparison and context**
What is the story comparing to what? Is the comparison group fair?
What would change the headline if the comparison were constructed differently?
*Example: "The 'majority' claim is relative to all workers in these occupations. If restricted to paid employees only (excluding self-employed), the share over 50 may differ. Check whether the self-employed filter is editorially appropriate."*

**6. Sensitivity check**
What is the single most consequential methodological choice in the code?
If that choice were made differently, would it change the headline?
*Example: "The `GQ == '1'` filter (1970s household definition per Sadowski's methodology) is the most consequential filter. Removing it or using a different definition could materially change state-level estimates. This methodology choice should be documented in the story or methodology note."*

**7. The question a skeptical expert would ask**
One specific question a critical outside expert would raise about this analysis.
*Example: "Why use IPUMS ACS rather than the Current Population Survey for occupational data? ACS provides state-level sample sizes but may have different occupational coding than BLS standards."*

---

## What it explicitly does NOT do

- Does not say "the story is wrong"
- Does not rewrite the analysis or suggest alternative code
- Does not run the code or reproduce results
- Does not replace the data editor — it prepares the data editor for the conversation
- Does not flag every possible concern — it focuses on the most consequential ones

---

## Stack

```
anthropic          # claude-sonnet-4-6 — structured output via system prompt
streamlit          # UI — same repo, ui/layer4_app.py
python-dotenv      # .env loading for local dev
```

No database. No embeddings. Stateless — one API call per review.

The Layer 2 flagging logic can optionally be run first and its output
passed into the Layer 4 prompt as additional context.

---

## Prompt design (draft)

```
SYSTEM:
You are a senior data editor at a wire service reviewing an analysis
before publication. Your job is to surface risks and questions, not
to approve or reject the story. Be specific — cite variable names,
line numbers, and exact claims. Do not invent concerns that aren't
grounded in the code or story text.

USER:
STORY CLAIM:
{story_text}

ANALYSIS SCRIPT ({filename}):
{code_text}

LAYER 2 FLAGS ALREADY DETECTED:
{layer2_summary}   ← omit section if not provided

Produce a structured editorial memo with exactly these 7 sections:
1. Central claim
2. What the code produces
3. Population and universe
4. Time coverage
5. Comparison and context
6. Sensitivity check
7. Question a skeptical expert would ask

For each section, write 2–4 sentences. Be specific. Cite line numbers
or variable names where relevant. If you cannot determine something
from the code alone, say so explicitly rather than speculating.
```

---

## Key design decisions

**Use claude-sonnet-4-6, not a smaller model.**
The task requires genuine code + text comprehension. Haiku will hallucinate
variable names and miss subtle mismatches between claim and analysis.

**Structured sections, not free-form.**
Free-form LLM output is hard to act on. The 7-section structure maps to
specific editorial sign-off steps. Each section should produce one action item.

**"Say so explicitly" instruction.**
Critical — prevents the model from fabricating a confident-sounding assessment
when it doesn't have enough information. Uncertainty is more useful than wrong confidence.

**Layer 2 flags as optional context.**
Passing Layer 2 output into the prompt lets the LLM skip re-detecting technical issues
(which it may get wrong anyway) and focus on editorial reasoning. The two layers
complement rather than duplicate each other.

**One call, not a chain.**
No multi-step agentic flow. The entire review happens in a single API call.
Keeps latency low, cost predictable, and the output auditable.

---

## Cost estimate

| Script length | Story length | Estimated tokens | Estimated cost |
|---|---|---|---|
| 100 lines | 300 words | ~3,000 input | ~$0.03 |
| 300 lines | 800 words | ~7,000 input | ~$0.07 |
| 800 lines | 1,500 words | ~15,000 input | ~$0.15 |

At ~$0.05–0.15 per review, affordable for newsroom use at moderate volume.

---

## Privacy considerations

Story text and analysis code are sent to Anthropic's API.
Same policy as Layer 3 (OpenAI embeddings): appropriate for most newsroom use,
but teams with strict pre-publication confidentiality policies should review
Anthropic's data handling terms before deploying.

For fully local operation, a self-hosted model (e.g. via Ollama + llama3)
could be substituted, but output quality will degrade significantly on the
code-comprehension sections.

---

## Build order / prerequisites

1. Layer 2 (`ui/layer2_app.py`) — done ✅
2. Layer 4 can be built independently — does not require Layer 2 to run
3. Optional enhancement: pass Layer 2 output as context (requires running both in sequence)

**Estimated build time:** 1–2 sessions. The plumbing is simpler than Layer 3.
The hard work is prompt iteration — plan for 3–5 rounds of testing against
real stories before the output is trustworthy.

---

## Open questions before building

- **Q1:** Should the story input be headline+lede only, or full draft?
  Full draft gives better context but may hit token limits for long pieces.
  Recommendation: full draft up to ~2,000 words, truncate with warning beyond that.

- **Q2:** Should Layer 4 be a standalone app or integrated into Layer 2?
  Recommendation: standalone (`ui/layer4_app.py`) — keeps the stateless code checker
  separate from the LLM-dependent editorial tool. Different trust levels.

- **Q3:** How do we evaluate output quality?
  Unlike Layers 1–2, there's no precision/recall metric.
  Recommendation: build a gold set of 10 story+script pairs where a data editor
  has written the actual memo. Score LLM output against it qualitatively.

- **Q4:** Should the memo be editable in the UI before sharing?
  Recommendation: yes — add a `st.text_area` with the memo pre-populated.
  Editors should be able to annotate before forwarding to the reporter.
