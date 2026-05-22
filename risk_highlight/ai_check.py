"""
AI second-pass check for Layer 1 copy risk.

Calls GPT-4o on a text excerpt using the same flag taxonomy as Layer 1,
then logs the comparison to Supabase.
"""

import json
import os
from dataclasses import dataclass
from datetime import date

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
  agency_name          — any government agency name that is misspelled, uses the wrong word \
(e.g. "Customs and Border Patrol" instead of "Customs and Border Protection"), is outdated, \
has been restructured, eliminated, or renamed. Check all agency names carefully against their \
correct official names.

Reply ONLY with valid JSON in this exact format (no markdown, no extra text):
{
  "flag": true,
  "spans": [
    {"flag_type": "vague_attribution", "text": "experts say", "reason": "No named source"},
    {"flag_type": "quantitative_claim", "text": "1.56 million", "reason": "Specific figure needs sourcing"}
  ],
  "explanation": "One concise sentence explaining the main risk."
}

If there are no risk patterns, reply:
{
  "flag": false,
  "spans": [],
  "explanation": "No significant risk patterns identified."
}
"""


@dataclass
class AIResult:
    flagged: bool
    issue_types: list[str]
    spans: list[dict]
    explanation: str
    llm_only: list[str]
    tool_only: list[str]
    agreed: bool


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _call_llm(system_prompt: str, user_content: str) -> str:
    """Call GPT-4o with web search available and return raw output text."""
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.responses.create(
        model="gpt-4o",
        tools=[{"type": "web_search_preview"}],
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    return response.output_text or "{}"


def _call_llm_with_forced_search(system_prompt: str, user_content: str) -> str:
    """Call GPT-4o with web search required on every call and return raw output text."""
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.responses.create(
        model="gpt-4o",
        tools=[{"type": "web_search_preview"}],
        tool_choice="required",
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    return response.output_text or "{}"


def _parse_llm_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON; returns {} on failure."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# AI second pass
# ---------------------------------------------------------------------------

def run_ai_check(text: str, tool_flags: list) -> AIResult:
    """Call GPT-4o and return an AIResult with spans and comparison vs tool flags."""
    parsed = _parse_llm_json(_call_llm(SYSTEM_PROMPT, text))

    flagged = bool(parsed.get("flag", False))
    explanation = str(parsed.get("explanation", "")).strip()

    raw_spans = parsed.get("spans", [])
    spans = [
        {"flag_type": s["flag_type"], "text": s.get("text", ""), "reason": s.get("reason", "")}
        for s in raw_spans
        if isinstance(s, dict) and s.get("flag_type") in VALID_ISSUE_TYPES
    ]
    llm_types = list(dict.fromkeys(s["flag_type"] for s in spans))

    tool_flag_types = [f.flag_type for f in tool_flags]
    tool_spans = [{"flag_type": f.flag_type, "text": f.text, "reason": f.reason} for f in tool_flags]

    tool_set = set(tool_flag_types)
    llm_set = set(llm_types)
    llm_only = sorted(llm_set - tool_set)
    tool_only = sorted(tool_set - llm_set)
    agreed = tool_set == llm_set

    result = AIResult(
        flagged=flagged,
        issue_types=llm_types,
        spans=spans,
        explanation=explanation,
        llm_only=llm_only,
        tool_only=tool_only,
        agreed=agreed,
    )

    _log_to_supabase(text, tool_flag_types, tool_spans, llm_types, spans, agreed, llm_only, tool_only)

    return result


def _log_to_supabase(
    text: str,
    tool_flags: list[str],
    tool_spans: list[dict],
    llm_flags: list[str],
    llm_spans: list[dict],
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
            "tool_spans": tool_spans,
            "llm_flags": llm_flags,
            "llm_spans": llm_spans,
            "agreed": agreed,
            "llm_only": llm_only,
            "tool_only": tool_only,
        }).execute()
    except Exception as e:
        print(f"Warning: Supabase logging failed: {e}")


# ---------------------------------------------------------------------------
# Full AI review
# ---------------------------------------------------------------------------

FULL_REVIEW_PROMPT = """\
Today's date is {{today}}. Your training data is outdated — do not use it to confirm or deny any claim.

You are an experienced journalism editor and fact-checker reviewing a text excerpt \
before publication. Your job is to identify every claim that deserves scrutiny, \
then immediately search the web to verify each one.

For each concern:
1. Identify the specific phrase from the article
2. Search for authoritative information (government sources, official records, primary data)
3. Return a verdict based on what you find

Look for:
- Numbers, figures, percentages, dollar amounts that may be wrong
- Names, titles, or roles (people change jobs — always search to confirm current status)
- Dates, timelines, and historical claims
- Rankings and superlatives ("largest", "first", "top producer")
- Agency or organization names that may be misspelled or outdated
- Causal claims and logical inconsistencies
- Anything a careful editor would flag before publishing

IMPORTANT:
- You MUST perform a web search for EVERY finding before assigning a verdict
- NEVER use training data to confirm or deny a claim — your knowledge is outdated
- Search even for things you think you know — facts, roles, and titles change
- Use primary sources: .gov sites, official records, academic sources
- For any person's current role, title, or status — always search, never assume
- If the article says "million" but sources say "billion", that is a discrepancy
- If you cannot find a current authoritative source, verdict must be "unverifiable"
- When calculating time intervals ("over the past X years", "since YYYY"), use today's date above

Reply ONLY with valid JSON in this exact format (no markdown, no extra text):
{
  "findings": [
    {
      "text": "exact phrase from the article",
      "concern": "what specifically to check",
      "verdict": "discrepancy" | "appears_supported" | "unverifiable",
      "explanation": "one or two sentences on what you found",
      "authoritative_value": "what the source actually says, or empty string",
      "source": "URL used, or empty string"
    }
  ],
  "summary": "One sentence overall assessment."
}

If nothing needs checking:
{
  "findings": [],
  "summary": "No significant editorial concerns identified."
}
"""


def full_review(text: str) -> dict:
    """
    Single-pass editorial review: identifies concerns and verifies each via web search.
    Uses forced web search to prevent model from defaulting to training data.
    Returns dict with 'findings' and 'summary'.
    """
    prompt = FULL_REVIEW_PROMPT.replace("{{today}}", date.today().isoformat())
    parsed = _parse_llm_json(_call_llm_with_forced_search(prompt, text))
    return {
        "findings": parsed.get("findings", []),
        "summary": parsed.get("summary", ""),
    }

