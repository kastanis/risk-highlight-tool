"""
Layer 1 benchmark — LLM runner (GPT-4o).

Reads evaluation/benchmark/results.csv (output of run_benchmark.py),
calls GPT-4o once per row, writes three new columns:
  llm_flag          "flag" | "clean"
  llm_issue_types   comma-separated issue types identified by LLM
  llm_explanation   LLM's brief reasoning string

Updates results.csv in-place (overwrites).

Run from repo root:
    uv run python evaluation/benchmark/run_llm.py

Requires OPENAI_API_KEY in .env or environment.
"""

import csv
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

BENCH_DIR  = Path(__file__).parent
INPUT_CSV  = BENCH_DIR / "results.csv"

NEW_COLS = ["llm_flag", "llm_issue_types", "llm_explanation"]

VALID_ISSUE_TYPES = {
    "quantitative_claim",
    "vague_attribution",
    "passive_attribution",
    "causal_claim",
    "certainty_language",
    "trend_language",
    "comparative_claim",
    "temporal_claim",
    "named_entity",
}

SYSTEM_PROMPT = """\
You are a journalism copy-risk checker. Given a short text excerpt, identify \
any risk patterns that a fact-checker or editor should scrutinize. Use only \
these category names (use as many as apply):

  quantitative_claim   — specific numbers, percentages, or dollar amounts \
that need sourcing
  vague_attribution    — "experts say", "researchers found", "sources say", \
"studies show", "many believe" — attribution without a named source
  passive_attribution  — "it was reported", "it is believed", "it has been \
found" — actor removed from the claim
  causal_claim         — "led to", "caused", "resulted in", "due to", \
"contributed to" — asserts causation
  certainty_language   — "shows", "proves", "confirms", "demonstrates", \
"reveals" — certainty verb that over-states evidence
  trend_language       — "surged", "plummeted", "skyrocketed", "rose \
sharply", "dramatically declined" — directional language without magnitude
  comparative_claim    — "highest", "lowest", "fastest", "more than", \
"all-time" — comparison without stated baseline
  temporal_claim       — "last year", "since 2010", "over the past decade", \
"historically" — time reference to verify
  named_entity         — person, organization, or place name that introduces \
a factual claim requiring verification

Reply ONLY with valid JSON in this exact format (no markdown, no extra text):
{
  "flag": true,
  "issue_types": ["vague_attribution", "quantitative_claim"],
  "explanation": "One concise sentence explaining the main risk."
}

If there are no risk patterns, reply:
{
  "flag": false,
  "issue_types": [],
  "explanation": "No significant risk patterns identified."
}
"""


def call_gpt4o(client: OpenAI, text: str, max_retries: int = 3) -> dict:
    """Call GPT-4o and return parsed JSON. Retries on rate limits."""
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                temperature=0,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            parsed = json.loads(raw)
            return parsed
        except Exception as exc:
            if "rate" in str(exc).lower() and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"  Rate limit hit — waiting {wait}s…", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  LLM error: {exc}", file=sys.stderr)
                return {"flag": False, "issue_types": [], "explanation": f"ERROR: {exc}"}
    return {"flag": False, "issue_types": [], "explanation": "ERROR: max retries exceeded"}


def parse_llm_response(parsed: dict) -> tuple[str, str, str]:
    """Normalise LLM JSON into (llm_flag, llm_issue_types, llm_explanation)."""
    flag = "flag" if parsed.get("flag") else "clean"

    raw_types = parsed.get("issue_types", [])
    if isinstance(raw_types, str):
        raw_types = [t.strip() for t in raw_types.split(",")]
    types = [t for t in raw_types if t in VALID_ISSUE_TYPES]
    issue_types = ",".join(types)

    explanation = str(parsed.get("explanation", "")).strip()
    return flag, issue_types, explanation


def main():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set. Add it to .env or environment.", file=sys.stderr)
        sys.exit(1)

    if not INPUT_CSV.exists():
        print(f"Input not found: {INPUT_CSV}\nRun run_benchmark.py first.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    rows = []
    with INPUT_CSV.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        original_fields = list(reader.fieldnames or [])
        for row in reader:
            rows.append(row)

    out_fields = original_fields + [c for c in NEW_COLS if c not in original_fields]

    print(f"Calling GPT-4o on {len(rows)} rows…")
    for i, row in enumerate(rows, 1):
        text = row["text_excerpt"]
        print(f"  [{i:03d}/{len(rows)}] id={row['id']}", end="", flush=True)

        parsed = call_gpt4o(client, text)
        flag, issue_types, explanation = parse_llm_response(parsed)

        row["llm_flag"] = flag
        row["llm_issue_types"] = issue_types
        row["llm_explanation"] = explanation

        status = "FLAG" if flag == "flag" else "clean"
        print(f" → {status} [{issue_types or '—'}]")

        # Small delay to stay well under rate limits
        time.sleep(0.3)

    with INPUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(rows)

    flagged = sum(1 for r in rows if r["llm_flag"] == "flag")
    print(f"\nDone. LLM flagged {flagged}/{len(rows)} rows.")
    print(f"Output written to: {INPUT_CSV}")


if __name__ == "__main__":
    main()
