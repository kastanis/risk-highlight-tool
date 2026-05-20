"""
Layer 1 — Copy Risk: shared flagging logic.

Single source of truth for flag_text() and all constants.
Imported by ui/layer1_app.py, evaluation/run_eval.py, and
evaluation/benchmark/run_benchmark.py.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import spacy
from rapidfuzz import fuzz, process


@dataclass
class Flag:
    start: int
    end: int
    text: str
    flag_type: str
    priority: str
    reason: str


PRIORITY_RANK = {"High": 0, "Medium": 1, "Low": 2}

FLAG_COLORS = {
    "quantitative_claim":  "#74c0fc",
    "vague_attribution":   "#ff6b6b",
    "passive_attribution": "#f783ac",
    "causal_claim":        "#ff922b",
    "certainty_language":  "#ffd43b",
    "trend_language":      "#63e6be",
    "comparative_claim":   "#a9e34b",
    "temporal_claim":      "#ffa8a8",
    "agency_name":         "#cc5de8",  # purple
}

HIGH_FLAGS = {"quantitative_claim", "vague_attribution", "passive_attribution", "causal_claim", "agency_name"}

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
        | \b(?:economists?|doctors?|lawyers?|professors?|historians?|sociologists?|psychologists?)\s+(?:say|says|said|argue|argues|argued|warn|warns|warned|suggest|suggests|suggested|claim|claims|claimed)\b
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
        | \b(?:was|were|has\s+been)\s+found\s+to\b
        | \b(?:is|was|were)\s+(?:widely\s+)?considered\s+(?:too|very|quite|an?\s+\w+|the\s+\w+)
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
    "MONEY":    ("quantitative_claim", "High",   "Monetary amount — verify figure and source"),
    "CARDINAL": ("quantitative_claim", "High",   "Specific count — verify figure and source"),
    "PERCENT":  ("quantitative_claim", "High",   "Percentage — verify figure and source"),
    "DATE":     ("temporal_claim",     "Medium", "Date — verify accuracy and relevance"),
    "TIME":     ("temporal_claim",     "Medium", "Time — verify accuracy (exact times are high-risk in breaking news)"),
}


def _load_yaml_patterns() -> list:
    path = Path(__file__).parent.parent / "data" / "patterns" / "layer1_patterns.yaml"
    if not path.exists():
        return []
    import yaml
    out = []
    try:
        data = yaml.safe_load(path.read_text()) or {}
        for p in data.get("patterns", []):
            required = {"flag_type", "priority", "reason", "pattern"}
            if not required.issubset(p.keys()):
                print(f"Warning: skipping pattern missing fields: {p}")
                continue
            try:
                out.append((p["flag_type"], p["priority"], p["reason"],
                            re.compile(p["pattern"], re.IGNORECASE)))
            except re.error as e:
                print(f"Warning: skipping invalid regex in layer1_patterns.yaml: {e}")
    except Exception as e:
        print(f"Warning: failed to load layer1_patterns.yaml: {e}")
    return out


REGEX_PATTERNS = REGEX_PATTERNS + _load_yaml_patterns()


# ---------------------------------------------------------------------------
# Agency name index — loaded once at module level
# ---------------------------------------------------------------------------

def _load_agency_index(max_tier: int = 1) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """
    Returns (full_names, abbreviations) where each entry is
    (match_string, canonical_name, status).
    Only loads agencies with tier <= max_tier (default: tier 1 only).
    """
    path = Path(__file__).parent.parent / "data" / "agencies" / "federal_agencies.yaml"
    if not path.exists():
        return [], []
    try:
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
    except Exception as e:
        print(f"Warning: failed to load federal_agencies.yaml: {e}")
        return [], []

    full_names = []
    abbreviations = []
    for a in data.get("agencies", []):
        if a.get("tier", 2) > max_tier:
            continue
        canonical = a.get("canonical", "")
        status = a.get("status", "active")
        if not canonical:
            continue
        full_names.append((canonical, canonical, status))
        for abbr in a.get("abbreviations", []):
            if not abbr:
                continue
            abbreviations.append((abbr, canonical, status))
            # Long alternates (e.g. "Department of Justice") also go in full_names
            # so spaCy ORG spans that exactly match them aren't flagged as near-misses.
            if len(abbr) >= 6 and not re.match(r'^[A-Z]{2,8}$', abbr):
                full_names.append((abbr, canonical, status))

    return full_names, abbreviations


_AGENCY_FULL, _AGENCY_ABBR = _load_agency_index()
_AGENCY_FULL_STRINGS = [t[0] for t in _AGENCY_FULL]
_AGENCY_ABBR_STRINGS = [t[0] for t in _AGENCY_ABBR]

# Thresholds: abbreviations need higher score (short strings are noisy at low thresholds)
_ABBR_THRESHOLD = 85
_FULL_THRESHOLD = 93


def _flag_agencies(text: str) -> list[Flag]:
    """
    Finds agency mentions in text using two-pass fuzzy matching:
    - Short all-caps tokens → matched against abbreviation list
    - Longer spans (via spaCy ORG entities) → matched against full name list

    Only flags near-misses (close but not exact). Exact matches pass clean.
    """
    if not _AGENCY_FULL and not _AGENCY_ABBR:
        return []

    flags = []
    nlp = load_nlp()
    doc = nlp(text)

    # Pass 1: abbreviation matching on short all-caps tokens
    abbr_pattern = re.compile(r'\b[A-Z]{2,8}\b')
    for m in abbr_pattern.finditer(text):
        token = m.group()
        if not _AGENCY_ABBR_STRINGS:
            continue
        result = process.extractOne(token, _AGENCY_ABBR_STRINGS, scorer=fuzz.ratio)
        if result is None:
            continue
        match_str, score, idx = result
        if score >= _ABBR_THRESHOLD:
            _, canonical, status = _AGENCY_ABBR[idx]
            is_exact = token == match_str
            if is_exact and status == "active":
                continue  # exact match to active agency — no flag
            if is_exact and status in ("restructured", "eliminated"):
                reason = f"Agency status uncertain — {canonical} has been {status}. Verify before publishing."
            else:
                reason = f"Near-match to \"{canonical}\" ({score}% match) — verify spelling"
            flags.append(Flag(
                start=m.start(), end=m.end(), text=token,
                flag_type="agency_name", priority="High", reason=reason
            ))

    # Pass 2: full name matching on spaCy ORG entities
    for ent in doc.ents:
        if ent.label_ != "ORG":
            continue
        span = ent.text.strip()
        # Strip leading "the"/"The" — spaCy often includes it in ORG spans
        span_norm = re.sub(r'^[Tt]he\s+', '', span)
        span_norm = re.sub(r'^U\.S\.\s+', '', span_norm)
        if len(span_norm) < 6:  # too short for reliable full-name matching
            continue
        if not _AGENCY_FULL_STRINGS:
            continue
        result = process.extractOne(span_norm, _AGENCY_FULL_STRINGS, scorer=fuzz.token_sort_ratio)
        if result is None:
            continue
        match_str, score, idx = result
        if score >= _FULL_THRESHOLD:
            match_str_val, canonical, status = _AGENCY_FULL[idx]
            # Exact if span matches the canonical name OR any known alternate (match_str_val)
            is_exact = (span_norm.lower() == canonical.lower()
                        or span_norm.lower() == match_str_val.lower())
            if is_exact and status == "active":
                continue
            if is_exact and status in ("restructured", "eliminated"):
                reason = f"Agency status uncertain — {canonical} has been {status}. Verify before publishing."
            else:
                reason = f"Near-match to \"{canonical}\" ({score}% match) — verify agency name"
            flags.append(Flag(
                start=ent.start_char, end=ent.end_char, text=ent.text,
                flag_type="agency_name", priority="High", reason=reason
            ))

    return flags


_nlp = None


def load_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


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
    flags.extend(_flag_agencies(text))

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
