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
current figure. You MUST use primary sources. Search specifically for:
- Government agency websites (.gov) — USDA, CDC, BLS, Census Bureau, Fed, FEMA, etc.
- Academic or peer-reviewed publications
- Official international bodies — UN, WHO, World Bank, IMF
- Official financial or legal filings

Do NOT cite news organizations (AP, Reuters, NYT, etc.) as your source. \
If a government or academic source exists for this type of claim, you must find and cite it directly. \
News articles are not acceptable sources even if they contain the correct figure. \
If you can only find news sources and no primary source, return verdict "unverifiable".

Reply ONLY with valid JSON in this exact format (no markdown, no extra text):
{
  "verdict": "confirmed" | "discrepancy" | "unverifiable",
  "explanation": "One or two sentences explaining what you found.",
  "authoritative_value": "The figure you found (e.g. '1.56 billion bushels'), or empty string if unverifiable.",
  "source": "URL of the source you used, or empty string if none found."
}

Verdicts:
- confirmed: the figure in the claim exactly matches what the authoritative source says
- discrepancy: the figure in the claim differs from what the source shows — use this even if the difference seems explainable or the source uses a slightly different framing. If the numbers do not match, it is a discrepancy, not confirmed.
- unverifiable: could not find a reliable authoritative source to check against

IMPORTANT: Do not rationalize or reconcile differences between the claim and the source. If the claim says 58% and the source says 68%, that is a discrepancy. Report what the source actually says in authoritative_value and flag it as discrepancy.
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


OPEN_CLAIM_SYSTEM_PROMPT = """\
You are a journalism fact-checker. Given a specific claim from a news article and \
an editorial concern about it, search for authoritative information to verify whether \
the claim is accurate.

You MUST use primary sources. Prioritize:
1. Official records, databases, or government sources
2. Academic or peer-reviewed sources
3. The original source material being referenced (e.g. IMDb for film facts, official bios for roles)
4. News organizations only as a last resort

Do NOT rationalize or reconcile discrepancies. If facts differ, report the discrepancy.

Reply ONLY with valid JSON in this exact format (no markdown, no extra text):
{
  "verdict": "confirmed" | "discrepancy" | "unverifiable",
  "explanation": "One or two sentences explaining what you found.",
  "authoritative_value": "What the authoritative source actually says, or empty string if unverifiable.",
  "source": "URL of the source you used, or empty string."
}
"""


def verify_open_concern(phrase: str, concern: str, context: str) -> FactCheckResult:
    """
    Verify a free-form editorial concern from open review via web search.

    Args:
        phrase: the specific text span flagged by open review
        concern: the editorial concern to investigate
        context: the full article text for context
    """
    import json
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    user_prompt = (
        f'Claim from article: "{phrase}"\n'
        f'Editorial concern: {concern}\n'
        f'Full context: "{context[:500]}"\n\n'
        f'Search for authoritative information to verify whether this claim is accurate.'
    )

    response = client.responses.create(
        model="gpt-4o",
        tools=[{"type": "web_search_preview"}],
        input=[
            {"role": "system", "content": OPEN_CLAIM_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    raw = response.output_text or "{}"
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
            claim=phrase,
            verdict="unverifiable",
            explanation="Could not parse verification response.",
            source="",
            authoritative_value="",
        )

    return FactCheckResult(
        claim=phrase,
        verdict=parsed.get("verdict", "unverifiable"),
        explanation=parsed.get("explanation", ""),
        source=parsed.get("source", ""),
        authoritative_value=parsed.get("authoritative_value", ""),
    )
