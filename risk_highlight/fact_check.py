"""
Fact-checker for quantitative claims.

Given a claim (text span), calls GPT-4o with web search to verify
the figure against authoritative sources.
"""

import os
from dataclasses import dataclass
from datetime import date

from dotenv import load_dotenv

from risk_highlight.ai_check import _call_llm_with_forced_search, _log_usage, _parse_llm_json

load_dotenv()


@dataclass
class FactCheckResult:
    claim: str
    verdict: str        # "confirmed" | "discrepancy" | "unverifiable"
    explanation: str
    source: str
    authoritative_value: str


SYSTEM_PROMPT = """\
Today's date is {{today}}. Your training data is outdated — do not use it to confirm or deny any figure.

You are a journalism fact-checker specializing in quantitative claims. \
Given a claim from a news article, verify whether the figure is accurate.

Search the web for the most authoritative current figure. You MUST use primary sources:
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

def _build_result(claim: str, parsed: dict, fallback_explanation: str = "Could not parse response.") -> FactCheckResult:
    if not parsed:
        return FactCheckResult(
            claim=claim,
            verdict="unverifiable",
            explanation=fallback_explanation,
            source="",
            authoritative_value="",
        )
    return FactCheckResult(
        claim=claim,
        verdict=parsed.get("verdict", "unverifiable"),
        explanation=parsed.get("explanation", ""),
        source=parsed.get("source", ""),
        authoritative_value=parsed.get("authoritative_value", ""),
    )


def fact_check_claim(claim_text: str, context: str) -> tuple[FactCheckResult, dict]:
    """
    Verify a quantitative claim against web sources.
    Returns (FactCheckResult, usage_dict).
    """
    prompt = SYSTEM_PROMPT.replace("{{today}}", date.today().isoformat())
    user_prompt = (
        f'Claim to verify: "{claim_text}"\n'
        f'Full sentence: "{context}"\n\n'
        f'Search the web for the most authoritative current figure related to this claim '
        f'and check whether "{claim_text}" is accurate.'
    )
    raw, usage = _call_llm_with_forced_search(prompt, user_prompt)
    parsed = _parse_llm_json(raw)
    result = _build_result(claim_text, parsed, "Could not parse fact-check response.")
    _log_usage("fact_check", claim_text, usage)
    return result, usage

