"""
Script: hw02_eda.py
Dataset: data/raw/fact_transactions.csv
Author: Sarah Lie
Generated: 2026-09-21

Performs exploratory data analysis on Wildcat Capital's transaction
history: loads the data, checks structure and quality, computes
summary statistics, group-level comparisons, and correlations, and
saves three charts plus a plain-text profile of the findings.
"""

import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# Make sure output folders exist
os.makedirs("hw02/charts", exist_ok=True)

profile_lines = []

def log(text=""):
    """Print to the terminal and also save the line for hw02_profile.txt."""
    print(text)
    profile_lines.append(str(text))

# ---------------------------------------------------------------
# 1. Load the data
# ---------------------------------------------------------------
df = pd.read_csv("data/raw/fact_transactions.csv")

# ---------------------------------------------------------------
# 2. Shape
# ---------------------------------------------------------------
log("=" * 60)
log("DATASET SHAPE")
log("=" * 60)
log(f"Rows: {df.shape[0]}, Columns: {df.shape[1]}")
log("")

# ---------------------------------------------------------------
# 3. Column names and data types
# ---------------------------------------------------------------
log("=" * 60)
log("COLUMN NAMES AND DATA TYPES")
log("=" * 60)
log(df.dtypes.to_string())
log("")

# ---------------------------------------------------------------
# 4. Missing values per column
# ---------------------------------------------------------------
log("=" * 60)
log("MISSING VALUES PER COLUMN")
log("=" * 60)
log(df.isnull().sum().to_string())
log("")

# ---------------------------------------------------------------
# 5. Descriptive statistics (numeric columns)
# ---------------------------------------------------------------
log("=" * 60)
log("DESCRIPTIVE STATISTICS (NUMERIC COLUMNS)")
log("=" * 60)
log(df.describe().to_string())
log("")

# ---------------------------------------------------------------
# 6. Value counts / percentages for txn_type
# ---------------------------------------------------------------
log("=" * 60)
log("TXN_TYPE VALUE COUNTS AND PERCENTAGES")
log("=" * 60)
txn_counts = df["txn_type"].value_counts()
txn_pct = df["txn_type"].value_counts(normalize=True) * 100
txn_summary = pd.DataFrame({"count": txn_counts, "percentage": txn_pct.round(2)})
log(txn_summary.to_string())
log("")

# ---------------------------------------------------------------
# 7. Unique clients, advisors, securities
# ---------------------------------------------------------------
log("=" * 60)
log("UNIQUE ENTITY COUNTS")
log("=" * 60)
log(f"Unique clients: {df['client_id'].nunique()}")
log(f"Unique advisors: {df['advisor_id'].nunique()}")
log(f"Unique securities: {df['security_id'].nunique()}")
log("")

# ---------------------------------------------------------------
# 8. Earliest / latest txn_date
# ---------------------------------------------------------------
log("=" * 60)
log("DATE RANGE")
log("=" * 60)
log(f"Earliest txn_date: {df['txn_date'].min()}")
log(f"Latest txn_date: {df['txn_date'].max()}")
log("")

# ---------------------------------------------------------------
# 9. Duplicate txn_id check
# ---------------------------------------------------------------
log("=" * 60)
log("DUPLICATE TXN_ID CHECK")
log("=" * 60)
dup_count = df["txn_id"].duplicated().sum()
log(f"Duplicate txn_id count: {dup_count}")
log("")

# ---------------------------------------------------------------
# 10. Mean, median, skewness of amount
# ---------------------------------------------------------------
log("=" * 60)
log("AMOUNT: MEAN, MEDIAN, SKEWNESS")
log("=" * 60)
amount_mean = df["amount"].mean()
amount_median = df["amount"].median()
amount_skew = df["amount"].skew()
log(f"Mean amount: {amount_mean:.2f}")
log(f"Median amount: {amount_median:.2f}")
log(f"Skewness of amount: {amount_skew:.2f}")
log("")

# ---------------------------------------------------------------
# 11. Group by txn_type: count, mean, median amount
# ---------------------------------------------------------------
log("=" * 60)
log("AMOUNT BY TXN_TYPE (GROUPED)")
log("=" * 60)
grouped = df.groupby("txn_type")["amount"].agg(["count", "mean", "median"]).round(2)
grouped = grouped.sort_values("mean", ascending=False)
log(grouped.to_string())
log("")

# ---------------------------------------------------------------
# 12. Correlation matrix (shares, price, amount)
# ---------------------------------------------------------------
log("=" * 60)
log("CORRELATION MATRIX (SHARES, PRICE, AMOUNT)")
log("=" * 60)
corr_matrix = df[["shares", "price", "amount"]].corr().round(2)
log(corr_matrix.to_string())
log("")

pairs = []
cols = corr_matrix.columns
for i in range(len(cols)):
    for j in range(i + 1, len(cols)):
        pairs.append((cols[i], cols[j], corr_matrix.iloc[i, j]))
pairs_sorted = sorted(pairs, key=lambda p: abs(p[2]), reverse=True)

log("Three strongest correlations:")
for a, b, val in pairs_sorted[:3]:
    log(f"  {a} - {b}: {val:.2f}")
log("")

# ---------------------------------------------------------------
# 13. Shares: min, max, negative count by txn_type
# ---------------------------------------------------------------
log("=" * 60)
log("SHARES: MIN, MAX, NEGATIVE COUNT BY TXN_TYPE")
log("=" * 60)
shares_summary = df.groupby("txn_type")["shares"].agg(
    min_shares="min",
    max_shares="max",
    negative_count=lambda x: (x < 0).sum()
)
log(shares_summary.to_string())
log("")

# ---------------------------------------------------------------
# 14. Shape check warning
# ---------------------------------------------------------------
if df.shape != (298772, 9):
    print(f"WARNING: Expected shape (298772, 9) but got {df.shape}.")
else:
    print("Shape check passed: (298772, 9) as expected.")

# ---------------------------------------------------------------
# 15. Charts
# ---------------------------------------------------------------
plt.figure(figsize=(10, 6))
plt.hist(df["amount"], bins=50, color="steelblue", edgecolor="white")
plt.axvline(amount_mean, color="red", linestyle="--", linewidth=2,
            label=f"Mean: ${amount_mean:,.2f}")
plt.axvline(amount_median, color="green", linestyle="--", linewidth=2,
            label=f"Median: ${amount_median:,.2f}")
plt.title("Distribution of Transaction Amount")
plt.xlabel("Amount ($)")
plt.ylabel("Frequency")
plt.legend()
plt.tight_layout()
plt.savefig("hw02/charts/hist_amount.png", dpi=150)
plt.close()

plt.figure(figsize=(10, 6))
sns.boxplot(data=df, x="amount", y="txn_type", orient="h")
plt.title("Amount Distribution by Transaction Type")
plt.xlabel("Amount ($)")
plt.ylabel("Transaction Type")
plt.tight_layout()
plt.savefig("hw02/charts/box_amount_by_type.png", dpi=150)
plt.close()

plt.figure(figsize=(10, 6))
sns.scatterplot(data=df, x="shares", y="amount", hue="txn_type", alpha=0.5, s=15)
plt.title("Shares vs. Amount by Transaction Type")
plt.xlabel("Shares")
plt.ylabel("Amount ($)")
plt.tight_layout()
plt.savefig("hw02/charts/scatter_shares_amount.png", dpi=150)
plt.close()

print("Charts saved to hw02/charts/")

# ---------------------------------------------------------------
# 16. Save plain-text profile (items 2-13)
# ---------------------------------------------------------------
with open("hw02/hw02_profile.txt", "w") as f:
    f.write("\n".join(profile_lines))

print("Profile summary saved to hw02/hw02_profile.txt")