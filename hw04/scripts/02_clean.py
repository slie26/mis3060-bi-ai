"""
HW4 Part C - 02_clean.py
Wildcat Capital: build a clean copy of the eight warehouse tables.

What this script does (and only this - it follows decision_log.md exactly):
  Step 1  Safety: strip leading/trailing whitespace from every text value (expect 0 changes)
  Step 2  Issue 1: add is_non_trading_day (0/1) to fact_transactions
  Step 3  Issue 2: add is_return_outlier (0/1) to fact_portfolio_snapshot (3x IQR on return_ytd)
  Step 4  Issue 5: verify (but do not change) is_post_departure_txn
  Step 5  Reconciliation checks that change nothing (fees, trade amounts and signs, alpha)
  Then    Re-measure the evidence for every "leave as is" issue (3, 4, 6-15),
          compare every count with decision_log.md, quarantine bookkeeping,
          write clean files and the audit trail.

Run from the repo root:   python hw04/scripts/02_clean.py
(Paths are built from this file's location, so it also works from anywhere else.)

Raw files are read as text (dtype=str, keep_default_na=False) and written back as
text with "\n" line endings. After writing, the script re-reads every clean file
and asserts that each original column holds exactly the same text as the raw file.
The values are identical; the file layout may differ slightly (for example,
Windows "\r\n" line endings in a raw file become "\n").

Needs pandas 1.5 or newer (for to_csv(lineterminator=...)).
"""

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths and settings
# ---------------------------------------------------------------------------
HW_DIR = Path(__file__).resolve().parent.parent          # .../mis3060-bi-ai/hw04
RAW_DIR = HW_DIR / "data" / "raw"
CLEAN_DIR = HW_DIR / "data" / "clean"
AUDIT_DIR = HW_DIR / "data" / "audit"

# Each table and its primary key (used for the audit trail and quarantine files)
TABLES = {
    "dim_advisor": "advisor_id",
    "dim_client": "client_id",
    "dim_date": "date_id",
    "dim_security": "security_id",
    "dim_benchmark": "benchmark_id",
    "fact_fees": "fee_id",
    "fact_portfolio_snapshot": "snapshot_id",
    "fact_transactions": "txn_id",
}

# Row and column counts printed on the assignment sheet (Issue 14 compares against these)
SHEET_ROWS = {
    "dim_advisor": 25, "dim_client": 2525, "dim_date": 1827, "dim_security": 500,
    "dim_benchmark": 8, "fact_fees": 122197, "fact_portfolio_snapshot": 129547,
    "fact_transactions": 298772,
}
SHEET_COLS = {
    "dim_advisor": 7, "dim_client": 14, "dim_date": 12, "dim_security": 8,
    "dim_benchmark": 4, "fact_fees": 8, "fact_portfolio_snapshot": 13,
    "fact_transactions": 9,
}
# Columns that arrived in the raw extract but are not on the assignment sheet
UPSTREAM_COLS = {
    "fact_transactions": ["is_post_departure_txn"],
    "fact_portfolio_snapshot": ["is_return_suspect"],
}

# Numbers quoted as evidence in decision_log.md. Every one is compared with
# what the script measures; any difference stops the script before files are written.
LOG_EVIDENCE = {
    # Issue 1
    "nontrading_all_types": 84946,
    "buy_sell_weekend": 40630,
    "buy_sell_saturday": 20481,
    "buy_sell_sunday": 20149,
    # Issues 2-4
    "outliers": 3977,
    "outlier_not_suspect": 576,
    "suspect_not_outlier": 474,
    "abs_return_gt_1": 977,
    "abs_return_gt_1_suspect": 977,
    # Issue 5
    "post_departure_rows": 2410,
    "post_departure_clients": 131,
    # Issues 6-9
    "dup_names": 3,
    "blank_sector": 219,
    "blank_expense_ratio": 281,
    "blank_security_rows": 101528,
    "certifications_none": 6,
    # Issue 10
    "fee_early_same_month": 858,
    "snap_early_same_month": 930,
    "fee_early_month_level": 0,
    "snap_early_month_level": 0,
    # Issue 11
    "fee_groups_mismatch": 28746,
    "fee_groups_both": 28746,
    "fee_groups_fee_only": 93451,
    # Issue 12
    "snap_months_no_fee": 7350,
    "snap_months_no_fee_joining": 72,
    "snap_months_no_fee_inactive": 362,
    # Issue 13
    "risk_unknown": 75,
}

IQR_K = 3.0          # outlier fence = Q1 - 3*IQR ... Q3 + 3*IQR
AMOUNT_TOL = 0.01    # dollars: stored amounts are rounded to cents
ALPHA_TOL = 0.0002   # returns are stored to ~4 decimals, so allow two rounding steps

TRUE_TOKENS = {"1", "1.0", "true", "t", "yes", "y"}
FALSE_TOKENS = {"0", "0.0", "false", "f", "no", "n"}

TRADE_TYPES = ["Buy", "Sell"]
PRICED_TYPES = ["Buy", "Sell", "Dividend"]          # amount = shares x price, amount > 0
CASH_TYPES = ["Deposit", "Withdrawal", "Advisory Fee"]  # no security involved

READ_ARGS = dict(dtype=str, keep_default_na=False, encoding="utf-8-sig")
WRITE_ARGS = dict(index=False, lineterminator="\n")

# ---------------------------------------------------------------------------
# Audit-trail containers
# ---------------------------------------------------------------------------
cleaning_log = []     # one dict per row of cleaning_log.csv
value_changes = []    # list of small DataFrames, concatenated at the end
log_mismatches = []   # every count that differs from decision_log.md


def log_step(table, issue, action, rows_affected, note):
    """Add one row to cleaning_log.csv and echo it to the screen."""
    cleaning_log.append({"table": table, "issue": issue, "action": action,
                         "rows_affected": int(rows_affected), "note": note})
    print(f"  LOG -> [{table}] {issue}: {action} ({int(rows_affected):,} rows)")


def record_flag(table, df, flag_col):
    """For a new flag column, record every row where the flag = 1 in value_changes.
    old_value is blank because the column did not exist before."""
    key = TABLES[table]
    hit_keys = df.loc[df[flag_col] == 1, key].values
    value_changes.append(pd.DataFrame({
        "table": table, "key_column": key, "key": hit_keys,
        "column": flag_col, "old_value": "", "new_value": "1"}))


def banner(text):
    print("\n" + "=" * 78 + f"\n{text}\n" + "=" * 78)


def compare_to_log(label, actual, log_key):
    """Print our count next to the decision-log evidence and remember any difference.
    All differences are asserted together before any file is written."""
    expected = LOG_EVIDENCE[log_key]
    actual = int(actual)
    if actual == expected:
        verdict = "matches decision log"
    else:
        verdict = "DIFFERS from decision log"
        log_mismatches.append(f"{label}: script {actual:,} vs log {expected:,}")
    print(f"  {label}: {actual:,} (log: {expected:,}) -> {verdict}")


# ---------------------------------------------------------------------------
# Small helpers for converting text on purpose (we never convert the stored
# columns; these are only used to *measure* things)
# ---------------------------------------------------------------------------
def to_flag(series, name):
    """Turn True/False or 1/0 text into 0/1 integers. Stops if anything else appears."""
    s = series.str.strip().str.lower()
    out = pd.Series(np.nan, index=series.index)
    out[s.isin(TRUE_TOKENS)] = 1
    out[s.isin(FALSE_TOKENS)] = 0
    bad = out.isna()
    assert not bad.any(), (f"{name}: {bad.sum()} values are not true/false or 1/0, "
                           f"e.g. {list(series[bad].unique()[:5])}")
    return out.astype(int)


def to_num(series):
    """Text -> number. Blank cells become NaN; nothing else is altered."""
    return pd.to_numeric(series.where(series.str.strip() != ""), errors="coerce")


def to_date(series):
    """Text -> date. Blank cells become NaT."""
    return pd.to_datetime(series.where(series.str.strip() != ""), errors="coerce")


def month_of(dates):
    """Date -> 'YYYY-MM' text, used for client x month comparisons."""
    return dates.dt.strftime("%Y-%m")


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ===========================================================================
# LOAD
# ===========================================================================
banner("LOAD raw tables as text")
raw, raw_hash = {}, {}
for t in TABLES:
    path = RAW_DIR / f"{t}.csv"
    assert path.exists(), f"Missing raw file: {path}"
    raw_hash[t] = file_hash(path)            # fingerprint so we can prove raw was not modified
    raw[t] = pd.read_csv(path, **READ_ARGS)
    print(f"  {t:<26} {len(raw[t]):>8,} rows  {raw[t].shape[1]:>3} cols")

# Work on copies. The raw DataFrames stay untouched for before/after comparisons.
clean = {t: df.copy() for t, df in raw.items()}
raw_rows = {t: len(df) for t, df in raw.items()}
raw_cols = {t: list(df.columns) for t, df in raw.items()}
added_flags = {t: [] for t in TABLES}       # new columns we add, in order


# ===========================================================================
# STEP 1 - Safety: strip leading/trailing whitespace from every text value
# ===========================================================================
banner("STEP 1  Safety: strip leading/trailing whitespace (expect 0 changes)")
total_ws = 0
for t, df in clean.items():
    key = TABLES[t]
    table_changes = 0
    for col in df.columns:
        stripped = df[col].str.strip()
        changed = df[col] != stripped
        n = int(changed.sum())
        if n:
            # Record exactly what changed before overwriting it
            value_changes.append(pd.DataFrame({
                "table": t, "key_column": key, "key": df.loc[changed, key].values,
                "column": col, "old_value": df.loc[changed, col].values,
                "new_value": stripped[changed].values}))
            df[col] = stripped
            table_changes += n
    # After-state: no value in the table has outer whitespace any more
    for col in df.columns:
        assert (df[col] == df[col].str.strip()).all(), f"{t}.{col} still has whitespace"
    print(f"  {t:<26} values changed: before-fix {table_changes:,} -> after-fix 0 remaining")
    log_step(t, "Safety: whitespace", "standardize (strip)", table_changes,
             "Leading/trailing whitespace stripped from all text values; audit expected none.")
    total_ws += table_changes

assert total_ws == 0, (
    f"{total_ws} values had outer whitespace. The audit said 0, so this is a new "
    "finding: add it to decision_log.md before relying on this fix.")
print(f"  Total whitespace changes: {total_ws} (as expected)")


# ===========================================================================
# STEP 2 - Issue 1: flag transactions dated on non-trading days
# ===========================================================================
banner("STEP 2  Issue 1: add is_non_trading_day to fact_transactions")
tx = clean["fact_transactions"]
dd = clean["dim_date"]

# Build a lookup: calendar date -> is_trading_day (0/1) from dim_date
dd_dates = to_date(dd["date"])
assert dd_dates.notna().all(), "Some dim_date.date values did not parse as dates"
assert dd_dates.is_unique, "dim_date.date is not unique - cannot use it as a lookup"
dd_trading = to_flag(dd["is_trading_day"], "dim_date.is_trading_day")
trading_lookup = pd.Series(dd_trading.values, index=dd_dates.values)

# Weekend according to dim_date.day_of_week (the independent check the log asks for)
dow = dd["day_of_week"].str.strip()
calendar_weekend = dd_dates.dt.dayofweek >= 5          # pandas: Mon=0 ... Sat=5, Sun=6
if dow.str.fullmatch(r"\d+").all():
    # Numeric day codes have no universal meaning (is 0 Monday or Sunday?),
    # so fall back to the calendar date itself.
    print("  day_of_week is numeric; weekend taken from the calendar date (Sat/Sun)")
    dim_weekend = calendar_weekend
else:
    dim_weekend = dow.str.lower().str[:3].isin(["sat", "sun"])
    disagree = int((dim_weekend != calendar_weekend).sum())
    print(f"  dim_date.day_of_week vs calendar: {disagree} disagreements")
weekend_lookup = pd.Series(dim_weekend.values, index=dd_dates.values)

# dim_date does not mark market holidays (Issue 15), so "non-trading" should equal
# "weekend". Show both mismatch directions; the count check below fails if either > 0.
holidays = int(((dd_trading == 0) & ~dim_weekend).sum())
weekend_trading = int(((dd_trading == 1) & dim_weekend).sum())
print(f"  dim_date: weekday non-trading days = {holidays}, weekend trading days = {weekend_trading}")

# Join each transaction date to dim_date
tx_dates = to_date(tx["txn_date"])
assert tx_dates.notna().all(), f"{tx_dates.isna().sum()} txn_date values did not parse"
tx_trading = tx_dates.map(trading_lookup)
unmatched = int(tx_trading.isna().sum())
assert unmatched == 0, f"{unmatched} txn_date values are not in dim_date (RI problem not in the log)"

before_cols = len(tx.columns)
tx["is_non_trading_day"] = (tx_trading == 0).astype(int)
added_flags["fact_transactions"].append("is_non_trading_day")

n_flag = int(tx["is_non_trading_day"].sum())
tx_weekend = tx_dates.map(weekend_lookup).astype(bool)
n_weekend = int(tx_weekend.sum())
is_trade = tx["txn_type"].isin(TRADE_TYPES)
n_trade_flag = int(tx.loc[is_trade, "is_non_trading_day"].sum())
print(f"  Columns: before {before_cols} -> after {len(tx.columns)}")
print(f"  Rows on a weekend per dim_date.day_of_week: {n_weekend:,}")
compare_to_log("All txn types flagged", n_flag, "nontrading_all_types")
compare_to_log("Buy/Sell rows flagged", n_trade_flag, "buy_sell_weekend")
compare_to_log("...Buy/Sell on Saturday", (is_trade & (tx_dates.dt.dayofweek == 5)).sum(),
               "buy_sell_saturday")
compare_to_log("...Buy/Sell on Sunday", (is_trade & (tx_dates.dt.dayofweek == 6)).sum(),
               "buy_sell_sunday")
print("  Flagged rows by txn_type:")
print(tx.groupby("txn_type")["is_non_trading_day"].agg(["sum", "count"]).to_string())

# After-state asserts
assert set(tx["is_non_trading_day"].unique()) <= {0, 1}
assert tx.columns[-1] == "is_non_trading_day"
assert n_flag == n_weekend, "Non-trading-day count does not equal the weekend count"
assert (tx["is_non_trading_day"].astype(bool) == tx_weekend).all(), \
    "Same totals, but flagged rows are not exactly the weekend rows"

record_flag("fact_transactions", tx, "is_non_trading_day")
log_step("fact_transactions", "Issue 1: Buys/Sells on non-trading days", "flag", n_flag,
         f"Added is_non_trading_day = 1 where txn_date is a non-trading day in dim_date "
         f"({n_flag:,} rows, all txn types; {n_trade_flag:,} Buy/Sell). Equals the weekend count "
         f"from dim_date.day_of_week, so the flag means weekend-dated (see Issue 15). Dates not moved.")


# ===========================================================================
# STEP 3 - Issue 2: flag extreme returns with a 3x IQR rule
# ===========================================================================
banner("STEP 3  Issue 2: add is_return_outlier to fact_portfolio_snapshot")
snap = clean["fact_portfolio_snapshot"]
suspect_before = snap["is_return_suspect"].copy()      # must not change

ret = to_num(snap["return_ytd"])
print(f"  return_ytd blank/unparseable: {int(ret.isna().sum())} (never flagged)")
q1, q3 = ret.quantile(0.25), ret.quantile(0.75)
iqr = q3 - q1
low, high = q1 - IQR_K * iqr, q3 + IQR_K * iqr
print(f"  Q1={q1:.4f}  Q3={q3:.4f}  IQR={iqr:.4f}  fences: [{low:.4f}, {high:.4f}]")

outlier = (ret < low) | (ret > high)                   # NaN compares as False
before_cols = len(snap.columns)
snap["is_return_outlier"] = outlier.astype(int)
added_flags["fact_portfolio_snapshot"].append("is_return_outlier")

suspect = to_flag(snap["is_return_suspect"], "is_return_suspect")
n_out = int(snap["is_return_outlier"].sum())
out_and_suspect = int(((snap["is_return_outlier"] == 1) & (suspect == 1)).sum())
out_not_suspect = int(((snap["is_return_outlier"] == 1) & (suspect == 0)).sum())
suspect_not_out = int(((snap["is_return_outlier"] == 0) & (suspect == 1)).sum())

print(f"  Columns: before {before_cols} -> after {len(snap.columns)}")
compare_to_log("Outliers flagged", n_out, "outliers")
print(f"  ...already flagged is_return_suspect = 1: {out_and_suspect:,}")
compare_to_log("...NOT already flagged as suspect", out_not_suspect, "outlier_not_suspect")
compare_to_log("Suspect but not an outlier (Issue 3)", suspect_not_out, "suspect_not_outlier")

# After-state asserts
assert snap["is_return_suspect"].equals(suspect_before), "is_return_suspect was changed!"
assert set(snap["is_return_outlier"].unique()) <= {0, 1}
assert snap.columns[-1] == "is_return_outlier"
assert out_and_suspect + out_not_suspect == n_out
flagged_ret = ret[snap["is_return_outlier"] == 1]
assert ((flagged_ret < low) | (flagged_ret > high)).all(), "A flagged row is inside the fences"
unflagged_ret = ret[snap["is_return_outlier"] == 0].dropna()
assert unflagged_ret.between(low, high).all(), "An unflagged row is outside the fences"

record_flag("fact_portfolio_snapshot", snap, "is_return_outlier")
log_step("fact_portfolio_snapshot", "Issue 2: Extreme returns not flagged", "flag", n_out,
         f"Added is_return_outlier = 1 where return_ytd is outside 3xIQR fences "
         f"[{low:.4f}, {high:.4f}]: {n_out:,} rows, {out_not_suspect:,} not already suspect. "
         f"is_return_suspect unchanged.")


# ===========================================================================
# STEP 4 - Issue 5: verify the existing post-departure flag (no change)
# ===========================================================================
banner("STEP 4  Issue 5: verify is_post_departure_txn (keep unchanged)")
dc = clean["dim_client"]
post_before = tx["is_post_departure_txn"].copy()

assert dc["client_id"].is_unique, "dim_client.client_id is not unique"
client_active = pd.Series(to_flag(dc["is_active"], "dim_client.is_active").values,
                          index=dc["client_id"].values)
post = to_flag(tx["is_post_departure_txn"], "is_post_departure_txn")
flagged = tx[post == 1]
flagged_dates = tx_dates[post == 1]
flagged_active = flagged["client_id"].map(client_active)

# Each client's last snapshot month (snapshots are dated the 1st of the month they cover)
snap_dates = to_date(snap["snapshot_date"])
assert snap_dates.notna().all(), "Some snapshot_date values did not parse"
snap_month = month_of(snap_dates)
last_snap_month = snap_month.groupby(snap["client_id"]).max()
flagged_last = flagged["client_id"].map(last_snap_month)
flagged_month = month_of(flagged_dates)

n_post = len(flagged)
n_post_clients = flagged["client_id"].nunique()
n_after_last = int((flagged_month > flagged_last).sum())     # 'YYYY-MM' text sorts like dates
n_in_2023 = int((flagged_dates.dt.year == 2023).sum())
compare_to_log("Rows flagged post-departure", n_post, "post_departure_rows")
compare_to_log("Distinct clients", n_post_clients, "post_departure_clients")
print(f"  Flagged rows whose client is missing from dim_client: {int(flagged_active.isna().sum())}")
print(f"  Flagged rows whose client is_active = True: {int((flagged_active == 1).sum())}")
print(f"  Flagged rows whose client has no snapshot at all: {int(flagged_last.isna().sum())}")
print(f"  Flagged rows dated in a month after the client's last snapshot month: "
      f"{n_after_last:,} of {n_post:,}")
print(f"  Flagged rows dated in 2023: {n_in_2023:,} of {n_post:,}")

# After-state asserts: flag untouched, and every flagged row is confirmed three ways
assert tx["is_post_departure_txn"].equals(post_before), "is_post_departure_txn was changed!"
assert flagged_active.notna().all(), "A flagged row points to a client not in dim_client"
assert (flagged_active == 0).all(), "A post-departure row belongs to an ACTIVE client"
assert flagged_last.notna().all(), "A flagged row's client has no snapshots to compare with"
assert n_after_last == n_post, "A post-departure row is dated in or before the last snapshot month"
assert n_in_2023 == n_post, "A post-departure row is not dated in 2023"

log_step("fact_transactions", "Issue 5: Post-departure transactions", "flag (kept, verified)",
         n_post, f"Existing flag kept unchanged; rows kept. Verified: all {n_post:,} flagged rows "
         f"({n_post_clients} clients) belong to clients with is_active = False, are dated after "
         f"the client's last snapshot month, and are dated in 2023.")


# ===========================================================================
# STEP 5 - Reconciliation checks (nothing is changed; the script stops if one fails)
# ===========================================================================
banner("STEP 5  Reconciliation checks (no changes)")

# 5a. Fees: amount = aum_basis x bps_charged / 10,000 / 12
fees = clean["fact_fees"]
f_amt, f_aum, f_bps = to_num(fees["amount"]), to_num(fees["aum_basis"]), to_num(fees["bps_charged"])
ok_rows = f_amt.notna() & f_aum.notna() & f_bps.notna()
f_diff = (f_amt - f_aum * f_bps / 10000 / 12).abs()[ok_rows]
f_fail = int((f_diff > AMOUNT_TOL).sum())
print(f"  5a fact_fees: {int(ok_rows.sum()):,} rows checked, {int((~ok_rows).sum())} skipped (blank), "
      f"max diff ${f_diff.max():.4f}, failures {f_fail}")
assert f_fail == 0, "fact_fees.amount does not equal aum_basis x bps / 10000 / 12"
log_step("fact_fees", "Reconciliation: fee formula", "verified (no change)", int(ok_rows.sum()),
         f"amount = aum_basis x bps_charged / 10000 / 12 within ${AMOUNT_TOL} on every row "
         f"(max diff ${f_diff.max():.4f}). Supports Issue 11: fact_fees is the fee authority.")

# 5b. Transactions: amount = shares x price for Buy / Sell / Dividend, and amount > 0.
# The sign rule is checked first; the formula then compares sizes (absolute values),
# so a share count stored as negative on Sells would not count as a formula failure.
priced = tx["txn_type"].isin(PRICED_TYPES)
t_amt, t_sh, t_px = to_num(tx["amount"]), to_num(tx["shares"]), to_num(tx["price"])
ok_rows = priced & t_amt.notna() & t_sh.notna() & t_px.notna()

not_positive = ok_rows & (t_amt <= 0)
n_not_positive = int(not_positive.sum())
print(f"  5b sign rule: Buy/Sell/Dividend rows with amount <= 0: {n_not_positive}")
if n_not_positive:
    print(tx.loc[not_positive, "txn_type"].value_counts().to_string())
assert n_not_positive == 0, "A Buy/Sell/Dividend amount is zero or negative"

t_diff = (t_amt.abs() - (t_sh * t_px).abs()).abs()[ok_rows]
t_fail = int((t_diff > AMOUNT_TOL).sum())
print(f"  5b formula: {int(ok_rows.sum()):,} Buy/Sell/Dividend rows checked, "
      f"{int((priced & ~ok_rows).sum())} skipped (blank), max diff ${t_diff.max():.4f}, failures {t_fail}")
if t_fail:
    print("     worst rows:")
    print(tx.loc[t_diff.sort_values(ascending=False).index[:5],
                 ["txn_id", "txn_type", "shares", "price", "amount"]].to_string())
assert t_fail == 0, "fact_transactions.amount does not equal shares x price"
log_step("fact_transactions", "Reconciliation: amount = shares x price, amount > 0",
         "verified (no change)", int(ok_rows.sum()),
         f"All Buy/Sell/Dividend amounts > 0 and equal to shares x price within ${AMOUNT_TOL} "
         f"(max diff ${t_diff.max():.4f}).")

# 5c. Snapshots: active_alpha_ytd = return_ytd - benchmark_return_ytd
s_bench, s_alpha = to_num(snap["benchmark_return_ytd"]), to_num(snap["active_alpha_ytd"])
ok_rows = ret.notna() & s_bench.notna() & s_alpha.notna()
a_diff = (s_alpha - (ret - s_bench)).abs()[ok_rows]
a_fail_mask = a_diff > ALPHA_TOL
a_fail = int(a_fail_mask.sum())
print(f"  5c fact_portfolio_snapshot: {int(ok_rows.sum()):,} rows checked, "
      f"{int((~ok_rows).sum())} skipped (blank), max diff {a_diff.max():.6f}, failures {a_fail}")
if a_fail:
    print(f"     failures that are is_return_suspect = 1: "
          f"{int((suspect[a_fail_mask[a_fail_mask].index] == 1).sum())}")
assert a_fail == 0, "active_alpha_ytd does not equal return_ytd - benchmark_return_ytd"
log_step("fact_portfolio_snapshot", "Reconciliation: alpha formula", "verified (no change)",
         int(ok_rows.sum()), f"active_alpha_ytd = return_ytd - benchmark_return_ytd within "
         f"{ALPHA_TOL} on every row (max diff {a_diff.max():.6f}).")


# ===========================================================================
# "LEAVE AS IS" ISSUES - nothing changes; re-measure the evidence for the log
# ===========================================================================
banner("LEFT AS IS  Issues 3, 4, 6-15: no values changed, evidence re-measured")

# Issue 3 - suspect but not an outlier (counted in Step 3)
log_step("fact_portfolio_snapshot", "Issue 3: Returns flagged but not extreme", "left as is",
         suspect_not_out, f"{suspect_not_out:,} rows have is_return_suspect = 1 but pass 3xIQR. "
         "Original flag likely uses a different test (jumps, near -100%); not proven wrong.")

# Issue 4 - |return_ytd| > 1, all already suspect
big = ret.abs() > 1
n_big, n_big_suspect = int(big.sum()), int((big & (suspect == 1)).sum())
compare_to_log("Issue 4 |return_ytd| > 1", n_big, "abs_return_gt_1")
compare_to_log("...of which already is_return_suspect = 1", n_big_suspect, "abs_return_gt_1_suspect")
log_step("fact_portfolio_snapshot", "Issue 4: Returns above 100%", "left as is", n_big,
         f"{n_big:,} rows with |return_ytd| > 1, {n_big_suspect:,} already suspect. Divide-by-100 "
         "test failed (fits neighbouring months 0.7% of the time), so not a scale error; "
         "true value cannot be recovered.")

# Issue 6 - security names shared by two IDs
sec = clean["dim_security"]
name_counts = sec["name"].value_counts()
dup_names = name_counts[name_counts > 1]
n_dup_rows = int(sec["name"].isin(dup_names.index).sum())
compare_to_log("Issue 6 names used by more than one security", len(dup_names), "dup_names")
print(f"  ...{n_dup_rows} rows; tickers unique: {sec['ticker'].is_unique}")
log_step("dim_security", "Issue 6: Securities sharing a name", "left as is", n_dup_rows,
         f"{len(dup_names)} names appear twice ({', '.join(dup_names.index)}), each pair with a "
         f"different ticker; all tickers unique = {sec['ticker'].is_unique}. Different securities.")

# Issue 7 - blank sector / expense ratio are 'does not apply'
blank_sector = sec["sector"] == ""
blank_er = sec["expense_ratio_bps"] == ""
non_equity = sec["asset_class"] != "Equity"
non_etf = to_flag(sec["is_etf"], "dim_security.is_etf") == 0
compare_to_log("Issue 7 blank sector", blank_sector.sum(), "blank_sector")
print(f"  ...blank sector rows == non-equity rows: {(blank_sector == non_equity).all()}")
compare_to_log("Issue 7 blank expense_ratio_bps", blank_er.sum(), "blank_expense_ratio")
print(f"  ...blank expense ratio rows == non-ETF rows: {(blank_er == non_etf).all()}")
log_step("dim_security", "Issue 7: Blank sector and expense ratio", "left as is",
         int(blank_sector.sum() + blank_er.sum()),
         f"sector blank in {int(blank_sector.sum())} rows = non-equity rows "
         f"({(blank_sector == non_equity).all()}); expense_ratio_bps blank in {int(blank_er.sum())} "
         f"rows = non-ETF rows ({(blank_er == non_etf).all()}). Blank means 'does not apply'.")

# Issue 8 - blank security fields on cash transactions. Checked in both directions:
#   (a) every row with a blank security_id is a cash type
#   (b) no cash-type row has a security_id
is_cash = tx["txn_type"].isin(CASH_TYPES)
blank_sec = tx["security_id"] == ""
no_sec = blank_sec & (tx["shares"] == "") & (tx["price"] == "")
blank_not_cash = int((blank_sec & ~is_cash).sum())
cash_with_sec = int((is_cash & ~blank_sec).sum())
compare_to_log("Issue 8 rows with no security/shares/price", no_sec.sum(), "blank_security_rows")
print(f"  ...blank security_id rows that are NOT a cash type: {blank_not_cash}")
print(f"  ...cash-type rows that DO have a security_id: {cash_with_sec}")
assert blank_not_cash == 0, "A non-cash transaction is missing its security_id"
assert cash_with_sec == 0, "A cash transaction (Deposit/Withdrawal/Advisory Fee) has a security_id"
log_step("fact_transactions", "Issue 8: Blank security fields on cash rows", "left as is",
         int(no_sec.sum()), f"{int(no_sec.sum()):,} rows blank in security_id/shares/price. Verified "
         f"both ways: every blank-security row is {'/'.join(CASH_TYPES)}, and no cash row has a "
         "security_id. Legitimate.")

# Issue 9 - certifications = "None" is a real answer
n_none = int((clean["dim_advisor"]["certifications"] == "None").sum())
compare_to_log("Issue 9 certifications = 'None'", n_none, "certifications_none")
log_step("dim_advisor", "Issue 9: certifications = 'None'", "left as is", n_none,
         f"{n_none} advisors hold no certifications; 'None' is a real value, kept as text.")

# Shared lookups for Issues 10-12: each client's start date and start month
client_since = to_date(dc["client_since"])
assert client_since.notna().all(), "Some client_since values did not parse"
since_lookup = pd.Series(client_since.values, index=dc["client_id"].values)
since_month_lookup = pd.Series(month_of(client_since).values, index=dc["client_id"].values)
fee_dates = to_date(fees["fee_date"])
assert fee_dates.notna().all(), "Some fee_date values did not parse"
fee_month = month_of(fee_dates)

# Issue 10 - dated before client_since by day, but in the same month (dating convention)
def early_counts(dates, months, client_ids):
    """Rows dated before client_since at day level but not at month level,
    and rows dated before client_since at month level (expected 0)."""
    day_before = dates < client_ids.map(since_lookup)
    month_before = months < client_ids.map(since_month_lookup)
    return int((day_before & ~month_before).sum()), int(month_before.sum())

fee_early, fee_early_month = early_counts(fee_dates, fee_month, fees["client_id"])
snap_early, snap_early_month = early_counts(snap_dates, snap_month, snap["client_id"])
compare_to_log("Issue 10 fee rows before client_since, same month", fee_early, "fee_early_same_month")
compare_to_log("Issue 10 snapshot rows before client_since, same month", snap_early,
               "snap_early_same_month")
compare_to_log("Issue 10 fee rows before client_since month", fee_early_month, "fee_early_month_level")
compare_to_log("Issue 10 snapshot rows before client_since month", snap_early_month,
               "snap_early_month_level")
log_step("fact_fees / fact_portfolio_snapshot", "Issue 10: Dated before client_since", "left as is",
         fee_early + snap_early,
         f"{fee_early:,} fee + {snap_early:,} snapshot rows precede client_since by days but fall in "
         f"the client's joining month; month-level violations: {fee_early_month} fee, "
         f"{snap_early_month} snapshot. Records are dated the 1st of the month they cover.")

# Issue 11 - fact_fees total vs Advisory Fee debits, per client x month.
# Debits are compared as absolute values so a negative sign alone is not a mismatch.
fee_cm = (pd.DataFrame({"client_id": fees["client_id"], "month": fee_month, "fee_amt": f_amt})
          .groupby(["client_id", "month"], as_index=False)["fee_amt"].sum())
adv = tx["txn_type"] == "Advisory Fee"
adv_cm = (pd.DataFrame({"client_id": tx.loc[adv, "client_id"], "month": month_of(tx_dates[adv]),
                        "adv_amt": t_amt[adv].abs()})
          .groupby(["client_id", "month"], as_index=False)["adv_amt"].sum())
fee_vs_adv = fee_cm.merge(adv_cm, on=["client_id", "month"], how="outer", indicator=True)
both_sides = fee_vs_adv[fee_vs_adv["_merge"] == "both"]
n_both = len(both_sides)
n_fee_mismatch = int(((both_sides["fee_amt"] - both_sides["adv_amt"]).abs() > AMOUNT_TOL).sum())
n_fee_only = int((fee_vs_adv["_merge"] == "left_only").sum())
compare_to_log("Issue 11 client-months on both sides", n_both, "fee_groups_both")
compare_to_log("Issue 11 ...where fee total != Advisory Fee debits", n_fee_mismatch,
               "fee_groups_mismatch")
compare_to_log("Issue 11 client-months only in fact_fees", n_fee_only, "fee_groups_fee_only")
log_step("fact_fees / fact_transactions", "Issue 11: Fees vs transaction fee debits", "left as is",
         n_fee_mismatch,
         f"{n_fee_mismatch:,} of {n_both:,} client-months present in both tables have a fact_fees "
         f"total different from the Advisory Fee debits; {n_fee_only:,} client-months only in "
         "fact_fees. Tables record fees differently; fact_fees is internally consistent "
         "(Step 5a) and is the authority.")

# Issue 12 - snapshot client-months with no fee row
snap_cm = pd.DataFrame({"client_id": snap["client_id"], "month": snap_month}).drop_duplicates()
snap_vs_fee = snap_cm.merge(fee_cm[["client_id", "month"]], on=["client_id", "month"],
                            how="left", indicator=True)
no_fee = snap_vs_fee[snap_vs_fee["_merge"] == "left_only"]
n_no_fee = len(no_fee)
n_no_fee_joining = int((no_fee["month"] == no_fee["client_id"].map(since_month_lookup)).sum())
n_no_fee_inactive = int((no_fee["client_id"].map(client_active) == 0).sum())
compare_to_log("Issue 12 snapshot client-months with no fee", n_no_fee, "snap_months_no_fee")
compare_to_log("Issue 12 ...in the client's joining month", n_no_fee_joining,
               "snap_months_no_fee_joining")
compare_to_log("Issue 12 ...belonging to inactive clients", n_no_fee_inactive,
               "snap_months_no_fee_inactive")
log_step("fact_portfolio_snapshot / fact_fees", "Issue 12: Snapshot months with no fee", "left as is",
         n_no_fee,
         f"{n_no_fee:,} client-months have a snapshot but no fee row ({n_no_fee_joining} are the "
         f"client's joining month; {n_no_fee_inactive} client-months belong to inactive clients). "
         "Could be waivers/partial months; filling would invent revenue.")

# Issue 13 - unknown risk profile
n_unknown = int((dc["risk_profile"] == "Unknown").sum())
compare_to_log("Issue 13 risk_profile = 'Unknown'", n_unknown, "risk_unknown")
log_step("dim_client", "Issue 13: Unknown risk profile", "left as is", n_unknown,
         f"{n_unknown} clients 'Unknown'. Benchmark suggests Balanced, but risk profile is a "
         "suitability record from the client questionnaire; not inferred.")

# Issue 14 - counts differ from the assignment sheet
for t in ["dim_client", "fact_transactions", "fact_portfolio_snapshot"]:
    row_diff = raw_rows[t] - SHEET_ROWS[t]
    extra = UPSTREAM_COLS.get(t, [])
    # The only extra columns must be the documented upstream flags
    assert len(raw_cols[t]) == SHEET_COLS[t] + len(extra), f"{t}: unexpected column count"
    assert all(c in raw_cols[t] for c in extra), f"{t}: expected upstream column missing"
    print(f"  Issue 14 {t}: rows raw {raw_rows[t]:,} vs sheet {SHEET_ROWS[t]:,} ({row_diff:+,}); "
          f"cols raw {len(raw_cols[t])} vs sheet {SHEET_COLS[t]}")
    rows_part = (f"Row count matches the sheet ({raw_rows[t]:,})." if row_diff == 0 else
                 f"Raw has {raw_rows[t]:,} rows vs sheet {SHEET_ROWS[t]:,} ({row_diff:+,}); "
                 "removed upstream and not available.")
    cols_part = (f" Only column added upstream: {', '.join(extra)}." if extra else
                 " Columns match the sheet.")
    log_step(t, "Issue 14: Counts differ from assignment sheet", "left as is", abs(row_diff),
             rows_part + cols_part + " Extract was partly cleaned upstream; instructor confirmed files.")

# Issue 15 - dim_date marks only weekends as non-trading (no market holidays).
# Measured with the fixed-date US market holidays (Jan 1, Jul 4, Dec 25) that fall on a weekday.
fixed_holiday = (((dd_dates.dt.month == 1) & (dd_dates.dt.day == 1)) |
                 ((dd_dates.dt.month == 7) & (dd_dates.dt.day == 4)) |
                 ((dd_dates.dt.month == 12) & (dd_dates.dt.day == 25))) & ~calendar_weekend
n_holiday_trading = int((fixed_holiday & (dd_trading == 1)).sum())
jan1_2020 = dd_trading[dd_dates == pd.Timestamp("2020-01-01")]
print(f"  Issue 15 weekday Jan 1 / Jul 4 / Dec 25 marked is_trading_day = 1: "
      f"{n_holiday_trading} of {int(fixed_holiday.sum())}")
print(f"  ...2020-01-01 is_trading_day = {jan1_2020.iloc[0] if len(jan1_2020) else 'not in dim_date'}")
assert holidays == 0, "dim_date does mark some weekdays as non-trading - Issue 15 no longer holds"
log_step("dim_date", "Issue 15: Market holidays not marked", "left as is", n_holiday_trading,
         f"dim_date marks 0 weekdays as non-trading; {n_holiday_trading} weekday Jan 1/Jul 4/Dec 25 "
         "dates have is_trading_day = 1 (e.g. 2020-01-01). is_non_trading_day therefore means "
         "weekend-dated only. Holiday calendar not added: it is not in the source data.")


# ===========================================================================
# QUARANTINE - machinery is in place; no decision removes rows this time
# ===========================================================================
banner("QUARANTINE  raw rows = clean rows + quarantined rows")
quarantined = {t: pd.DataFrame(columns=list(df.columns) + ["quarantine_issue", "quarantine_reason"])
               for t, df in clean.items()}


def quarantine(table, mask, issue, reason):
    """Move the rows where mask is True out of the clean table into its quarantine set.
    Every column is kept, plus the issue and reason, so each row can be traced back."""
    df = clean[table]
    moved = df[mask].copy()
    moved["quarantine_issue"] = issue
    moved["quarantine_reason"] = reason
    quarantined[table] = pd.concat([quarantined[table], moved], ignore_index=True)
    clean[table] = df[~mask].copy()
    log_step(table, issue, "quarantine", len(moved), reason)
    return len(moved)


# (No quarantine() calls: decision_log.md removes no rows.)

for t in TABLES:
    c, q = len(clean[t]), len(quarantined[t])
    print(f"  {t:<26} raw {raw_rows[t]:>8,} = clean {c:>8,} + quarantined {q:>3,}  -> {raw_rows[t] == c + q}")
    assert raw_rows[t] == c + q, f"{t}: rows lost or created"


# ===========================================================================
# COMPARE WITH DECISION LOG - stop before writing anything if a count differs
# ===========================================================================
banner("DECISION LOG  every measured count must match the evidence in decision_log.md")
print(f"  Counts compared: {len(LOG_EVIDENCE)} evidence values; differences: {len(log_mismatches)}")
for m in log_mismatches:
    print(f"  DIFFERS: {m}")
assert not log_mismatches, (
    f"{len(log_mismatches)} count(s) differ from decision_log.md (listed above). Investigate, "
    "then update the log or the script before writing clean files.")


# ===========================================================================
# FINAL CHECKS AND WRITE
# ===========================================================================
banner("WRITE clean tables and audit trail")

# Same columns as raw, in the same order, with any new flags at the end
for t, df in clean.items():
    expected_cols = raw_cols[t] + added_flags[t]
    assert list(df.columns) == expected_cols, f"{t}: unexpected columns {list(df.columns)}"
    assert df[raw_cols[t]].equals(raw[t].loc[df.index, raw_cols[t]]), f"{t}: an original value changed"

CLEAN_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

for t, df in clean.items():
    out_path = CLEAN_DIR / f"{t}.csv"
    df.to_csv(out_path, **WRITE_ARGS)
    quarantined[t].to_csv(AUDIT_DIR / f"quarantine_{t}.csv", **WRITE_ARGS)

    # Re-read what was actually written and prove the original columns are identical
    # text to raw, and the new flags are only "0"/"1".
    back = pd.read_csv(out_path, **READ_ARGS)
    assert list(back.columns) == raw_cols[t] + added_flags[t], f"{t}: written columns differ"
    expected_raw = raw[t].loc[df.index, raw_cols[t]].reset_index(drop=True)
    assert back[raw_cols[t]].equals(expected_raw), f"{t}: written file differs from raw"
    for f in added_flags[t]:
        assert back[f].isin(["0", "1"]).all(), f"{t}.{f}: written flag is not 0/1"
    print(f"  wrote clean/{t}.csv ({len(df):,} rows, re-read: original columns identical to raw) "
          f"and audit/quarantine_{t}.csv ({len(quarantined[t])} rows)")

log_df = pd.DataFrame(cleaning_log, columns=["table", "issue", "action", "rows_affected", "note"])
log_df.to_csv(AUDIT_DIR / "cleaning_log.csv", **WRITE_ARGS)

vc_cols = ["table", "key_column", "key", "column", "old_value", "new_value"]
vc_df = pd.concat(value_changes, ignore_index=True)[vc_cols] if value_changes else pd.DataFrame(columns=vc_cols)
vc_df.to_csv(AUDIT_DIR / "value_changes.csv", **WRITE_ARGS)

# value_changes must match the flags exactly
for t, flags in added_flags.items():
    for f in flags:
        assert (vc_df["column"] == f).sum() == int(clean[t][f].sum()), f"value_changes wrong for {f}"

# Every decision-log issue (1-15) has a cleaning_log row
for i in range(1, 16):
    assert log_df["issue"].str.startswith(f"Issue {i}:").any(), f"No cleaning_log row for Issue {i}"

# Prove the raw files were never modified
for t in TABLES:
    assert file_hash(RAW_DIR / f"{t}.csv") == raw_hash[t], f"Raw file {t}.csv was modified!"

print(f"  wrote audit/cleaning_log.csv ({len(log_df)} rows)")
print(f"  wrote audit/value_changes.csv ({len(vc_df):,} rows)")
print("  raw files unchanged (SHA-256 identical before and after)")
banner("DONE - all assertions passed")
