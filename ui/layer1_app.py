"""
Layer 1 — Copy Risk Checker (Streamlit app)

Thin wrapper around flag_text(). All flagging logic lives here as an inline
copy kept in sync with analysis/layer1_copy_risk.ipynb and evaluation/run_eval.py.
Package extraction (risk_highlight/layer1/) happens after this demo validates the UX.

Run:
    uv run streamlit run ui/layer1_app.py
"""

import re
from dataclasses import dataclass

import spacy
import streamlit as st

# ---------------------------------------------------------------------------
# Flag logic — inline copy, keep in sync with analysis/layer1_copy_risk.ipynb
# ---------------------------------------------------------------------------

@dataclass
class Flag:
    start: int
    end: int
    text: str
    flag_type: str
    priority: str
    reason: str


FLAG_COLORS = {
    "quantitative_claim":  "#74c0fc",  # blue
    "vague_attribution":   "#ff6b6b",  # red
    "passive_attribution": "#f783ac",  # rose
    "causal_claim":        "#ff922b",  # orange
    "certainty_language":  "#ffd43b",  # yellow
    "trend_language":      "#63e6be",  # teal
    "comparative_claim":   "#a9e34b",  # green
    "temporal_claim":      "#ffa8a8",  # pink
    "named_entity":        "#dee2e6",  # grey
}

PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2}

REGEX_PATTERNS = [
    ("quantitative_claim", "High", "Hedged figure — does the reporter have the exact number?",
     re.compile(r"""(?x)
        \b(?:nearly|roughly|approximately|about|around|almost|
           an?\s+estimated|more\s+or\s+less|upwards?\s+of|
           as\s+(?:many|few|much)\s+as)
        \s+
        (?:
            \d+(?:\.\d+)?%
          | \$\d+(?:[,.]\d+)*(?:\s*(?:million|billion|trillion|thousand))?
          | \d+(?:,\d{3})+
          | \d+(?:\.\d+)?\s*(?:million|billion|trillion|thousand)
          | \d+(?:\.\d+)?\s+cents?
          | \d+\s+(?:people|jobs?|homes?|cases?|deaths?|workers?|residents?|students?)
          | half | a\s+(?:third|quarter|fifth)
        )
     """, re.IGNORECASE)),

    ("quantitative_claim", "High", "Specific number — source needed",
     re.compile(r"""(?x)
        \b\d+(?:\.\d+)?%
        | \$\d+(?:[,.]\d+)*(?:\s*(?:million|billion|trillion|thousand))?
        | \b\d+(?:,\d{3})+\b
        | \b\d+(?:\.\d+)?\s*(?:million|billion|trillion|thousand)\b
        | \b\d+(?:\.\d+)?\s+cents?\b
        | \branked?\s+\d+(?:st|nd|rd|th)?\b
        | \b\d+\s+(?:newly\s+)?(?:wallets?|accounts?|users?|addresses?)\b
        | \b(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:million|billion|thousand)\b
     """, re.IGNORECASE)),

    ("vague_attribution", "High", "Unattributed source — who specifically?",
     re.compile(r"""(?x)
        \b(?:experts?|officials?|researchers?|scientists?|analysts?|sources?|
           investigators?|authorities|critics?|observers?|insiders?|advocates?)
        \s+(?:say|says|said|claim|claims|claimed|warn|warns|warned|
             argue|argues|argued|suggest|suggests|suggested|report|reports|reported|
             found|find|finds)
        | (?:studies|research|data|reports?|evidence|findings?)\s+(?:show|shows|suggest|indicate|find|found)
        | \baccording\s+to\s+(?:sources?|officials?|experts?|reports?)\b
        | \bmany\s+(?:believe|say|argue|think|feel)\b
        | \bsome\s+(?:believe|say|argue|think|suggest)\b
     """, re.IGNORECASE)),

    ("passive_attribution", "High", "Actor removed — who found/reported/estimated this?",
     re.compile(r"""(?x)
        \bit\s+(?:has\s+been|have\s+been|was|were|is|are)\s+
        (?:found|reported|estimated|suggested|noted|observed|
           believed|claimed|alleged|determined|confirmed|shown|
           established|documented|revealed|understood|acknowledged)
        (?:\s+that)?
        | \bit\s+(?:appears?|seems?|looks?)\s+(?:that\s+)?(?:the\s+)?(?:data\s+)?(?:suggests?|shows?|indicates?)
        | \b(?:is|are|was|were)\s+(?:widely\s+)?(?:believed|reported|understood|considered|known)\s+to\b
        | \bhas\s+been\s+(?:widely\s+)?(?:reported|noted|documented|established|confirmed)\b
     """, re.IGNORECASE)),

    ("trend_language", "Medium", "Directional language — what is the actual magnitude and baseline?",
     re.compile(r"""(?x)
        \b(?:surged?|soared?|skyrocketed?|spiked?|jumped?|leaped?|shot\s+up|
           plummeted?|plunged?|collapsed?|cratered?|nosedived?|tanked?|
           slumped?|tumbled?|dropped?\s+sharply|fell?\s+sharply|
           rose?\s+sharply|rose?\s+dramatically|climbed?\s+sharply|
           declined?\s+sharply|declined?\s+dramatically|
           rapidly\s+(?:increased?|decreased?|grew?|fell?)|
           significantly\s+(?:increased?|decreased?|grew?|fell?|higher|lower|worse|better)|
           dramatically\s+(?:increased?|decreased?|rose?|fell?|dropped?|worse(?:ned?)?|deteriorated?)|
           dramatic\s+(?:drop|decline|fall|rise|increase)|
           escalated\s+sharply)\b
     """, re.IGNORECASE)),

    ("comparative_claim", "Medium", "Comparative claim — compared to what, over what period?",
     re.compile(r"""(?x)
        \b(?:highest|lowest|most|least|best|worst|largest|smallest|
           greatest|fewest|fastest|slowest|first|last)\b
        | \bmore\s+than\b | \bless\s+than\b | \bfewer\s+than\b
        | \bat\s+(?:an?\s+)?all[-\s]time\b
        | \b(?:higher|lower|greater|smaller)\s+than\b
        | \bhighly\s+(?:unlikely|likely|specific|improbable)\b
     """, re.IGNORECASE)),

    ("temporal_claim", "Medium", "Time reference — verify the period is accurate and current",
     re.compile(r"""(?x)
        \b(?:last|this|next)\s+(?:year|month|week|decade|quarter|fiscal\s+year)\b
        | \bsince\s+(?:19|20)\d{2}\b
        | \bin\s+(?:19|20)\d{2}\b
        | \bin\s+recent\s+(?:years?|months?|weeks?|decades?)\b
        | \bover\s+the\s+(?:past|last)\s+\d+\s+(?:years?|months?|decades?)\b
        | \bhistorically\b | \bfor\s+(?:decades?|years?|generations?)\b
     """, re.IGNORECASE)),
]

CAUSAL_CONNECTIVES = [
    "led to", "leads to", "lead to",
    "caused", "causes", "cause",
    "resulted in", "results in",
    "because of", "due to", "owing to",
    "triggered", "triggers",
    "drove", "drives",
    "produced", "produces",
    "contributed to", "contributes to",
    "as a result of", "as a consequence of",
]

CERTAINTY_VERBS = {
    "shows", "show", "proves", "prove", "confirms", "confirm",
    "demonstrates", "demonstrate", "reveals", "reveal",
    "establishes", "establish", "means", "mean",
}

NER_RULES = {
    "PERSON":   ("named_entity",       "Medium", "PERSON — verify name and any claims attributed to them"),
    "ORG":      ("named_entity",       "Medium", "ORG — verify organization name and role"),
    "GPE":      ("named_entity",       "Medium", "GPE — verify place name and context"),
    "NORP":     ("named_entity",       "Medium", "NORP — verify group name and characterization"),
    "MONEY":    ("quantitative_claim", "High",   "Monetary amount — verify figure and source"),
    "CARDINAL": ("quantitative_claim", "High",   "Specific count — verify figure and source"),
    "PERCENT":  ("quantitative_claim", "High",   "Percentage — verify figure and source"),
    "DATE":     ("temporal_claim",     "Medium", "Date — verify accuracy and relevance"),
    "TIME":     ("temporal_claim",     "Medium", "Time — verify accuracy (exact times are high-risk in breaking news)"),
}


@st.cache_resource
def load_nlp():
    return spacy.load("en_core_web_sm")


def _flag_spacy(doc) -> list[Flag]:
    flags = []
    text_lower = doc.text.lower()

    for phrase in CAUSAL_CONNECTIVES:
        for m in re.finditer(re.escape(phrase), text_lower):
            flags.append(Flag(
                start=m.start(), end=m.end(),
                text=doc.text[m.start():m.end()],
                flag_type="causal_claim", priority="High",
                reason="Asserts causation — verify mechanism and evidence"
            ))

    for token in doc:
        if token.lemma_.lower() in CERTAINTY_VERBS and token.pos_ == "VERB":
            flags.append(Flag(
                start=token.idx, end=token.idx + len(token.text),
                text=token.text,
                flag_type="certainty_language", priority="Medium",
                reason="Certainty verb without hedge — consider 'suggests' or 'indicates'"
            ))

    for ent in doc.ents:
        if ent.label_ in NER_RULES:
            ft, p, r = NER_RULES[ent.label_]
            flags.append(Flag(
                start=ent.start_char, end=ent.end_char,
                text=ent.text, flag_type=ft, priority=p, reason=r
            ))

    return flags


def flag_text(text: str) -> list[Flag]:
    flags = []
    for flag_type, priority, reason, pattern in REGEX_PATTERNS:
        for m in pattern.finditer(text):
            flags.append(Flag(m.start(), m.end(), m.group(), flag_type, priority, reason))

    nlp = load_nlp()
    doc = nlp(text)
    flags.extend(_flag_spacy(doc))

    flags.sort(key=lambda f: (f.start, PRIORITY_RANK[f.priority]))

    seen: dict[str, int] = {}
    deduped = []
    for flag in flags:
        last_idx = seen.get(flag.flag_type)
        if last_idx is not None and flag.start < deduped[last_idx].end:
            pass
        else:
            seen[flag.flag_type] = len(deduped)
            deduped.append(flag)

    deduped.sort(key=lambda f: f.start)
    return deduped


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
        return f"<p style='font-family:sans-serif;font-size:15px;line-height:1.8'>{text}</p>"

    resolved = _resolve_overlaps(flags)
    parts = []
    cursor = 0

    for primary, co_flags in resolved:
        segment = text[cursor:primary.start]
        parts.append(segment.replace("\n", "<br>"))

        color = FLAG_COLORS.get(primary.flag_type, "#eeeeee")
        multi = len(co_flags) > 1

        if multi:
            lines = " | ".join(
                f"{f.flag_type}: {f.reason}" for f in co_flags
            )
            tooltip = f"MULTIPLE FLAGS — {lines}"
            style = (
                f"background:{color};padding:2px 4px;border-radius:3px;"
                f"cursor:help;text-decoration:underline dotted #333;text-underline-offset:3px"
            )
            indicator = '<sup style="font-size:9px;color:#333">+</sup>'
        else:
            tooltip = f"{primary.flag_type}: {primary.reason}"
            style = f"background:{color};padding:2px 4px;border-radius:3px;cursor:help"
            indicator = ""

        parts.append(
            f'<mark style="{style}" title="{tooltip}">{primary.text}{indicator}</mark>'
        )
        cursor = primary.end

    tail = text[cursor:].replace("\n", "<br>")
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

# Run flagging. Sidebar checkbox state is available via session_state with
# default=True on first render, so filtering is safe before the sidebar block runs.
flags = flag_text(text) if text.strip() else []


def _active_flags(all_flags: list[Flag]) -> list[Flag]:
    """Filter flags to only those with active sidebar checkboxes."""
    active_types = [k for k in FLAG_COLORS if st.session_state.get(f"cb_{k}", True)]
    return [f for f in all_flags if f.flag_type in active_types]


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

# --- Legend ---
st.divider()
st.subheader("Flag types")

legend_cols = st.columns(len(FLAG_COLORS))
for col, (ftype, color) in zip(legend_cols, FLAG_COLORS.items()):
    with col:
        st.markdown(
            f"<span style='background:{color};padding:3px 8px;border-radius:4px;"
            f"font-size:12px;white-space:nowrap'>{ftype.replace('_', ' ')}</span>",
            unsafe_allow_html=True,
        )

# --- Flag table ---
if flags:
    filtered = _active_flags(flags)
    st.divider()
    st.subheader(f"Flags ({len(filtered)} shown, {len(flags)} total)")

    if filtered:
        header = "<tr style='background:#f0f0f0'>" + "".join(
            f"<th style='padding:6px 10px;text-align:left;font-size:13px'>{h}</th>"
            for h in ["Flag type", "Matched text", "Reason"]
        ) + "</tr>"

        body = ""
        for f in filtered:
            color = FLAG_COLORS.get(f.flag_type, "#eee")
            badge = (
                f"<span style='background:{color};padding:1px 7px;border-radius:3px;"
                f"font-size:12px'>{f.flag_type.replace('_', ' ')}</span>"
            )
            body += "<tr style='border-bottom:1px solid #eee'>"
            body += f"<td style='padding:5px 10px'>{badge}</td>"
            body += f"<td style='padding:5px 10px;font-family:monospace;font-size:12px'>{f.text}</td>"
            body += f"<td style='padding:5px 10px;font-size:12px;color:#555'>{f.reason}</td>"
            body += "</tr>"

        st.markdown(
            f"<table style='font-family:sans-serif;border-collapse:collapse;width:100%'>"
            f"<thead>{header}</thead><tbody>{body}</tbody></table>",
            unsafe_allow_html=True,
        )
    else:
        st.info("No flag types selected — use the sidebar to enable categories.")

# --- Sidebar ---
with st.sidebar:
    st.header("Show / hide flag types")

    for ftype, color in FLAG_COLORS.items():
        st.checkbox(
            ftype.replace("_", " "),
            value=True,
            key=f"cb_{ftype}",
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
