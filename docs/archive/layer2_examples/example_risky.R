# Example R script — contains known data risk patterns for Layer 2 testing.

library(dplyr)
library(readr)

# Load without checking anything
df <- read_csv("evictions.csv")

# Just print head — no inspection
head(df)

# Second load — also no checks
df2 <- read.csv("names.csv")

# No dtype inspection
evictions <- df %>% filter(county == "Los Angeles")

# Cast ZIP to numeric — leading zeros lost
df$zip_num <- as.numeric(df$zip)

# Total row not excluded before groupby
by_county <- df %>%
  filter(county != "Total") %>%
  group_by(county) %>%
  summarise(total = sum(count))

# Mean with no range check and no median
avg_rent <- mean(df$rent)
print(paste("Average rent:", avg_rent))

# groupby without table() inspection
by_type <- df %>% group_by(housing_type) %>% summarise(n = n())

# Unexplained filter threshold
high_risk <- df %>% filter(rate > 0.15)

# Sentinel value filter — -999 may be missing data code
income_avg <- df %>%
  filter(income != -999) %>%
  summarise(mean_income = mean(income))

# Left join with no row count check
merged <- left_join(df, df2, by = "county")

# Join on string key (county_name is not an ID)
merged2 <- inner_join(df, df2, by = "county_name")

# Outer join with no anti-join check
left_result <- left_join(df, df2, by = "id")

# Hardcoded alpha threshold
result <- t.test(df$group_a, df$group_b)
if (result$p.value < 0.05) {
  print("Significant")
}

# Percentage with no denominator printed
pct <- sum(df$evicted) / nrow(df) * 100
cat(sprintf("Eviction rate: %.1f%%\n", pct))

# Aggregation with no na.rm
total_evictions <- sum(df$evictions)
