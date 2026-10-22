r"""
03_validate.py -- HW4 Part D: data validation for Wildcat Capital

Run from the repo root:
    cd C:\MIS3060\mis3060-bi-ai
    python hw04/scripts/03_validate.py

This script is READ-ONLY for data: it never changes a file in hw04/data/.
It only writes reports to hw04/reports/.

What it does, for both hw04/data/raw/ and hw04/data/clean/:
  1. Referential integrity (RI) on the 13 relationships in README_clean.md
  2. Row-level business rules (ranges, allowed lists, flags, dates)
  3. Cross-table reconciliations (fee formula, fee vs snapshot AUM,
     shares x price, active alpha, advisor consistency)
  4. 1.5 x IQR outlier counts on transaction amount and snapshot AUM
  5. A data-quality scorecard, one row per table per stage. pct_rule_pass
     includes "ISSUE HANDLED" rules (decision log Issues 1 and 2), so raw scores
     below 100% where known issues are unflagged and clean scores 100%.
  6. After ALL reports are written: a self-test of check_referential_integrity
     and assertions that the CLEAN stage has 0 orphans, 100% rule pass and
     100% on reconciliations (a), (c), (d). A failure lists every problem.

Outputs (hw04/reports/):
  data_quality_scorecard.csv  - the scorecard (required)
  ri_results.csv              - one row per relationship per stage (required)
  rule_results.csv            - detail behind pct_rule_pass (extra)
  reconciliation_results.csv  - detail for the reconciliations (extra)
  iqr_outliers.csv            - 1.5 x IQR outlier counts per column per stage

Reusing check_referential_integrity in HW5: a file whose name starts with a
digit can't be imported with a plain `import`. Either copy the function, or:
    import importlib.util
    spec = importlib.util.spec_from_file_location("v", "hw04/scripts/03_validate.py")
    v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)
    v.check_referential_integrity(...)
(main() only runs when the file is executed directly, so loading it is safe.)
"""

from pathlib import Path
import sys

import numpy as np
import pandas as pd

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", None)
pd.set_option("display.max_colwidth", 70)

# ---------------------------------------------------------------------------
# Paths and settings
# ---------------------------------------------------------------------------
REPO_ROOT = Path.cwd()                      # the script must be run from the repo root
HW_DIR = REPO_ROOT / "hw04"
STAGE_DIRS = {"raw": HW_DIR / "data" / "raw", "clean": HW_DIR / "data" / "clean"}
REPORTS_DIR = HW_DIR / "reports"

# All dates in the extract are expected as YYYY-MM-DD. A date in any other
# format counts as a type-validity failure (that is a real finding).
DATE_FORMAT = "%Y-%m-%d"

TABLES = [
    "dim_advisor", "dim_client", "dim_date", "dim_security", "dim_benchmark",
    "fact_fees", "fact_portfolio_snapshot", "fact_transactions",
]

# Primary key of each table (used for the key-uniqueness score).
PRIMARY_KEYS = {
    "dim_advisor": "advisor_id",
    "dim_client": "client_id",
    "dim_date": "date_id",
    "dim_security": "security_id",
    "dim_benchmark": "benchmark_id",
    "fact_fees": "fee_id",
    "fact_portfolio_snapshot": "snapshot_id",
    "fact_transactions": "txn_id",
}

# The 13 relationships, numbered as in README_clean.md section 1.
# (id, many-side table, foreign key, one-side table, primary key)
RELATIONSHIPS = [
    (1, "dim_client", "advisor_id", "dim_advisor", "advisor_id"),
    (2, "fact_transactions", "advisor_id", "dim_advisor", "advisor_id"),
    (3, "fact_fees", "advisor_id", "dim_advisor", "advisor_id"),
    (4, "fact_portfolio_snapshot", "advisor_id", "dim_advisor", "advisor_id"),
    (5, "fact_transactions", "client_id", "dim_client", "client_id"),
    (6, "fact_fees", "client_id", "dim_client", "client_id"),
    (7, "fact_portfolio_snapshot", "client_id", "dim_client", "client_id"),
    (8, "fact_transactions", "security_id", "dim_security", "security_id"),
    (9, "dim_security", "benchmark_id", "dim_benchmark", "benchmark_id"),
    (10, "fact_portfolio_snapshot", "benchmark_id", "dim_benchmark", "benchmark_id"),
    (11, "fact_transactions", "txn_date", "dim_date", "date"),
    (12, "fact_fees", "fee_date", "dim_date", "date"),
    (13, "fact_portfolio_snapshot", "snapshot_date", "dim_date", "date"),
]

# ---------------------------------------------------------------------------
# Allowed values. CONFIRMED = seen in README_clean.md / decision_log.md.
# ASSUMED = my best guess; the script prints any value found outside the list
# (see "sample_failing_values"), so check those lists against the data
# dictionary and edit them if a legitimate value is reported as a failure.
# ---------------------------------------------------------------------------
SECURITY_TXN_TYPES = {"Buy", "Sell", "Dividend"}                  # CONFIRMED
CASH_TXN_TYPES = {"Deposit", "Withdrawal", "Advisory Fee"}        # CONFIRMED
TXN_TYPES = SECURITY_TXN_TYPES | CASH_TXN_TYPES
ASSET_CLASSES = {"Equity", "Fixed Income", "Alternative", "Cash Equivalent"}  # CONFIRMED
# Benchmarks use their own asset-class labels (e.g. benchmark 3 = "60/40 Blend" is Multi-Asset)
BENCHMARK_ASSET_CLASSES = {"Equity", "Fixed Income", "Multi-Asset", "International",
                           "Small Cap", "Emerging", "Cash"}                    # CONFIRMED
CLIENT_TIERS = {"Retail", "HNW", "UHNW"}                                      # CONFIRMED
RISK_PROFILES = {"Aggressive", "Moderately Aggressive", "Balanced",
                 "Moderately Conservative", "Conservative", "Unknown"}        # CONFIRMED
FEE_TYPES = {"Advisory", "Management", "Custodial", "Performance"}            # CONFIRMED
ACCOUNT_TYPES = {"Taxable", "IRA", "Roth IRA", "Trust", "529"}                # CONFIRMED
REGIONS = {"Northeast", "Mid-Atlantic", "Southeast", "Midwest", "West"}       # CONFIRMED
# "Issue handled" rules (see run_rules) and the failure counts the decision log
# predicts for them. Raw must fail exactly these; clean must fail 0.
ISSUE_PREFIX = "ISSUE HANDLED"
EXPECTED_RAW_ISSUE_FAILS = {"Issue 1:": 40_630, "Issue 2:": 576}

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO",
    "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}

# ---------------------------------------------------------------------------
# Expected data types, by column name (used for the type-validity score).
# Every column ending in "_id" must be a whole number (blank allowed, e.g.
# security_id on cash rows - blanks are scored by completeness instead).
# ---------------------------------------------------------------------------
NUMERIC_COLS = {
    "amount", "aum", "aum_basis", "initial_aum", "price", "shares",
    "return_ytd", "benchmark_return_ytd", "active_alpha_ytd", "cash_pct",
    "bps_charged", "expense_ratio_bps", "years_experience", "aum_target_mm",
}
WHOLE_NUMBER_COLS = {"age", "year", "month", "quarter"}


def is_date_col(col):
    """A column holds dates if it is called 'date', ends in '_date', or is client_since."""
    return col == "date" or col.endswith("_date") or col == "client_since"


def is_flag_col(col):
    """Every column starting with 'is_' is a yes/no flag."""
    return col.startswith("is_")


# ---------------------------------------------------------------------------
# Small helpers for turning text into numbers / dates / flags.
# Everything is read as text, so these never change the data; they only
# produce a parsed copy for checking. Anything that can't be parsed becomes
# NaN / NaT, which the type-validity check then counts.
# ---------------------------------------------------------------------------
FLAG_MAP = {"0": 0, "1": 1, "false": 0, "true": 1}


def txt(s):
    """Trimmed text version of a column."""
    return s.astype(str).str.strip()


def num(s):
    """Text -> number. Blank or non-numeric text becomes NaN."""
    return pd.to_numeric(txt(s).replace("", np.nan), errors="coerce")


def dt(s):
    """Text -> date (YYYY-MM-DD). Blank or badly formatted text becomes NaT."""
    return pd.to_datetime(txt(s), format=DATE_FORMAT, errors="coerce")


def flag(s):
    """Text -> 0/1. Accepts 0/1 and True/False (any case); anything else is NaN."""
    return txt(s).str.lower().map(FLAG_MAP)


def pct(part, whole):
    """Percentage rounded to 4 decimals; NaN when there is nothing to measure."""
    return round(100.0 * part / whole, 4) if whole else np.nan


def has(df, *cols):
    return all(c in df.columns for c in cols)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_stage(stage):
    """Read all eight CSVs of one stage as text, exactly as stored."""
    folder = STAGE_DIRS[stage]
    tables = {}
    for name in TABLES:
        path = folder / f"{name}.csv"
        if not path.exists():
            sys.exit(f"ERROR: {path} not found. Run this script from the repo root.")
        # dtype=str + keep_default_na=False: every cell stays as its original
        # text, so 'None' in dim_advisor.certifications stays 'None'.
        # utf-8-sig quietly drops a byte-order mark if a raw file has one.
        tables[name] = pd.read_csv(path, dtype=str, keep_default_na=False,
                                   encoding="utf-8-sig")
    return tables


# ---------------------------------------------------------------------------
# 1. Referential integrity
# ---------------------------------------------------------------------------
def _normalise_keys(s):
    """
    Turn a key column into comparable text, plus a mask of null keys.
    Null = isna() (NaN/None) or blank after trimming. Whole numbers stored as
    floats lose their '.0' ("45.0" -> "45"), so int and float IDs match.
    """
    missing = s.isna()
    k = s.astype(object).where(~missing, "").astype(str).str.strip()
    k = k.str.replace(r"^([+-]?\d+)\.0+$", r"\1", regex=True)
    return k, missing | (k == "")


def check_referential_integrity(fact_df, fact_key, dim_df, dim_key):
    """
    Check that every foreign key in a "many" table exists in a "one" table.

    Parameters
    ----------
    fact_df : pandas.DataFrame
        The many-side table (usually a fact table, but any child table works,
        e.g. dim_client -> dim_advisor).
    fact_key : str
        Foreign-key column in fact_df.
    dim_df : pandas.DataFrame
        The one-side (lookup) table.
    dim_key : str
        Primary-key column in dim_df.

    Works however the tables were loaded
    ------------------------------------
    You get the same answer whether the CSVs were read as text
    (dtype=str, keep_default_na=False) or with plain pd.read_csv, where pandas
    guesses types. With a plain read, an ID column that contains blanks becomes
    float (45 -> 45.0) and blanks become NaN; both cases are handled:
    * NULL key = a missing value (NaN/None, anything isna() catches) OR a
      blank / whitespace-only string. Nulls are NOT orphans; they are reported
      separately as null_key_rate_pct, because some blanks are legitimate
      (e.g. security_id on cash transactions).
    * Keys are compared as TRIMMED TEXT ("  42 " matches "42"), and a whole
      number written as a float is normalised on BOTH sides ("45.0" -> "45"),
      so an int column on one side matches a float column on the other.
      A genuinely fractional key such as "45.5" is left alone and will not match.
    * An ORPHAN is a non-null fact key that is not found in dim_df[dim_key].

    Returns
    -------
    dict with:
        total_rows           rows in fact_df
        null_key_rows        rows whose key is blank
        null_key_rate_pct    null_key_rows / total_rows x 100
        non_null_rows        rows with a non-blank key
        matched_rows         non-blank keys found in the dimension
        match_rate_pct       matched_rows / non_null_rows x 100 (NaN if no non-null keys)
        orphan_rows          non-blank keys NOT found in the dimension
        distinct_orphan_keys number of different orphan key values
        sample_orphan_keys   up to 5 orphan values, '; '-separated
        dim_duplicate_keys   repeated non-null keys on the one side (should be 0;
                             duplicates there would make the relationship many-to-many)

    Example
    -------
    >>> res = check_referential_integrity(fact_fees, "client_id", dim_client, "client_id")
    >>> res["match_rate_pct"], res["orphan_rows"]
    """
    for df, col, label in [(fact_df, fact_key, "fact_df"), (dim_df, dim_key, "dim_df")]:
        if col not in df.columns:
            raise KeyError(f"{label} has no column '{col}'")

    fact_keys, is_null = _normalise_keys(fact_df[fact_key])
    dim_keys, dim_null = _normalise_keys(dim_df[dim_key])
    dim_keys = dim_keys[~dim_null]               # a null primary key can't be matched to
    valid_keys = set(dim_keys)

    in_dim = fact_keys.isin(valid_keys)
    orphan_mask = ~is_null & ~in_dim
    orphan_values = fact_keys[orphan_mask].dropna()   # no NaN can reach sorted() below

    total = len(fact_keys)
    null_rows = int(is_null.sum())
    non_null = total - null_rows
    matched = int((~is_null & in_dim).sum())

    return {
        "total_rows": total,
        "null_key_rows": null_rows,
        "null_key_rate_pct": pct(null_rows, total),
        "non_null_rows": non_null,
        "matched_rows": matched,
        "match_rate_pct": pct(matched, non_null),
        "orphan_rows": int(orphan_mask.sum()),
        "distinct_orphan_keys": int(orphan_values.nunique()),
        "sample_orphan_keys": "; ".join(sorted(orphan_values.unique())[:5]),
        "dim_duplicate_keys": int(dim_keys.duplicated().sum()),
    }


def run_ri(t, stage):
    rows = []
    for rel_id, fact, fkey, dim, dkey in RELATIONSHIPS:
        res = check_referential_integrity(t[fact], fkey, t[dim], dkey)
        rows.append({"relationship_id": rel_id, "stage": stage,
                     "relationship": f"{fact}.{fkey} -> {dim}.{dkey}",
                     "fact_table": fact, "fact_key": fkey,
                     "dim_table": dim, "dim_key": dkey, **res})
    return rows


# ---------------------------------------------------------------------------
# 2. Row-level business rules
# Each rule says which rows it APPLIES to and which of those PASS.
# A rule only applies to values that could be parsed; unparseable or blank
# values are already counted by the type-validity / completeness scores, so
# they are not counted a second time here.
# ---------------------------------------------------------------------------
def add_rule(results, stage, table, rule, applies, passed, values=None):
    applies = pd.Series(applies).eq(True)        # NaN -> False, no warnings
    passed = pd.Series(passed).eq(True)
    failed = applies & ~passed
    sample = ""
    if failed.any() and values is not None:
        counts = txt(values[failed]).value_counts().head(5)
        sample = "; ".join(f"'{v}' x{c}" for v, c in counts.items())
    results.append({
        "stage": stage, "table": table, "rule": rule,
        "rows_checked": int(applies.sum()),
        "rows_failed": int(failed.sum()),
        "pct_pass": pct(int((applies & passed).sum()), int(applies.sum())),
        "sample_failing_values": sample,
    })


def run_rules(t, stage):
    R, skipped = [], []

    def need(table, *cols, rule=""):
        """True if the columns exist; otherwise note the rule as skipped."""
        missing = [c for c in cols if c not in t[table].columns]
        if missing:
            skipped.append(f"{table}: '{rule}' (missing {', '.join(missing)})")
        return not missing

    def allowed(table, col, allowed_set):
        if need(table, col, rule=f"{col} in allowed list"):
            s = txt(t[table][col])
            add_rule(R, stage, table, f"{col} in allowed list", s != "",
                     s.isin(allowed_set), t[table][col])

    def numeric_rule(table, col, label, test):
        if need(table, col, rule=f"{col} {label}"):
            x = num(t[table][col])
            add_rule(R, stage, table, f"{col} {label}", x.notna(), test(x), t[table][col])

    # dim_date's own range is the valid range for every fact date
    dd = t["dim_date"]
    d_dates = dt(dd["date"])
    dmin, dmax = d_dates.min(), d_dates.max()

    def in_date_range(table, col):
        if need(table, col, rule=f"{col} within dim_date range"):
            d = dt(t[table][col])
            add_rule(R, stage, table, f"{col} within dim_date range ({dmin:%Y-%m-%d} to {dmax:%Y-%m-%d})",
                     d.notna(), d.between(dmin, dmax), t[table][col])

    def date_parts_match(table, date_col, parts):
        """year / month / quarter columns must agree with the table's own date column."""
        df = t[table]
        d = dt(df[date_col])
        getters = {"year": d.dt.year, "month": d.dt.month, "quarter": d.dt.quarter}
        for part in parts:
            if need(table, part, rule=f"{part} matches {date_col}"):
                p = num(df[part])
                add_rule(R, stage, table, f"{part} matches {date_col}",
                         p.notna() & d.notna(), p == getters[part], df[part])

    def first_of_month(table, col):
        if need(table, col, rule=f"{col} is the 1st of the month"):
            d = dt(t[table][col])
            add_rule(R, stage, table, f"{col} is the 1st of the month",
                     d.notna(), d.dt.day == 1, t[table][col])

    # --- Generic: every is_* flag holds only 0/1 (True/False accepted for the
    # flags that were delivered that way). The two flags my cleaning script
    # added must be exactly 0 or 1.
    added_flags = {"is_non_trading_day", "is_return_outlier"}
    for name, df in t.items():
        for col in [c for c in df.columns if is_flag_col(c)]:
            s = txt(df[col])
            if col in added_flags:
                add_rule(R, stage, name, f"{col} is 0 or 1", s != "", s.isin({"0", "1"}), df[col])
            else:
                add_rule(R, stage, name, f"{col} is 0/1 or True/False", s != "",
                         flag(df[col]).notna(), df[col])

    # --- dim_client
    c = t["dim_client"]
    numeric_rule("dim_client", "age", "is a whole number from 18 to 100",
                 lambda x: x.between(18, 100) & (x % 1 == 0))
    numeric_rule("dim_client", "initial_aum", "> 0", lambda x: x > 0)
    allowed("dim_client", "risk_profile", RISK_PROFILES)
    allowed("dim_client", "client_tier", CLIENT_TIERS)
    allowed("dim_client", "primary_account_type", ACCOUNT_TYPES)
    allowed("fact_portfolio_snapshot", "account_type", ACCOUNT_TYPES)
    allowed("dim_client", "state", US_STATES)
    if need("dim_client", "zip_code", rule="zip_code is 5 digits"):
        z = txt(c["zip_code"])     # catches ZIPs that lost a leading zero (e.g. 1234)
        add_rule(R, stage, "dim_client", "zip_code is 5 digits (or ZIP+4)", z != "",
                 z.str.fullmatch(r"\d{5}(-\d{4})?"), c["zip_code"])
    if need("dim_client", "client_since", rule="client_since not after dim_date end"):
        d = dt(c["client_since"])
        add_rule(R, stage, "dim_client", "client_since not after last dim_date date",
                 d.notna(), d <= dmax, c["client_since"])

    # --- dim_security
    s_ = t["dim_security"]
    allowed("dim_security", "asset_class", ASSET_CLASSES)
    numeric_rule("dim_security", "expense_ratio_bps", ">= 0 (where present)", lambda x: x >= 0)
    if need("dim_security", "ticker", rule="ticker is unique"):
        tk = txt(s_["ticker"])     # ticker is the business key (decision log, Issue 6)
        add_rule(R, stage, "dim_security", "ticker is unique", tk != "",
                 ~tk.duplicated(keep=False), s_["ticker"])

    # --- dim_date: the calendar must agree with itself
    if need("dim_date", "date", rule="date is unique"):
        ds = txt(dd["date"])       # date is the join key for relationships 11-13
        add_rule(R, stage, "dim_date", "date is unique", ds != "",
                 ~ds.duplicated(keep=False), dd["date"])
    date_parts_match("dim_date", "date", ("year", "month", "quarter"))
    if need("dim_date", "is_trading_day", rule="weekends are not trading days"):
        f = flag(dd["is_trading_day"])
        weekend = d_dates.dt.dayofweek >= 5
        add_rule(R, stage, "dim_date", "weekend dates have is_trading_day = 0",
                 weekend & f.notna(), f == 0, dd["date"])
    # Calendar flags must agree with the date itself
    for col, truth in [("is_month_end", d_dates.dt.is_month_end),
                       ("is_quarter_end", d_dates.dt.is_quarter_end),
                       ("is_year_end", d_dates.dt.is_year_end)]:
        if need("dim_date", col, rule=f"{col} matches date"):
            f = flag(dd[col])
            add_rule(R, stage, "dim_date", f"{col} matches date",
                     d_dates.notna() & f.notna(), f == truth.astype(int), dd["date"])
    # day_of_week: the data dictionary doesn't say how days are coded, so the
    # coding is read from the data. Names ("Monday" or "Mon") are compared to the
    # date's weekday name; numbers are tested against the four common
    # numberings and the one that fits most rows is used. Any row that doesn't
    # fit that one numbering fails.
    if need("dim_date", "day_of_week", rule="day_of_week matches date"):
        raw_dow = txt(dd["day_of_week"])
        n = num(dd["day_of_week"])
        if n.notna().any():
            mon0 = d_dates.dt.dayofweek                    # Monday = 0 ... Sunday = 6
            codings = {"Mon=0..Sun=6": mon0, "Mon=1..Sun=7": mon0 + 1,
                       "Sun=0..Sat=6": (mon0 + 1) % 7, "Sun=1..Sat=7": (mon0 + 1) % 7 + 1}
            best = max(codings, key=lambda k: int((n == codings[k]).sum()))
            add_rule(R, stage, "dim_date", f"day_of_week matches date (coded {best})",
                     n.notna() & d_dates.notna(), n == codings[best], dd["day_of_week"])
        else:
            full = d_dates.dt.day_name().str.lower()
            low = raw_dow.str.lower()
            add_rule(R, stage, "dim_date", "day_of_week matches date (weekday name)",
                     (raw_dow != "") & d_dates.notna(), (low == full) | (low == full.str[:3]),
                     dd["day_of_week"])
    # month_name: accepts the full name ("January") or the 3-letter form ("Jan")
    if need("dim_date", "month_name", rule="month_name matches date"):
        mn = txt(dd["month_name"]).str.lower()
        full = d_dates.dt.month_name().str.lower()
        add_rule(R, stage, "dim_date", "month_name matches date",
                 (mn != "") & d_dates.notna(), (mn == full) | (mn == full.str[:3]),
                 dd["month_name"])

    # --- dim_advisor
    numeric_rule("dim_advisor", "years_experience", "between 0 and 50", lambda v: v.between(0, 50))
    numeric_rule("dim_advisor", "aum_target_mm", "> 0", lambda v: v > 0)
    allowed("dim_advisor", "region", REGIONS)

    # --- dim_benchmark
    b = t["dim_benchmark"]
    if need("dim_benchmark", "benchmark_id", rule="benchmark_id is a unique whole number"):
        k = txt(b["benchmark_id"])
        add_rule(R, stage, "dim_benchmark", "benchmark_id is a unique whole number", k != "",
                 k.str.fullmatch(r"\d+") & ~k.duplicated(keep=False), b["benchmark_id"])
    allowed("dim_benchmark", "asset_class", BENCHMARK_ASSET_CLASSES)
    if need("dim_benchmark", "ticker_proxy", rule="ticker_proxy not blank"):
        add_rule(R, stage, "dim_benchmark", "ticker_proxy not blank",
                 pd.Series(True, index=b.index), txt(b["ticker_proxy"]) != "", b["benchmark_id"])

    # --- fact_transactions
    x = t["fact_transactions"]
    allowed("fact_transactions", "txn_type", TXN_TYPES)
    numeric_rule("fact_transactions", "amount", "> 0", lambda v: v > 0)
    in_date_range("fact_transactions", "txn_date")
    if need("fact_transactions", "txn_type", "security_id", "shares", "price",
            rule="security fields by txn_type"):
        typ = txt(x["txn_type"])
        sec = typ.isin(SECURITY_TXN_TYPES)
        cash = typ.isin(CASH_TXN_TYPES)
        for col in ["shares", "price"]:
            v = num(x[col])
            add_rule(R, stage, "fact_transactions", f"{col} > 0 for Buy/Sell/Dividend",
                     sec & v.notna(), v > 0, x[col])
        add_rule(R, stage, "fact_transactions", "security_id present for Buy/Sell/Dividend",
                 sec, txt(x["security_id"]) != "", x["txn_type"])
        # This proves the completeness exemption below is safe: cash rows
        # really have nothing in the three security fields.
        all_blank = (txt(x["security_id"]) == "") & (txt(x["shares"]) == "") & (txt(x["price"]) == "")
        add_rule(R, stage, "fact_transactions",
                 "security_id/shares/price blank for Deposit/Withdrawal/Advisory Fee",
                 cash, all_blank, x["txn_type"])
    # --- fact_fees
    allowed("fact_fees", "fee_type", FEE_TYPES)
    numeric_rule("fact_fees", "amount", "> 0", lambda v: v > 0)
    numeric_rule("fact_fees", "bps_charged", "> 0", lambda v: v > 0)
    numeric_rule("fact_fees", "aum_basis", "> 0", lambda v: v > 0)
    in_date_range("fact_fees", "fee_date")
    first_of_month("fact_fees", "fee_date")

    # --- fact_portfolio_snapshot
    p = t["fact_portfolio_snapshot"]
    numeric_rule("fact_portfolio_snapshot", "cash_pct", "between 0 and 1", lambda v: v.between(0, 1))
    numeric_rule("fact_portfolio_snapshot", "aum", ">= 0", lambda v: v >= 0)
    numeric_rule("fact_portfolio_snapshot", "return_ytd", ">= -1 (cannot lose more than 100%)",
                 lambda v: v >= -1)
    numeric_rule("fact_portfolio_snapshot", "benchmark_return_ytd", "between -1 and 1",
                 lambda v: v.between(-1, 1))
    in_date_range("fact_portfolio_snapshot", "snapshot_date")
    first_of_month("fact_portfolio_snapshot", "snapshot_date")
    date_parts_match("fact_portfolio_snapshot", "snapshot_date", ("year", "month"))

    # =======================================================================
    # ISSUE-HANDLED RULES -- CIRCULAR BY DESIGN
    # These rules re-derive each known issue (decision log Issues 1, 4, 5) and
    # check that every affected row carries its flag. They prove the FLAGS are
    # complete and consistent; they do NOT prove the underlying values are
    # correct. A weekend-dated trade still has a doubtful date, a return above
    # 100% is still unusable, and a post-departure transaction is still odd -
    # the rule only shows that an analyst can find and filter every one of them.
    # =======================================================================

    # Rules whose name starts with ISSUE_PREFIX are the "issue handled" rules.
    # They run on BOTH stages. On raw, a flag column that cleaning adds later
    # doesn't exist yet, so it is treated as all 0 and every known issue row
    # fails - that is the point: raw has the problem undocumented, clean has
    # every affected row flagged. They feed pct_rule_pass and pct_issues_flagged.
    def flag_or_zero(df, col):
        """0/1 version of a flag column; all 0 when the column doesn't exist yet (raw stage)."""
        if col in df.columns:
            return flag(df[col]).fillna(0)
        return pd.Series(0, index=df.index)

    # ISSUE HANDLED - Issue 1: every Buy/Sell dated on a weekend (dim_date has
    # no market holidays, Issue 15) must carry is_non_trading_day = 1.
    trading = dict(zip(txt(dd["date"]), flag(dd["is_trading_day"])))
    weekend_dated = txt(x["txn_date"]).map(trading) == 0
    buy_sell = txt(x["txn_type"]).isin({"Buy", "Sell"})
    add_rule(R, stage, "fact_transactions",
             f"{ISSUE_PREFIX} Issue 1: Buy/Sell weekend-dated (dim_date has no holidays, "
             f"Issue 15) has is_non_trading_day = 1",
             buy_sell & weekend_dated, flag_or_zero(x, "is_non_trading_day") == 1, x["txn_date"])

    # ISSUE HANDLED - Issue 2: every return_ytd outside 3 x IQR must carry
    # is_return_suspect = 1 OR is_return_outlier = 1.
    r_all = num(p["return_ytd"])
    extreme, _, _ = iqr_outliers(r_all, k=3.0)
    handled = (flag_or_zero(p, "is_return_suspect") == 1) | (flag_or_zero(p, "is_return_outlier") == 1)
    add_rule(R, stage, "fact_portfolio_snapshot",
             f"{ISSUE_PREFIX} Issue 2: return_ytd outside 3x IQR has is_return_suspect = 1 "
             f"or is_return_outlier = 1",
             extreme, handled, p["return_ytd"])

    # Issue 1 (clean only): is_non_trading_day comes from dim_date.is_trading_day, which marks
    # only weekends (no market holidays, Issue 15), so this checks weekend dating.
    label = "is_non_trading_day = 1 exactly when txn_date is weekend-dated (dim_date has no holidays, Issue 15)"
    if need("fact_transactions", "is_non_trading_day", "txn_date", rule=label):
        trading = dict(zip(txt(dd["date"]), flag(dd["is_trading_day"])))
        expected = 1 - txt(x["txn_date"]).map(trading)
        f = flag(x["is_non_trading_day"])
        add_rule(R, stage, "fact_transactions", label,
                 f.notna() & expected.notna(), f == expected, x["txn_date"])

    # Issue 5: is_post_departure_txn, checked in both directions.
    if need("fact_transactions", "is_post_departure_txn", "client_id", "txn_date",
            rule="post-departure flag consistency") and has(c, "client_id", "is_active"):
        f = flag(x["is_post_departure_txn"])
        active = dict(zip(txt(c["client_id"]), flag(c["is_active"])))
        cl_active = txt(x["client_id"]).map(active)
        # Forward: every flagged row belongs to an inactive client
        add_rule(R, stage, "fact_transactions", "is_post_departure_txn = 1 only for inactive clients",
                 (f == 1) & cl_active.notna(), cl_active == 0, x["client_id"])
        # Reverse: every transaction by an inactive client dated in a month AFTER
        # that client's last snapshot month is flagged. Compared at month level
        # because snapshots are dated the 1st of the month (Issue 10). Inactive
        # clients with no snapshot at all have no "last month", so they are skipped.
        last_snap = (pd.DataFrame({"client": txt(p["client_id"]),
                                   "month": dt(p["snapshot_date"]).dt.to_period("M")})
                     .dropna().groupby("client")["month"].max())
        txn_month = dt(x["txn_date"]).dt.to_period("M")
        client_last = txt(x["client_id"]).map(last_snap)
        known = txn_month.notna() & client_last.notna()
        after_last = pd.Series(False, index=x.index)
        after_last[known] = txn_month[known] > client_last[known]
        add_rule(R, stage, "fact_transactions",
                 "inactive client + txn month after last snapshot month => is_post_departure_txn = 1",
                 (cl_active == 0) & after_last & f.notna(), f == 1, x["client_id"])

    # Issue 4: every |return_ytd| > 1 is already flagged suspect.
    if need("fact_portfolio_snapshot", "return_ytd", "is_return_suspect", rule="|return| > 1 is flagged suspect"):
        r = num(p["return_ytd"])
        add_rule(R, stage, "fact_portfolio_snapshot", "is_return_suspect = 1 wherever |return_ytd| > 1",
                 r.abs() > 1, flag(p["is_return_suspect"]) == 1, p["return_ytd"])

    return R, skipped


# ---------------------------------------------------------------------------
# 3. Cross-table reconciliations (reported separately, NOT part of
# pct_rule_pass, because a mismatch here can be a recording convention
# rather than a bad row).
# ---------------------------------------------------------------------------
def rec_row(stage, check, compared, matching, tolerance, detail=""):
    return {"stage": stage, "check": check, "rows_compared": int(compared),
            "rows_matching": int(matching), "pct_matching": pct(int(matching), int(compared)),
            "tolerance": tolerance, "detail": detail}


def run_reconciliations(t, stage):
    out = []
    f, p, x, c = t["fact_fees"], t["fact_portfolio_snapshot"], t["fact_transactions"], t["dim_client"]

    # (a) fee amount = aum_basis x bps_charged / 10,000 / 12  (monthly fee)
    amt, basis, bps = num(f["amount"]), num(f["aum_basis"]), num(f["bps_charged"])
    expected = basis * bps / 10000 / 12
    both = amt.notna() & expected.notna()
    diff = (amt - expected).abs()
    out.append(rec_row(stage, "(a) fee amount = aum_basis x bps_charged / 10000 / 12",
                       both.sum(), (both & (diff <= 0.01)).sum(), "$0.01",
                       f"max diff ${diff[both].max():,.4f}" if both.any() else ""))

    # (b) fee aum_basis vs snapshot aum for the same client and month.
    # Also tried against the PREVIOUS month's snapshot, because a fee is often
    # charged on last month's closing balance - if that matches better, the
    # gap is a timing convention, not an error.
    fees = pd.DataFrame({"client": txt(f["client_id"]),
                         "month": dt(f["fee_date"]).dt.to_period("M"),
                         "basis": basis})
    snaps = pd.DataFrame({"client": txt(p["client_id"]),
                          "month": dt(p["snapshot_date"]).dt.to_period("M"),
                          "aum": num(p["aum"])}).dropna(subset=["month"])
    dup_snaps = int(snaps.duplicated(["client", "month"]).sum())
    snaps = snaps.drop_duplicates(["client", "month"])
    prev = snaps.assign(month=snaps["month"] + 1)       # snapshot moved forward one month
    for label, snap_table in [("same month", snaps), ("previous month", prev)]:
        # LEFT join: every fee row stays in the denominator. A fee with no
        # snapshot for that client-month (or an unreadable basis/aum) can't be
        # reconciled, so it counts as NOT matching rather than disappearing.
        m = fees.merge(snap_table, on=["client", "month"], how="left")
        paired = m["basis"].notna() & m["aum"].notna()
        d = (m["basis"] - m["aum"]).abs()
        rel = d / m["aum"].abs().replace(0, np.nan)
        detail = (f"fee rows with no {label} snapshot (counted as not matching): {int((~paired).sum()):,}; "
                  f"within 0.5%: {pct(int((paired & (rel <= 0.005)).sum()), len(m))}% of all fees; "
                  f"max diff ${d[paired].max():,.4f}; median gap {rel[paired].median() * 100:.4f}%"
                  if paired.any() else "no overlapping client-months")
        if dup_snaps and label == "same month":
            detail += f"; {dup_snaps} duplicate client-month snapshots ignored"
        out.append(rec_row(stage, f"(b) fee aum_basis = snapshot aum ({label})",
                           len(m), (paired & (d <= 0.01)).sum(), "$0.01", detail))

    # (c) transaction amount = shares x price. Compared as absolute values so a
    # sign convention (e.g. negative Sells) doesn't hide a real match; the
    # 'amount > 0' rule reports signs separately. Tolerance is the larger of
    # 1 cent or 0.1%, because price is stored rounded.
    typ = txt(x["txn_type"])
    expected = num(x["shares"]) * num(x["price"])
    amt = num(x["amount"])
    gap = (amt.abs() - expected.abs()).abs()
    tol = np.maximum(0.01, 0.001 * expected.abs())
    for ty in ["Buy", "Sell", "Dividend", "all three"]:
        rows = (typ.isin(SECURITY_TXN_TYPES) if ty == "all three" else typ == ty) \
               & expected.notna() & amt.notna()
        out.append(rec_row(stage, f"(c) txn amount = shares x price [{ty}]",
                           rows.sum(), (rows & (gap <= tol)).sum(), "max($0.01, 0.1%)",
                           f"max diff ${gap[rows].max():,.4f}; median gap ${gap[rows].median():,.4f}"
                           if rows.any() else ""))

    # (d) active_alpha_ytd = return_ytd - benchmark_return_ytd
    if has(p, "active_alpha_ytd", "return_ytd", "benchmark_return_ytd"):
        alpha = num(p["active_alpha_ytd"])
        expected = num(p["return_ytd"]) - num(p["benchmark_return_ytd"])
        both = alpha.notna() & expected.notna()
        d = (alpha - expected).abs()
        out.append(rec_row(stage, "(d) active_alpha_ytd = return_ytd - benchmark_return_ytd",
                           both.sum(), (both & (d <= 0.0002)).sum(), "0.0002 (rounding)",
                           f"max diff {d[both].max():.6f}" if both.any() else ""))

    # (e) Informational: does each fact row's advisor equal the client's
    # assigned advisor in dim_client? This matters for Power BI's two paths
    # to dim_advisor (README section 1). Clients can change advisor over time,
    # so a mismatch is not necessarily an error.
    assigned = dict(zip(txt(c["client_id"]), txt(c["advisor_id"])))
    for name in ["fact_transactions", "fact_fees", "fact_portfolio_snapshot"]:
        df = t[name]
        exp = txt(df["client_id"]).map(assigned)
        rows = exp.notna() & (txt(df["advisor_id"]) != "")
        out.append(rec_row(stage, f"(e) {name}.advisor_id = dim_client.advisor_id",
                           rows.sum(), (rows & (txt(df["advisor_id"]) == exp)).sum(), "exact",
                           "informational: advisor reassignments are legitimate"))
    return out


# ---------------------------------------------------------------------------
# 4. IQR outliers (1.5 x IQR). Counted and printed only - nothing is written
# back to the data.
# ---------------------------------------------------------------------------
def iqr_outliers(values, k=1.5):
    """Return (mask, lower fence, upper fence) for values outside Q1 - k*IQR .. Q3 + k*IQR."""
    v = values.dropna()
    q1, q3 = v.quantile(0.25), v.quantile(0.75)
    lo, hi = q1 - k * (q3 - q1), q3 + k * (q3 - q1)
    return values.notna() & ((values < lo) | (values > hi)), lo, hi


IQR_NOTE = ("'flagged' only means the value is far from the middle of its column - "
            "large trades and very large portfolios are normal for a wealth manager, so a "
            "flagged value is a prompt to look, not proof that it is wrong.")


def report_outliers(t, stage):
    """Print the IQR outlier counts and return one row per column for iqr_outliers.csv."""
    print(f"\n--- IQR outliers (1.5 x IQR), {stage} ---")
    x = t["fact_transactions"]
    rows = []
    for table, col in [("fact_transactions", "amount"), ("fact_portfolio_snapshot", "aum")]:
        vals = num(t[table][col])
        mask, lo, hi = iqr_outliers(vals)
        rows.append({"table": table, "column": col, "stage": stage,
                     "lower_fence": round(lo, 2), "upper_fence": round(hi, 2),
                     "outliers": int(mask.sum()),
                     "pct": pct(int(mask.sum()), int(vals.notna().sum())),
                     "note": IQR_NOTE})
        print(f"{table}.{col}: {int(mask.sum()):,} of {int(vals.notna().sum()):,} values flagged "
              f"({pct(int(mask.sum()), int(vals.notna().sum()))}%), fences {lo:,.2f} to {hi:,.2f}")
        if table == "fact_transactions":
            # Amounts mix very different kinds of transaction, so show which types drive the count
            by_type = txt(x["txn_type"])[mask].value_counts()
            print("    flagged by txn_type: " + ", ".join(f"{k} {v:,}" for k, v in by_type.items()))
    print("Note: " + IQR_NOTE)
    return rows


# ---------------------------------------------------------------------------
# 5. Scorecard
# ---------------------------------------------------------------------------
def legit_blank_mask(name, df):
    """
    True where a blank cell legitimately means "does not apply" (README_clean.md
    section 4). These cells are NOT counted as missing in pct_completeness:
      - dim_security.sector            for non-Equity funds (sector only applies to companies)
      - dim_security.expense_ratio_bps for individual stocks (is_etf = False)
      - fact_transactions.security_id, shares, price for Deposit / Withdrawal /
        Advisory Fee rows (cash movements involve no security)
    The rule "security_id/shares/price blank for Deposit/..." checks that the
    exemption is safe. A blank anywhere else counts as missing.
    """
    mask = pd.DataFrame(False, index=df.index, columns=df.columns)
    if name == "dim_security":
        if has(df, "sector", "asset_class"):
            mask["sector"] = txt(df["asset_class"]) != "Equity"
        if has(df, "expense_ratio_bps", "is_etf"):
            mask["expense_ratio_bps"] = flag(df["is_etf"]) == 0
    if name == "fact_transactions" and "txn_type" in df.columns:
        cash = txt(df["txn_type"]).isin(CASH_TXN_TYPES)
        for col in ["security_id", "shares", "price"]:
            if col in df.columns:
                mask[col] = cash
    return mask


def completeness(name, df):
    blank = df.apply(lambda s: txt(s) == "")
    exempt_blank = blank & legit_blank_mask(name, df)
    required_cells = blank.size - int(exempt_blank.values.sum())   # legit blanks leave the denominator
    missing = int((blank & ~exempt_blank).values.sum())
    return pct(required_cells - missing, required_cells)


def key_uniqueness(name, df):
    """% of rows whose primary key is non-blank and appears exactly once."""
    pk = PRIMARY_KEYS[name]
    if pk not in df.columns:
        return np.nan
    k = txt(df[pk])
    return pct(int(((k != "") & ~k.duplicated(keep=False)).sum()), len(df))


def type_validity(name, df, stage, problems):
    """% of non-blank cells in typed columns (numbers, dates, flags) that parse as that type."""
    checked = valid = 0
    for col in df.columns:
        if is_flag_col(col):
            ok, kind = flag(df[col]).notna(), "flag"
        elif is_date_col(col):
            ok, kind = dt(df[col]).notna(), "date"
        elif col in WHOLE_NUMBER_COLS or col.endswith("_id"):
            v = num(df[col])
            ok, kind = v.notna() & (v % 1 == 0), "whole number"
        elif col in NUMERIC_COLS:
            ok, kind = num(df[col]).notna(), "number"
        else:
            continue
        nonblank = txt(df[col]) != ""
        n_bad = int((nonblank & ~ok).sum())
        checked += int(nonblank.sum())
        valid += int((nonblank & ok).sum())
        if n_bad:
            sample = "; ".join(txt(df[col])[nonblank & ~ok].unique()[:3])
            problems.append(f"{stage} {name}.{col}: {n_bad:,} not a valid {kind} (e.g. {sample})")
    return pct(valid, checked)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not HW_DIR.exists():
        sys.exit("ERROR: hw04/ not found. Run from the repo root: C:\\MIS3060\\mis3060-bi-ai")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    ri_all, rules_all, recs_all, score_rows, type_problems = [], [], [], [], []
    iqr_rows = []

    for stage in ["raw", "clean"]:
        print("\n" + "=" * 78 + f"\nSTAGE: {stage.upper()}  ({STAGE_DIRS[stage]})\n" + "=" * 78)
        t = load_stage(stage)

        ri = run_ri(t, stage)
        rules, skipped = run_rules(t, stage)
        recs = run_reconciliations(t, stage)
        ri_all += ri
        rules_all += rules
        recs_all += recs

        # Readable RI summary
        ri_df = pd.DataFrame(ri)
        print("\n--- Referential integrity ---")
        print(ri_df[["relationship_id", "relationship", "match_rate_pct", "orphan_rows",
                     "distinct_orphan_keys", "null_key_rate_pct"]].to_string(index=False))
        print("(Null keys are reported separately from orphans. ~34% null on relationship 8 "
              "is expected: cash transactions have no security.)")

        # Rule summary: show failures, count passes
        rule_df = pd.DataFrame(rules)
        fails = rule_df[rule_df["rows_failed"] > 0]
        print(f"\n--- Business rules: {len(rule_df)} rules, "
              f"{len(rule_df) - len(fails)} fully passed, {len(fails)} with failures ---")
        if len(fails):
            print(fails[["table", "rule", "rows_checked", "rows_failed", "pct_pass",
                         "sample_failing_values"]].to_string(index=False))
        for s in skipped:
            print(f"  skipped (column not in this stage): {s}")

        print("\n--- Reconciliations ---")
        print(pd.DataFrame(recs)[["check", "rows_compared", "pct_matching", "detail"]]
              .to_string(index=False))

        iqr_rows += report_outliers(t, stage)

        # Scorecard rows for this stage
        for name in TABLES:
            df = t[name]
            tr = rule_df[rule_df["table"] == name]
            ri_t = ri_df[ri_df["fact_table"] == name]
            # "Issue handled" rules are circular by design: they prove every known
            # issue row carries a flag, not that the underlying values are correct.
            # They are why pct_rule_pass is below 100% on raw and 100% on clean.
            ih = tr[tr["rule"].str.startswith(ISSUE_PREFIX)]
            score_rows.append({
                "table": name,
                "stage": stage,
                "rows": len(df),
                # Completeness excludes legitimately blank fields - see legit_blank_mask()
                "pct_completeness": completeness(name, df),
                "pct_key_uniqueness": key_uniqueness(name, df),
                "pct_type_validity": type_validity(name, df, stage, type_problems),
                # % of individual rule checks passed (reconciliations not included)
                "pct_rule_pass": pct(int(tr["rows_checked"].sum() - tr["rows_failed"].sum()),
                                     int(tr["rows_checked"].sum())),
                # Matched non-null foreign keys / all non-null foreign keys, across every
                # relationship where this table is the many side. Blank for tables with
                # no foreign keys (dim_advisor, dim_date, dim_benchmark).
                "pct_referential_match": pct(int(ri_t["matched_rows"].sum()),
                                             int(ri_t["non_null_rows"].sum())),
                # % of known-issue rows (decision log Issues 1 and 2) that carry a flag.
                # Blank for tables with no known issue to flag.
                "pct_issues_flagged": pct(int(ih["rows_checked"].sum() - ih["rows_failed"].sum()),
                                          int(ih["rows_checked"].sum())),
            })

    if type_problems:
        print("\n--- Type-validity problems ---")
        for line in type_problems:
            print("  " + line)

    # Save reports
    score = pd.DataFrame(score_rows)
    score["table"] = pd.Categorical(score["table"], TABLES, ordered=True)
    score = score.sort_values(["table", "stage"], key=lambda s: s.map({"raw": 0, "clean": 1})
                              if s.name == "stage" else s).reset_index(drop=True)
    score.to_csv(REPORTS_DIR / "data_quality_scorecard.csv", index=False)
    pd.DataFrame(ri_all).to_csv(REPORTS_DIR / "ri_results.csv", index=False)
    pd.DataFrame(rules_all).to_csv(REPORTS_DIR / "rule_results.csv", index=False)
    pd.DataFrame(recs_all).to_csv(REPORTS_DIR / "reconciliation_results.csv", index=False)
    pd.DataFrame(iqr_rows).to_csv(REPORTS_DIR / "iqr_outliers.csv", index=False)

    print("\n" + "=" * 78 + "\nDATA QUALITY SCORECARD\n" + "=" * 78)
    print(score.to_string(index=False))
    print(f"\nSaved to {REPORTS_DIR}: data_quality_scorecard.csv, ri_results.csv, "
          "rule_results.csv, reconciliation_results.csv, iqr_outliers.csv")
    print("iqr_outliers.csv: Note: " + IQR_NOTE)

    # Every report is already on disk at this point, so a failed assertion
    # below never leaves you without the CSVs you need to investigate it.
    self_test_ri()
    assert_clean_stage(ri_all, rules_all, recs_all)


# ---------------------------------------------------------------------------
# 6. Assertions on the CLEAN stage (run after all reports are written)
# The raw stage is allowed to fail - finding those failures is the point.
# The clean stage is what goes to Power BI, so it must pass these outright.
# All problems are collected first, so one run shows every failure at once.
# ---------------------------------------------------------------------------
def assert_clean_stage(ri_all, rules_all, recs_all):
    problems = []

    # (1) No orphans in any of the 13 relationships (null keys are allowed)
    for r in ri_all:
        if r["stage"] == "clean" and r["orphan_rows"] > 0:
            problems.append(f"RI {r['relationship_id']} {r['relationship']}: "
                            f"{r['orphan_rows']:,} orphan rows (e.g. {r['sample_orphan_keys']})")

    # (2) 100% rule pass: no clean rule may have a single failing row
    for r in rules_all:
        if r["stage"] == "clean" and r["rows_failed"] > 0:
            problems.append(f"Rule [{r['table']}] {r['rule']}: {r['rows_failed']:,} failing rows "
                            f"({r['sample_failing_values']})")

    # (3) Reconciliations (a), (c) and (d) must match on every row compared.
    # (b) and (e) are excluded on purpose: they compare tables that can
    # legitimately disagree (timing, missing fee months, advisor changes).
    for r in recs_all:
        if r["stage"] == "clean" and r["check"][:3] in {"(a)", "(c)", "(d)"} \
                and r["rows_matching"] != r["rows_compared"]:
            problems.append(f"Reconciliation {r['check']}: {r['rows_matching']:,} of "
                            f"{r['rows_compared']:,} match ({r['detail']})")

    # (4) "Issue handled" rules: raw must fail exactly the counts in the
    # decision log (the issues exist, unflagged); clean must fail 0.
    for key, expected_raw in EXPECTED_RAW_ISSUE_FAILS.items():
        for stage, expected in [("raw", expected_raw), ("clean", 0)]:
            hits = [r for r in rules_all if r["stage"] == stage
                    and r["rule"].startswith(f"{ISSUE_PREFIX} {key}")]
            got = sum(r["rows_failed"] for r in hits)
            if len(hits) != 1 or got != expected:
                problems.append(f"{ISSUE_PREFIX} {key} {stage}: expected {expected:,} failing rows, "
                                f"got {got:,} ({len(hits)} matching rule(s))")

    if problems:
        print("\n" + "=" * 78 + f"\nCLEAN-STAGE ASSERTIONS FAILED ({len(problems)})\n" + "=" * 78)
        for line in problems:
            print("  - " + line)
    assert not problems, f"{len(problems)} clean-stage check(s) failed - see the list above"
    print("\nClean-stage assertions passed: 0 orphans, 100% rule pass, "
          "100% on reconciliations (a), (c), (d).")
    print("Issue-handled counts match the decision log: Issue 1 raw 40,630 -> clean 0; "
          "Issue 2 raw 576 -> clean 0.")


# ---------------------------------------------------------------------------
# 7. Self-test for check_referential_integrity
# Loads the same tables twice: as text (how this script reads them) and with a
# plain pd.read_csv, where pandas guesses types - security_id becomes a float
# column (5 -> 5.0) with NaN on cash rows. Relationship 8 is used because it
# has both nulls and float-looking keys. Both loads must give the same answer;
# this is what makes the function safe to reuse in HW5.
# ---------------------------------------------------------------------------
def self_test_ri(stage="clean"):
    folder = STAGE_DIRS[stage]
    as_text = dict(dtype=str, keep_default_na=False, encoding="utf-8-sig")
    fact_text = pd.read_csv(folder / "fact_transactions.csv", **as_text)
    dim_text = pd.read_csv(folder / "dim_security.csv", **as_text)
    fact_plain = pd.read_csv(folder / "fact_transactions.csv", low_memory=False)
    dim_plain = pd.read_csv(folder / "dim_security.csv")

    a = check_referential_integrity(fact_text, "security_id", dim_text, "security_id")
    b = check_referential_integrity(fact_plain, "security_id", dim_plain, "security_id")
    for key in ["match_rate_pct", "orphan_rows", "distinct_orphan_keys", "null_key_rows"]:
        assert a[key] == b[key], (f"self-test failed on {key}: text load {a[key]} "
                                  f"vs plain load {b[key]}")
    print(f"\nSelf-test passed: check_referential_integrity gives the same result for a text load "
          f"and a plain pd.read_csv load (match rate {a['match_rate_pct']}%, "
          f"{a['null_key_rows']:,} null keys, plain-load dtype {fact_plain['security_id'].dtype}).")


if __name__ == "__main__":
    main()
