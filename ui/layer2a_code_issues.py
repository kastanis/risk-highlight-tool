"""
Layer 2a — Code Issues (Streamlit app)

For the data reporter. Upload or paste a Python or R analysis script,
get back flagged lines with reasons. Static analysis only — does not run the code.

Run locally:
    uv run streamlit run ui/layer2a_code_issues.py
"""

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

import streamlit as st


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CodeFlag:
    line: int
    col: int
    end_line: int
    code: str
    flag_type: str
    priority: str
    reason: str
    language: str


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
    "no_category_check":           "#4dabf7",
    "no_join_count_check":         "#f03e3e",
    "join_on_string":              "#ffa8a8",
    "no_unmatched_check":          "#ff6b6b",
    "hardcoded_threshold":         "#ffd43b",
    "percentage_without_base":     "#ffd43b",
    "no_null_before_aggregation":  "#ff6b6b",
    "projection_not_set":          "#f03e3e",
    "hardcoded_path":              "#f783ac",
}

HIGH_FLAGS = {
    "no_shape_check", "no_na_check", "zip_as_numeric",
    "no_join_count_check", "no_unmatched_check",
    "hardcoded_threshold", "no_null_before_aggregation",
    "projection_not_set",
}

PRIORITY_ORDER = {"High": 0, "Medium": 1}

FLAG_DEFINITIONS = {
    "no_shape_check":              "Data was loaded but no row count check (len/shape/nrow/skim) was found nearby. You may not know if the file loaded completely.",
    "no_na_check":                 "Data was loaded but no missing-value check (isna/dropna/is.na/skim) was found nearby. Silent NAs can corrupt aggregations.",
    "no_dtype_check":              "Data was loaded but no dtype inspection (dtypes/str/glimpse/skim) was found nearby. Columns may have parsed as the wrong type.",
    "zip_as_numeric":              "A ZIP code column was cast to a numeric type. Leading zeros will be silently dropped (e.g. 07030 → 7030).",
    "encoding_not_set":            "File read with no encoding argument. Non-ASCII characters (accented names, special symbols) may be corrupted on some platforms.",
    "excel_date_risk":             "read_excel() with no dtype= argument. Excel stores dates as serial numbers; pandas may silently misparse date columns.",
    "no_category_check":           "A groupby was used with no value_counts/table/unique check on the grouping column. Unexpected category values (typos, nulls) may produce phantom groups.",
    "no_join_count_check":         "A merge/join was performed with no row count check before or after. You may not know if rows were unexpectedly gained or lost.",
    "join_on_string":              "A join key looks like a free-text string column. String joins are fragile — whitespace, case, or encoding differences will silently drop rows.",
    "no_unmatched_check":          "A left/right/outer join was performed with no check for unmatched rows. Rows that failed to match are silently excluded from the result.",
    "hardcoded_threshold":         "A hardcoded significance threshold (p < 0.05) was found. This alpha choice should be documented and justified.",
    "percentage_without_base":     "A percentage was calculated but the denominator (base N) was not printed nearby. Readers cannot verify what the percentage is of.",
    "no_null_before_aggregation":  "An aggregation was computed with no null handling (na.rm/dropna/fillna) nearby. NAs propagate silently through sum/mean in many languages.",
    "projection_not_set":          "A spatial join was performed with no CRS/projection check nearby. Mismatched projections produce wrong geometries with no error.",
    "hardcoded_path":              "An absolute or user-specific file path was found. The script will not run on another machine or in a shared environment.",
}


# ---------------------------------------------------------------------------
# Python flagging — AST + regex
# ---------------------------------------------------------------------------

def _src_line(source_lines: list[str], lineno: int) -> str:
    return source_lines[lineno - 1].rstrip() if 0 < lineno <= len(source_lines) else ""


def _code_only(line: str) -> str:
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


_ZIP_PATTERNS = re.compile(r"\bzip(?:_?code)?s?\b", re.IGNORECASE)


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

            if re.search(r"[/\*]\s*100", c) and re.search(r"\bpct\b|percent|rate", c, re.IGNORECASE):
                nearby = self.source_lines[max(0, i - 3): i + 3]
                if not any(re.search(r"n=|n =", l) or "print" in l for l in nearby):
                    self.flags.append(CodeFlag(line=i, col=0, end_line=i, code=s,
                        flag_type="percentage_without_base", priority="Medium",
                        reason="Percentage calculated — denominator not printed nearby",
                        language="python"))

            if ".groupby(" in c:
                nearby = self.source_lines[max(0, i - 6): i + 6]
                if not any("value_counts" in l for l in nearby):
                    self.flags.append(CodeFlag(line=i, col=0, end_line=i, code=s,
                        flag_type="no_category_check", priority="Medium",
                        reason="groupby() with no value_counts() to verify categories",
                        language="python"))

            if re.search(r"""['"](/Users/|/home/|C:\\\\|~/|~\\\\)""", c):
                self.flags.append(CodeFlag(line=i, col=0, end_line=i, code=s,
                    flag_type="hardcoded_path", priority="Medium",
                    reason="Absolute/user-specific path — script will not run on another machine",
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

        if _R_GROUP_BY.search(line):
            nearby = lines[max(0,i-6): i+6]
            if not any(re.search(r"\b(?:table|unique|levels|value_counts)\s*\(", l)
                       or "n()" in l for l in nearby):
                _flag(i, "no_category_check", "Medium",
                      "group_by() with no table()/unique() check on categories")

        if re.search(r"p\.value\s*[<>]=?\s*0\.05|alpha\s*=\s*0\.05", line):
            _flag(i, "hardcoded_threshold", "High",
                  "Hardcoded alpha 0.05 — document the significance threshold")

        if re.search(r"[*/]\s*100", line) and re.search(r"pct|percent|rate", line, re.IGNORECASE):
            nearby = lines[max(0,i-3): i+3]
            if not any(re.search(r"n=|print|cat\(", l) for l in nearby):
                _flag(i, "percentage_without_base", "Medium",
                      "Percentage with no denominator printed")

        if _R_AGG_FUNCS.search(line):
            if not re.search(r"na\.rm", line):
                nearby = lines[max(0,i-6): i+6]
                if not any(re.search(r"na\.rm|complete\.cases|is\.na|drop_na|na\.omit", l)
                           for l in nearby):
                    _flag(i, "no_null_before_aggregation", "High",
                          "Aggregation with no NA handling (na.rm / na.omit / drop_na)")

        if re.search(r"""['"](/Users/|/home/|C:\\\\|~/|~/)""", line):
            _flag(i, "hardcoded_path", "Medium",
                  "Absolute/user-specific path — script will not run on another machine")

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
# Rendering
# ---------------------------------------------------------------------------

def render_flags(flags: list[CodeFlag], source: str, filename: str) -> str:
    source_lines = source.splitlines()
    flag_map: dict[int, list[CodeFlag]] = {}
    for f in flags:
        flag_map.setdefault(f.line, []).append(f)

    seen_types = sorted({f.flag_type for f in flags})

    summary_rows = ""
    for ft in seen_types:
        ft_flags = [f for f in flags if f.flag_type == ft]
        color = FLAG_COLORS.get(ft, "#eee")
        lines_str = ", ".join(str(f.line) for f in ft_flags)
        defn = FLAG_DEFINITIONS.get(ft, "")
        priority = "High" if ft in HIGH_FLAGS else "Medium"
        priority_style = (
            "background:#ff6b6b;color:#fff;" if priority == "High"
            else "background:#ffd43b;color:#333;"
        )
        summary_rows += (
            f'<tr>'
            f'<td style="background:{color};padding:4px 8px;white-space:nowrap;font-weight:bold;">'
            f'{ft.replace("_"," ")}</td>'
            f'<td style="padding:4px 8px;white-space:nowrap;">'
            f'<span style="{priority_style}padding:1px 6px;border-radius:3px;font-size:0.8em;">'
            f'{priority}</span></td>'
            f'<td style="padding:4px 8px;">{len(ft_flags)}</td>'
            f'<td style="padding:4px 8px;font-family:monospace;color:#666;white-space:nowrap;">{lines_str}</td>'
            f'<td style="padding:4px 8px;color:#444;font-size:0.88em;">{defn}</td>'
            f'</tr>'
        )

    code_rows = ""
    for i, line in enumerate(source_lines, start=1):
        line_flags = flag_map.get(i, [])
        safe_line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if line_flags:
            primary = sorted(line_flags, key=lambda f: PRIORITY_ORDER.get(f.priority, 9))[0]
            bg = FLAG_COLORS.get(primary.flag_type, "#fff9c4")
            annotation_parts = []
            for f in line_flags:
                fc = FLAG_COLORS.get(f.flag_type, "#eee")
                annotation_parts.append(
                    f'<div style="display:flex;align-items:center;gap:4px;margin-bottom:3px;white-space:nowrap;">'
                    f'<span style="flex-shrink:0;display:inline-block;width:9px;height:9px;'
                    f'border-radius:2px;background:{fc};"></span>'
                    f'<span style="font-size:0.78em;font-weight:bold;color:#333;">'
                    f'{f.flag_type.replace("_"," ")}</span>'
                    f'</div>'
                )
            annotation = "".join(annotation_parts)
            code_rows += (
                f'<tr style="background:{bg}44;">'
                f'<td style="padding:2px 8px;vertical-align:top;min-width:120px;max-width:200px;">{annotation}</td>'
                f'<td style="color:#888;padding:2px 8px;font-family:monospace;'
                f'user-select:none;min-width:36px;text-align:right;vertical-align:top;">{i}</td>'
                f'<td style="font-family:monospace;white-space:pre;padding:2px 4px 2px 8px;'
                f'vertical-align:top;border-left:3px solid {bg};">'
                f'{safe_line}</td>'
                f'</tr>'
            )
        else:
            code_rows += (
                f'<tr>'
                f'<td></td>'
                f'<td style="color:#ccc;padding:2px 8px;font-family:monospace;'
                f'user-select:none;min-width:36px;text-align:right;">{i}</td>'
                f'<td style="font-family:monospace;white-space:pre;color:#555;'
                f'padding:2px 12px;">{safe_line}</td>'
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
      <h3 style="font-size:1em;margin-bottom:6px;">Summary</h3>
      <table>
        <tr style="background:#f1f3f5;font-weight:bold;">
          <td style="padding:4px 8px;">Flag type</td>
          <td style="padding:4px 8px;">Priority</td>
          <td style="padding:4px 8px;">Count</td>
          <td style="padding:4px 8px;">Lines</td>
          <td style="padding:4px 8px;">Definition</td>
        </tr>
        {summary_rows}
      </table>
      <h3 style="font-size:1em;margin-bottom:6px;">Annotated source — <code>{filename}</code></h3>
      <table>
        <tr style="background:#f1f3f5;font-size:0.82em;color:#666;">
          <td style="padding:2px 8px;">Flags</td>
          <td style="padding:2px 8px;">Line</td>
          <td style="padding:2px 8px;">Code</td>
        </tr>
        {code_rows}
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
    page_title="Code Issues",
    page_icon="🔬",
    layout="wide",
)

st.title("Code Issues")
st.caption(
    "For the data reporter. Upload or paste a Python or R script — "
    "get back flagged lines with reasons. Static analysis only, does not run the code."
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

    high_types = [ft for ft in FLAG_COLORS if ft in HIGH_FLAGS]
    med_types  = [ft for ft in FLAG_COLORS if ft not in HIGH_FLAGS]

    st.markdown("**High priority**")
    for ft in sorted(high_types):
        st.checkbox(ft.replace("_", " "), value=True, key=f"cb_{ft}")

    st.markdown("**Medium priority**")
    for ft in sorted(med_types):
        st.checkbox(ft.replace("_", " "), value=True, key=f"cb_{ft}")

    st.divider()
    st.header("About")
    st.markdown(
        "Flags technical risk patterns in Python and R analysis scripts.\n\n"
        "**High** — things likely to produce wrong numbers silently\n\n"
        "**Medium** — things that may be wrong depending on context\n\n"
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
if st.session_state.get("l2a_cache_key") != cache_key:
    with st.spinner(f"Analyzing {filename}…"):
        flags = flag_code(source, filename)
    st.session_state["l2a_flags"]     = flags
    st.session_state["l2a_cache_key"] = cache_key
else:
    flags = st.session_state["l2a_flags"]

filtered = _filter_flags(flags)
n_high   = sum(1 for f in filtered if f.priority == "High")
n_med    = sum(1 for f in filtered if f.priority == "Medium")

col_h, col_m, _ = st.columns([1, 1, 6])
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

st.divider()

if not filtered:
    st.success("No flags match the current filter.")
else:
    st.markdown(render_flags(filtered, source, filename), unsafe_allow_html=True)
