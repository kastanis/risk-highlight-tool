"""
Layer 2b — Decision Points (Streamlit app)

For the editor. Upload or paste a Python or R analysis script, get back
the methodology choices that need editorial sign-off — in plain English,
no code annotation required.

Run locally:
    uv run streamlit run ui/layer2b_decision_points.py
"""

import re
from dataclasses import dataclass
from pathlib import Path

import streamlit as st


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class DecisionPoint:
    line: int
    lines: list[int]
    code: str
    category: str
    question: str


# ---------------------------------------------------------------------------
# Category display config
# ---------------------------------------------------------------------------

CATEGORY_COLORS = {
    "filter_threshold":   "#ff922b",
    "date_cutoff":        "#ffd43b",
    "unit_of_analysis":   "#74c0fc",
    "join_type":          "#ff6b6b",
    "stat_test_choice":   "#63e6be",
    "exclusion_filter":   "#ff922b",
    "column_selection":   "#dee2e6",
    "rate_denominator":   "#f03e3e",
    "time_period":        "#ffa8a8",
    "deduplication":      "#a9e34b",
    "smoothing_choice":   "#cc5de8",
    "imputation":         "#ff6b9d",
}

CATEGORY_LABELS = {
    "filter_threshold":  "Filter threshold",
    "date_cutoff":       "Date cutoff",
    "unit_of_analysis":  "Unit of analysis",
    "join_type":         "Join type",
    "stat_test_choice":  "Statistical test",
    "exclusion_filter":  "Exclusion filter",
    "column_selection":  "Column selection",
    "rate_denominator":  "Rate denominator",
    "time_period":       "Time period",
    "deduplication":     "Deduplication",
    "smoothing_choice":  "Smoothing",
    "imputation":        "Imputation",
}


# ---------------------------------------------------------------------------
# Question generators
# ---------------------------------------------------------------------------

def _q_filter_threshold(line: str) -> str:
    m = re.search(r"[><!]=?\s*(\d+(?:\.\d+)?)", line)
    val = m.group(1) if m else "this value"
    return (f"Filter threshold {val} used. What is the basis for this cutoff? "
            "Is it from the data definition, a legal standard, or an analytic choice? "
            "Was it chosen before or after seeing the distribution?")

def _q_date_cutoff(line: str) -> str:
    m = re.search(r"((?:19|20)\d{2}(?:-\d{2}(?:-\d{2})?)?)", line)
    date = m.group(1) if m else "this date"
    return (f"Date boundary {date} used. Why this cutoff? "
            "Was it chosen before or after seeing the data? "
            "How many rows does it drop, and is the final period complete?")

def _q_unit_of_analysis(line: str) -> str:
    m = re.search(r"""groupby\s*\(\s*['"]?([\w_]+)['"]?\s*\)|group_by\s*\(\s*`?([\w_]+)`?\s*\)""", line)
    col = m.group(1) or m.group(2) if m else None
    if col:
        return (f"'{col}' is the unit of analysis. Is this the right level of aggregation? "
                "Were alternative groupings considered? Does this match the editorial claim?")
    return ("This groupby key defines the unit of analysis. Was the right level of aggregation chosen? "
            "Were alternative groupings considered?")

def _q_join_type(line: str) -> str:
    m = re.search(r"how=['\"](\w+)['\"]|(?:left|right|full|inner)_join", line)
    jtype = m.group(1) if (m and m.group(1)) else (m.group(0).replace("_join","") if m else "this")
    return (f"{jtype.capitalize()} join used. Who is excluded by this join type? "
            "Was the row count checked before and after? "
            "For outer joins: were unmatched rows investigated?")

def _q_stat_test(line: str) -> str:
    m = re.search(r"\b(ttest_ind|ttest_1samp|mannwhitneyu|chi2_contingency|anova|pearsonr|spearmanr)\b", line)
    test = m.group(1) if m else "this test"
    return (f"{test} chosen. Were the assumptions checked (normality, independence, equal variance)? "
            "Was this test chosen before or after seeing the data? "
            "Were alternative tests considered?")

def _q_exclusion_filter(line: str) -> str:
    return ("This filter removes rows from the analysis. "
            "Are the excluded rows documented? What share of the data do they represent? "
            "Does removing them change the story?")

def _q_column_selection(line: str) -> str:
    return ("These columns were selected for analysis. Were alternative columns or metrics considered? "
            "Is this the right variable for the editorial question?")

def _q_rate_denominator(line: str) -> str:
    return ("Rate or percentage calculated. What population is this normalized against? "
            "Is the denominator consistent across all comparisons in the story? "
            "Is the final period complete (no partial month/year)?")

def _q_time_period(line: str) -> str:
    m = re.search(r"((?:19|20)\d{2}(?:-\d{2}(?:-\d{2})?)?)", line)
    year = m.group(1) if m else "this year"
    return (f"Year/period {year} referenced. Why this time boundary? "
            "Were trend patterns checked before and after? "
            "Is the final period in the data complete?")

def _q_deduplication(line: str) -> str:
    return ("Records were deduplicated. What was the deduplication key? "
            "Which duplicate was kept (first, last, or another)? "
            "How many records were removed, and why do duplicates exist?")

def _q_imputation(line: str) -> str:
    m = re.search(r"fillna\s*\(([^)]{1,40})\)|replace_na\s*\(([^)]{1,40})\)|fill_value\s*=\s*([^\s,)]{1,30})", line)
    val = next((g for g in (m.group(1), m.group(2), m.group(3)) if g), None) if m else None
    val_str = f"with {val.strip()}" if val else ""
    return (f"Missing values imputed {val_str}. Why was this fill value chosen? "
            "How many rows are affected? Does imputing change the direction of any finding?")

def _q_r_stat_test(line: str) -> str:
    m = re.search(r"\b(t\.test|wilcox\.test|chisq\.test|fisher\.test|lm|glm|cor\.test|aov|anova)\s*\(", line)
    test = m.group(1) if m else "this test"
    return (f"{test}() chosen. Were the assumptions checked (normality, independence, equal variance)? "
            "Was this test selected before or after seeing the data? "
            "Were alternative tests considered?")

def _q_smoothing(line: str) -> str:
    m = re.search(r"k\s*=\s*(\d+)|n\s*=\s*(\d+)|window\s*=\s*(\d+)", line)
    k = next((g for g in (m.group(1), m.group(2), m.group(3)) if g), None) if m else None
    window = f"{k}-period" if k else "rolling"
    return (f"{window} smoothing applied. Why this window size? "
            "Was it matched to a published methodology? "
            "How does the choice affect the apparent trend?")


_DP_PATTERNS = [
    ("filter_threshold",
     re.compile(r"(?:df|data|gdf)\[.*?[><!]=?\s*\d+(?:\.\d+)?\b|filter\s*\(.*?[><!]=?\s*\d+(?:\.\d+)?\b"),
     _q_filter_threshold),
    ("date_cutoff",
     re.compile(r"[><!]=?\s*['\"](?:19|20)\d{2}|as\.Date\s*\(['\"]|\.dt\.|pd\.to_datetime"),
     _q_date_cutoff),
    ("unit_of_analysis",
     re.compile(r"\.groupby\s*\(|group_by\s*\("),
     _q_unit_of_analysis),
    ("join_type",
     re.compile(r"how=['\"](?:left|right|outer|inner)['\"]|(?:left|right|full|inner)_join\s*\("),
     _q_join_type),
    ("stat_test_choice",
     re.compile(r"\b(?:ttest_ind|ttest_1samp|mannwhitneyu|chi2_contingency|anova|pearsonr|spearmanr)\s*\("
                r"|\b(?:t\.test|wilcox\.test|chisq\.test|fisher\.test|lm|glm|cor\.test|aov)\s*\("),
     lambda line: _q_stat_test(line) if re.search(r"ttest|mannwhitney|chi2|pearsonr|spearmanr", line)
                  else _q_r_stat_test(line)),
    ("exclusion_filter",
     re.compile(r"(?:df|data)\[(?:df|data)\[.*?\]\s*(?:!=|>|<|>=|<=|~)"),
     _q_exclusion_filter),
    ("column_selection",
     re.compile(r"\[\[[\w'\",\s]+\]\]"),
     _q_column_selection),
    ("rate_denominator",
     re.compile(r"/\s*(?:df|data|pop|total|n)\b|/\s*sum\s*\("),
     _q_rate_denominator),
    ("time_period",
     re.compile(r"year\s*==\s*\d{4}|[><!]=?\s*['\"]?(?:19|20)\d{2}['\"]?|\.dt\.year|<\s*(?:19|20)\d{2}\b"),
     _q_time_period),
    ("deduplication",
     re.compile(r"\.drop_duplicates\(|\.duplicated\(|drop_duplicates\("),
     _q_deduplication),
    ("smoothing_choice",
     re.compile(r"rollmean\s*\(|rollmedian\s*\(|rolling\s*\(\s*window|\.rolling\("),
     _q_smoothing),
    ("imputation",
     re.compile(r"\.fillna\s*\(|replace_na\s*\(|\.interpolate\s*\(|imputeTS|mice\s*\(|Amelia"),
     _q_imputation),
]


def _code_only(line: str) -> str:
    idx = line.find("#")
    return line[:idx] if idx != -1 else line


def find_decision_points(source: str) -> list[DecisionPoint]:
    lines = source.splitlines()
    grouped: dict[tuple[str, str], DecisionPoint] = {}
    seen_line_cat: set[tuple[int, str]] = set()

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        c = _code_only(line)
        for category, pattern, question_fn in _DP_PATTERNS:
            if pattern.search(c):
                if (i, category) in seen_line_cat:
                    continue
                seen_line_cat.add((i, category))
                question = question_fn(c)
                key = (category, question)
                if key in grouped:
                    grouped[key].lines.append(i)
                else:
                    grouped[key] = DecisionPoint(
                        line=i, lines=[i], code=stripped[:120],
                        category=category, question=question,
                    )

    return sorted(grouped.values(), key=lambda p: p.line)


# ---------------------------------------------------------------------------
# Plain-text export
# ---------------------------------------------------------------------------

def points_to_text(points: list[DecisionPoint], filename: str) -> str:
    lines = [
        f"Decision Points — {filename}",
        f"{len(points)} methodology choice(s) requiring editorial sign-off",
        "",
    ]
    for p in points:
        label = CATEGORY_LABELS.get(p.category, p.category.replace("_", " "))
        line_str = ", ".join(str(n) for n in p.lines)
        lines += [
            f"[{label}]  line {line_str}",
            f"  Code:     {p.code}",
            f"  Question: {p.question}",
            "",
        ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Streamlit app
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Decision Points",
    page_icon="📋",
    layout="wide",
)

st.title("Decision Points")
st.caption(
    "For the editor. Upload or paste an analysis script — get back the methodology "
    "choices that need sign-off, in plain English."
)

# --- Sidebar ---
with st.sidebar:
    st.header("Input")
    input_mode = st.radio(
        "Input mode",
        ["Upload a file", "Paste code"],
        label_visibility="collapsed",
        horizontal=True,
    )

    uploaded = None
    pasted_source = None
    pasted_lang = None

    if input_mode == "Upload a file":
        uploaded = st.file_uploader(
            "Drop a .py or .R file here",
            type=["py", "r", "R"],
            label_visibility="collapsed",
        )
    else:
        pasted_lang = st.radio(
            "Language",
            ["Python", "R"],
            horizontal=True,
        )
        pasted_source = st.text_area(
            "Paste code here",
            height=300,
            placeholder="Paste your Python or R script here…",
            label_visibility="collapsed",
        )

    st.divider()
    st.header("About")
    st.markdown(
        "Surfaces the methodology choices in an analysis script that an editor "
        "needs to understand before sign-off.\n\n"
        "Each item is a question — not a flag. The code may be perfectly correct; "
        "these are the choices that need to be documented and justified.\n\n"
        "**Supported:** `.py`, `.R`"
    )

# --- Main panel ---
if input_mode == "Upload a file":
    if uploaded is None:
        st.info("Upload a .py or .R file in the sidebar to begin.")
        st.stop()
    source   = uploaded.read().decode("utf-8", errors="replace")
    filename = uploaded.name
else:
    if not pasted_source or not pasted_source.strip():
        st.info("Paste code in the sidebar to begin.")
        st.stop()
    source   = pasted_source
    filename = "pasted_code.py" if pasted_lang == "Python" else "pasted_code.R"

cache_key = f"{filename}:{hash(source)}"
if st.session_state.get("l2b_cache_key") != cache_key:
    with st.spinner(f"Analyzing {filename}…"):
        points = find_decision_points(source)
    st.session_state["l2b_points"]    = points
    st.session_state["l2b_cache_key"] = cache_key
else:
    points = st.session_state["l2b_points"]

# --- Summary badge + download ---
col_badge, col_dl, _ = st.columns([1, 2, 5])
with col_badge:
    badge_color = "#ff6b6b" if points else "#2d8a4e"
    badge_text  = f"{len(points)} decision pt{'s' if len(points) != 1 else ''}"
    st.markdown(
        f"<div style='background:{badge_color};padding:6px 14px;border-radius:6px;"
        f"text-align:center;color:#fff;font-weight:bold;font-size:1.1em;'>"
        f"{badge_text}</div>",
        unsafe_allow_html=True,
    )
with col_dl:
    if points:
        st.download_button(
            label="Download checklist (.txt)",
            data=points_to_text(points, filename),
            file_name=f"decision_points_{filename}.txt",
            mime="text/plain",
        )

st.divider()

if not points:
    st.success("No decision points detected.")
    st.stop()

# --- Decision points table ---
for p in points:
    color = CATEGORY_COLORS.get(p.category, "#eee")
    label = CATEGORY_LABELS.get(p.category, p.category.replace("_", " "))
    if len(p.lines) == 1:
        line_str = f"line {p.lines[0]}"
    elif len(p.lines) <= 4:
        line_str = "lines " + ", ".join(str(n) for n in p.lines)
    else:
        line_str = "lines " + ", ".join(str(n) for n in p.lines[:3]) + f" +{len(p.lines)-3} more"

    safe_code = p.code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    st.markdown(
        f"<div style='border-left:4px solid {color};padding:10px 16px;"
        f"margin-bottom:12px;background:#fafafa;border-radius:0 4px 4px 0;'>"
        f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:6px;'>"
        f"<span style='background:{color};padding:2px 8px;border-radius:3px;"
        f"font-size:0.82em;font-weight:bold;'>{label}</span>"
        f"<span style='font-size:0.82em;color:#888;'>{line_str}</span>"
        f"</div>"
        f"<div style='font-family:monospace;font-size:0.85em;color:#555;"
        f"background:#f1f3f5;padding:4px 8px;border-radius:3px;margin-bottom:8px;"
        f"overflow-x:auto;white-space:nowrap;'>{safe_code}</div>"
        f"<div style='font-size:0.92em;color:#333;line-height:1.5;'>{p.question}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
