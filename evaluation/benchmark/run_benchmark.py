"""
Layer 1 benchmark — tool runner.

Reads evaluation/benchmark/snippets.csv, runs flag_text() on each row,
writes evaluation/benchmark/results.csv with four added columns:
  tool_flag          "flag" | "clean"
  tool_issue_types   comma-separated unique flag types found
  tool_matched_texts pipe-separated matched spans (truncated to 80 chars each)
  tool_explanation   reason string of the highest-priority flag (or "")

Run from repo root:
    uv run python evaluation/benchmark/run_benchmark.py
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from risk_highlight.layer1 import Flag, PRIORITY_RANK, flag_text  # noqa: E402

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

BENCH_DIR = Path(__file__).parent
INPUT_CSV  = BENCH_DIR / "snippets.csv"
OUTPUT_CSV = BENCH_DIR / "results.csv"

NEW_COLS = ["tool_flag", "tool_issue_types", "tool_matched_texts", "tool_explanation"]


def main():
    if not INPUT_CSV.exists():
        print(f"Input not found: {INPUT_CSV}", file=sys.stderr)
        sys.exit(1)

    rows = []
    with INPUT_CSV.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        original_fields = reader.fieldnames or []
        for row in reader:
            rows.append(row)

    print(f"Running tool on {len(rows)} rows…")
    for row in rows:
        text = row["text_excerpt"]
        flags = flag_text(text)

        if flags:
            row["tool_flag"] = "flag"
            types = []
            seen_types = set()
            for f in flags:
                if f.flag_type not in seen_types:
                    types.append(f.flag_type)
                    seen_types.add(f.flag_type)
            row["tool_issue_types"] = ",".join(types)

            matched = []
            for f in flags:
                snippet = f.text[:80] + ("…" if len(f.text) > 80 else "")
                matched.append(snippet)
            row["tool_matched_texts"] = " | ".join(matched)

            # Highest-priority flag's reason
            best = min(flags, key=lambda f: PRIORITY_RANK[f.priority])
            row["tool_explanation"] = best.reason
        else:
            row["tool_flag"] = "clean"
            row["tool_issue_types"] = ""
            row["tool_matched_texts"] = ""
            row["tool_explanation"] = ""

    out_fields = original_fields + [c for c in NEW_COLS if c not in original_fields]
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(rows)

    flagged = sum(1 for r in rows if r["tool_flag"] == "flag")
    print(f"Done. {flagged}/{len(rows)} rows flagged.")
    print(f"Output: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
