"""
Layer 1 evaluation — precision, recall, F1 per flag type.

Run from repo root:
    uv run python evaluation/run_eval.py

A predicted flag matches a gold flag if:
  - same flag_type
  - predicted span overlaps the gold span (not required to be identical)
"""

import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import spacy

# ---------------------------------------------------------------------------
# Inline copy of flag_text() — avoids import path complexity until
# the package is extracted from the notebook.
# Keep in sync with analysis/layer1_copy_risk.ipynb.
# ---------------------------------------------------------------------------

nlp = spacy.load("en_core_web_sm")


@dataclass
class Flag:
    start: int
    end: int
    text: str
    flag_type: str
    priority: str
    reason: str


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

    ("vague_attribution", "High", "Unattributed source",
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

    ("trend_language", "Medium", "Directional language",
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

    ("comparative_claim", "Medium", "Comparative claim",
     re.compile(r"""(?x)
        \b(?:highest|lowest|most|least|best|worst|largest|smallest|
           greatest|fewest|fastest|slowest|first|last)\b
        | \bmore\s+than\b | \bless\s+than\b | \bfewer\s+than\b
        | \bat\s+(?:an?\s+)?all[-\s]time\b
        | \b(?:higher|lower|greater|smaller)\s+than\b
        | \bhighly\s+(?:unlikely|likely|specific|improbable)\b
     """, re.IGNORECASE)),

    ("temporal_claim", "Medium", "Time reference",
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
    "led to", "leads to", "caused", "causes", "resulted in",
    "because of", "due to", "owing to", "triggered", "drove",
    "produced", "contributed to", "as a result of",
]

CERTAINTY_VERBS = {
    "shows", "show", "proves", "prove", "confirms", "confirm",
    "demonstrates", "demonstrate", "reveals", "reveal",
    "establishes", "establish", "means", "mean",
}

NER_RULES = {
    "PERSON":   ("named_entity",       "Medium", "PERSON"),
    "ORG":      ("named_entity",       "Medium", "ORG"),
    "GPE":      ("named_entity",       "Medium", "GPE"),
    "NORP":     ("named_entity",       "Medium", "NORP"),
    "MONEY":    ("quantitative_claim", "High",   "Monetary amount"),
    "CARDINAL": ("quantitative_claim", "High",   "Specific count"),
    "PERCENT":  ("quantitative_claim", "High",   "Percentage"),
    "DATE":     ("temporal_claim",     "Medium", "Date"),
    "TIME":     ("temporal_claim",     "Medium", "Time"),
}


def flag_text(text: str) -> list[Flag]:
    flags = []
    for flag_type, priority, reason, pattern in REGEX_PATTERNS:
        for m in pattern.finditer(text):
            flags.append(Flag(m.start(), m.end(), m.group(), flag_type, priority, reason))

    doc = nlp(text)
    text_lower = doc.text.lower()

    for phrase in CAUSAL_CONNECTIVES:
        for m in re.finditer(re.escape(phrase), text_lower):
            flags.append(Flag(m.start(), m.end(), doc.text[m.start():m.end()],
                              "causal_claim", "High", "Asserts causation"))

    for token in doc:
        if token.lemma_.lower() in CERTAINTY_VERBS and token.pos_ == "VERB":
            flags.append(Flag(token.idx, token.idx + len(token.text), token.text,
                              "certainty_language", "Medium", "Certainty verb"))

    for ent in doc.ents:
        if ent.label_ in NER_RULES:
            ft, p, r = NER_RULES[ent.label_]
            flags.append(Flag(ent.start_char, ent.end_char, ent.text, ft, p, r))

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
# Matching logic
# ---------------------------------------------------------------------------

def spans_overlap(a_start, a_end, b_start, b_end) -> bool:
    """True if two spans share at least one character."""
    return a_start < b_end and b_start < a_end


def match_flags(predicted: list[Flag], gold: list[dict]) -> tuple[int, int, int]:
    """
    Returns (true_positives, false_positives, false_negatives).
    A predicted flag is a TP if there exists an unmatched gold flag of the same
    flag_type whose span overlaps the predicted span.
    """
    unmatched_gold = list(gold)
    tp = 0
    fp = 0

    for pred in predicted:
        matched = False
        for i, g in enumerate(unmatched_gold):
            if (g["flag_type"] == pred.flag_type and
                    spans_overlap(pred.start, pred.end, g["start"], g["end"])):
                tp += 1
                unmatched_gold.pop(i)
                matched = True
                break
        if not matched:
            fp += 1

    fn = len(unmatched_gold)
    return tp, fp, fn


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def run_eval(gold_path: Path, verbose: bool = False):
    records = [json.loads(line) for line in gold_path.read_text().splitlines() if line.strip()]

    # Per-type accumulators
    totals: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    # For verbose output
    fp_examples: list[tuple[str, Flag]] = []
    fn_examples: list[tuple[str, dict]] = []

    for record in records:
        predicted = flag_text(record["text"])
        gold_flags = record["flags"]

        # Evaluate per flag type separately
        all_types = set(f.flag_type for f in predicted) | set(g["flag_type"] for g in gold_flags)

        for ft in all_types:
            pred_ft = [f for f in predicted if f.flag_type == ft]
            gold_ft = [g for g in gold_flags if g["flag_type"] == ft]
            tp, fp, fn = match_flags(pred_ft, gold_ft)
            totals[ft]["tp"] += tp
            totals[ft]["fp"] += fp
            totals[ft]["fn"] += fn

            if verbose:
                for f in pred_ft:
                    # Check if it was a FP
                    matched = any(
                        spans_overlap(f.start, f.end, g["start"], g["end"])
                        for g in gold_ft
                    )
                    if not matched:
                        fp_examples.append((record["id"], f))
                for g in gold_ft:
                    matched = any(
                        spans_overlap(p.start, p.end, g["start"], g["end"])
                        for p in pred_ft
                    )
                    if not matched:
                        fn_examples.append((record["id"], g))

    # Print results
    flag_types = sorted(totals.keys())
    header = f"{'Flag type':<25} {'Precision':>9} {'Recall':>9} {'F1':>9} {'TP':>5} {'FP':>5} {'FN':>5}"
    bar = "─" * len(header)
    print(f"\n{'LAYER 1 EVALUATION':^{len(header)}}")
    print(f"Gold set: {gold_path}  ({len(records)} records)\n")
    print(header)
    print(bar)

    overall = {"tp": 0, "fp": 0, "fn": 0}
    for ft in flag_types:
        t = totals[ft]
        tp, fp, fn = t["tp"], t["fp"], t["fn"]
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall    = tp / (tp + fn) if (tp + fn) else 0.0
        f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        print(f"{ft:<25} {precision:>9.2f} {recall:>9.2f} {f1:>9.2f} {tp:>5} {fp:>5} {fn:>5}")
        for k in ("tp", "fp", "fn"):
            overall[k] += t[k]

    print(bar)
    tp, fp, fn = overall["tp"], overall["fp"], overall["fn"]
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    print(f"{'OVERALL':<25} {precision:>9.2f} {recall:>9.2f} {f1:>9.2f} {tp:>5} {fp:>5} {fn:>5}\n")

    if verbose and fp_examples:
        print(f"FALSE POSITIVES (sample, up to 10):")
        for id_, f in fp_examples[:10]:
            print(f"  [{id_}] [{f.flag_type}] {repr(f.text)}")

    if verbose and fn_examples:
        print(f"\nMISSES — gold flags not caught (sample, up to 10):")
        for id_, g in fn_examples[:10]:
            print(f"  [{id_}] [{g['flag_type']}] {repr(g['matched_text'])}")


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    gold_path = Path(__file__).parent / "gold" / "layer1_gold.jsonl"
    if not gold_path.exists():
        print(f"Gold set not found: {gold_path}", file=sys.stderr)
        sys.exit(1)
    run_eval(gold_path, verbose=verbose)
