# Bulletproofing Suite — Vision

*Last updated: 2026-04-23*

---

## The goal

A repo-aware bulletproofing suite for data journalism. Instead of uploading files
one by one, you point the tool at a story repo and it produces a single sign-off
package covering code, copy, methodology, and sourcing.

The workflow:

```
Reporter opens a PR or flags a story for review
→ Tool runs against the repo
→ Produces a single bulletproofing report
→ Editor reviews the report before sign-off
```

Everything is already in the repo: the analysis scripts, the data (or data paths),
the story draft, the methodology notes. No uploads needed.

---

## The three failure modes in data journalism

**1. The analysis is wrong**
Bad join, wrong filter, silent NAs, hardcoded threshold. The code is technically
broken or methodologically questionable.
→ Layer 2 catches this. Already built.

**2. The copy overstates the analysis**
The number in the lede doesn't match what the code actually produces, or the
framing is stronger than the evidence.
→ Layer 4 catches this. Not yet built.

**3. The sourcing isn't there**
A claim in the story has no source in the notes, no citation in the code, and
no paper trail.
→ Layer 3 catches this when integrated with Layer 1. Partially built.

---

## What a repo-aware tool would do

**1. Find the code automatically**
Scan for `.py` / `.R` / `.ipynb` files, run Layer 2 on each, aggregate flags.

**2. Find the story draft**
Look for a `README.md`, `story.md`, `draft.txt`, or a `docs/` folder.
Or the reporter specifies the file path.

**3. Cross-reference code → copy**
Run Layer 1 on the story draft. For each flagged claim, search the code for the
variable or calculation that produces it. That's Layer 4.

**4. Check reproducibility**
Does `main.py` / `analysis.R` run without errors? Does it produce the expected
output files? Hard to do in a browser — straightforward against a repo.

**5. Generate the sign-off package**
- Layer 2 flag summary (code risks)
- Layer 4 editorial memo (does the analysis support the claim?)
- Methodology note draft (generated from Layer 2 decision points)
- Pre-publication checklist with open items requiring human sign-off

---

## What's missing from the current suite

### Layer 4 — Editorial Judgment *(most important gap)*
Cross-references story claims against the code that produced them. This is the
connective tissue. Nothing else in the suite does this. Spec: `docs/LAYER4_SCOPE.md`.

### Methodology note generator
Every data story should publish a methodology note. Reporters write these from
scratch. The tool could generate a draft from the Layer 2 decision points —
"we used a left join on county FIPS codes, we excluded records before 2018,
we defined X as Y." Editors already have all this from the decision point
checklist. Turning it into publishable prose is a short LLM call.

### Pre-publication checklist
A single-page summary: here's what the tool found, here's what still needs
human sign-off, here's what's cleared. A sign-off document that an editor
and reporter both review before publication. Structured output from running
all layers together.

### Reproducibility check
Does the script actually run top-to-bottom without errors? Layer 2 does static
analysis but never executes the code. A sandboxed execution check would catch
a whole class of errors that static analysis misses. Requires infrastructure
beyond a browser session.

---

## Delivery options

**Option A — GitHub Action** *(best fit for repo-based workflow)*
Runs automatically on PR. Posts a comment with the bulletproofing report.
Reporter and editor both see it before merge. No separate tool to open.
Part of the PR process, not a separate step anyone has to remember.

**Option B — CLI tool**
`uv run python bulletproof.py --repo .` — runs locally against the current
directory, prints the report. Fast, no cloud dependency, works in any repo.
Fastest to build.

**Option C — Streamlit pointing at a GitHub URL**
Paste a GitHub repo URL, tool clones it, runs everything, shows the report.
Middle ground — cloud UI, reads from the repo rather than file uploads.

---

## Priority order

1. **Layer 4** — highest editorial value, closes the biggest gap
2. **Methodology note generator** — low effort, high newsroom value, reuses Layer 2 output already available
3. **Pre-publication checklist** — the unifying output that makes the suite feel like one tool
4. **Repo-aware runner (CLI or GitHub Action)** — unlocks the full vision
5. **Layer 3 stability** — worth fixing properly once the core suite is complete

---

## Current layer status

| Layer | What | Status |
|-------|------|--------|
| 1 | Copy risk checker (regex + spaCy) | ✅ Done, deployed |
| 2 | Code risk checker (AST + regex) | ✅ Done, deployed |
| 3 | Notes recall (RAG, OpenAI embeddings) | ⚠️ Done, PDF stability issues on Cloud |
| 4 | Editorial judgment (LLM, story vs code) | ❌ Not built |
| 5 | Data readiness checker (pandas + GPT) | ✅ Done, deploy pending |
