"""
Example Python script — contains known data risk patterns for Layer 2 testing.
"""

import pandas as pd

# Load data — missing checks follow
df = pd.read_csv("evictions.csv")

# Immediately print head — no shape, na, dtype inspection
print(df.head())

# Second load — also missing checks
df2 = pd.read_csv("names.csv")

# Cast ZIP to int — leading zeros lost
df["zip"] = df["zip"].astype(int)

# Filter without dtype check
evictions = df[df["county"] == "Los Angeles"]

# Exclude total row but via fragile string match — Total row present
total = df[df["county"] != "Total"].groupby("county")["count"].sum()

# Mean with no range check and no median
avg_rent = df["rent"].mean()
print("Average rent:", avg_rent)

# groupby with no category inspection first
by_county = df.groupby("county")["evictions"].sum()

# Unexplained filter threshold
high_risk = df[df["rate"] > 0.15]

# Sentinel value filter
income_avg = df[df["income"] != -99]["income"].mean()

# Merge with no row count check
merged = df.merge(df2, on="county")

# Join on string key (county_name is not an ID)
merged2 = df.merge(df2, on="county_name")

# Left join with no unmatched check afterward
left = df.merge(df2, on="id", how="left")

# Hardcoded significance threshold
from scipy import stats
t, p = stats.ttest_ind(df["group_a"], df["group_b"])
if p < 0.05:
    print("Significant")

# Percentage with no denominator shown
pct = df["evicted"].sum() / len(df) * 100
print(f"Eviction rate: {pct:.1f}%")

# Aggregation with no null handling
total_evictions = df["evictions"].sum()

# pct_change with no base-year note
annual = df.groupby("year")["evictions"].sum().pct_change()
