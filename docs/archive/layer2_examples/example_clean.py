"""
Example Python script — clean practices. Should produce no High flags.
"""

import pandas as pd

# Load with encoding set
df = pd.read_csv("evictions.csv", encoding="utf-8")

# Shape, NA, and dtype checks immediately after load
print(f"Loaded {len(df)} rows, {df.shape[1]} columns")
print(df.isna().sum())
print(df.dtypes)

# Keep ZIP as string — no cast to int
df["zip"] = df["zip"].astype(str).str.zfill(5)
df = df.dropna(subset=["rent", "evictions"])  # drop rows missing key fields

# Value range check, then mean/median on clean data
print(df["rent"].min(), df["rent"].max())
print("Mean rent:", df["rent"].mean())
print("Median rent:", df["rent"].median())

# Category check before groupby, then aggregate on clean data
print(df["county"].value_counts())
by_county = df.dropna(subset=["evictions"]).groupby("county")["evictions"].sum()

# Exclude total rows explicitly via isin, not string equality
df_clean = df[~df["county"].str.lower().isin(["total", "subtotal"])]

# Null handling before aggregation
total_evictions = df_clean["evictions"].dropna().sum()

# Load second dataset — with checks
df2 = pd.read_csv("demographics.csv", encoding="utf-8")
print(f"df2: {len(df2)} rows")
print(df2.isna().sum())
print(df2.dtypes)

# Row count before and after merge
print(f"Before merge: {len(df_clean)} rows")
merged = df_clean.merge(df2, on="fips_code")  # numeric ID, not string
print(f"After merge: {len(merged)} rows")

# Anti-join check for unmatched rows
unmatched = df_clean[~df_clean["fips_code"].isin(df2["fips_code"])]
print(f"Unmatched rows: {len(unmatched)}")

# Percentage with denominator explicitly printed
n = len(merged)
evicted_n = merged["evicted"].dropna().sum()
pct = evicted_n / n * 100
print(f"Eviction rate: {pct:.1f}% (n={n})")
