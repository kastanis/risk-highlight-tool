"""
Layer 1 — Copy Risk Checker (Streamlit app)

Run:
    uv run streamlit run ui/layer1_app.py
"""

import html
import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Populate os.environ from st.secrets so downstream modules (ai_check, fact_check)
# can read keys via os.getenv() without changes. st.secrets is a no-op locally
# when keys aren't set there, so .env still works for local dev.
for _k in ("OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"):
    if _k not in os.environ and _k in st.secrets:
        os.environ[_k] = st.secrets[_k]

sys.path.insert(0, str(Path(__file__).parent.parent))
from risk_highlight.layer1 import (  # noqa: E402
    FLAG_COLORS, HIGH_FLAGS, PRIORITY_RANK, Flag, flag_text
)
from risk_highlight.ai_check import full_review, run_ai_check  # noqa: E402
from risk_highlight.fact_check import fact_check_claim  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(text: str) -> str:
    """Escape characters that break Streamlit markdown rendering."""
    return text.replace("$", r"\$").replace("%", r"\%")


VERDICT_LABEL = {
    "confirmed":    ("Appears supported",  "#2f9e44"),
    "discrepancy":  ("Discrepancy found",  "#e03131"),
    "unverifiable": ("Could not verify",   "#868e96"),
}


def _render_verdict(result) -> None:
    label, color = VERDICT_LABEL.get(result.verdict, ("Unknown", "#868e96"))
    st.markdown(
        f"<div style='margin-top:6px'>"
        f"<span style='background:{color};color:#fff;padding:3px 10px;"
        f"border-radius:4px;font-weight:bold;font-size:13px'>{label}</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown(_safe(result.explanation))
    if result.authoritative_value:
        st.caption(f"Found: {_safe(result.authoritative_value)}")
    if result.source:
        st.markdown(
            f"<span style='font-size:12px;color:#888'>Source: "
            f"<a href='{html.escape(result.source)}' target='_blank'>{html.escape(result.source)}</a></span>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _resolve_overlaps(flags: list[Flag]) -> list[tuple[Flag, list[Flag]]]:
    sorted_flags = sorted(flags, key=lambda f: (f.start, PRIORITY_RANK[f.priority]))
    resolved = []
    for flag in sorted_flags:
        if resolved and flag.start < resolved[-1][0].end:
            resolved[-1][1].append(flag)
        else:
            resolved.append((flag, [flag]))
    return resolved


def render_highlighted(text: str, flags: list[Flag]) -> str:
    """Returns HTML with inline colored highlights and hover tooltips."""
    if not flags:
        return (
            f"<p style='font-family:sans-serif;font-size:15px;line-height:1.8'>"
            f"{html.escape(text)}</p>"
        )

    resolved = _resolve_overlaps(flags)
    parts = []
    cursor = 0

    for primary, co_flags in resolved:
        segment = html.escape(text[cursor:primary.start])
        parts.append(segment.replace("\n", "<br>"))

        color = FLAG_COLORS.get(primary.flag_type, "#eeeeee")
        multi = len(co_flags) > 1

        if multi:
            lines = " | ".join(
                f"{f.flag_type}: {f.reason}" for f in co_flags
            )
            tooltip = html.escape(f"MULTIPLE FLAGS — {lines}")
            style = (
                f"background:{color};padding:2px 4px;border-radius:3px;"
                f"cursor:help;text-decoration:underline dotted #333;text-underline-offset:3px"
            )
            indicator = '<sup style="font-size:9px;color:#333">+</sup>'
        else:
            tooltip = html.escape(f"{primary.flag_type}: {primary.reason}")
            style = f"background:{color};padding:2px 4px;border-radius:3px;cursor:help"
            indicator = ""

        parts.append(
            f'<mark style="{style}" title="{tooltip}">{html.escape(primary.text)}{indicator}</mark>'
        )
        cursor = primary.end

    tail = html.escape(text[cursor:]).replace("\n", "<br>")
    parts.append(tail)

    return (
        "<div style='font-family:sans-serif;font-size:15px;line-height:1.9;"
        "max-width:100%;word-wrap:break-word'>"
        + "".join(parts)
        + "</div>"
    )


# ---------------------------------------------------------------------------
# Streamlit app
# ---------------------------------------------------------------------------

SAMPLE_TEXT = (
    "Evictions rose sharply in Los Angeles, increasing by 27%, which shows the new policy hurt renters. "
    "Experts say the housing shortage has gotten significantly worse over the past decade. "
    "It is estimated that 400,000 families are at risk. "
    "Researchers found that the rezoning led to a 34% increase in property values within two years."
)

st.set_page_config(
    page_title="Copy Risk Checker",
    page_icon="🔍",
    layout="wide",
)

st.title("Copy Risk Checker")
st.caption(
    "Flags risk patterns in journalism copy and AI-generated text. "
    "Does not decide truth or rewrite copy — only highlights what deserves a second look."
)

# --- Input ---
col_input, col_output = st.columns([1, 1], gap="large")

with col_input:
    st.subheader("Input")
    text = st.text_area(
        label="Paste text",
        value=SAMPLE_TEXT,
        height=340,
        label_visibility="collapsed",
        placeholder="Paste journalism copy or AI-generated text here…",
    )
    st.button("Check for risk flags", type="primary", use_container_width=True)

# Auto-clear all AI/fact-check results when text changes.
_text_hash = hash(text)
if st.session_state.get("_text_hash") != _text_hash:
    for key in list(st.session_state.keys()):
        if key.startswith(("ai_result", "or_result", "fc_result_", "or_verify_result_")):
            del st.session_state[key]
    st.session_state["_text_hash"] = _text_hash

# Run flagging. Sidebar checkbox state is available via session_state with
# default=True on first render, so filtering is safe before the sidebar block runs.
flags = flag_text(text) if text.strip() else []

# Priority filter — must be set before _active_flags() is first called,
# so the radio is rendered here (before the output panel) rather than below.
if flags:
    _pf_choice = st.radio(
        "Show priority:",
        options=["All", "High", "Medium"],
        horizontal=True,
        key="priority_radio",
    )
    st.session_state["priority_filter"] = None if _pf_choice == "All" else _pf_choice


def _active_flags(all_flags: list[Flag]) -> list[Flag]:
    """Filter flags by active sidebar checkboxes and priority filter badge."""
    active_types = [k for k in FLAG_COLORS if st.session_state.get(f"cb_{k}", True)]
    pf = st.session_state.get("priority_filter")
    return [
        f for f in all_flags
        if f.flag_type in active_types and (pf is None or f.priority == pf)
    ]


# --- Output ---
with col_output:
    st.subheader("Highlighted output")

    if text.strip():
        if flags:
            display_flags = _active_flags(flags)
            if display_flags:
                st.markdown(render_highlighted(text, display_flags), unsafe_allow_html=True)
            else:
                st.info("No flag types selected — use the sidebar to enable categories.")
        else:
            st.success("No risk flags found.")
    else:
        st.info("Paste text in the input panel to begin.")

# --- Summary badges + flag table ---
if flags:
    # Counts always reflect the full type-filtered set, not the priority-filtered subset,
    # so badges show real totals even when one priority is selected.
    type_filtered = [
        f for f in flags
        if st.session_state.get(f"cb_{f.flag_type}", True)
    ]
    n_high = sum(1 for f in type_filtered if f.priority == "High")
    n_med  = sum(1 for f in type_filtered if f.priority == "Medium")

    st.divider()

    # Static count badges + radio filter. Badges always show full type-filtered
    # totals regardless of which priority is active.
    n_total = len(type_filtered)
    st.markdown(
        f"<div style='display:flex;gap:8px;align-items:center;padding-bottom:4px'>"
        f"<span style='background:#ff6b6b;color:#fff;padding:4px 12px;"
        f"border-radius:6px;font-weight:bold;font-size:1em'>{n_high} High</span>"
        f"<span style='background:#ffd43b;color:#333;padding:4px 12px;"
        f"border-radius:6px;font-weight:bold;font-size:1em'>{n_med} Medium</span>"
        f"<span style='background:#e9ecef;color:#333;padding:4px 12px;"
        f"border-radius:6px;font-size:1em'>{n_total} Total</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("&nbsp;", unsafe_allow_html=True)

    filtered = _active_flags(flags)
    if filtered:
        header = (
            "<tr style='background:#f1f3f5;font-weight:bold;'>"
            + "".join(
                f"<th style='padding:6px 10px;text-align:left;font-size:13px'>{h}</th>"
                for h in ["Flag type", "Priority", "Matched text", "Reason"]
            )
            + "</tr>"
        )
        body = ""
        for f in filtered:
            color = FLAG_COLORS.get(f.flag_type, "#eee")
            priority_style = (
                "background:#ff6b6b;color:#fff;" if f.priority == "High"
                else "background:#ffd43b;color:#333;"
            )
            body += "<tr style='border-bottom:1px solid #eee'>"
            body += (
                f"<td style='padding:5px 10px;background:{color};font-weight:bold;"
                f"white-space:nowrap;font-size:12px'>{f.flag_type.replace('_', ' ')}</td>"
            )
            body += (
                f"<td style='padding:5px 10px;white-space:nowrap;'>"
                f"<span style='{priority_style}padding:1px 6px;border-radius:3px;"
                f"font-size:11px;'>{f.priority}</span></td>"
            )
            body += f"<td style='padding:5px 10px;font-family:monospace;font-size:12px'>{html.escape(f.text)}</td>"
            body += f"<td style='padding:5px 10px;font-size:12px;color:#444'>{html.escape(f.reason)}</td>"
            body += "</tr>"

        st.markdown(
            f"<table style='font-family:sans-serif;border-collapse:collapse;width:100%'>"
            f"<thead>{header}</thead><tbody>{body}</tbody></table>",
            unsafe_allow_html=True,
        )
    else:
        st.info("No flag types selected — use the sidebar to enable categories.")

# --- AI second pass ---
if st.session_state.get("ai_enabled") and text.strip():
    if st.session_state.get("run_ai"):
        with st.spinner("Running GPT-4o…"):
            try:
                ai_result = run_ai_check(text, flags)
                st.session_state["ai_result"] = ai_result
            except Exception as e:
                st.session_state["ai_result"] = None
                st.error(f"AI check failed: {e}")

    ai_result = st.session_state.get("ai_result")
    if ai_result:
        st.divider()
        st.subheader("AI second pass (GPT-4o)")

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("LLM flagged", "Yes" if ai_result.flagged else "No")
        col_b.metric("LLM-only finds", len(ai_result.llm_only))
        col_c.metric("Agreed with tool", "Yes" if ai_result.agreed else "No")

        st.caption(f"**GPT-4o explanation:** {ai_result.explanation}")

        if ai_result.llm_only:
            st.markdown("**Flag types found by AI but not tool:**")
            llm_only_spans = [s for s in ai_result.spans if s["flag_type"] in ai_result.llm_only]
            rows_html = ""
            for s in llm_only_spans:
                rows_html += (
                    "<tr style='border-bottom:1px solid #eee'>"
                    f"<td style='padding:5px 10px;font-weight:bold;font-size:12px'>{s['flag_type'].replace('_', ' ')}</td>"
                    "<td style='padding:5px 10px'>"
                    "<span style='background:#7950f2;color:#fff;padding:1px 6px;"
                    "border-radius:3px;font-size:11px'>AI</span></td>"
                    f"<td style='padding:5px 10px;font-family:monospace;font-size:12px'>{html.escape(s['text'])}</td>"
                    f"<td style='padding:5px 10px;font-size:12px;color:#444'>{html.escape(s['reason'])}</td>"
                    "</tr>"
                )
            st.markdown(
                f"<table style='font-family:sans-serif;border-collapse:collapse;width:100%'>"
                f"<tbody>{rows_html}</tbody></table>",
                unsafe_allow_html=True,
            )

        if ai_result.tool_only:
            st.markdown("**Flag types found by tool but not AI:**")
            st.caption(", ".join(ft.replace("_", " ") for ft in ai_result.tool_only))

# --- Full AI review ---
if st.session_state.get("or_enabled") and text.strip():
    if st.session_state.get("run_or"):
        with st.spinner("Reviewing and verifying claims…"):
            try:
                or_result = full_review(text)
                st.session_state["or_result"] = or_result
            except Exception as e:
                st.session_state["or_result"] = None
                st.error(f"Full AI review failed: {e}")

    or_result = st.session_state.get("or_result")
    if or_result:
        st.divider()
        st.subheader("Full AI review (GPT-4o)")
        st.caption(or_result.get("summary", ""))

        findings = or_result.get("findings", [])
        if findings:
            VERDICT_ICON = {
                "discrepancy":      ("🔴", "#fff0f0", "#e03131"),
                "appears_supported": ("🟢", "#f0fff4", "#2f9e44"),
                "unverifiable":     ("🟡", "#fffff0", "#868e96"),
            }
            for f in findings:
                phrase = f.get("text", "")
                concern = f.get("concern", "")
                verdict = f.get("verdict", "unverifiable")
                explanation = f.get("explanation", "")
                auth_value = f.get("authoritative_value", "")
                source = f.get("source", "")
                icon, bg, border = VERDICT_ICON.get(verdict, ("🟡", "#fffff0", "#868e96"))
                label = verdict.replace("_", " ").title()
                st.markdown(
                    f"<div style='border-left:4px solid {border};padding:8px 14px;margin:8px 0;"
                    f"background:{bg};border-radius:0 4px 4px 0'>"
                    f"{icon} <strong>{label}</strong> — "
                    f"<span style='font-family:monospace;font-size:12px'>\"{html.escape(_safe(phrase))}\"</span><br>"
                    f"<span style='font-size:13px;color:#333;margin-top:4px;display:block'>{html.escape(_safe(explanation))}</span>"
                    + (f"<span style='font-size:12px;color:#555'>Found: {html.escape(_safe(auth_value))}</span><br>" if auth_value else "")
                    + (f"<span style='font-size:11px;color:#888'>Source: <a href='{html.escape(source)}' target='_blank'>{html.escape(source)}</a></span>" if source else "")
                    + "</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.success("No editorial concerns identified.")

# --- Fact checker ---
_VAGUE_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "half"}
quant_flags = [
    f for f in flags
    if f.flag_type == "quantitative_claim" and f.text.lower().strip() not in _VAGUE_WORDS
] if flags else []
if quant_flags and text.strip():
    st.divider()
    st.subheader("Fact checker")
    st.caption(
        "Searches the web to verify specific figures against authoritative sources. "
        "Results cite the source used — always confirm before publishing."
    )

    for i, f in enumerate(quant_flags):
        with st.expander(f'"{f.text}"', expanded=False):
            if st.button("Verify this figure", key=f"fc_btn_{i}", type="primary"):
                with st.spinner("Searching…"):
                    try:
                        fc = fact_check_claim(f.text, text)
                        st.session_state[f"fc_result_{i}"] = fc
                    except Exception as e:
                        st.session_state[f"fc_result_{i}"] = None
                        st.error(f"Fact check failed: {e}")

            fc = st.session_state.get(f"fc_result_{i}")
            if fc:
                _render_verdict(fc)

# --- Sidebar ---
with st.sidebar:
    st.header("Show / hide flag types")

    high_types = [ft for ft in FLAG_COLORS if ft in HIGH_FLAGS]
    med_types  = [ft for ft in FLAG_COLORS if ft not in HIGH_FLAGS]

    st.markdown("**High priority**")
    for ft in sorted(high_types):
        st.checkbox(ft.replace("_", " "), value=True, key=f"cb_{ft}")

    st.markdown("**Medium priority**")
    for ft in sorted(med_types):
        st.checkbox(ft.replace("_", " "), value=True, key=f"cb_{ft}")

    st.divider()
    st.header("AI second pass")
    st.caption("Runs the same flag categories as the rule-based tool — shows what AI catches that rules miss. Flags are logged anonymously to improve the tool.")
    ai_enabled = st.toggle("Enable GPT-4o check", key="ai_enabled")
    if ai_enabled:
        if not os.getenv("OPENAI_API_KEY"):
            st.warning("OPENAI_API_KEY not set in .env or Streamlit secrets")
        else:
            st.button(
                "Run AI check",
                key="run_ai",
                type="primary",
                use_container_width=True,
                disabled=not text.strip(),
            )

    st.divider()
    st.header("Full AI review")
    st.caption("(In progress) Identify and verify all claims in one pass — figures, titles, dates, rankings, and more. "
               "NOTE: LLM is relying on stale training information.")
    or_enabled = st.toggle("Enable full AI review", key="or_enabled")
    if or_enabled:
        if not os.getenv("OPENAI_API_KEY"):
            st.warning("OPENAI_API_KEY not set in .env or Streamlit secrets")
        else:
            st.button(
                "Run full AI review",
                key="run_or",
                type="primary",
                use_container_width=True,
                disabled=not text.strip(),
            )

    st.divider()
    st.header("About")
    st.markdown(
        "Built to surface known risk patterns in journalism copy and AI-generated content — "
        "vague sourcing, unsupported numbers, hidden actors, and causal claims that need evidence.\n\n"
        "Every flag is produced by a named, auditable rule. "
        "No LLM judgment in the flagging logic.\n\n"
        "**Hover** any highlight to see the flag type and reason.\n\n"
        "**Underlined+** = multiple flag types on the same span."
    )
    st.divider()
    st.markdown(
        "**What this does NOT do**\n"
        "- Declare claims true or false\n"
        "- Rewrite or suggest alternative copy\n"
        "- Score the article as good or bad\n"
        "- Make editorial judgments"
    )
