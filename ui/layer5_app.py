"""
Layer 5 — Data Readiness Checker (Streamlit app)

Upload a CSV or Excel file and get a 7-section Data Readiness Report.

Rule-based sections (pandas, no LLM):
  Section 1 — Overview (column profiles)
  Section 4 — Readiness Status (threshold rules)

LLM sections (gpt-4o-mini, receives stats + 20-row sample + value distributions):
  Section 2 — Data Quality Issues
  Section 3 — Outliers & Anomalies
  Section 5 — Recommendations
  Section 6 — Questions for the Data Provider
  Section 7 — Limitations

Run:
    uv run streamlit run ui/layer5_app.py
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NARRATIVE_MODEL = "gpt-4o-mini"

SAMPLE_ROWS   = 20    # rows sent to LLM
TOP_N_VALUES  = 10    # top frequent values per column sent to LLM

THRESHOLDS = {
    "not_ready_missing_pct":   50.0,   # any column >50% missing  → Not Ready
    "not_ready_duplicate_pct": 30.0,   # >30% duplicate rows      → Not Ready
    "caution_missing_pct":     20.0,   # any column >20% missing  → Use With Caution
    "caution_duplicate_pct":   10.0,   # >10% duplicate rows      → Use With Caution
}

# Known sentinel / suppression values common in government and survey data
SENTINEL_VALUES = {
    "(X)",      # ACS not applicable
    "*****",    # ACS suppressed MOE
    "***",      # generic suppressed
    "**",
    "*",
    "-",
    "—",
    "–",
    "N/A",
    "n/a",
    "NA",
    "N.A.",
    "n.a.",
    "null",
    "NULL",
    ".",        # SAS missing
    "S",        # BLS suppressed
    "D",        # Census disclosure avoidance
    "W",        # BLS withheld
    "Z",        # rounds to zero
}

# ---------------------------------------------------------------------------
# Contextual callouts — shown inline when an issue is detected
# Each key matches an issue_type in data/resources/layer5_resources.yaml
# ---------------------------------------------------------------------------

CALLOUTS = {
    "sentinel_values": {
        "title": "What are sentinel/suppression values?",
        "body": (
            "Government agencies use special codes instead of blank cells when data is "
            "suppressed, not applicable, or withheld. Common ones: `(X)` in ACS means "
            "\"not applicable\"; `*****` means the margin of error is too large to report; "
            "`S`, `D`, `W` are BLS/Census disclosure-avoidance codes. "
            "These are not errors in the original data — they are intentional signals.\n\n"
            "**What AI tools get wrong:** If you ask ChatGPT or Claude to calculate an "
            "average or sum from a column containing `(X)` or `*****`, the model will "
            "either silently skip them, treat them as zero, or produce a nonsense result — "
            "without warning you. A 2024 Cambridge study found that LLMs analyzing "
            "census-style survey data reached substantively different conclusions than "
            "human-verified analysis. Always clean sentinel values before any calculation."
        ),
        "resource_type": "sentinel_values",
    },
    "missing_values": {
        "title": "Why missing values matter more than they look",
        "body": (
            "A missing value (blank cell, NaN) can mean several different things: "
            "the data was never collected, it was collected but lost, the question "
            "didn't apply to that row, or the agency chose not to report it. "
            "Treating all four as the same thing produces wrong analysis.\n\n"
            "**What AI tools get wrong:** LLMs will describe a dataset's "
            "\"average age\" or \"total population\" without flagging that 15% of "
            "the rows are missing that value. The model does not distinguish between "
            "\"missing at random\" and \"missing because of a reporting threshold\" — "
            "a distinction that can completely change what the data means."
        ),
        "resource_type": "missing_values",
    },
    "duplicates": {
        "title": "Duplicate rows: expected or a problem?",
        "body": (
            "Duplicates can be intentional (the same entity appears in multiple time "
            "periods) or a data error (a row was accidentally repeated during export). "
            "In some datasets — like DP-series Census tables — label duplicates are "
            "expected because the same label appears under multiple sections. "
            "In others — like a list of unique incidents or people — any duplicate "
            "is a data quality failure.\n\n"
            "**What AI tools get wrong:** LLMs do not check for duplicates before "
            "summarizing data. If you ask \"how many records are there?\" an LLM "
            "will count all rows including duplicates and report a confident number. "
            "Always confirm whether duplicates are intentional before analysis."
        ),
        "resource_type": "duplicates",
    },
    "mixed_types": {
        "title": "Mixed data types: why a column can't be both text and numbers",
        "body": (
            "A column that contains mostly numbers but also some text values — "
            "like `\"N/A\"`, `\"n/a\"`, or `\"(X)\"` — can't be used for math as-is. "
            "Spreadsheet software and analysis tools will either skip the text values "
            "silently, treat the whole column as text (so no calculations work), "
            "or throw an error. The result is that totals, averages, and comparisons "
            "may be wrong or missing without any obvious warning.\n\n"
            "This often happens when data from multiple sources is combined, or when "
            "an agency uses text codes alongside numbers in the same column. "
            "The fix is to decide: should those text values become blank (missing), "
            "be replaced with a number (e.g. 0), or be moved to a separate notes column?\n\n"
            "**What AI tools get wrong:** If you ask an LLM to calculate an average "
            "from a mixed column, it may quietly drop the text values and compute "
            "the average from whatever numbers remain — without telling you how many "
            "values it excluded or what they contained."
        ),
        "resource_type": "numeric_parsing",
    },
    "llm_limits": {
        "title": "What LLMs are not reliable for in data analysis",
        "body": (
            "Research benchmarks show consistent failure patterns when LLMs work "
            "with structured data:\n\n"
            "- **TableBench (AAAI 2024):** GPT-4 significantly underperforms humans "
            "on structured data Q&A tasks, especially numerical reasoning and fact-checking\n"
            "- **Tabular reasoning (2025):** Simply transposing a table degrades LLM "
            "performance substantially — models are sensitive to data layout, not just content\n"
            "- **Census/survey data (Cambridge 2024):** LLM analysis of census-style "
            "data reached different conclusions than human-verified analysis on key covariates\n"
            "- **DS-1000 (ICML 2023):** The best model achieved 43% accuracy on "
            "realistic data science coding tasks\n\n"
            "**Safe to ask LLMs:** Explain what a column name means, draft a question "
            "for the data provider, summarize the structure of a dataset.\n\n"
            "**Not safe without verification:** Calculate totals or averages, identify "
            "trends, compare values across columns, make claims about what the data shows."
        ),
        "resource_type": "llm_limits",
    },
}


def _load_resources() -> dict[str, list[dict]]:
    """Load resource links from YAML registry. Returns dict keyed by issue_type."""
    path = Path(__file__).parent.parent / "data" / "resources" / "layer5_resources.yaml"
    if not path.exists():
        return {}
    import yaml
    data = yaml.safe_load(path.read_text()) or {}
    result: dict[str, list[dict]] = {}
    for entry in data.get("resources", []):
        result[entry["issue_type"]] = entry.get("links", [])
    return result


STATUS_COLORS = {
    "Decent":             "#2f9e44",
    "Use With Caution":   "#e67700",
    "Not Ready":          "#ff6b6b",
}

STATUS_TEXT_COLORS = {
    "Decent":           "#fff",
    "Use With Caution": "#fff",
    "Not Ready":        "#fff",
}

# Background tint colors for contextual callout boxes (hex + 44 = ~27% opacity)
CALLOUT_COLORS = {
    "sentinel_values": "#ff922b44",   # orange — data quality warning
    "missing_values":  "#ffd43b44",   # yellow — caution-level issue
    "duplicates":      "#ffd43b44",   # yellow — caution-level issue
    "mixed_types":     "#ff922b44",   # orange — data quality warning
    "llm_limits":      "#74c0fc44",   # blue  — informational
}


# ---------------------------------------------------------------------------
# OpenAI client (reuses Layer 3 pattern)
# ---------------------------------------------------------------------------

@st.cache_resource
def get_client() -> OpenAI:
    key = None
    try:
        key = st.secrets["OPENAI_API_KEY"]
    except Exception:
        key = os.getenv("OPENAI_API_KEY")
    if not key:
        st.error("OPENAI_API_KEY not set. Add it in Streamlit Cloud → Settings → Secrets.")
        st.stop()
    return OpenAI(api_key=key)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ColumnProfile:
    name: str
    dtype: str
    missing_count: int
    missing_pct: float
    unique_count: int
    min_val: str = ""
    max_val: str = ""
    notes: list[str] = field(default_factory=list)
    sentinel_count: int = 0
    sentinel_found: list[str] = field(default_factory=list)
    mixed_type_count: int = 0   # non-null cells that can't be parsed as numeric in an object column


@dataclass
class DatasetProfile:
    filename: str
    n_rows: int
    n_cols: int
    n_duplicates: int
    duplicate_pct: float
    columns: list[ColumnProfile]
    status: str          # "Decent" | "Use With Caution" | "Not Ready"
    status_reason: str   # one-sentence explanation


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def load_file(uploaded_file) -> pd.DataFrame:
    suffix = uploaded_file.name.rsplit(".", 1)[-1].lower()
    if suffix == "csv":
        return pd.read_csv(uploaded_file)
    elif suffix in ("xlsx", "xls"):
        return pd.read_excel(uploaded_file)
    raise ValueError(f"Unsupported file type: .{suffix}")


# ---------------------------------------------------------------------------
# Profiling (pandas, rule-based)
# ---------------------------------------------------------------------------

def _infer_type(series: pd.Series) -> str:
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "float"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    # Try date parsing on object columns
    if series.dtype == object:
        sample = series.dropna().head(20)
        try:
            parsed = pd.to_datetime(sample, infer_datetime_format=True, errors="coerce")
            if parsed.notna().mean() > 0.8:
                return "date/datetime"
        except Exception:
            pass
        return "text"
    return str(series.dtype)


def _column_notes(series: pd.Series, dtype_label: str) -> list[str]:
    notes = []
    n_non_null = series.notna().sum()
    if n_non_null == 0:
        notes.append("entirely empty")
        return notes
    if series.nunique() == n_non_null and n_non_null > 1:
        notes.append("all unique — possible ID column")
    if series.nunique() == 1:
        notes.append("single value — constant column")
    if dtype_label in ("integer", "float"):
        vals = series.dropna()
        if (vals < 0).any():
            notes.append("contains negative values")
        if dtype_label == "integer" and series.nunique() <= 20:
            notes.append("low cardinality — may be categorical")
    return notes


def _detect_sentinels(series: pd.Series) -> tuple[int, list[str]]:
    """Count sentinel/suppression values in a text column. Returns (count, found_values)."""
    if series.dtype != object:
        return 0, []
    found: dict[str, int] = {}
    for val in series.dropna():
        s = str(val).strip()
        if s in SENTINEL_VALUES:
            found[s] = found.get(s, 0) + 1
        # Also catch ± prefix (MOE format) and % suffix blocking numeric parse
        elif s.startswith("±") or s.startswith("+/-"):
            found["± (MOE prefix)"] = found.get("± (MOE prefix)", 0) + 1
    total = sum(found.values())
    return total, list(found.keys())


def _detect_mixed_types(series: pd.Series) -> int:
    """Count cells in an object column that look numeric but share space with text.

    Returns the count of non-numeric, non-sentinel, non-null values in a column
    where at least some values ARE numeric — indicating the column is mixed.
    """
    if series.dtype != object:
        return 0
    non_null = series.dropna()
    if len(non_null) == 0:
        return 0
    numeric_count = pd.to_numeric(non_null, errors="coerce").notna().sum()
    # Only flag as mixed if there are BOTH numeric and non-numeric values
    if numeric_count == 0 or numeric_count == len(non_null):
        return 0
    return int(len(non_null) - numeric_count)


def profile_dataframe(df: pd.DataFrame, filename: str) -> DatasetProfile:
    n_rows, n_cols = df.shape
    n_duplicates = int(df.duplicated().sum())
    duplicate_pct = (n_duplicates / n_rows * 100) if n_rows > 0 else 0.0

    col_profiles = []
    for col in df.columns:
        series = df[col]
        missing_count = int(series.isna().sum())
        missing_pct = (missing_count / n_rows * 100) if n_rows > 0 else 0.0
        unique_count = int(series.nunique(dropna=True))
        dtype_label = _infer_type(series)

        min_val = max_val = ""
        if dtype_label in ("integer", "float"):
            vals = series.dropna()
            if not vals.empty:
                min_val = str(vals.min())
                max_val = str(vals.max())

        notes = _column_notes(series, dtype_label)
        sentinel_count, sentinel_found = _detect_sentinels(series)
        if sentinel_count > 0:
            notes.append(f"sentinel values: {', '.join(sentinel_found)} ({sentinel_count} cells)")
        mixed_type_count = _detect_mixed_types(series)
        if mixed_type_count > 0:
            notes.append(f"mixed types: {mixed_type_count} non-numeric cell(s) in a mostly-numeric column")
        col_profiles.append(ColumnProfile(
            name=col,
            dtype=dtype_label,
            missing_count=missing_count,
            missing_pct=round(missing_pct, 1),
            unique_count=unique_count,
            min_val=min_val,
            max_val=max_val,
            notes=notes,
            sentinel_count=sentinel_count,
            sentinel_found=sentinel_found,
            mixed_type_count=mixed_type_count,
        ))

    # Readiness status
    if n_rows == 0:
        status = "Not Ready"
        status_reason = "Dataset has 0 rows."
    elif any(c.missing_pct > THRESHOLDS["not_ready_missing_pct"] for c in col_profiles):
        worst = max(col_profiles, key=lambda c: c.missing_pct)
        status = "Not Ready"
        status_reason = (
            f'Column "{worst.name}" is {worst.missing_pct:.0f}% missing '
            f'(threshold: >{THRESHOLDS["not_ready_missing_pct"]:.0f}%).'
        )
    elif duplicate_pct > THRESHOLDS["not_ready_duplicate_pct"]:
        status = "Not Ready"
        status_reason = (
            f"{duplicate_pct:.1f}% of rows are duplicates "
            f'(threshold: >{THRESHOLDS["not_ready_duplicate_pct"]:.0f}%).'
        )
    elif any(c.missing_pct > THRESHOLDS["caution_missing_pct"] for c in col_profiles):
        worst = max(col_profiles, key=lambda c: c.missing_pct)
        status = "Use With Caution"
        status_reason = (
            f'Column "{worst.name}" is {worst.missing_pct:.0f}% missing '
            f'(threshold: >{THRESHOLDS["caution_missing_pct"]:.0f}%).'
        )
    elif duplicate_pct > THRESHOLDS["caution_duplicate_pct"]:
        status = "Use With Caution"
        status_reason = (
            f"{duplicate_pct:.1f}% of rows are duplicates "
            f'(threshold: >{THRESHOLDS["caution_duplicate_pct"]:.0f}%).'
        )
    elif any(c.sentinel_count > 0 for c in col_profiles):
        affected = [c.name for c in col_profiles if c.sentinel_count > 0]
        total_sentinels = sum(c.sentinel_count for c in col_profiles)
        status = "Use With Caution"
        status_reason = (
            f"{total_sentinels} sentinel/suppression value(s) detected in "
            f"{len(affected)} column(s) — these will block numeric parsing unless cleaned."
        )
    else:
        status = "Decent"
        status_reason = "Passes all readiness thresholds."

    return DatasetProfile(
        filename=filename,
        n_rows=n_rows,
        n_cols=n_cols,
        n_duplicates=n_duplicates,
        duplicate_pct=round(duplicate_pct, 1),
        columns=col_profiles,
        status=status,
        status_reason=status_reason,
    )


# ---------------------------------------------------------------------------
# LLM prompt construction
# ---------------------------------------------------------------------------

def _build_column_table(profile: DatasetProfile) -> str:
    lines = ["Column | Type | Missing % | Unique | Notes"]
    lines.append("---|---|---|---|---")
    for c in profile.columns:
        range_str = f"{c.min_val}–{c.max_val}" if c.min_val else ""
        notes_str = "; ".join(c.notes) if c.notes else ""
        if range_str:
            notes_str = f"range: {range_str}" + (f"; {notes_str}" if notes_str else "")
        lines.append(f"{c.name} | {c.dtype} | {c.missing_pct}% | {c.unique_count} | {notes_str}")
    return "\n".join(lines)


def _build_sample_table(df: pd.DataFrame) -> str:
    sample = df.head(SAMPLE_ROWS)
    return sample.to_markdown(index=False)


def _build_value_distributions(df: pd.DataFrame) -> str:
    parts = []
    for col in df.columns:
        counts = df[col].value_counts(dropna=False).head(TOP_N_VALUES)
        vals = ", ".join(f'"{v}" ({n})' for v, n in counts.items())
        parts.append(f"{col}: {vals}")
    return "\n".join(parts)


def _build_sentinel_summary(profile: DatasetProfile) -> str:
    rows = [c for c in profile.columns if c.sentinel_count > 0]
    if not rows:
        return "(none detected)"
    lines = []
    for c in rows:
        lines.append(f"  {c.name}: {c.sentinel_count} cell(s) — values: {', '.join(c.sentinel_found)}")
    return "\n".join(lines)


def build_llm_prompt(profile: DatasetProfile, df: pd.DataFrame) -> str:
    col_table = _build_column_table(profile)
    sample_table = _build_sample_table(df)
    distributions = _build_value_distributions(df)
    sentinel_summary = _build_sentinel_summary(profile)

    return f"""You are a data readiness assistant for journalists.
Analyze the dataset profile and sample below, then write five sections of a Data Readiness Report.

Output ONLY the five sections, each starting with its exact section header on its own line.
Use plain bullet points (• or -). Be specific — reference actual column names and values.
Do not summarize, comment, or add any text before or after the sections.

========================
DATASET: {profile.filename}
Rows: {profile.n_rows:,} | Columns: {profile.n_cols} | Duplicate rows: {profile.n_duplicates:,} ({profile.duplicate_pct:.1f}%)
Readiness status: {profile.status} — {profile.status_reason}

SENTINEL / SUPPRESSION VALUES DETECTED:
{sentinel_summary}

COLUMN PROFILES:
{col_table}

SAMPLE (first {SAMPLE_ROWS} rows):
{sample_table}

TOP VALUE FREQUENCIES PER COLUMN:
{distributions}
========================

Write exactly these sections:

SECTION 2 — DATA QUALITY ISSUES
SECTION 3 — OUTLIERS & ANOMALIES
SECTION 5 — RECOMMENDATIONS
SECTION 6 — QUESTIONS FOR THE DATA PROVIDER
SECTION 7 — LIMITATIONS

Rules:
- Section 2: report ONLY issues NOT already captured by the structured stats above (sentinel counts, missing %, duplicate count are already shown). Look for semantic anomalies: impossible values (e.g. age=999), values that look like the wrong type, inconsistent formats within a column, values that suggest the data was merged incorrectly. Do NOT re-state sentinel counts, missing percentages, or duplicate row counts — those are displayed separately.
- Section 3: identify specific outliers or anomalies in numeric distributions (extreme min/max, future dates, negative values where none are expected). Reference column names and example values.
- Section 5: actionable cleaning or verification steps for a journalist or data editor.
- Section 6: questions to ask the agency or source that provided this data.
- Section 7: what this dataset cannot answer; scope limitations; what to be careful about.
- If a section has nothing to report, write: "(No issues detected, but human review can confirm.)"
- Do NOT draw causal claims, interpret policy, invent data, or make publication decisions.
- Do NOT produce Section 1 or Section 4 — those are handled separately.
"""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def generate_narrative(profile: DatasetProfile, df: pd.DataFrame, client: OpenAI) -> str:
    prompt = build_llm_prompt(profile, df)
    response = client.chat.completions.create(
        model=NARRATIVE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1500,
    )
    return response.choices[0].message.content.strip()


def _split_sections(narrative: str) -> dict[str, str]:
    """Parse LLM output into a dict keyed by section number."""
    import re
    sections: dict[str, str] = {}
    pattern = re.compile(r"SECTION\s+(\d+)\s*[—–-]\s*[^\n]+", re.IGNORECASE)
    matches = list(pattern.finditer(narrative))
    for i, m in enumerate(matches):
        num = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(narrative)
        sections[num] = narrative[start:end].strip()
    return sections


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

@st.cache_resource
def load_resources() -> dict[str, list[dict]]:
    return _load_resources()


def _render_callout(issue_type: str, resources: dict[str, list[dict]]) -> None:
    """Render a collapsible 'Why this matters' callout for a detected issue."""
    callout = CALLOUTS.get(issue_type)
    if not callout:
        return
    links = resources.get(callout["resource_type"], [])
    bg = CALLOUT_COLORS.get(issue_type, "#f1f3f544")
    with st.expander(callout["title"]):
        st.markdown(
            f"<div style='background:{bg};border-radius:6px;padding:10px 14px;margin-bottom:4px'>",
            unsafe_allow_html=True,
        )
        st.markdown(callout["body"])
        if links:
            st.markdown("**Learn more:**")
            for link in links:
                st.markdown(f"- [{link['label']}]({link['url']})")
        st.markdown("</div>", unsafe_allow_html=True)


def _render_status_badge(status: str, reason: str) -> None:
    color = STATUS_COLORS.get(status, "#888")
    text_color = STATUS_TEXT_COLORS.get(status, "#fff")
    st.markdown(
        f"<div style='background:{color};padding:10px 20px;border-radius:8px;"
        f"color:{text_color};font-weight:bold;font-size:1.2em;display:inline-block;"
        f"margin-bottom:6px'>{status}</div>",
        unsafe_allow_html=True,
    )
    st.caption(reason)


def _render_section(title: str, body: str) -> None:
    st.markdown(f"**{title}**")
    if body:
        st.markdown(body)
    else:
        st.markdown("_(No issues detected, but human review can confirm.)_")


# ---------------------------------------------------------------------------
# Streamlit app
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Data Readiness Checker",
    layout="wide",
)

st.title("Data Readiness Checker")
st.caption(
    "Upload a CSV or Excel file to get a structured readiness report. "
    "Tells you what's in the data, what's missing, and what to be careful about — "
    "not whether to publish."
)

# --- Sidebar ---
with st.sidebar:
    st.header("Upload dataset")

    uploaded = st.file_uploader(
        "Drop file here",
        type=["csv", "xlsx", "xls"],
        label_visibility="collapsed",
    )

    st.divider()

    with st.expander("Readiness thresholds"):
        st.markdown(
            f"**Not Ready** if:\n"
            f"- Any column >{THRESHOLDS['not_ready_missing_pct']:.0f}% missing\n"
            f"- >{THRESHOLDS['not_ready_duplicate_pct']:.0f}% duplicate rows\n"
            f"- 0 rows\n\n"
            f"**Use With Caution** if:\n"
            f"- Any column >{THRESHOLDS['caution_missing_pct']:.0f}% missing\n"
            f"- >{THRESHOLDS['caution_duplicate_pct']:.0f}% duplicate rows\n"
            f"- Sentinel/suppression values detected (e.g. `(X)`, `*****`, `±`, `N/A`)\n\n"
            f"**Decent**: passes all thresholds"
        )

    st.divider()
    st.header("About")
    st.markdown(
        "**What this does:**\n"
        "- Describes what is present in the dataset\n"
        "- Flags missing values, duplicates, and anomalies\n"
        "- Suggests cleaning steps and source questions\n\n"
        "**What this does NOT do:**\n"
        "- Draw causal claims or interpret patterns\n"
        "- Invent or infer missing data\n"
        "- Make publication decisions\n"
        "- Sign off on data quality\n\n"
        f"Narrative sections use `{NARRATIVE_MODEL}` (OpenAI). "
        "A sample of the data is sent for anomaly detection. "
        "Nothing is stored after the session ends."
    )

# --- Main panel ---
if uploaded is None:
    st.info("Upload a CSV or Excel file in the sidebar to begin.")
    st.stop()

# Load + profile on every upload
try:
    df = load_file(uploaded)
except Exception as e:
    st.error(f"Could not read file: {e}")
    st.stop()

profile = profile_dataframe(df, uploaded.name)

# Run LLM automatically when a new file is uploaded (cached per filename)
if st.session_state.get("narrative_filename") != uploaded.name:
    client = get_client()
    with st.spinner(f"Analyzing with {NARRATIVE_MODEL}…"):
        try:
            narrative = generate_narrative(profile, df, client)
            sections = _split_sections(narrative)
            st.session_state["narrative_sections"] = sections
            st.session_state["narrative_filename"] = uploaded.name
        except Exception as e:
            st.error(f"Report generation failed: {e}")
            st.stop()

sections = st.session_state.get("narrative_sections", {})
resources = load_resources()

# Detect which issues are present for contextual callouts
has_sentinels    = any(c.sentinel_count > 0 for c in profile.columns)
has_missing      = any(c.missing_pct > 0 for c in profile.columns)
has_dupes        = profile.n_duplicates > 0
has_mixed_types  = any(c.mixed_type_count > 0 for c in profile.columns)


def _render_llm_section(num: str, title: str) -> None:
    """Render an LLM section, normalizing bullet characters to markdown."""
    st.subheader(title)
    body = sections.get(num, "")
    if not body:
        st.markdown("_(No issues detected, but human review can confirm.)_")
        return
    # Normalize • bullets to markdown - bullets so st.markdown renders them as a list
    normalized = "\n".join(
        ("- " + line.lstrip("•").lstrip("·").strip()) if line.strip().startswith(("•", "·")) else line
        for line in body.splitlines()
    )
    st.markdown(normalized)


# Issue type → display color (solid, for inline highlight spans)
_ISSUE_COLORS = {
    "sentinel": "#ff922b",   # orange
    "missing":  "#ffd43b",   # yellow
    "mixed":    "#ff922b",   # orange
    "dupes":    "#ffd43b",   # yellow
}


def _highlight(text: str, color: str) -> str:
    """Wrap text in an inline colored highlight span (Layer 1/2 style)."""
    return (
        f"<span style='background:{color};padding:2px 6px;"
        f"border-radius:3px;font-size:0.95em'>{text}</span>"
    )


def _render_section2_rule_bullets(profile: DatasetProfile) -> None:
    """Render rule-based colored bullets for Section 2 (sentinels, missing, dupes)."""
    bullets = []

    # Sentinel/suppression values
    sentinel_cols = [c for c in profile.columns if c.sentinel_count > 0]
    for c in sentinel_cols:
        vals = ", ".join(f"`{v}`" for v in c.sentinel_found)
        label = _highlight("Sentinel/suppression values", _ISSUE_COLORS["sentinel"])
        bullets.append(
            f"<li style='margin-bottom:6px'>{label} detected in "
            f"<strong>{c.name}</strong>: {c.sentinel_count} cell(s) — {vals}</li>"
        )

    # Missing values
    missing_cols = [c for c in profile.columns if c.missing_pct > 0]
    for c in missing_cols:
        label = _highlight("Missing values", _ISSUE_COLORS["missing"])
        bullets.append(
            f"<li style='margin-bottom:6px'>{label} in "
            f"<strong>{c.name}</strong>: {c.missing_count} cells ({c.missing_pct:.1f}%)</li>"
        )

    # Mixed types
    mixed_cols = [c for c in profile.columns if c.mixed_type_count > 0]
    for c in mixed_cols:
        label = _highlight("Mixed data types", _ISSUE_COLORS["mixed"])
        bullets.append(
            f"<li style='margin-bottom:6px'>{label} in "
            f"<strong>{c.name}</strong>: {c.mixed_type_count} non-numeric cell(s) "
            f"in a mostly-numeric column — column cannot be used for math as-is</li>"
        )

    # Duplicates
    if profile.n_duplicates > 0:
        label = _highlight("Duplicate rows", _ISSUE_COLORS["dupes"])
        bullets.append(
            f"<li style='margin-bottom:6px'>{label}: "
            f"{profile.n_duplicates:,} rows ({profile.duplicate_pct:.1f}% of total)</li>"
        )

    if bullets:
        st.markdown(
            "<ul style='list-style:none;padding-left:0'>" + "".join(bullets) + "</ul>",
            unsafe_allow_html=True,
        )


# --- Section 1: Overview ---
st.subheader("Section 1 — Overview")

col_a, col_b, col_c, _ = st.columns([1, 1, 1, 5])
with col_a:
    st.metric("Rows", f"{profile.n_rows:,}")
with col_b:
    st.metric("Columns", profile.n_cols)
with col_c:
    st.metric("Duplicate rows", f"{profile.n_duplicates:,} ({profile.duplicate_pct:.1f}%)")

overview_data = []
for c in profile.columns:
    range_str = f"{c.min_val} – {c.max_val}" if c.min_val else "—"
    notes_str = "; ".join(c.notes) if c.notes else "—"
    overview_data.append({
        "Column": c.name,
        "Type": c.dtype,
        "Missing %": f"{c.missing_pct:.1f}%",
        "Missing count": c.missing_count,
        "Unique": c.unique_count,
        "Range": range_str,
        "Notes": notes_str,
    })

st.dataframe(overview_data, use_container_width=True, hide_index=True)
st.divider()

# --- Section 2: Data Quality Issues ---
st.subheader("Section 2 — Data Quality Issues")
_render_section2_rule_bullets(profile)
body2 = sections.get("2", "")
if body2:
    normalized2 = "\n".join(
        ("- " + line.lstrip("•").lstrip("·").strip()) if line.strip().startswith(("•", "·")) else line
        for line in body2.splitlines()
    )
    st.markdown(normalized2)
if has_sentinels:
    _render_callout("sentinel_values", resources)
if has_missing:
    _render_callout("missing_values", resources)
if has_mixed_types:
    _render_callout("mixed_types", resources)
if has_dupes:
    _render_callout("duplicates", resources)
st.divider()

# --- Section 3: Outliers & Anomalies (LLM) ---
_render_llm_section("3", "Section 3 — Outliers & Anomalies")
st.divider()

# --- Section 4: Readiness Status (rule-based) ---
st.subheader("Section 4 — Readiness Status")
_render_status_badge(profile.status, profile.status_reason)
st.divider()

# --- Sections 5–7 (LLM) ---
_render_llm_section("5", "Section 5 — Recommendations")
st.divider()

_render_llm_section("6", "Section 6 — Questions for the Data Provider")
st.divider()

_render_llm_section("7", "Section 7 — Limitations")

st.divider()

# --- AI Limits callout — always shown ---
_render_callout("llm_limits", resources)

st.divider()

# --- Data journalism checklist ---
with st.expander("Before you publish: a data checklist"):
    st.markdown(
        "Use this as a guide while you work through the data. "
        "None of these steps require coding — they are about asking the right questions.\n\n"

        "**Understand what you have**\n"
        "- Read any documentation that came with the data. What does each column mean? "
        "What does a single row represent — one person? One incident? One year?\n"
        "- Find out who collected this data and why. Government agencies, nonprofits, "
        "and private companies all have different reasons for tracking things — "
        "and different incentives to leave things out.\n"
        "- Ask: is this the original data, or has it already been processed or summarized? "
        "Processed data can hide problems that only exist in the raw version.\n\n"

        "**Talk to people before you analyze**\n"
        "- Find a subject-matter expert — someone who uses this kind of data in their work — "
        "and ask them what to watch out for. A housing researcher will know things about "
        "eviction data that no tool can tell you.\n"
        "- If the data comes from a government agency, call the press office and ask "
        "for the methodology report. Most agencies publish one. Ask them to walk you through "
        "what the suppressed values mean.\n\n"

        "**Check the numbers make sense**\n"
        "- Look up the total somewhere else — a published report, a press release, "
        "a prior year's version — and see if your row count matches.\n"
        "- Spot-check a few rows. Pick a row at random and try to verify it against "
        "another source. If you can't verify even one row, that's worth noting.\n"
        "- Look at the minimum and maximum values for any numeric column. "
        "Does the lowest number seem possible? Does the highest? Outliers can be "
        "real, or they can be data entry errors.\n\n"

        "**Before you write**\n"
        "- Have someone who did not do the analysis try to reproduce your main finding. "
        "If they get the same number a different way, you can feel more confident.\n"
        "- Be precise about what the data covers. Which years? Which geography? "
        "Which population? A number that is true for one city in one year "
        "is not necessarily true more broadly.\n"
        "- Write down your methodology in plain language — what you did, "
        "in what order, and what you chose not to include. "
        "You will need this if an editor or reader asks how you got your number.\n\n"

        "**If AI was used in your analysis, how was it used and how was the output verified?**\n"
        "- Generative AI can introduce errors or distortions in analysis and framing, "
        "even when the writing looks polished and confident. It can be very wrong.\n"
        "- Any number, trend, or claim that came from or was shaped by an AI tool "
        "should be traced back to the original source data and confirmed independently.\n\n"

        "**Sources:** "
        "[ProPublica data bulletproofing guide](https://github.com/propublica/guides/blob/master/data-bulletproofing.md) · "
        "[IRE/NICAR tipsheets](https://www.ire.org/resources/) · "
        "[EJC Verification Handbook](https://datajournalism.com/read/handbook/verification-2)"
    )
