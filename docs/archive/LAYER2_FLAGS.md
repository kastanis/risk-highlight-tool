# Layer 2 — Code Risk Flag Taxonomy

*Derived from the AP Data Checklist. Maps checklist items to detectable code patterns.*
*Covers Python (pandas) and R. SQL to follow.*

---

## Two output types

Layer 2 produces two distinct outputs with different audiences:

| Output type | What it surfaces | Audience |
|---|---|---|
| **Risk flags** | Things that may be wrong — missing checks, dangerous patterns, likely bugs | Data team technical reviewer |
| **Decision points** | Methodological choices that affect the story — not bugs, but judgment calls | Editor or senior reporter |

Risk flags say "something might be broken here."
Decision points say "a choice was made here — does the editor know about it?"

---

## What we can detect automatically vs. what needs human eyes

Some checklist items are detectable in code. Others require running the data.
This document covers only what static analysis of the code itself can flag.

---

## Flag taxonomy

### Import / Load checks

| Flag | What triggers it | Language | Priority | AP checklist ref |
|---|---|---|---|---|
| `no_shape_check` | Data loaded with no `len()`, `nrow()`, `.shape` check afterward | Python/R | High | length_match |
| `no_na_check` | No `.isna()`, `is.na()`, `complete.cases()` after load or merge | Python/R | High | check_nas |
| `no_dtype_check` | No `.dtypes`, `str()`, or `class()` call after load | Python/R | Medium | column types |
| `zip_as_numeric` | ZIP code column cast to int or float, or used in arithmetic | Python/R | High | leading_zero_check |
| `encoding_not_set` | `read_csv()` / `read.csv()` with no `encoding=` argument | Python/R | Medium | encoding_check |
| `excel_date_risk` | Reading `.xls` or `.xlsx` with date columns and no dtype override | Python | Medium | Excel date trap |

### Column / value checks

| Flag | What triggers it | Language | Priority | AP checklist ref |
|---|---|---|---|---|
| `no_value_range_check` | No `.min()` / `.max()` / `range()` on numeric columns before analysis | Python/R | Medium | min/max check |
| `no_category_check` | `.groupby()` or `group_by()` on a string column with no `.value_counts()` / `table()` before use | Python/R | Medium | category_check |
| `total_row_risk` | String "total" or "Total" present in a column used for aggregation | Python/R | High | total_check |
| `magic_number` | Unexplained numeric literal used as a filter threshold or divisor | Python/R | Medium | General |
| `sentinel_value_risk` | Numeric values like `-99`, `-999`, `9999` in a column used for averaging | Python/R | High | numeric codes as null |

### Joins

| Flag | What triggers it | Language | Priority | AP checklist ref |
|---|---|---|---|---|
| `no_join_count_check` | Merge/join with no row count check before and after | Python/R | High | count_rows |
| `join_on_string` | Merge/join key is a string/character column (not a numeric ID) | Python/R | Medium | joining on alpha |
| `no_unmatched_check` | Left/right/outer join with no check for unmatched rows (anti-join) | Python/R | High | Table A not in B |

### Statistical analysis

| Flag | What triggers it | Language | Priority | AP checklist ref |
|---|---|---|---|---|
| `hardcoded_threshold` | `p < 0.05`, `alpha = 0.05`, or bare `0.05` in a statistical test | Python/R | High | General |
| `percentage_without_base` | Percentage calculated with no `n=` or denominator printed | Python/R | High | "out of what?" |
| `small_denominator_risk` | Percentage where denominator variable is under 30 (if detectable) | Python/R | High | 1 in 3 = 33% |
| `mean_without_median` | `.mean()` / `mean()` with no `.median()` / `median()` nearby | Python/R | Medium | outlier check |
| `no_null_before_aggregation` | Aggregation (sum, mean, count) with no prior null handling | Python/R | High | missing data |
| `pct_change_without_base_note` | `pct_change()` or year-over-year calculation with no comment on base year | Python | Medium | time comparison |

### Geographies

| Flag | What triggers it | Language | Priority | AP checklist ref |
|---|---|---|---|---|
| `geocoding_unverified` | Call to geocoding library/API with no match rate check | Python/R | High | lat/long clusters |
| `projection_not_set` | Spatial join or distance calculation with no CRS/projection check | Python/R | High | projection check |
| `hardcoded_geo_count` | Hardcoded expected count of geographies (e.g. `== 50` for states) with no comment | Python/R | Medium | geography count |

---

## Decision points

Methodological choices a second person should explicitly verify. These are **not** bugs —
they are places where the analyst made a judgment call that affects the story outcome.

Detected automatically from code patterns. Rendered as a separate review checklist,
distinct from the risk flag report.

| Decision point | What triggers it | Question for reviewer |
|---|---|---|
| `filter_threshold` | Numeric comparison used to subset rows (`df["rate"] > 0.15`) | What is the basis for this threshold? Is it from a data definition, legal standard, or an analytic choice? |
| `unit_of_analysis` | `.groupby()` / `group_by()` call defining the level of aggregation | Was the right unit chosen? Would the finding change at a different level (e.g. county vs. state)? |
| `join_type` | `how="left"`, `how="outer"`, `how="inner"` in a merge | Who is excluded by this join type? Does the denominator change with a different join? |
| `stat_test_choice` | Call to `ttest_ind`, `mannwhitneyu`, `chi2_contingency`, `pearsonr`, etc. | Why this test? Were the assumptions (normality, independence, sample size) checked? |
| `exclusion_filter` | Row-level filter removing records from the analysis | Are excluded records documented? What share of the data do they represent? |
| `date_cutoff` | Hard-coded year or date range in a filter | Why this date boundary? Was it chosen before or after seeing the data? |
| `rate_denominator` | Division by a population, total, or count variable | What population is this rate normalized against? Is the denominator consistent across comparisons? |
| `time_period` | Year selection or `.dt.year` filtering | Which time period was chosen and why? Were patterns checked before and after this window? |
| `deduplication` | `.drop_duplicates()` or `.duplicated()` call | What was the deduplication key? Which duplicate was kept? How many records were removed? |
| `column_selection` | Double-bracket column subset (`df[["col1", "col2"]]`) | Were alternative columns considered? Is this the right metric for the question? |

---

## What we cannot detect statically (requires running the data)

These are important AP checklist items but need data to evaluate — not detectable from code alone:

- Whether row counts match source file
- Whether spot-checked rows match original
- Whether category values have casing/spelling issues
- Whether dates are transposed (MM/DD vs DD/MM)
- Whether 1/1/1900 sentinel dates are present
- Whether outliers are reasonable
- Whether geographic clusters indicate a lat/long error

These belong in the **AUDIT_TEMPLATE.md** and **VETTING_REQUEST.md** process, not in automated code analysis.

---

## Not in scope for Layer 2

- Correctness of the analysis (we can't know without running it)
- Whether the methodology is appropriate for the question
- Whether the story conclusion matches the data
- R package version conflicts
- SQL query performance
