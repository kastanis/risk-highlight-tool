"""
Layer 2 — Code Risk Checker (Streamlit app)

Upload a .py or .R file, get back flagged lines with reasons and
a decision-point checklist for editorial review.

All flagging logic is inlined — no imports from the notebook.

Run locally:
    uv run streamlit run ui/layer2_app.py
"""

import ast
import io
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import streamlit as st


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CodeFlag:
    line: int          # 1-indexed
    col: int           # 0-indexed column offset
    end_line: int
    code: str          # exact source text of flagged line
    flag_type: str
    priority: str      # "High" or "Medium"
    reason: str
    language: str      # "python" or "r"


@dataclass
class DecisionPoint:
    line: int           # first occurrence
    lines: list[int]    # all occurrences
    code: str           # code snippet from first occurrence
    category: str
    question: str


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FLAG_COLORS = {
    "no_shape_check":              "#ff6b6b",
    "no_na_check":                 "#ff922b",
    "no_dtype_check":              "#ffd43b",
    "zip_as_numeric":              "#f03e3e",
    "encoding_not_set":            "#a9e34b",
    "excel_date_risk":             "#63e6be",
    "no_value_range_check":        "#74c0fc",
    "no_category_check":           "#4dabf7",
    "total_row_risk":              "#ff6b6b",
    "magic_number":                "#dee2e6",
    "sentinel_value_risk":         "#ff922b",
    "no_join_count_check":         "#f03e3e",
    "join_on_string":              "#ffa8a8",
    "no_unmatched_check":          "#ff6b6b",
    "hardcoded_threshold":         "#ffd43b",
    "percentage_without_base":     "#ff922b",
    "small_denominator_risk":      "#f03e3e",
    "mean_without_median":         "#74c0fc",
    "no_null_before_aggregation":  "#ff6b6b",
    "pct_change_without_base_note":"#a9e34b",
    "geocoding_unverified":        "#ff922b",
    "projection_not_set":          "#f03e3e",
    "hardcoded_geo_count":         "#ffd43b",
}

HIGH_FLAGS = {
    "no_shape_check", "no_na_check", "zip_as_numeric", "total_row_risk",
    "sentinel_value_risk", "no_join_count_check", "no_unmatched_check",
    "hardcoded_threshold", "no_null_before_aggregation", "geocoding_unverified",
    "projection_not_set", "percentage_without_base", "small_denominator_risk",
}

PRIORITY_ORDER = {"High": 0, "Medium": 1}

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
}


# ---------------------------------------------------------------------------
# Python flagging — AST + regex
# ---------------------------------------------------------------------------

def _src_line(source_lines: list[str], lineno: int) -> str:
    return source_lines[lineno - 1].rstrip() if 0 < lineno <= len(source_lines) else ""


def _code_only(line: str) -> str:
    """Strip inline comment — avoids comments with flag keywords causing false negatives."""
    idx = line.find("#")
    return line[:idx] if idx != -1 else line


def _window(source_lines: list[str], lineno: int, before: int = 5, after: int = 5) -> list[str]:
    start = max(0, lineno - 1 - before)
    end   = min(len(source_lines), lineno + after)
    return source_lines[start: lineno - 1] + source_lines[lineno: end]


def _has_nearby_call(source_lines: list[str], lineno: int, methods: list[str],
                     before: int = 5, after: int = 5) -> bool:
    joined = " ".join(_code_only(l) for l in _window(source_lines, lineno, before, after))
    return any(m in joined for m in methods)


_SENTINEL_RE   = re.compile(r"!=\s*-(?:99+|999+)|!=\s*(?:9999|99999)\b")
_ZIP_PATTERNS  = re.compile(r"\bzip(?:_?code)?s?\b", re.IGNORECASE)
_PCT_CHANGE    = re.compile(r"\.pct_change\s*\(")


class PythonFlagger(ast.NodeVisitor):
    def __init__(self, source: str):
        self.source_lines = source.splitlines()
        self.flags: list[CodeFlag] = []
        self._read_csv_lines: list[int] = []
        self._merge_lines: list[int] = []
        self._agg_lines: list[int] = []
        self._merge_how: dict[int, str] = {}

    def _flag(self, node, flag_type, priority, reason):
        lineno = node.lineno
        end_line = getattr(node, "end_lineno", lineno)
        self.flags.append(CodeFlag(
            line=lineno, col=node.col_offset, end_line=end_line,
            code=_src_line(self.source_lines, lineno),
            flag_type=flag_type, priority=priority, reason=reason, language="python",
        ))

    def _get_func_name(self, node: ast.Call) -> str | None:
        if isinstance(node.func, ast.Attribute): return node.func.attr
        if isinstance(node.func, ast.Name): return node.func.id
        return None

    def visit_Call(self, node: ast.Call):
        fn = self._get_func_name(node)

        if fn in ("read_csv", "read_excel", "read_table", "read_parquet"):
            self._read_csv_lines.append(node.lineno)
            if fn in ("read_csv", "read_table"):
                if not any(kw.arg == "encoding" for kw in node.keywords):
                    self._flag(node, "encoding_not_set", "Medium",
                               f"{fn}() with no encoding= argument")
            if fn == "read_excel":
                if not any(kw.arg == "dtype" for kw in node.keywords):
                    self._flag(node, "excel_date_risk", "Medium",
                               "read_excel() with no dtype= — date columns may parse incorrectly")

        if fn in ("merge", "join"):
            self._merge_lines.append(node.lineno)
            how = "inner"
            for kw in node.keywords:
                if kw.arg == "how" and isinstance(kw.value, ast.Constant):
                    how = kw.value.value
            self._merge_how[node.lineno] = how
            for kw in node.keywords:
                if kw.arg == "on" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    col = kw.value.value
                    if not re.search(r"(?:id|fips|code|num|key|_id)$", col, re.IGNORECASE):
                        self._flag(node, "join_on_string", "Medium",
                                   f"Merge key '{col}' looks like a string column — verify uniqueness")

        if fn in ("sum", "mean", "count", "median", "std", "var"):
            self._agg_lines.append(node.lineno)

        if "geocod" in (fn or ""):
            if not _has_nearby_call(self.source_lines, node.lineno,
                                    ["match_rate", "len(", "shape", "count"]):
                self._flag(node, "geocoding_unverified", "High",
                           "Geocoding call with no match-rate check nearby")

        if fn in ("sjoin", "sjoin_nearest"):
            if not _has_nearby_call(self.source_lines, node.lineno,
                                    ["crs", "epsg", "set_crs", "to_crs"]):
                self._flag(node, "projection_not_set", "High",
                           "Spatial join with no CRS check nearby")

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        if isinstance(node.value, ast.Call):
            fn = self._get_func_name(node.value)
            if fn == "astype" and node.value.args:
                arg = node.value.args[0]
                is_numeric = (
                    (isinstance(arg, ast.Name) and arg.id in ("int", "float", "int64", "float64")) or
                    (isinstance(arg, ast.Constant) and arg.value in ("int", "float", "int64", "float64"))
                )
                if is_numeric and _ZIP_PATTERNS.search(ast.unparse(node)):
                    self._flag(node, "zip_as_numeric", "High",
                               "ZIP code column cast to numeric — leading zeros will be lost")
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare):
        for comparator in node.comparators:
            if isinstance(comparator, ast.Constant) and comparator.value == 0.05:
                self._flag(node, "hardcoded_threshold", "High",
                           "Hardcoded p < 0.05 — document the alpha choice")
        self.generic_visit(node)

    def run_post_checks(self):
        self._check_loads()
        self._check_merges()
        self._check_aggregations()
        self._check_regex_passes()

    def _check_loads(self):
        all_load_lines = set(self._read_csv_lines)
        for lineno in self._read_csv_lines:
            after_lines = []
            for offset in range(1, 9):
                nxt = lineno + offset
                if nxt in all_load_lines:
                    break
                if nxt <= len(self.source_lines):
                    after_lines.append(self.source_lines[nxt - 1])
            before_lines = self.source_lines[max(0, lineno - 4): lineno - 1]
            block = " ".join(_code_only(l) for l in before_lines + after_lines)
            lc = _src_line(self.source_lines, lineno)

            if not any(m in block for m in ["len(", "shape", "nrow", "count"]):
                self.flags.append(CodeFlag(line=lineno, col=0, end_line=lineno, code=lc,
                    flag_type="no_shape_check", priority="High",
                    reason="Data loaded — no row count check nearby (len/shape)",
                    language="python"))

            if not any(m in block for m in ["isna", "isnull", "notna", "dropna", "fillna"]):
                self.flags.append(CodeFlag(line=lineno, col=0, end_line=lineno, code=lc,
                    flag_type="no_na_check", priority="High",
                    reason="Data loaded — no NA check nearby (isna/dropna)",
                    language="python"))

            if not any(m in block for m in ["dtypes", "info(", ".dtype"]):
                self.flags.append(CodeFlag(line=lineno, col=0, end_line=lineno, code=lc,
                    flag_type="no_dtype_check", priority="Medium",
                    reason="Data loaded — no dtype check nearby (.dtypes/.info())",
                    language="python"))

    def _check_merges(self):
        for lineno in self._merge_lines:
            if not _has_nearby_call(self.source_lines, lineno,
                                    ["len(", "shape", "print"], before=3, after=3):
                self.flags.append(CodeFlag(line=lineno, col=0, end_line=lineno,
                    code=_src_line(self.source_lines, lineno),
                    flag_type="no_join_count_check", priority="High",
                    reason="Merge with no row count check before or after",
                    language="python"))
            how = self._merge_how.get(lineno, "inner")
            if how in ("left", "right", "outer"):
                if not _has_nearby_call(self.source_lines, lineno,
                                        ["isin", "indicator", "anti", "~"],
                                        before=4, after=8):
                    self.flags.append(CodeFlag(line=lineno, col=0, end_line=lineno,
                        code=_src_line(self.source_lines, lineno),
                        flag_type="no_unmatched_check", priority="High",
                        reason=f"{how} join — no check for unmatched rows",
                        language="python"))

    def _check_aggregations(self):
        for lineno in self._agg_lines:
            line = self.source_lines[lineno - 1]
            if any(m in _code_only(line) for m in
                   ["dropna", "fillna", "notna", "skipna", "isna", "isnull"]):
                continue
            if not _has_nearby_call(self.source_lines, lineno,
                                    ["dropna", "fillna", "isna", "notna", "isnull"],
                                    before=5, after=2):
                self.flags.append(CodeFlag(line=lineno, col=0, end_line=lineno,
                    code=line.rstrip(),
                    flag_type="no_null_before_aggregation", priority="High",
                    reason="Aggregation with no prior null handling",
                    language="python"))

    def _check_regex_passes(self):
        for i, line in enumerate(self.source_lines, start=1):
            s = line.strip()
            c = _code_only(line)
            if not s or s.startswith("#"):
                continue

            if re.search(r'["\'](?:total|Total)["\']', c) and re.search(r"!=|==", c):
                self.flags.append(CodeFlag(line=i, col=0, end_line=i, code=s,
                    flag_type="total_row_risk", priority="High",
                    reason='"Total" row detected — verify exclusion from aggregation',
                    language="python"))

            if _SENTINEL_RE.search(c):
                self.flags.append(CodeFlag(line=i, col=0, end_line=i, code=s,
                    flag_type="sentinel_value_risk", priority="High",
                    reason="Sentinel value filter — verify this is not actual missing data",
                    language="python"))

            if re.search(r"[/\*]\s*100", c) and re.search(r"\bpct\b|percent|rate", c, re.IGNORECASE):
                nearby = self.source_lines[max(0, i - 3): i + 3]
                if not any(re.search(r"n=|n =", l) or "print" in l for l in nearby):
                    self.flags.append(CodeFlag(line=i, col=0, end_line=i, code=s,
                        flag_type="percentage_without_base", priority="High",
                        reason="Percentage calculated — denominator not printed nearby",
                        language="python"))

            if ".mean()" in c:
                nearby = self.source_lines[max(0, i - 4): i + 4]
                if not any(".median()" in l for l in nearby):
                    self.flags.append(CodeFlag(line=i, col=0, end_line=i, code=s,
                        flag_type="mean_without_median", priority="Medium",
                        reason="mean() used — no median() nearby (check for outliers)",
                        language="python"))

            if re.search(r"\.(mean|sum)\(", c):
                nearby = self.source_lines[max(0, i - 6): i + 6]
                if not any(re.search(r"\.(min|max|describe)\(", l) for l in nearby):
                    self.flags.append(CodeFlag(line=i, col=0, end_line=i, code=s,
                        flag_type="no_value_range_check", priority="Medium",
                        reason="Aggregation with no min/max range check nearby",
                        language="python"))

            if ".groupby(" in c:
                nearby = self.source_lines[max(0, i - 6): i + 6]
                if not any("value_counts" in l for l in nearby):
                    self.flags.append(CodeFlag(line=i, col=0, end_line=i, code=s,
                        flag_type="no_category_check", priority="Medium",
                        reason="groupby() with no value_counts() to verify categories",
                        language="python"))

            if _PCT_CHANGE.search(c):
                nearby = self.source_lines[max(0, i - 3): i + 3]
                if not any("#" in l for l in nearby):
                    self.flags.append(CodeFlag(line=i, col=0, end_line=i, code=s,
                        flag_type="pct_change_without_base_note", priority="Medium",
                        reason="pct_change() with no comment explaining base period",
                        language="python"))

            m = re.search(r"[><!]=?\s*(\d+\.\d+)\b", c)
            if m:
                val = float(m.group(1))
                if val not in (0.0, 0.5, 1.0, 100.0, 0.05):
                    self.flags.append(CodeFlag(line=i, col=0, end_line=i, code=s,
                        flag_type="magic_number", priority="Medium",
                        reason=f"Unexplained threshold {m.group(1)} — add a comment",
                        language="python"))


# ---------------------------------------------------------------------------
# R flagging — regex-based
# ---------------------------------------------------------------------------

_R_LOAD_FUNCS = re.compile(r"\b(?:read\.csv|read_csv|read\.table|fread|readRDS|load)\s*\(")
_R_JOIN_FUNCS = re.compile(r"\b(?:left_join|right_join|full_join|inner_join|merge)\s*\(")
_R_AGG_FUNCS  = re.compile(r"\b(?:sum|mean|count|n\(|summarise|summarize)\s*\(")
_R_GROUP_BY   = re.compile(r"\bgroup_by\s*\(")


def _r_has_nearby(lines: list[str], lineno: int, patterns: list[str], window: int = 6) -> bool:
    start = max(0, lineno - 1 - window)
    end   = min(len(lines), lineno + window)
    block = " ".join(lines[start:end])
    return any(p in block for p in patterns)


def flag_r(source: str) -> list[CodeFlag]:
    lines = source.splitlines()
    flags: list[CodeFlag] = []
    load_lines: list[int] = []
    merge_lines: list[int] = []
    merge_outer: list[int] = []

    def _flag(lineno, flag_type, priority, reason):
        flags.append(CodeFlag(
            line=lineno, col=0, end_line=lineno,
            code=lines[lineno-1].strip(),
            flag_type=flag_type, priority=priority,
            reason=reason, language="r",
        ))

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if _R_LOAD_FUNCS.search(line):
            load_lines.append(i)
            if not re.search(r"encoding|fileEncoding", line):
                _flag(i, "encoding_not_set", "Medium",
                      "read function with no encoding argument")

        if _R_JOIN_FUNCS.search(line):
            merge_lines.append(i)
            if re.search(r"\bleft_join|right_join|full_join", line):
                merge_outer.append(i)
            m = re.search(r'by\s*=\s*["\']([^"\']+)["\']', line)
            if m:
                col = m.group(1)
                if not re.search(r"(?:id|fips|code|num|key)$", col, re.IGNORECASE):
                    _flag(i, "join_on_string", "Medium",
                          f"Join key '{col}' looks like a string column")

        if re.search(r"as\.numeric|as\.integer", line) and _ZIP_PATTERNS.search(line):
            _flag(i, "zip_as_numeric", "High",
                  "ZIP column cast to numeric — leading zeros will be lost")

        if re.search(r'["\'][Tt]otal["\']', line) and re.search(r"!=|==", line):
            _flag(i, "total_row_risk", "High",
                  '"Total" row detected — verify exclusion from aggregation')

        if re.search(r"\bmean\s*\(", line):
            nearby = lines[max(0,i-4): i+4]
            if not any(re.search(r"\bmedian\s*\(", l) for l in nearby):
                _flag(i, "mean_without_median", "Medium",
                      "mean() used — no median() nearby")

        if re.search(r"\b(?:mean|sum)\s*\(", line):
            nearby = lines[max(0,i-6): i+6]
            if not any(re.search(r"\b(?:min|max|range|summary)\s*\(", l) for l in nearby):
                _flag(i, "no_value_range_check", "Medium",
                      "Aggregation with no min/max/range check nearby")

        if _R_GROUP_BY.search(line):
            nearby = lines[max(0,i-6): i+6]
            if not any(re.search(r"\b(?:table|unique|levels|value_counts)\s*\(", l)
                       or "n()" in l for l in nearby):
                _flag(i, "no_category_check", "Medium",
                      "group_by() with no table()/unique() check on categories")

        m = re.search(r"!=\s*(-99+|-999+|9999)", line)
        if m:
            _flag(i, "sentinel_value_risk", "High",
                  f"Sentinel value {m.group(1)} — verify it represents missing data")

        if re.search(r"p\.value\s*[<>]=?\s*0\.05|alpha\s*=\s*0\.05", line):
            _flag(i, "hardcoded_threshold", "High",
                  "Hardcoded alpha 0.05 — document the significance threshold")

        if re.search(r"[*/]\s*100", line) and re.search(r"pct|percent|rate", line, re.IGNORECASE):
            nearby = lines[max(0,i-3): i+3]
            if not any(re.search(r"n=|print|cat\(", l) for l in nearby):
                _flag(i, "percentage_without_base", "High",
                      "Percentage with no denominator printed")

        if _R_AGG_FUNCS.search(line):
            nearby = lines[max(0,i-6): i+6]
            if not any(re.search(r"na\.rm|complete\.cases|is\.na|drop_na|na\.omit", l)
                       for l in nearby):
                _flag(i, "no_null_before_aggregation", "High",
                      "Aggregation with no NA handling (na.rm / na.omit / drop_na)")

        m = re.search(r"[><!]=?\s*(\d+\.\d+)\b", line)
        if m:
            val = float(m.group(1))
            if val not in (0.0, 0.5, 1.0, 100.0, 0.05) and "#" not in line:
                _flag(i, "magic_number", "Medium",
                      f"Unexplained threshold {m.group(1)} — add a comment")

    for lineno in load_lines:
        if not _r_has_nearby(lines, lineno, ["nrow", "dim", "str(", "length(",
                                              "skim(", "skim ", "glimpse(", "summary("]):
            _flag(lineno, "no_shape_check", "High",
                  "Data loaded — no nrow()/dim()/skim() check nearby")
        if not _r_has_nearby(lines, lineno, ["is.na", "complete.cases", "na.omit",
                                              "drop_na", "summary(", "skim(", "skim "]):
            _flag(lineno, "no_na_check", "High",
                  "Data loaded — no is.na() / complete.cases() / skim() check nearby")
        if not _r_has_nearby(lines, lineno, ["str(", "class(", "glimpse(", "glimpse ",
                                              "summary(", "skim(", "skim "]):
            _flag(lineno, "no_dtype_check", "Medium",
                  "Data loaded — no str()/class()/glimpse()/skim() dtype check nearby")

    for lineno in merge_lines:
        if not _r_has_nearby(lines, lineno, ["nrow", "dim", "print"]):
            _flag(lineno, "no_join_count_check", "High",
                  "Join with no row count check before or after")

    for lineno in merge_outer:
        if not _r_has_nearby(lines, lineno, ["anti_join", "is.na", "filter"]):
            _flag(lineno, "no_unmatched_check", "High",
                  "Outer join with no anti-join / unmatched-row check")

    flags.sort(key=lambda f: (f.line, PRIORITY_ORDER.get(f.priority, 9)))
    return flags


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def flag_code(source: str, filename: str) -> list[CodeFlag]:
    """Flag a Python or R script from source text."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".py":
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            st.error(f"SyntaxError in uploaded file: {e}")
            return []
        flagger = PythonFlagger(source)
        flagger.visit(tree)
        flagger.run_post_checks()
        flags = flagger.flags
    elif suffix == ".r":
        flags = flag_r(source)
    else:
        return []
    flags.sort(key=lambda f: (f.line, PRIORITY_ORDER.get(f.priority, 9)))
    return flags


# ---------------------------------------------------------------------------
# Decision point detector
# ---------------------------------------------------------------------------

# Each entry: (category, compiled_pattern, question_fn)
# question_fn receives the matched line and returns a context-aware question string.

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
    # Python: .groupby("col") — R: group_by(col)
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

def _q_smoothing(line: str) -> str:
    m = re.search(r"k\s*=\s*(\d+)|n\s*=\s*(\d+)|window\s*=\s*(\d+)", line)
    k = next((g for g in (m.group(1), m.group(2), m.group(3)) if g), None) if m else None
    window = f"{k}-period" if k else "rolling"
    return (f"{window} smoothing applied. Why this window size? "
            "Was it matched to a published methodology? "
            "How does the choice affect the apparent trend?")


_DP_PATTERNS = [
    ("filter_threshold",
     re.compile(r"(?:df|data|gdf)\[.*?[><!]=?\s*\d+(?:\.\d+)?\b"),
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
     re.compile(r"\b(?:ttest_ind|ttest_1samp|mannwhitneyu|chi2_contingency|anova|pearsonr|spearmanr)\s*\("),
     _q_stat_test),
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
     re.compile(r"year\s*==\s*\d{4}|(?:19|20)\d{2}|\.dt\.year"),
     _q_time_period),
    ("deduplication",
     re.compile(r"\.drop_duplicates\(|\.duplicated\(|drop_duplicates\("),
     _q_deduplication),
    ("smoothing_choice",
     re.compile(r"rollmean\s*\(|rollmedian\s*\(|rolling\s*\(\s*window|\.rolling\("),
     _q_smoothing),
]


def find_decision_points(source: str) -> list[DecisionPoint]:
    lines = source.splitlines()
    # key: (category, question) -> DecisionPoint
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
# Rendering — returns HTML strings for st.markdown(unsafe_allow_html=True)
# ---------------------------------------------------------------------------

def render_flags(flags: list[CodeFlag], source: str, filename: str) -> str:
    source_lines = source.splitlines()
    flag_map: dict[int, list[CodeFlag]] = {}
    for f in flags:
        flag_map.setdefault(f.line, []).append(f)

    seen_types = sorted({f.flag_type for f in flags})
    legend_items = "".join(
        f'<span style="background:{FLAG_COLORS.get(ft,"#eee")};'
        f'padding:2px 8px;margin:2px;border-radius:3px;font-size:0.85em;">'
        f'{ft.replace("_"," ")}</span>'
        for ft in seen_types
    )

    summary_rows = ""
    for ft in seen_types:
        ft_flags = [f for f in flags if f.flag_type == ft]
        color = FLAG_COLORS.get(ft, "#eee")
        lines_str = ", ".join(str(f.line) for f in ft_flags)
        priority = ft_flags[0].priority
        summary_rows += (
            f'<tr>'
            f'<td style="background:{color};padding:4px 8px;white-space:nowrap;">'
            f'{ft.replace("_"," ")}</td>'
            f'<td style="padding:4px 8px;">{priority}</td>'
            f'<td style="padding:4px 8px;">{len(ft_flags)}</td>'
            f'<td style="padding:4px 8px;font-family:monospace;color:#666;">{lines_str}</td>'
            f'</tr>'
        )

    code_rows = ""
    for i, line in enumerate(source_lines, start=1):
        line_flags = flag_map.get(i, [])
        safe_line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if line_flags:
            primary = sorted(line_flags, key=lambda f: PRIORITY_ORDER.get(f.priority, 9))[0]
            bg = FLAG_COLORS.get(primary.flag_type, "#fff9c4")
            annotation = " ".join(
                f'<span style="background:{FLAG_COLORS.get(f.flag_type,"#eee")};'
                f'padding:1px 5px;border-radius:3px;font-size:0.78em;white-space:nowrap;">'
                f'{f.flag_type.replace("_"," ")}: {f.reason}</span>'
                for f in line_flags
            )
            code_rows += (
                f'<tr style="background:{bg}33;">'
                f'<td style="color:#888;padding:2px 8px;font-family:monospace;'
                f'user-select:none;min-width:36px;text-align:right;vertical-align:top;">{i}</td>'
                f'<td style="font-family:monospace;white-space:pre;padding:2px 12px;'
                f'vertical-align:top;">{safe_line}</td>'
                f'<td style="padding:2px 8px;vertical-align:top;">{annotation}</td>'
                f'</tr>'
            )
        else:
            code_rows += (
                f'<tr>'
                f'<td style="color:#ccc;padding:2px 8px;font-family:monospace;'
                f'user-select:none;min-width:36px;text-align:right;">{i}</td>'
                f'<td style="font-family:monospace;white-space:pre;color:#555;'
                f'padding:2px 12px;">{safe_line}</td>'
                f'<td></td>'
                f'</tr>'
            )

    return f"""
    <style>
      .l2-report {{ font-family: sans-serif; }}
      .l2-report table {{ border-collapse: collapse; width: 100%; margin-bottom: 16px; }}
      .l2-report td {{ vertical-align: top; }}
      .l2-report tr:hover {{ filter: brightness(0.97); }}
    </style>
    <div class="l2-report">
      <div style="margin-bottom:12px;">{legend_items}</div>
      <h3 style="font-size:1em;margin-bottom:6px;">Summary</h3>
      <table>
        <tr style="background:#f1f3f5;font-weight:bold;">
          <td style="padding:4px 8px;">Flag type</td>
          <td style="padding:4px 8px;">Priority</td>
          <td style="padding:4px 8px;">Count</td>
          <td style="padding:4px 8px;">Lines</td>
        </tr>
        {summary_rows}
      </table>
      <h3 style="font-size:1em;margin-bottom:6px;">Annotated source — <code>{filename}</code></h3>
      <table>{code_rows}</table>
    </div>
    """


def render_decision_points(points: list[DecisionPoint], filename: str) -> str:
    if not points:
        return "<p style='color:#888;'>No decision points detected.</p>"

    rows = ""
    for p in points:
        color = CATEGORY_COLORS.get(p.category, "#eee")
        safe_code = p.code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if len(p.lines) == 1:
            lines_display = str(p.lines[0])
        elif len(p.lines) <= 4:
            lines_display = ", ".join(str(n) for n in p.lines)
        else:
            lines_display = ", ".join(str(n) for n in p.lines[:3]) + f" +{len(p.lines)-3} more"
        rows += (
            f'<tr>'
            f'<td style="padding:6px 8px;color:#888;font-family:monospace;'
            f'text-align:right;vertical-align:top;white-space:nowrap;">{lines_display}</td>'
            f'<td style="padding:6px 8px;vertical-align:top;white-space:nowrap;">'
            f'<span style="background:{color};padding:2px 7px;border-radius:3px;'
            f'font-size:0.82em;">{p.category.replace("_"," ")}</span></td>'
            f'<td style="padding:6px 8px;font-family:monospace;font-size:0.88em;'
            f'vertical-align:top;">{safe_code}</td>'
            f'<td style="padding:6px 8px;font-size:0.88em;color:#444;'
            f'vertical-align:top;">{p.question}</td>'
            f'</tr>'
        )

    return f"""
    <style>
      .dp-report {{ font-family: sans-serif; }}
      .dp-report table {{ border-collapse: collapse; width: 100%; }}
      .dp-report td {{ border-bottom: 1px solid #eee; }}
      .dp-report tr:hover {{ background: #f8f9fa; }}
    </style>
    <div class="dp-report">
      <p style="color:#555;margin-bottom:12px;">
        {len(points)} methodological choice(s) in <code>{filename}</code> — verify each with an editor or peer reviewer
      </p>
      <table>
        <tr style="background:#f1f3f5;font-weight:bold;">
          <td style="padding:6px 8px;min-width:40px;">Line</td>
          <td style="padding:6px 8px;">Category</td>
          <td style="padding:6px 8px;">Code</td>
          <td style="padding:6px 8px;">Question for reviewer</td>
        </tr>
        {rows}
      </table>
    </div>
    """


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

def _active_flag_types() -> set[str]:
    return {ft for ft in FLAG_COLORS if st.session_state.get(f"cb_{ft}", True)}


def _filter_flags(flags: list[CodeFlag]) -> list[CodeFlag]:
    active = _active_flag_types()
    return [f for f in flags if f.flag_type in active]


# ---------------------------------------------------------------------------
# Streamlit app
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Code Risk Checker",
    page_icon="🔬",
    layout="wide",
)

st.title("Code Risk Checker")
st.caption(
    "Upload a Python or R analysis script. "
    "Get back flagged lines with reasons and a decision-point checklist for editors."
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
    st.header("Show / hide flag types")

    high_types  = [ft for ft in FLAG_COLORS if ft in HIGH_FLAGS]
    med_types   = [ft for ft in FLAG_COLORS if ft not in HIGH_FLAGS]

    st.markdown("**High priority**")
    for ft in sorted(high_types):
        color = FLAG_COLORS[ft]
        label = f'<span style="background:{color};padding:1px 6px;border-radius:3px;font-size:0.82em;">{ft.replace("_"," ")}</span>'
        st.checkbox(ft.replace("_", " "), value=True, key=f"cb_{ft}")

    st.markdown("**Medium priority**")
    for ft in sorted(med_types):
        st.checkbox(ft.replace("_", " "), value=True, key=f"cb_{ft}")

    st.divider()
    st.header("About")
    st.markdown(
        "Flags data-journalism risk patterns in Python and R analysis scripts. "
        "**Does not run the code.** Static analysis only.\n\n"
        "**Risk flags** — things that may be wrong (for the data team)\n\n"
        "**Decision points** — methodology choices needing editorial sign-off\n\n"
        "**Supported:** `.py`, `.R`  —  upload a file or paste code directly."
    )

# --- Main panel ---
# Resolve source + filename from whichever input mode is active
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
if st.session_state.get("l2_cache_key") != cache_key:
    with st.spinner(f"Analyzing {filename}…"):
        flags = flag_code(source, filename)
        dps   = find_decision_points(source)
    st.session_state["l2_flags"]     = flags
    st.session_state["l2_dps"]       = dps
    st.session_state["l2_cache_key"] = cache_key
else:
    flags = st.session_state["l2_flags"]
    dps   = st.session_state["l2_dps"]

filtered = _filter_flags(flags)
n_high   = sum(1 for f in filtered if f.priority == "High")
n_med    = sum(1 for f in filtered if f.priority == "Medium")

# Summary badges
col_h, col_m, col_t, _ = st.columns([1, 1, 1, 5])
with col_h:
    st.markdown(
        f"<div style='background:#ff6b6b;padding:6px 14px;border-radius:6px;"
        f"text-align:center;color:#fff;font-weight:bold;font-size:1.1em;'>"
        f"{n_high} High</div>", unsafe_allow_html=True
    )
with col_m:
    st.markdown(
        f"<div style='background:#ffd43b;padding:6px 14px;border-radius:6px;"
        f"text-align:center;font-weight:bold;font-size:1.1em;'>"
        f"{n_med} Medium</div>", unsafe_allow_html=True
    )
with col_t:
    st.markdown(
        f"<div style='background:#f1f3f5;padding:6px 14px;border-radius:6px;"
        f"text-align:center;font-size:1.1em;'>"
        f"{len(dps)} Decision pts</div>", unsafe_allow_html=True
    )

st.divider()

tab_dps, tab_flags = st.tabs(["Decision Points", "Risk Flags"])

with tab_dps:
    if not dps:
        st.success("No decision points detected.")
    else:
        st.markdown(render_decision_points(dps, filename), unsafe_allow_html=True)

with tab_flags:
    if not filtered:
        st.success("No flags match the current filter.")
    else:
        st.markdown(render_flags(filtered, source, filename), unsafe_allow_html=True)
