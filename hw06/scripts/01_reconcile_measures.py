"""
HW6 Part B - Reconcile the Power BI measure library against pandas.

What this script does, in order:
  0. Runs a small self-test on hand-built snapshot rows, so the trickiest
     logic (pinned last date, suspect exclusion, blank alpha) is proven
     before any real number is trusted.
  1. Loads the Wildcat Capital Clean CSVs from hw06/data/ and checks two
     data assumptions (Withdrawal amounts > 0, no fact date outside dim_date).
  2. Recomputes EVERY measure for EVERY slice in pandas. Nothing from Power BI
     is read during this step, so the pandas numbers are fully independent.
  3. Only then reads hw06/reports/powerbi_values.csv (measure, slice, value).
  4. Compares the two sides row by row and writes
     hw06/reports/measure_reconciliation.csv
     (measure, slice, powerbi_value, pandas_value, abs_diff, match).
  5. Prints a summary (including the largest difference per measure type)
     and exits with code 1 if anything does not match.

Run from the repo root (C:\\MIS3060\\mis3060-bi-ai):
    python hw06/scripts/01_reconcile_measures.py

"Blank" below means the same thing as BLANK() in DAX. In pandas we use None.
"""

import math
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# File locations. Paths are built from this script's own location, so the
# script works whether you run it from the repo root or from hw06/scripts.
# ---------------------------------------------------------------------------
HW_DIR = Path(__file__).resolve().parent.parent          # .../hw06
DATA_DIR = HW_DIR / "data"
REPORTS_DIR = HW_DIR / "reports"
PBI_FILE = REPORTS_DIR / "powerbi_values.csv"
OUT_FILE = REPORTS_DIR / "measure_reconciliation.csv"

# ---------------------------------------------------------------------------
# Tolerances from the assignment: currency measures may differ by up to one
# cent; ratios, % and bps by up to 0.0001. Ending Clients (a count) and
# Alpha Signal (text) must match exactly.
# ---------------------------------------------------------------------------
CURRENCY_TOL = 0.01
RATIO_TOL = 0.0001

CURRENCY_MEASURES = {
    "AUM (naive SUM)",
    "Total Fees",
    "Net Flows",
    "Ending AUM",
    "Ending AUM LY",
    "Ending AUM PM",
    "Avg AUM per Client",
    "Avg Monthly AUM",
}
EXACT_MEASURES = {"Ending Clients", "Alpha Signal"}

# Every measure the script knows how to compute, in display order.
ALL_MEASURES = [
    "AUM (naive SUM)",
    "Total Fees",
    "Net Flows",
    "Ending AUM",
    "Ending Clients",
    "Avg AUM per Client",
    "Ending AUM LY",
    "AUM YoY %",
    "Ending AUM PM",
    "AUM MoM %",
    "Avg Monthly AUM",
    "Fee Yield (bps)",
    "Organic Growth Rate",
    "AUM-Weighted Alpha",
    "Alpha Signal",
    "Top 10 Client Share",
]

# Minimum coverage required by the assignment (Part B). If any of these rows
# is missing from powerbi_values.csv, the script reports it as a failure.
YEAR_MEASURES = [  # measures 1, 4, 6-10 by year
    "Ending AUM", "Ending AUM LY", "AUM YoY %", "Avg Monthly AUM",
    "Fee Yield (bps)", "Organic Growth Rate", "AUM-Weighted Alpha", "Alpha Signal",
]
TIER_MEASURES = [  # measures 1, 3, 4, 7-11 by client tier for 2024
    "Ending AUM", "Avg AUM per Client", "Ending AUM LY", "AUM YoY %",
    "Fee Yield (bps)", "Organic Growth Rate", "AUM-Weighted Alpha",
    "Alpha Signal", "Top 10 Client Share",
]
DEC_MEASURES = ["Ending AUM", "Ending AUM PM", "AUM MoM %"]  # measure 5, Dec 2024

TIERS = ["HNW", "Retail", "UHNW"]

# The ONLY rows allowed to be blank. 2020 is the first year of data, so there
# is no prior year to compare with. A row that is blank on both sides but is
# not on this list fails, because two blanks can hide the same bug in both
# tools. A row on this list that is not blank on both sides also fails.
EXPECTED_BLANKS = {
    ("Ending AUM LY", "2020"),
    ("AUM YoY %", "2020"),
    ("Organic Growth Rate", "2020"),
}


def require(condition, message):
    """Like assert, but it still runs when Python is started with -O."""
    if not condition:
        raise AssertionError(message)


# ===========================================================================
# Step 1 - Load and prepare the data
# ===========================================================================
def to_flag(series):
    """Turn a 0/1 or True/False column into a clean True/False column.
    A missing value counts as 0 (not suspect)."""
    text = series.astype(str).str.strip().str.lower()
    return text.isin(["1", "1.0", "true"])


def prepare_data(snap, fees, txns, clients, dates):
    """Clean the raw tables and attach each client's tier to every fact row,
    so any slice can be filtered by tier the same way the dim_client
    relationship filters the fact tables in Power BI. The self-test uses this
    same function, so it tests the real preparation code."""
    snap, fees, txns, dates = snap.copy(), fees.copy(), txns.copy(), dates.copy()

    # Drop any time-of-day part so date comparisons are by calendar day only.
    snap["snapshot_date"] = pd.to_datetime(snap["snapshot_date"]).dt.normalize()
    fees["fee_date"] = pd.to_datetime(fees["fee_date"]).dt.normalize()
    txns["txn_date"] = pd.to_datetime(txns["txn_date"]).dt.normalize()
    dates["date"] = pd.to_datetime(dates["date"]).dt.normalize()

    # Look up each row's client tier (the pandas version of the relationship).
    tier_lookup = clients.set_index("client_id")["client_tier"]
    for df in (snap, fees, txns):
        df["client_tier"] = df["client_id"].map(tier_lookup)

    snap["is_suspect"] = to_flag(snap["is_return_suspect"])

    # Trim spaces and ignore upper/lower case, so " Deposit" and "deposit"
    # both count as Deposit.
    txns["txn_type_clean"] = txns["txn_type"].astype(str).str.strip().str.lower()

    return {"snap": snap, "fees": fees, "txns": txns, "dates": dates}


def load_data():
    """Read the CSVs from hw06/data/ and prepare them."""
    snap = pd.read_csv(DATA_DIR / "fact_portfolio_snapshot.csv")
    fees = pd.read_csv(DATA_DIR / "fact_fees.csv")
    txns = pd.read_csv(DATA_DIR / "fact_transactions.csv")
    clients = pd.read_csv(DATA_DIR / "dim_client.csv", usecols=["client_id", "client_tier"])
    dates = pd.read_csv(DATA_DIR / "dim_date.csv")
    return prepare_data(snap, fees, txns, clients, dates)


def validate_data(data):
    """Stop with a clear message if the data breaks an assumption the
    measures depend on, instead of producing quietly wrong numbers."""
    txns = data["txns"]

    # Net Flows = Deposits - Withdrawals only works if withdrawals are stored
    # as positive amounts. A negative one would be subtracted twice.
    withdrawals = txns.loc[txns["txn_type_clean"] == "withdrawal", "amount"]
    bad = withdrawals[~(withdrawals > 0)]  # also catches missing amounts
    require(bad.empty,
            f"{len(bad)} Withdrawal row(s) have an amount that is not > 0 "
            f"(e.g. {bad.head(3).tolist()}).")

    # The Total slice uses dim_date's full range. A fact row outside that
    # range would be dropped silently, so check that none exist.
    first_day, last_day = data["dates"]["date"].min(), data["dates"]["date"].max()
    for table, col in [("snap", "snapshot_date"), ("fees", "fee_date"), ("txns", "txn_date")]:
        values = data[table][col]
        missing = int(values.isna().sum())
        outside = int(((values < first_day) | (values > last_day)).sum())
        require(missing == 0, f"{table}.{col}: {missing} row(s) have no date.")
        require(outside == 0,
                f"{table}.{col}: {outside} row(s) fall outside dim_date "
                f"({first_day.date()} to {last_day.date()}).")


# ===========================================================================
# Step 2 - Define the slices
# A slice is (start date, end date, tier or None). The labels match the
# "slice" column in powerbi_values.csv exactly.
# ===========================================================================
def define_slices(dates):
    first_day = dates["date"].min()
    last_day = dates["date"].max()
    slices = {"Total": (first_day, last_day, None)}  # all data = the whole date table

    for year in sorted(dates["date"].dt.year.unique()):
        slices[str(year)] = (pd.Timestamp(year, 1, 1), pd.Timestamp(year, 12, 31), None)

    for tier in TIERS:
        slices[f"2024 {tier}"] = (pd.Timestamp(2024, 1, 1), pd.Timestamp(2024, 12, 31), tier)

    slices["2024-12"] = (pd.Timestamp(2024, 12, 1), pd.Timestamp(2024, 12, 31), None)
    return slices


def shift_back(slice_def, years=0, months=0):
    """Move a slice's whole date range back in time, keeping the same tier.
    This mirrors SAMEPERIODLASTYEAR (years=1) and DATEADD(..., -1, MONTH)
    (months=1). Example: 2024-12-01..2024-12-31 shifted one month becomes
    2024-11-01..2024-11-30."""
    start, end, tier = slice_def
    offset = pd.DateOffset(years=years, months=months)
    return (start - offset, end - offset, tier)


def filter_rows(df, date_col, slice_def):
    """Keep the rows of a fact table that fall inside the slice."""
    start, end, tier = slice_def
    mask = (df[date_col] >= start) & (df[date_col] <= end)
    if tier is not None:
        mask &= df["client_tier"] == tier
    return df[mask]


# ===========================================================================
# Small helpers that copy DAX's behavior with blanks
# ===========================================================================
def is_blank(value):
    return value is None or (isinstance(value, float) and math.isnan(value))


def sum_or_blank(series):
    """SUM in DAX returns BLANK when there is nothing to add, not 0."""
    values = series.dropna()
    return None if values.empty else float(values.sum())


def safe_divide(numerator, denominator):
    """Same as DAX DIVIDE: blank if either side is blank or the denominator is 0."""
    if is_blank(numerator) or is_blank(denominator) or denominator == 0:
        return None
    return numerator / denominator


def last_snapshot_rows(snap_rows):
    """The rows on the latest snapshot_date inside the slice (the LASTNONBLANK
    idea). Returns None if the slice has no snapshot rows at all."""
    if snap_rows.empty:
        return None
    last_date = snap_rows["snapshot_date"].max()
    return snap_rows[snap_rows["snapshot_date"] == last_date]


def ending_aum(snap, slice_def):
    """Sum of aum on the last snapshot date in the slice."""
    rows = last_snapshot_rows(filter_rows(snap, "snapshot_date", slice_def))
    return None if rows is None else sum_or_blank(rows["aum"])


# ===========================================================================
# Step 3 - Compute all measures for one slice (pandas only)
# ===========================================================================
def compute_measures(data, slice_def):
    snap, fees, txns = data["snap"], data["fees"], data["txns"]

    snap_s = filter_rows(snap, "snapshot_date", slice_def)
    fees_s = filter_rows(fees, "fee_date", slice_def)
    txns_s = filter_rows(txns, "txn_date", slice_def)
    last_rows = last_snapshot_rows(snap_s)

    m = {}

    # 0. The deliberate mistake: adding up month-end balances across months.
    m["AUM (naive SUM)"] = sum_or_blank(snap_s["aum"])

    # Base measures from the ICEs.
    m["Total Fees"] = sum_or_blank(fees_s["amount"])
    deposits = sum_or_blank(txns_s.loc[txns_s["txn_type_clean"] == "deposit", "amount"])
    withdrawals = sum_or_blank(txns_s.loc[txns_s["txn_type_clean"] == "withdrawal", "amount"])
    if deposits is None and withdrawals is None:
        m["Net Flows"] = None                      # blank - blank = blank in DAX
    else:
        m["Net Flows"] = (deposits or 0.0) - (withdrawals or 0.0)

    # 1-3. Balances at the last snapshot in the slice.
    if last_rows is None:
        m["Ending AUM"] = None
        m["Ending Clients"] = None
    else:
        m["Ending AUM"] = sum_or_blank(last_rows["aum"])
        m["Ending Clients"] = int(last_rows["client_id"].nunique())
    m["Avg AUM per Client"] = safe_divide(m["Ending AUM"], m["Ending Clients"])

    # 4. Same balance one year earlier (same tier), and growth.
    m["Ending AUM LY"] = ending_aum(snap, shift_back(slice_def, years=1))
    m["AUM YoY %"] = safe_divide(
        None if is_blank(m["Ending AUM"]) or is_blank(m["Ending AUM LY"])
        else m["Ending AUM"] - m["Ending AUM LY"],
        m["Ending AUM LY"],
    )

    # 5. Same balance one month earlier, and growth.
    m["Ending AUM PM"] = ending_aum(snap, shift_back(slice_def, months=1))
    m["AUM MoM %"] = safe_divide(
        None if is_blank(m["Ending AUM"]) or is_blank(m["Ending AUM PM"])
        else m["Ending AUM"] - m["Ending AUM PM"],
        m["Ending AUM PM"],
    )

    # 6. Average balance: total of all monthly balances / number of months.
    m["Avg Monthly AUM"] = safe_divide(
        m["AUM (naive SUM)"], snap_s["snapshot_date"].nunique() or None
    )

    # 7. Fee yield in basis points: monthly fees annualized (x 12) per dollar
    #    of monthly AUM, times 10,000.
    m["Fee Yield (bps)"] = safe_divide(
        None if is_blank(m["Total Fees"]) else m["Total Fees"] * 12 * 10_000,
        m["AUM (naive SUM)"],
    )

    # 8. Net new money relative to last year's ending balance.
    m["Organic Growth Rate"] = safe_divide(m["Net Flows"], m["Ending AUM LY"])

    # 9. AUM-weighted alpha at the last snapshot. The last date is found
    #    BEFORE dropping suspect rows; then suspects are excluded. A blank
    #    alpha adds nothing to the numerator but its aum stays in the
    #    denominator, which is what SUMX does with BLANK in DAX.
    if last_rows is None:
        m["AUM-Weighted Alpha"] = None
    else:
        clean = last_rows[~last_rows["is_suspect"]]
        weighted = (clean["aum"] * clean["active_alpha_ytd"]).dropna()
        numerator = None if weighted.empty else float(weighted.sum())
        m["AUM-Weighted Alpha"] = safe_divide(numerator, sum_or_blank(clean["aum"]))

    # 10. Text label from the alpha.
    alpha = m["AUM-Weighted Alpha"]
    if is_blank(alpha):
        m["Alpha Signal"] = None
    elif alpha >= 0.02:
        m["Alpha Signal"] = "Outperforming"
    elif alpha <= -0.02:
        m["Alpha Signal"] = "Lagging"
    else:
        m["Alpha Signal"] = "In line"

    # 11. Share of Ending AUM held by the 10 biggest clients in the slice,
    #     using only clients present on the last snapshot date.
    #     Ties on aum are broken by the lower client_id.
    if last_rows is None:
        m["Top 10 Client Share"] = None
    else:
        per_client = last_rows.groupby("client_id", as_index=False)["aum"].sum()
        top10 = per_client.sort_values(["aum", "client_id"], ascending=[False, True]).head(10)
        m["Top 10 Client Share"] = safe_divide(float(top10["aum"].sum()), m["Ending AUM"])

    return m


# ===========================================================================
# Step 0 - Self-test on hand-built rows (runs before the real data)
# ===========================================================================
def self_test():
    """Build a tiny dataset where the right and wrong logic give different
    answers, and check that compute_measures gives the right ones.

    The rows (all 2024):
      - Client 1 (HNW) has by far the biggest balance, 1,000,000, but only on
        2024-11-01. It left before the last date (2024-12-01), so the pinned
        last date must leave it out of Ending AUM and Top 10.
      - Clients 2-11 (HNW) on 2024-12-01: aum = 10 x client_id (20..110),
        alpha 0.01.
      - Client 12 (HNW) on 2024-12-01: aum 120, alpha BLANK. Its aum must stay
        in the alpha denominator but add nothing to the numerator.
      - Client 13 (HNW) on 2024-12-01: aum 10,000 (the largest on that date),
        alpha 0.50, is_return_suspect = 1. It counts in Ending AUM and
        Top 10, but must be left out of AUM-Weighted Alpha.
      - Client 20 (Retail) on 2024-12-01: aum 500, alpha BLANK. Its slice has
        no alpha at all, so alpha and Alpha Signal must both be blank.
    """
    nov, dec = "2024-11-01", "2024-12-01"
    rows = [(1, nov, 1_000_000.0, 0.10, 0)]
    rows += [(cid, dec, cid * 10.0, 0.01, 0) for cid in range(2, 12)]
    rows += [(12, dec, 120.0, float("nan"), 0),
             (13, dec, 10_000.0, 0.50, 1),
             (20, dec, 500.0, float("nan"), 0)]
    snap = pd.DataFrame(rows, columns=["client_id", "snapshot_date", "aum",
                                       "active_alpha_ytd", "is_return_suspect"])
    clients = pd.DataFrame({"client_id": list(range(1, 14)) + [20],
                            "client_tier": ["HNW"] * 13 + ["Retail"]})
    fees = pd.DataFrame({"fee_date": pd.to_datetime([]), "client_id": [], "amount": []})
    txns = pd.DataFrame({"txn_date": pd.to_datetime([]), "client_id": [],
                         "txn_type": [], "amount": []})
    dates = pd.DataFrame({"date": pd.date_range("2024-01-01", "2024-12-31")})

    data = prepare_data(snap, fees, txns, clients, dates)
    year = (pd.Timestamp(2024, 1, 1), pd.Timestamp(2024, 12, 31))

    def close(a, b):
        return a is not None and math.isclose(a, b, rel_tol=0, abs_tol=1e-12)

    # --- HNW slice ---
    hnw = compute_measures(data, (*year, "HNW"))
    ending = 650 + 120 + 10_000          # clients 2-11, 12 and 13; NOT client 1
    require(close(hnw["Ending AUM"], ending),
            f"Self-test: Ending AUM should be {ending}, got {hnw['Ending AUM']}")
    require(hnw["Ending Clients"] == 12,
            f"Self-test: Ending Clients should be 12, got {hnw['Ending Clients']}")

    # (a) Top 10 on 2024-12-01: client 13, 12, 11 ... 4. Client 1 is excluded
    #     even though it has the biggest balance in the year.
    top10 = 10_000 + 120 + sum(cid * 10 for cid in range(4, 12))
    require(close(hnw["Top 10 Client Share"], top10 / ending),
            f"Self-test (a): Top 10 Client Share should be {top10 / ending:.6f} "
            f"(departed client 1 excluded), got {hnw['Top 10 Client Share']}")

    # (b) + (c) Alpha: suspect client 13 excluded; client 12's blank alpha
    #     keeps its aum (120) in the denominator.
    alpha = (0.01 * 650) / (650 + 120)
    require(close(hnw["AUM-Weighted Alpha"], alpha),
            f"Self-test (b/c): AUM-Weighted Alpha should be {alpha:.6f}, "
            f"got {hnw['AUM-Weighted Alpha']}")
    require(hnw["Alpha Signal"] == "In line",
            f"Self-test: Alpha Signal should be 'In line', got {hnw['Alpha Signal']!r}")

    # (c) A slice where every alpha is blank gives blank alpha and blank signal.
    retail = compute_measures(data, (*year, "Retail"))
    require(close(retail["Ending AUM"], 500.0),
            f"Self-test: Retail Ending AUM should be 500, got {retail['Ending AUM']}")
    require(retail["AUM-Weighted Alpha"] is None,
            f"Self-test (c): Retail alpha should be blank, got {retail['AUM-Weighted Alpha']}")
    require(retail["Alpha Signal"] is None,
            f"Self-test (c): Retail Alpha Signal should be blank, got {retail['Alpha Signal']!r}")

    print("Self-test passed (pinned last date, suspect exclusion, blank alpha).")


# ===========================================================================
# Step 4 - Compare pandas with Power BI
# ===========================================================================
def measure_type(measure):
    if measure in EXACT_MEASURES:
        return "exact"
    if measure in CURRENCY_MEASURES:
        return "currency"
    return "ratio"


TOLERANCE = {"currency": CURRENCY_TOL, "ratio": RATIO_TOL, "exact": 0.0}


def compare(measure, slice_label, pbi_text, pandas_value):
    """Return (abs_diff, match, reason).
    Blank rows only match if they are on EXPECTED_BLANKS."""
    pbi_blank = pbi_text is None or pbi_text.strip() == ""
    pandas_blank = is_blank(pandas_value)
    expected_blank = (measure, slice_label) in EXPECTED_BLANKS

    if expected_blank:
        if pbi_blank and pandas_blank:
            return None, True, "expected blank"
        return None, False, "should be blank on both sides"
    if pbi_blank and pandas_blank:
        return None, False, "blank on both sides but not an expected blank"
    if pbi_blank or pandas_blank:
        return None, False, "blank on one side only"

    if measure == "Alpha Signal":  # text: exact comparison
        same = pbi_text.strip() == str(pandas_value).strip()
        return None, same, "" if same else "text differs"

    try:
        pbi_number = float(pbi_text)
    except ValueError:
        return None, False, "Power BI value is not a number"

    diff = abs(pbi_number - float(pandas_value))
    ok = diff <= TOLERANCE[measure_type(measure)]
    return diff, ok, "" if ok else "outside tolerance"


def required_rows(slice_labels):
    """The (measure, slice) pairs the assignment says must be covered."""
    years = [s for s in slice_labels if s.isdigit()]
    rows = [(m, "Total") for m in ALL_MEASURES]
    rows += [(m, y) for y in years for m in YEAR_MEASURES]
    rows += [(m, f"2024 {t}") for t in TIERS for m in TIER_MEASURES]
    rows += [(m, "2024-12") for m in DEC_MEASURES]
    return rows


def print_diff_summary(result):
    """Largest abs_diff per measure type, next to its tolerance, with the
    row it came from. Text and blank rows have no numeric difference."""
    print("\nLargest differences by measure type:")
    numeric = result.dropna(subset=["abs_diff"])
    for mtype in ["currency", "ratio", "exact"]:
        rows = numeric[numeric["measure"].map(measure_type) == mtype]
        tol = TOLERANCE[mtype]
        if rows.empty:
            print(f"  {mtype:<9} no numeric rows")
            continue
        worst = rows.loc[rows["abs_diff"].idxmax()]
        print(f"  {mtype:<9} max_abs_diff = {worst['abs_diff']:.3e}  (tolerance {tol:g})  "
              f"worst row: {worst['measure']} | {worst['slice']}")


def main():
    # --- Prove the tricky logic on hand-built data first ---
    self_test()

    # --- Independent pandas calculation (Power BI is not touched here) ---
    data = load_data()
    validate_data(data)
    slices = define_slices(data["dates"])
    pandas_results = {
        label: compute_measures(data, slice_def) for label, slice_def in slices.items()
    }

    # --- Only now read the Power BI export ---
    # dtype=str and keep_default_na=False keep blank cells as "" so we can
    # tell a true BLANK apart from a number.
    pbi = pd.read_csv(PBI_FILE, dtype=str, keep_default_na=False)
    pbi["measure"] = pbi["measure"].str.strip()
    pbi["slice"] = pbi["slice"].str.strip()

    output, reasons = [], []
    for _, row in pbi.iterrows():
        measure, slice_label, pbi_text = row["measure"], row["slice"], row["value"]
        if slice_label not in pandas_results or measure not in pandas_results[slice_label]:
            output.append([measure, slice_label, pbi_text, None, None, False])
            reasons.append("unknown measure or slice")
            continue
        pandas_value = pandas_results[slice_label][measure]
        abs_diff, match, reason = compare(measure, slice_label, pbi_text, pandas_value)
        output.append([measure, slice_label, pbi_text, pandas_value, abs_diff, match])
        reasons.append(reason)

    # Any required row that Power BI did not export is a failure too.
    exported = set(zip(pbi["measure"], pbi["slice"]))
    for measure, slice_label in required_rows(list(slices)):
        if (measure, slice_label) not in exported:
            output.append([measure, slice_label, "(missing)",
                           pandas_results[slice_label][measure], None, False])
            reasons.append("missing from powerbi_values.csv")

    result = pd.DataFrame(
        output,
        columns=["measure", "slice", "powerbi_value", "pandas_value", "abs_diff", "match"],
    )
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_FILE, index=False)
    result["reason"] = reasons  # used for printing only, not written to the CSV

    # --- Summary ---
    checked = len(result)
    matched = int(result["match"].sum())
    blank_matches = result[result["reason"] == "expected blank"]
    print(f"\nRows checked: {checked}")
    print(f"Rows matched: {matched}  "
          f"({matched - len(blank_matches)} with values, {len(blank_matches)} expected blanks)")
    print(f"Mismatches:   {checked - matched}")
    print(f"Written to:   {OUT_FILE}")

    if not blank_matches.empty:
        print("\nExpected blanks (blank in both Power BI and pandas):")
        for _, r in blank_matches.iterrows():
            print(f"  - {r['measure']} | {r['slice']}")

    print_diff_summary(result)

    bad = result[~result["match"]]
    if not bad.empty:
        print("\nMismatched rows:")
        for _, r in bad.iterrows():
            print(f"  - {r['measure']} | {r['slice']}: Power BI = {r['powerbi_value']!r}, "
                  f"pandas = {r['pandas_value']!r}, abs_diff = {r['abs_diff']} "
                  f"[{r['reason']}]")
        sys.exit(1)

    print("\nAll rows match.")


if __name__ == "__main__":
    main()
