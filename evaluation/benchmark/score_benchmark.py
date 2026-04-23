"""
Layer 1 benchmark — scorer.

Reads evaluation/benchmark/results.csv (after both run_benchmark.py and
run_llm.py have run), computes per-row and aggregate metrics, and writes:
  evaluation/benchmark/scored.csv      — full row-level detail
  evaluation/benchmark/scores_summary.txt — human-readable aggregate report

Run from repo root:
    uv run python evaluation/benchmark/score_benchmark.py
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

BENCH_DIR   = Path(__file__).parent
INPUT_CSV   = BENCH_DIR / "results.csv"
SCORED_CSV  = BENCH_DIR / "scored.csv"
SUMMARY_TXT = BENCH_DIR / "scores_summary.txt"

REQUIRED_COLS = {
    "id", "text_excerpt", "source", "human_label", "issue_type_gold",
    "tool_flag", "tool_issue_types",
    "llm_flag", "llm_issue_types",
}

# Map source labels to broad categories for the breakdown table
SOURCE_CATEGORY = {
    "ap wire draft":           "wire/draft",
    "wire service draft":      "wire/draft",
    "wire service":            "wire/draft",
    "data journalism — edited":"edited",
    "ai-generated summary":    "ai",
    "ai-generated memo":       "ai",
    "ai-generated analysis":   "ai",
    "ai-generated policy memo":"ai",
    "ai-generated policy brief":"ai",
    "pr copy":                 "pr",
}


def source_category(source: str) -> str:
    return SOURCE_CATEGORY.get(source.lower().strip(), "other")


def parse_types(cell: str) -> set[str]:
    if not cell or not cell.strip():
        return set()
    return {t.strip() for t in cell.split(",") if t.strip()}


def binary_metrics(tp: int, fp: int, fn: int, tn: int) -> dict:
    total = tp + fp + fn + tn
    accuracy  = (tp + tn) / total if total else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) else 0.0)
    return dict(accuracy=accuracy, precision=precision, recall=recall, f1=f1,
                tp=tp, fp=fp, fn=fn, tn=tn, total=total)


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) else 0.0)
    return precision, recall, f1


def score_row(row: dict) -> dict:
    human   = row["human_label"].strip().lower()
    tool    = row["tool_flag"].strip().lower()
    llm     = row["llm_flag"].strip().lower()
    gold    = parse_types(row.get("issue_type_gold", ""))
    t_types = parse_types(row.get("tool_issue_types", ""))
    l_types = parse_types(row.get("llm_issue_types", ""))

    def conf(pred, actual):
        if pred == "flag" and actual == "flag":
            return 1, 0, 0, 0   # tp fp fn tn
        if pred == "flag" and actual == "clean":
            return 0, 1, 0, 0
        if pred == "clean" and actual == "flag":
            return 0, 0, 1, 0
        return 0, 0, 0, 1       # both clean

    t_tp, t_fp, t_fn, t_tn = conf(tool, human)
    l_tp, l_fp, l_fn, l_tn = conf(llm, human)

    return {
        "tool_correct":         int(tool == human),
        "llm_correct":          int(llm == human),
        "tool_tp":              t_tp,
        "tool_fp":              t_fp,
        "tool_fn":              t_fn,
        "tool_tn":              t_tn,
        "llm_tp":               l_tp,
        "llm_fp":               l_fp,
        "llm_fn":               l_fn,
        "llm_tn":               l_tn,
        "tool_llm_agree":       int(tool == llm),
        "issue_type_overlap":   ",".join(sorted(t_types & gold)),
        "issue_type_tool_extra":   ",".join(sorted(t_types - gold)),
        "issue_type_tool_missed":  ",".join(sorted(gold - t_types)),
        "issue_type_llm_extra":    ",".join(sorted(l_types - gold)),
        "issue_type_llm_missed":   ",".join(sorted(gold - l_types)),
    }


SCORE_COLS = [
    "tool_correct", "llm_correct",
    "tool_tp", "tool_fp", "tool_fn", "tool_tn",
    "llm_tp",  "llm_fp",  "llm_fn",  "llm_tn",
    "tool_llm_agree",
    "issue_type_overlap",
    "issue_type_tool_extra", "issue_type_tool_missed",
    "issue_type_llm_extra",  "issue_type_llm_missed",
]


def build_summary(rows: list[dict]) -> str:
    lines = []
    w = 72

    def section(title):
        lines.append("")
        lines.append("=" * w)
        lines.append(f"  {title}")
        lines.append("=" * w)

    def row_line(label, *vals):
        label_w = 30
        lines.append(f"  {label:<{label_w}}" + "".join(f"{v:>10}" for v in vals))

    # ── Overall binary metrics ─────────────────────────────────────────────
    section("OVERALL BINARY METRICS  (flag vs clean)")

    t = defaultdict(int)
    l = defaultdict(int)
    agree = 0
    for r in rows:
        for k in ("tp", "fp", "fn", "tn"):
            t[k] += int(r[f"tool_{k}"])
            l[k] += int(r[f"llm_{k}"])
        agree += int(r["tool_llm_agree"])

    tm = binary_metrics(**t)
    lm = binary_metrics(**l)

    header = f"  {'Metric':<30}{'Tool':>10}{'LLM':>10}"
    lines.append(header)
    lines.append("  " + "-" * (w - 2))
    for metric in ("accuracy", "precision", "recall", "f1"):
        row_line(metric.capitalize(),
                 f"{tm[metric]:.3f}", f"{lm[metric]:.3f}")
    lines.append("  " + "-" * (w - 2))
    for metric in ("tp", "fp", "fn", "tn", "total"):
        row_line(metric.upper(), tm[metric], lm[metric])
    lines.append("")
    lines.append(f"  Tool–LLM agreement rate: {agree}/{len(rows)} "
                 f"({100*agree/len(rows):.1f}%)")

    # ── Per-issue-type metrics ─────────────────────────────────────────────
    section("PER-ISSUE-TYPE  (tool vs LLM, evaluated against gold label set)")

    all_types = set()
    for r in rows:
        all_types.update(parse_types(r.get("issue_type_gold", "")))

    type_stats: dict[str, dict] = {}
    for ft in sorted(all_types):
        tool_tp = tool_fp = tool_fn = 0
        llm_tp  = llm_fp  = llm_fn  = 0
        for r in rows:
            gold    = parse_types(r.get("issue_type_gold", ""))
            t_types = parse_types(r.get("tool_issue_types", ""))
            l_types = parse_types(r.get("llm_issue_types", ""))
            in_gold   = ft in gold
            tool_has  = ft in t_types
            llm_has   = ft in l_types
            if tool_has and in_gold:
                tool_tp += 1
            elif tool_has and not in_gold:
                tool_fp += 1
            elif not tool_has and in_gold:
                tool_fn += 1
            if llm_has and in_gold:
                llm_tp += 1
            elif llm_has and not in_gold:
                llm_fp += 1
            elif not llm_has and in_gold:
                llm_fn += 1
        type_stats[ft] = dict(
            tool_tp=tool_tp, tool_fp=tool_fp, tool_fn=tool_fn,
            llm_tp=llm_tp,   llm_fp=llm_fp,   llm_fn=llm_fn,
        )

    # header
    lines.append(
        f"  {'Flag type':<25}"
        f"{'T-P':>5}{'T-R':>5}{'T-F1':>6}"
        f"  {'L-P':>5}{'L-R':>5}{'L-F1':>6}"
        f"  {'Gold N':>6}"
    )
    lines.append("  " + "-" * (w - 2))
    for ft in sorted(type_stats):
        s = type_stats[ft]
        tp, tr, tf1 = prf(s["tool_tp"], s["tool_fp"], s["tool_fn"])
        lp, lr, lf1 = prf(s["llm_tp"],  s["llm_fp"],  s["llm_fn"])
        gold_n = s["tool_tp"] + s["tool_fn"]
        lines.append(
            f"  {ft:<25}"
            f"{tp:5.2f}{tr:5.2f}{tf1:6.2f}"
            f"  {lp:5.2f}{lr:5.2f}{lf1:6.2f}"
            f"  {gold_n:6d}"
        )

    # ── Breakdown by source category ───────────────────────────────────────
    section("BREAKDOWN BY SOURCE CATEGORY")

    cat_stats: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        cat = source_category(r.get("source", ""))
        cat_stats[cat]["n"] += 1
        cat_stats[cat]["tool_correct"] += int(r["tool_correct"])
        cat_stats[cat]["llm_correct"]  += int(r["llm_correct"])
        cat_stats[cat]["tool_fp"] += int(r["tool_fp"])
        cat_stats[cat]["tool_fn"] += int(r["tool_fn"])
        cat_stats[cat]["llm_fp"]  += int(r["llm_fp"])
        cat_stats[cat]["llm_fn"]  += int(r["llm_fn"])

    lines.append(
        f"  {'Category':<14}"
        f"{'N':>4}"
        f"  {'Tool Acc':>8}{'LLM Acc':>8}"
        f"  {'T-FP':>5}{'T-FN':>5}"
        f"  {'L-FP':>5}{'L-FN':>5}"
    )
    lines.append("  " + "-" * (w - 2))
    for cat in sorted(cat_stats):
        s = cat_stats[cat]
        n = s["n"]
        lines.append(
            f"  {cat:<14}{n:>4}"
            f"  {s['tool_correct']/n:>8.2f}{s['llm_correct']/n:>8.2f}"
            f"  {s['tool_fp']:>5}{s['tool_fn']:>5}"
            f"  {s['llm_fp']:>5}{s['llm_fn']:>5}"
        )

    # ── FP/FN examples ────────────────────────────────────────────────────
    section("TOOL FALSE POSITIVES  (tool=flag, human=clean, up to 10)")
    fps = [r for r in rows if int(r["tool_fp"])]
    if fps:
        for r in fps[:10]:
            lines.append(f"  [{r['id']}] {r['text_excerpt'][:90]}…")
            lines.append(f"        tool types: {r['tool_issue_types']}")
    else:
        lines.append("  None.")

    section("TOOL FALSE NEGATIVES  (tool=clean, human=flag, up to 10)")
    fns = [r for r in rows if int(r["tool_fn"])]
    if fns:
        for r in fns[:10]:
            lines.append(f"  [{r['id']}] {r['text_excerpt'][:90]}…")
            lines.append(f"        gold types: {r['issue_type_gold']}")
    else:
        lines.append("  None.")

    section("LLM FALSE POSITIVES  (llm=flag, human=clean, up to 10)")
    lfps = [r for r in rows if int(r["llm_fp"])]
    if lfps:
        for r in lfps[:10]:
            lines.append(f"  [{r['id']}] {r['text_excerpt'][:90]}…")
            lines.append(f"        llm types: {r['llm_issue_types']}")
    else:
        lines.append("  None.")

    section("LLM FALSE NEGATIVES  (llm=clean, human=flag, up to 10)")
    lfns = [r for r in rows if int(r["llm_fn"])]
    if lfns:
        for r in lfns[:10]:
            lines.append(f"  [{r['id']}] {r['text_excerpt'][:90]}…")
            lines.append(f"        gold types: {r['issue_type_gold']}")
    else:
        lines.append("  None.")

    lines.append("")
    lines.append("=" * w)
    return "\n".join(lines)


def main():
    if not INPUT_CSV.exists():
        print(
            f"Input not found: {INPUT_CSV}\n"
            "Run run_benchmark.py then run_llm.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    rows = []
    with INPUT_CSV.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        missing = REQUIRED_COLS - set(fields)
        if missing:
            print(f"Missing columns in input: {missing}", file=sys.stderr)
            sys.exit(1)
        for row in reader:
            rows.append(row)

    # Score each row
    scored_rows = []
    for row in rows:
        scored = dict(row)
        scored.update(score_row(row))
        scored_rows.append(scored)

    # Write scored.csv
    out_fields = fields + [c for c in SCORE_COLS if c not in fields]
    with SCORED_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(scored_rows)
    print(f"Scored CSV written: {SCORED_CSV}")

    # Build and write summary
    summary = build_summary(scored_rows)
    SUMMARY_TXT.write_text(summary, encoding="utf-8")
    print(f"Summary written:    {SUMMARY_TXT}")
    print()
    print(summary)


if __name__ == "__main__":
    main()
