"""
AI second-pass check for Layer 1 copy risk.

Calls GPT-4o on a text excerpt using the same flag taxonomy as Layer 1,
then logs the comparison to Supabase.
"""

import json
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

VALID_ISSUE_TYPES = {
    "quantitative_claim",
    "vague_attribution",
    "passive_attribution",
    "causal_claim",
    "certainty_language",
    "trend_language",
    "comparative_claim",
    "temporal_claim",
    "agency_name",
}

SYSTEM_PROMPT = """\
You are a journalism copy-risk checker. Given a short text excerpt, identify \
any risk patterns that a fact-checker or editor should scrutinize. Use only \
these category names (use as many as apply):

  quantitative_claim   — specific numbers, percentages, or dollar amounts that need sourcing
  vague_attribution    — "experts say", "researchers found", "sources say", "studies show", \
"many believe" — attribution without a named source
  passive_attribution  — "it was reported", "it is believed", "it has been found" — \
actor removed from the claim
  causal_claim         — "led to", "caused", "resulted in", "due to", "contributed to" — \
asserts causation
  certainty_language   — "shows", "proves", "confirms", "demonstrates", "reveals" — \
certainty verb that over-states evidence
  trend_language       — "surged", "plummeted", "skyrocketed", "rose sharply", \
"dramatically declined" — directional language without magnitude
  comparative_claim    — "highest", "lowest", "fastest", "more than", "all-time" — \
comparison without stated baseline
  temporal_claim       — "last year", "since 2010", "over the past decade", "historically" — \
time reference to verify
  agency_name          — federal agency name that may be misspelled, outdated, restructured, \
or no longer exist in its cited form

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


@dataclass
class AIResult:
    flagged: bool
    issue_types: list[str]
    explanation: str
    llm_only: list[str]
    tool_only: list[str]
    agreed: bool


def run_ai_check(text: str, tool_flag_types: list[str]) -> AIResult:
    """Call GPT-4o and return an AIResult with comparison vs tool flags."""
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

    flagged = bool(parsed.get("flag", False))
    raw_types = parsed.get("issue_types", [])
    if isinstance(raw_types, str):
        raw_types = [t.strip() for t in raw_types.split(",")]
    llm_types = [t for t in raw_types if t in VALID_ISSUE_TYPES]
    explanation = str(parsed.get("explanation", "")).strip()

    tool_set = set(tool_flag_types)
    llm_set = set(llm_types)
    llm_only = sorted(llm_set - tool_set)
    tool_only = sorted(tool_set - llm_set)
    agreed = tool_set == llm_set

    result = AIResult(
        flagged=flagged,
        issue_types=llm_types,
        explanation=explanation,
        llm_only=llm_only,
        tool_only=tool_only,
        agreed=agreed,
    )

    _log_to_supabase(text, tool_flag_types, llm_types, agreed, llm_only, tool_only)

    return result


def _log_to_supabase(
    text: str,
    tool_flags: list[str],
    llm_flags: list[str],
    agreed: bool,
    llm_only: list[str],
    tool_only: list[str],
) -> None:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        return
    try:
        from supabase import create_client
        sb = create_client(url, key)
        sb.table("comparisons").insert({
            "text": text,
            "tool_flags": tool_flags,
            "llm_flags": llm_flags,
            "agreed": agreed,
            "llm_only": llm_only,
            "tool_only": tool_only,
        }).execute()
    except Exception as e:
        print(f"Warning: Supabase logging failed: {e}")
