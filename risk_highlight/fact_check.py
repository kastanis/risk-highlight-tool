"""
Fact-checker for quantitative claims.

Given a claim (text span) and optional source URL, calls GPT-4o with
web search to verify the figure against authoritative sources.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class FactCheckResult:
    claim: str
    verdict: str        # "confirmed" | "discrepancy" | "unverifiable"
    explanation: str
    source: str         # URL cited by LLM or user-provided URL
    authoritative_value: str  # what the LLM found (e.g. "1.56 billion bushels")


SYSTEM_PROMPT = """\
You are a journalism fact-checker specializing in quantitative claims. \
Given a claim from a news article and optionally a source URL, verify \
whether the figure is accurate.

If a source URL is provided, check whether the figure in the claim \
matches what the source actually says.

If no source URL is provided, search the web for the most authoritative \
current figure from government agencies, academic institutions, or \
major news organizations.

Reply ONLY with valid JSON in this exact format (no markdown, no extra text):
{
  "verdict": "confirmed" | "discrepancy" | "unverifiable",
  "explanation": "One or two sentences explaining what you found.",
  "authoritative_value": "The figure you found (e.g. '1.56 billion bushels'), or empty string if unverifiable.",
  "source": "URL of the source you used, or empty string if none found."
}

Verdicts:
- confirmed: the figure in the claim matches authoritative sources
- discrepancy: the figure differs meaningfully from what sources show
- unverifiable: could not find a reliable authoritative source to check against
"""


def fact_check_claim(claim_text: str, context: str, source_url: str = "") -> FactCheckResult:
    """
    Verify a quantitative claim against web sources or a provided URL.

    Args:
        claim_text: the specific phrase to check (e.g. "1.56 million bushels")
        context: the full sentence for context
        source_url: optional URL the reporter cites as their source
    """
    import json
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    if source_url:
        user_prompt = (
            f'Claim to verify: "{claim_text}"\n'
            f'Full sentence: "{context}"\n'
            f'Reporter\'s source: {source_url}\n\n'
            f'Check whether the figure "{claim_text}" is supported by the source at that URL.'
        )
    else:
        user_prompt = (
            f'Claim to verify: "{claim_text}"\n'
            f'Full sentence: "{context}"\n\n'
            f'Search the web for the most authoritative current figure related to this claim '
            f'and check whether "{claim_text}" is accurate.'
        )

    response = client.responses.create(
        model="gpt-4o",
        tools=[{"type": "web_search_preview"}],
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    raw = response.output_text or "{}"
    # Strip markdown code fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return FactCheckResult(
            claim=claim_text,
            verdict="unverifiable",
            explanation="Could not parse fact-check response.",
            source="",
            authoritative_value="",
        )

    return FactCheckResult(
        claim=claim_text,
        verdict=parsed.get("verdict", "unverifiable"),
        explanation=parsed.get("explanation", ""),
        source=parsed.get("source", source_url),
        authoritative_value=parsed.get("authoritative_value", ""),
    )
