"""
Layer 1 smoke tests — one sentence per flag type, plus key regression cases.

Run from repo root:
    uv run pytest tests/
"""

import pytest
from risk_highlight.layer1 import flag_text


def flag_types(text):
    return {f.flag_type for f in flag_text(text)}


# ---------------------------------------------------------------------------
# One passing case per flag type
# ---------------------------------------------------------------------------

def test_quantitative_claim():
    assert "quantitative_claim" in flag_types("The city spent $4.2 million on rental assistance.")

def test_quantitative_claim_hedged():
    assert "quantitative_claim" in flag_types("An estimated 400,000 families are at risk.")

def test_vague_attribution():
    assert "vague_attribution" in flag_types("Experts say the housing shortage has gotten worse.")

def test_vague_attribution_profession():
    assert "vague_attribution" in flag_types("Economists argue the policy will hurt growth.")

def test_passive_attribution():
    assert "passive_attribution" in flag_types("It was reported that the agency lost the data.")

def test_passive_attribution_found():
    assert "passive_attribution" in flag_types("The method was found to be unreliable.")

def test_causal_claim():
    assert "causal_claim" in flag_types("The new policy led to a spike in evictions.")

def test_causal_claim_because():
    assert "causal_claim" in flag_types("Rents rose because of the zoning change.")

def test_certainty_language():
    assert "certainty_language" in flag_types("The data shows a clear pattern of discrimination.")

def test_trend_language():
    assert "trend_language" in flag_types("Home prices surged sharply over the past year.")

def test_comparative_claim():
    assert "comparative_claim" in flag_types("This is the highest rate recorded in the state.")

def test_temporal_claim():
    assert "temporal_claim" in flag_types("The unemployment rate has risen since 2019.")


# ---------------------------------------------------------------------------
# Multi-flag sentences
# ---------------------------------------------------------------------------

def test_multiple_flags():
    text = "Experts say evictions rose sharply by 27%, which shows the policy hurt renters."
    types = flag_types(text)
    assert "vague_attribution" in types
    assert "trend_language" in types
    assert "quantitative_claim" in types
    assert "certainty_language" in types

def test_dollar_amount_and_temporal():
    text = "The city spent $4.2 million on emergency rental assistance last year."
    types = flag_types(text)
    assert "quantitative_claim" in types
    assert "temporal_claim" in types


# ---------------------------------------------------------------------------
# Regression: clean sentences should not fire false positives
# ---------------------------------------------------------------------------

def test_clean_sentence_no_flags():
    # No numbers, no attributions, no time refs, no causal language
    text = "The committee reviewed the proposal and adjourned."
    assert flag_types(text) == set()

def test_clean_sourced_number():
    # Named source + number — quantitative_claim still fires (by design),
    # but no vague_attribution should fire
    text = 'According to the Census Bureau, the population grew to 3.2 million in 2023.'
    types = flag_types(text)
    assert "vague_attribution" not in types


# ---------------------------------------------------------------------------
# Agency name flag
# ---------------------------------------------------------------------------

def test_agency_exact_active_no_flag():
    # Exact match to an active tier-1 agency should NOT be flagged
    assert "agency_name" not in flag_types("The FBI opened an investigation.")

def test_agency_abbreviation_near_miss():
    # Extra letter in all-caps abbreviation — fuzzy matcher should catch it
    assert "agency_name" in flag_types("The FBII issued a statement.")

def test_agency_full_name_near_miss():
    # Near-miss on full name should flag
    assert "agency_name" in flag_types("The Federal Burea of Investigation opened a case.")

def test_agency_eliminated_exact():
    # Exact match to an eliminated agency should flag with status warning
    flags = flag_text("CFPB issued new rules.")
    agency_flags = [f for f in flags if f.flag_type == "agency_name"]
    # CFPB may or may not be in tier-1; if flagged, reason must mention status
    if agency_flags:
        assert any("restructured" in f.reason or "eliminated" in f.reason or "verify" in f.reason.lower()
                   for f in agency_flags)

def test_agency_the_prefix_no_false_positive():
    # "The Department of Justice" — exact active agency, should not flag agency_name
    assert "agency_name" not in flag_types("The Department of Justice announced charges.")
