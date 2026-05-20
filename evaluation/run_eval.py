"""
Layer 1 evaluation — precision, recall, F1 per flag type.

Run from repo root:
    uv run python evaluation/run_eval.py

A predicted flag matches a gold flag if:
  - same flag_type
  - predicted span overlaps the gold span (not required to be identical)
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from risk_highlight.layer1 import Flag, PRIORITY_RANK, flag_text  # noqa: E402


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
