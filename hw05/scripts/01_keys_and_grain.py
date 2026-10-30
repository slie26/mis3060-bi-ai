r"""
01_keys_and_grain.py -- HW5: keys, grain and measures for the Wildcat Capital star schema

Run from the repo root:
    cd C:\MIS3060\mis3060-bi-ai
    python hw05/scripts/01_keys_and_grain.py

This script is READ-ONLY for data: it never changes a file in hw05/data/.
It only writes one report: hw05/reports/keys_and_grain.csv
(columns: check, table, result, detail).

What it checks (and which part of the handout it supports):
  1. Row and column counts and headers match the HW5 handout     (setup)
  2. Every primary key is non-blank, unique and a plain whole
     number; dim_date.date is non-blank, unique and YYYY-MM-DD   (Part A)
  3. All 13 foreign-key relationships: 0 orphans, 0 blanks on
     required keys, 0 keys that only match after clean-up;
     blank security_id only on cash transactions                 (Part A)
  4. Fact dates match dim_date.date exactly and dim_date.date_id
     not at all                                                   (Part E c)
  5. Candidate grains of each fact table; fee/snapshot dates are
     the 1st of the month                                         (Part B)
  6. Advisor paths: fact advisor_id vs the client's advisor       (Part E b)
  7. Snowflake links dim_client -> dim_advisor and
     dim_security -> dim_benchmark; one benchmark per client?     (Part E d)
  8. Every numeric-looking column in each fact table, with min,
     max and its role (key, date part, flag or measure), plus any
     column that was skipped and why                              (Part C)

Blank keys: in every key column, an empty cell AND the text "NULL", "None"
or "N/A" (any case) count as blank. Those words are not real IDs.

Result values in the report:
  PASS / FAIL          a check that must hold
  UNIQUE / NOT UNIQUE  a grain candidate (informational - both outcomes are useful)
  SKIPPED              a fact-table column section 8 could not summarise, with the reason
  INFO                 a fact to use in star_design.md, not a pass/fail test

The report is saved first. If any check is FAIL, the script lists every
failure and exits with code 1; otherwise it prints exactly what was enforced.
"""

from pathlib import Path
import sys

import numpy as np
import pandas as pd

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", None)
pd.set_option("display.max_colwidth", 80)

# ---------------------------------------------------------------------------
# Paths and settings
# ---------------------------------------------------------------------------
REPO_ROOT = Path.cwd()                      # the script must be run from the repo root
HW_DIR = REPO_ROOT / "hw05"
DATA_DIR = HW_DIR / "data"
REPORTS_DIR = HW_DIR / "reports"
REPORT_FILE = REPORTS_DIR / "keys_and_grain.csv"

DATE_FORMAT = "%Y-%m-%d"                    # all dates in the extract are YYYY-MM-DD

TABLES = [
    "dim_advisor", "dim_benchmark", "dim_client", "dim_date", "dim_security",
    "fact_fees", "fact_portfolio_snapshot", "fact_transactions",
]
FACT_TABLES = ["fact_transactions", "fact_fees", "fact_portfolio_snapshot"]

# Rows and columns from the "Data" table in the HW5 handout.
EXPECTED_SHAPE = {
    "dim_advisor": (25, 7),
    "dim_benchmark": (8, 4),
    "dim_client": (2_500, 14),
    "dim_date": (1_827, 12),
    "dim_security": (500, 8),
    "fact_fees": (122_197, 8),
    "fact_portfolio_snapshot": (129_547, 14),
    "fact_transactions": (298_572, 10),
}

# The headers each file should have, in order.
EXPECTED_COLUMNS = {
    "dim_advisor": ["advisor_id", "first_name", "last_name", "region", "years_experience",
                    "aum_target_mm", "certifications"],
    "dim_benchmark": ["benchmark_id", "name", "asset_class", "ticker_proxy"],
    "dim_client": ["client_id", "first_name", "last_name", "age", "city", "state", "zip_code",
                   "risk_profile", "client_tier", "primary_account_type", "initial_aum",
                   "client_since", "advisor_id", "is_active"],
    "dim_date": ["date_id", "date", "year", "quarter", "month", "month_name", "week_of_year",
                 "day_of_week", "is_month_end", "is_quarter_end", "is_year_end", "is_trading_day"],
    "dim_security": ["security_id", "ticker", "name", "asset_class", "sector", "benchmark_id",
                     "is_etf", "expense_ratio_bps"],
    "fact_transactions": ["txn_id", "client_id", "advisor_id", "security_id", "txn_date",
                          "txn_type", "shares", "price", "amount", "is_post_departure_txn"],
    "fact_fees": ["fee_id", "client_id", "advisor_id", "fee_date", "fee_type", "aum_basis",
                  "bps_charged", "amount"],
    "fact_portfolio_snapshot": ["snapshot_id", "client_id", "advisor_id", "benchmark_id",
                                "snapshot_date", "year", "month", "aum", "return_ytd",
                                "benchmark_return_ytd", "active_alpha_ytd", "cash_pct",
                                "account_type", "is_return_suspect"],
}

# Primary key of each table (Part A). All must be plain whole numbers.
PRIMARY_KEYS = {
    "dim_advisor": "advisor_id",
    "dim_benchmark": "benchmark_id",
    "dim_client": "client_id",
    "dim_date": "date_id",
    "dim_security": "security_id",
    "fact_transactions": "txn_id",
    "fact_fees": "fee_id",
    "fact_portfolio_snapshot": "snapshot_id",
}

# The 13 relationships (same numbering as HW4).
# (id, many-side table, foreign key, one-side table, column it points to)
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

# Foreign keys that may legitimately be blank. Every other foreign key above
# is REQUIRED: a single blank is a FAIL. security_id is blank on cash rows,
# and section 3 separately checks that it is blank ONLY on cash rows.
ALLOWED_BLANK_FKS = {("fact_transactions", "security_id")}

# Transactions that move cash and involve no security (blank security_id is expected).
CASH_TXN_TYPES = {"Deposit", "Withdrawal", "Advisory Fee"}

# Date columns in each fact table (used for the date-join proof and date checks).
FACT_DATE_COLS = {
    "fact_transactions": "txn_date",
    "fact_fees": "fee_date",
    "fact_portfolio_snapshot": "snapshot_date",
}

# Candidate grains to test (Part B). Each is a list of columns that might
# identify one row. The script reports whether each combination is unique.
GRAIN_CANDIDATES = [
    ("fact_transactions", ["txn_id"]),
    ("fact_fees", ["client_id", "fee_date"]),
    ("fact_fees", ["client_id", "fee_date", "fee_type"]),
    ("fact_portfolio_snapshot", ["client_id", "snapshot_date"]),
    ("fact_portfolio_snapshot", ["client_id", "snapshot_date", "account_type"]),
]

# Numeric columns that describe the date rather than measure anything (Part C).
DATE_PART_COLS = {"year", "quarter", "month"}

# Text that means "no value" when it appears in a key column (compared in lower case).
NULL_TOKENS = {"null", "none", "n/a"}


# ---------------------------------------------------------------------------
# Small helpers. Everything is read as text, so these only make a parsed
# COPY for checking - the loaded tables are never changed.
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


def fmt_num(v):
    """Readable number: whole numbers with commas, others with 4 decimals."""
    if pd.isna(v):
        return ""
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.4f}"


def is_null_token(s):
    """True where a cell holds NULL / None / N/A (any case, spaces ignored)."""
    return txt(s).str.lower().isin(NULL_TOKENS)


def key_text(s):
    """Trimmed key text, with NULL / None / N/A turned into blank."""
    return txt(s).mask(is_null_token(s), "")


def with_blank_tokens(df, col):
    """
    A COPY of df in which NULL / None / N/A in `col` become "", so
    check_referential_integrity counts them as blank keys instead of orphans.
    Everything else in the cell is left exactly as loaded (spaces included),
    so the normalisation check below can still see it.
    """
    out = df.copy()
    out[col] = df[col].astype(str).mask(is_null_token(df[col]), "")
    return out


def quoted(values, n=5):
    """Up to n distinct values in quotes, so leading/trailing spaces are visible."""
    return "; ".join(f"'{v}'" for v in pd.Series(values).unique()[:n])


# ---------------------------------------------------------------------------
# Results collector. Every check adds one row to RESULTS, which becomes
# keys_and_grain.csv. show=True also prints the line.
# ---------------------------------------------------------------------------
RESULTS = []


def record(check, table, result, detail, show=True):
    RESULTS.append({"check": check, "table": table, "result": result, "detail": detail})
    if show:
        print(f"  [{result}] {table}: {check}\n          {detail}")


def pass_fail(ok):
    return "PASS" if ok else "FAIL"


def section(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_tables():
    """Read all eight CSVs as text, exactly as stored."""
    if not DATA_DIR.exists():
        sys.exit(f"ERROR: {DATA_DIR} not found. Run from the repo root: C:\\MIS3060\\mis3060-bi-ai")
    tables = {}
    for name in TABLES:
        path = DATA_DIR / f"{name}.csv"
        if not path.exists():
            sys.exit(f"ERROR: {path} not found.")
        # dtype=str + keep_default_na=False: every cell stays as its original text
        # (blanks stay "", 'None' stays 'None'). utf-8-sig drops a byte-order mark if present.
        tables[name] = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    return tables


# ---------------------------------------------------------------------------
# check_referential_integrity -- copied UNCHANGED from HW4 03_validate.py
# (together with the _normalise_keys helper it relies on; pct() is above).
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


def normalisation_only_matches(fact_df, fact_key, dim_df, dim_key):
    """
    Keys that check_referential_integrity counts as matched ONLY because it
    trims spaces and drops a trailing ".0" (e.g. " 45" or "45.0" vs "45").
    Power BI compares the stored values, so these would not join cleanly.
    Returns (number of rows, sample values in quotes).
    """
    f_raw = fact_df[fact_key].astype(str)
    d_raw = dim_df[dim_key].astype(str)
    f_norm, f_null = _normalise_keys(fact_df[fact_key])
    d_norm, d_null = _normalise_keys(dim_df[dim_key])
    exact = f_raw.isin(set(d_raw[~d_null]))         # matches the stored value as-is
    loose = f_norm.isin(set(d_norm[~d_null]))       # matches only after clean-up
    mask = ~f_null & loose & ~exact
    return int(mask.sum()), quoted(f_raw[mask])


# ---------------------------------------------------------------------------
# 1. Row and column counts
# ---------------------------------------------------------------------------
def check_row_counts(t):
    """Compare each table's shape and headers with the handout. Returns False if
    a required column is missing (the later checks would crash without it)."""
    section("1. Row and column counts vs the HW5 handout")
    all_columns_present = True
    for name in TABLES:
        df = t[name]
        exp_rows, exp_cols = EXPECTED_SHAPE[name]
        record("row and column count match handout", name,
               pass_fail(df.shape == (exp_rows, exp_cols)),
               f"{len(df):,} rows x {df.shape[1]} cols (handout: {exp_rows:,} x {exp_cols})")

        expected, got = EXPECTED_COLUMNS[name], list(df.columns)
        missing = [c for c in expected if c not in got]
        extra = [c for c in got if c not in expected]
        if got == expected:
            detail = "all headers present, in the expected order"
        else:
            detail = (f"missing: {missing or 'none'}; unexpected: {extra or 'none'}"
                      + ("; same columns but in a different order" if not missing and not extra else ""))
        record("column headers match expected list", name, pass_fail(got == expected), detail)
        if missing:
            all_columns_present = False
    return all_columns_present


# ---------------------------------------------------------------------------
# 2. Primary keys (Part A)
# ---------------------------------------------------------------------------
def check_unique_key(t, table, col, check_name, kind):
    """
    A key must be non-blank on every row, appear exactly once, and be stored
    in a clean format:
      kind="whole number" -> digits only, e.g. 42 (not 42.0, not ' 42')
      kind="date"         -> YYYY-MM-DD and a real calendar date (not ' 2020-01-01')
    NULL / None / N/A count as blank.
    """
    raw = t[table][col].astype(str)
    k = key_text(raw)
    nonblank = k != ""
    blanks = int((~nonblank).sum())
    tokens = int(is_null_token(raw).sum())

    dup_rows = k[nonblank].duplicated(keep=False)
    n_dup_rows = int(dup_rows.sum())

    # The format test runs on the value exactly as stored, so stray spaces fail.
    if kind == "whole number":
        fmt_ok = raw.str.fullmatch(r"\d+")
    else:
        fmt_ok = raw.str.fullmatch(r"\d{4}-\d{2}-\d{2}") & dt(raw).notna()
    bad_fmt = nonblank & ~fmt_ok
    n_bad_fmt = int(bad_fmt.sum())

    detail = (f"{len(k):,} rows, {k[nonblank].nunique():,} distinct values, "
              f"{blanks:,} blank ({tokens:,} of them written as NULL/None/N/A), "
              f"{n_dup_rows:,} rows share a value, {n_bad_fmt:,} not a plain {kind}")
    if n_dup_rows:
        examples = k[nonblank][dup_rows].value_counts().head(3)
        detail += "; duplicates e.g. " + "; ".join(f"'{v}' x{c}" for v, c in examples.items())
    if n_bad_fmt:
        detail += f"; bad format e.g. {quoted(raw[bad_fmt], 3)}"
    ok = blanks == 0 and n_dup_rows == 0 and n_bad_fmt == 0
    record(check_name, table, pass_fail(ok), detail)


def check_primary_keys(t):
    section("2. Primary keys: non-blank, unique and cleanly formatted (Part A)")
    for table, pk in PRIMARY_KEYS.items():
        check_unique_key(t, table, pk, f"primary key {pk} is non-blank, unique and a whole number",
                         "whole number")
    # The facts join to dim_date on the calendar date, not date_id (see section 4),
    # so 'date' must also be unique or the relationship would be many-to-many.
    check_unique_key(t, "dim_date", "date",
                     "date (the column facts join on) is non-blank, unique and YYYY-MM-DD", "date")


# ---------------------------------------------------------------------------
# 3. Foreign keys (Part A)
# ---------------------------------------------------------------------------
def check_foreign_keys(t):
    section("3. Foreign keys: referential integrity on all 13 relationships (Part A)")
    ri = {}
    rows = []
    for rel_id, fact, fkey, dim, dkey in RELATIONSHIPS:
        # NULL / None / N/A become blank on a COPY, so they count as blank keys, not orphans.
        f_df, d_df = with_blank_tokens(t[fact], fkey), with_blank_tokens(t[dim], dkey)
        res = check_referential_integrity(f_df, fkey, d_df, dkey)
        n_loose, loose_eg = normalisation_only_matches(f_df, fkey, d_df, dkey)
        res["normalised_only_rows"] = n_loose
        ri[rel_id] = res

        blank_allowed = (fact, fkey) in ALLOWED_BLANK_FKS
        label = f"{fact}.{fkey} -> {dim}[{dkey}]"
        rows.append({"id": rel_id, "relationship": label,
                     "blanks": "allowed" if blank_allowed else "required",
                     "match_rate_pct": res["match_rate_pct"], "orphans": res["orphan_rows"],
                     "null_keys": res["null_key_rows"], "null_rate_pct": res["null_key_rate_pct"],
                     "match_after_cleanup_only": n_loose,
                     "dup_keys_on_one_side": res["dim_duplicate_keys"]})

        # Each of these breaks the relationship in Power BI.
        problems = []
        if res["orphan_rows"]:
            problems.append(f"{res['orphan_rows']:,} orphans (e.g. {res['sample_orphan_keys']})")
        if res["null_key_rows"] and not blank_allowed:
            problems.append(f"{res['null_key_rows']:,} blank keys on a required foreign key")
        if n_loose:
            problems.append(f"{n_loose:,} keys match only after trimming spaces or dropping '.0' "
                            f"(e.g. {loose_eg})")
        if res["dim_duplicate_keys"]:
            problems.append(f"{res['dim_duplicate_keys']:,} duplicate keys on the one side")

        detail = (f"match {res['match_rate_pct']}% of {res['non_null_rows']:,} non-blank keys; "
                  f"{res['orphan_rows']:,} orphans; "
                  f"null-key rate {res['null_key_rate_pct']}% ({res['null_key_rows']:,} blank, "
                  f"{'allowed' if blank_allowed else 'not allowed'}); "
                  f"{n_loose:,} match only after clean-up; "
                  f"{res['dim_duplicate_keys']} duplicate keys on the one side")
        if problems:
            detail += ". FAIL because: " + "; ".join(problems)
        record(f"RI {rel_id}: {label} is a clean join", fact, pass_fail(not problems), detail,
               show=False)
    print(pd.DataFrame(rows).to_string(index=False))

    failed = [r for r in RESULTS if r["check"].startswith("RI ") and r["result"] == "FAIL"]
    if failed:
        print("\n  Relationships that FAIL:")
        for r in failed:
            print(f"    {r['check']}\n      {r['detail'].split('FAIL because: ')[-1]}")
    else:
        print("\n  All 13 relationships PASS: 0 orphans, 0 blanks on required keys, "
              "0 keys that need clean-up to match.")

    # Blank security_id must only appear on cash movements (Part E a).
    x = t["fact_transactions"]
    typ = txt(x["txn_type"])
    blank_sec = key_text(x["security_id"]) == ""
    by_type = typ[blank_sec].value_counts()
    bad = blank_sec & ~typ.isin(CASH_TXN_TYPES)
    detail = (f"{int(blank_sec.sum()):,} rows have a blank security_id: "
              + (", ".join(f"{k} {v:,}" for k, v in by_type.items()) or "none")
              + f"; {int(bad.sum()):,} of them are NOT Deposit/Withdrawal/Advisory Fee")
    print()
    record("blank security_id only on Deposit, Withdrawal and Advisory Fee rows",
           "fact_transactions", pass_fail(int(bad.sum()) == 0), detail)

    # The reverse is informational: do all cash rows have a blank security_id?
    cash = typ.isin(CASH_TXN_TYPES)
    cash_with_sec = int((cash & ~blank_sec).sum())
    record("cash rows (Deposit/Withdrawal/Advisory Fee) with a security_id", "fact_transactions",
           "INFO", f"{cash_with_sec:,} of {int(cash.sum()):,} cash rows carry a security_id")
    return ri


# ---------------------------------------------------------------------------
# 4. Date join proof (Part E c)
# PASS needs every fact date to be non-blank and found in dim_date.date
# (counts, not a rounded %), and no fact date to be found in dim_date.date_id.
# ---------------------------------------------------------------------------
def check_date_join(t):
    section("4. Which dim_date column do the fact dates match? (Part E c)")
    dd = t["dim_date"]
    dd_date = with_blank_tokens(dd, "date")
    print(f"  dim_date sample: date_id = {', '.join(dd['date_id'].head(3))}  |  "
          f"date = {', '.join(dd['date'].head(3))}")
    for fact, col in FACT_DATE_COLS.items():
        f_df = with_blank_tokens(t[fact], col)
        on_date = check_referential_integrity(f_df, col, dd_date, "date")
        on_id = check_referential_integrity(f_df, col, dd, "date_id")
        ok = (on_date["orphan_rows"] == 0 and on_date["null_key_rows"] == 0
              and on_id["matched_rows"] == 0)
        detail = (f"vs dim_date.date: {on_date['matched_rows']:,} matched, "
                  f"{on_date['orphan_rows']:,} orphans, {on_date['null_key_rows']:,} blank; "
                  f"vs dim_date.date_id: {on_id['matched_rows']:,} matched "
                  f"(sample {col}: {', '.join(t[fact][col].head(2))})")
        record("fact date joins to dim_date.date (0 orphans, 0 blanks), never to dim_date.date_id",
               fact, pass_fail(ok), detail)


# ---------------------------------------------------------------------------
# 5. Grain (Part B)
# A combination is UNIQUE only if no two rows share it AND no row has a
# blank in any of its columns (a blank can't identify a row).
# ---------------------------------------------------------------------------
def check_grain(t):
    section("5. Grain: which column combinations identify one row? (Part B)")
    for fact, cols in GRAIN_CANDIDATES:
        df = t[fact]
        keys = df[cols].apply(key_text)
        any_blank = int((keys == "").any(axis=1).sum())
        dup_mask = keys.duplicated(keep=False)
        n_combos = len(keys.drop_duplicates())
        unique = not dup_mask.any() and any_blank == 0
        detail = (f"{len(df):,} rows, {n_combos:,} distinct combinations, "
                  f"{int(dup_mask.sum()):,} rows share a combination, "
                  f"{any_blank:,} rows have a blank (or NULL/None/N/A) in these columns")
        if any_blank:
            detail += ". NOT UNIQUE because rows with a blank grain column can't be identified"
        if dup_mask.any():
            # Show one repeated combination and which other columns tell those rows apart.
            first = keys[dup_mask].iloc[0]
            same = (keys == first).all(axis=1)
            group = df[same]
            differ = [c for c in df.columns if c not in cols and group[c].nunique() > 1]
            detail += (f". Example: ({', '.join(first)}) appears {int(same.sum())} times; "
                       f"those rows differ in: {', '.join(differ) or 'nothing (exact duplicates)'}")
        record(f"grain candidate ({', '.join(cols)}) is unique", fact,
               "UNIQUE" if unique else "NOT UNIQUE", detail)

    # Fees and snapshots are monthly, dated on the 1st of the month.
    print()
    for fact in ["fact_fees", "fact_portfolio_snapshot"]:
        col = FACT_DATE_COLS[fact]
        d = dt(t[fact][col])
        unreadable = int(d.isna().sum())
        not_first = int((d.notna() & (d.dt.day != 1)).sum())
        detail = (f"{len(d):,} rows, {not_first:,} not on the 1st, {unreadable:,} blank or unreadable; "
                  f"range {d.min():%Y-%m-%d} to {d.max():%Y-%m-%d}" if d.notna().any()
                  else f"{unreadable:,} blank or unreadable dates")
        record(f"every {col} is the 1st of a month", fact,
               pass_fail(unreadable == 0 and not_first == 0), detail)


# ---------------------------------------------------------------------------
# 6. Advisor paths (Part E b)
# advisor_id reaches dim_advisor two ways: directly from each fact table, and
# via fact -> dim_client -> dim_advisor. If the two always agreed, either path
# would give the same answer; where they differ, the choice of active
# relationship changes the numbers.
# ---------------------------------------------------------------------------
def check_advisor_paths(t):
    section("6. Advisor paths: fact advisor_id vs the client's advisor in dim_client (Part E b)")
    c = t["dim_client"]
    assigned = dict(zip(key_text(c["client_id"]), key_text(c["advisor_id"])))
    for fact in FACT_TABLES:
        df = t[fact]
        client = key_text(df["client_id"])
        fact_adv = key_text(df["advisor_id"])
        client_adv = client.map(assigned)
        compared = client_adv.notna() & (fact_adv != "")
        same = compared & (fact_adv == client_adv)
        # Clients whose rows in this fact table carry more than one advisor_id
        multi = (pd.DataFrame({"client": client, "adv": fact_adv})[fact_adv != ""]
                 .groupby("client")["adv"].nunique())
        detail = (f"{pct(int(same.sum()), int(compared.sum()))}% of {int(compared.sum()):,} rows match "
                  f"({int((compared & ~same).sum()):,} differ); "
                  f"{int((multi > 1).sum()):,} clients appear with more than one advisor_id here")
        record("fact advisor_id = dim_client.advisor_id for that client", fact, "INFO", detail)


# ---------------------------------------------------------------------------
# 7. Snowflake links (Part E d)
# ---------------------------------------------------------------------------
def check_snowflake(t, ri):
    section("7. Dimension-to-dimension links (Part E d)")
    for rel_id, child, fkey, parent, pkey in [r for r in RELATIONSHIPS if r[0] in (1, 9)]:
        res = ri[rel_id]
        used = key_text(t[child][fkey])
        distinct_parents = used[used != ""].nunique()
        ok = (res["orphan_rows"] == 0 and res["null_key_rows"] == 0
              and res["normalised_only_rows"] == 0)
        detail = (f"{res['matched_rows']:,} of {res['total_rows']:,} {child} rows point to an existing "
                  f"{parent} row; {res['orphan_rows']:,} orphans; {res['null_key_rows']:,} blank; "
                  f"{res['normalised_only_rows']:,} match only after clean-up; "
                  f"{distinct_parents} distinct {fkey} values used out of {len(t[parent]):,} {parent} rows")
        record(f"snowflake link {child}.{fkey} -> {parent}[{pkey}] is valid", child,
               pass_fail(ok), detail)

    # Does each client always have the same benchmark in the snapshots? If yes,
    # benchmark behaves like a client attribute; if not, it belongs on the fact.
    p = t["fact_portfolio_snapshot"]
    snap = pd.DataFrame({"client": key_text(p["client_id"]), "bm": key_text(p["benchmark_id"])})
    clients_in_snap = snap["client"].nunique()
    per_client = snap[snap["bm"] != ""].groupby("client")["bm"].nunique()
    exactly_one = int((per_client == 1).sum())
    more = per_client[per_client > 1]
    blank_only = clients_in_snap - len(per_client)
    no_snapshot = len(t["dim_client"]) - clients_in_snap
    detail = (f"{'Yes' if len(more) == 0 and blank_only == 0 else 'No'} - "
              f"{clients_in_snap:,} clients have snapshots: {exactly_one:,} have exactly one benchmark_id, "
              f"{len(more):,} have more than one, {blank_only:,} only blank; "
              f"{no_snapshot:,} dim_client rows have no snapshot")
    if len(more):
        ex = more.index[0]
        detail += (f". Example: client {ex} has benchmark_id "
                   f"{', '.join(sorted(snap.loc[snap['client'] == ex, 'bm'].unique()))}")
    record("each client has exactly one benchmark_id in the snapshots",
           "fact_portfolio_snapshot", "INFO", detail)


# ---------------------------------------------------------------------------
# 8. Numeric columns in the fact tables (Part C)
# The script only says what ROLE each column plays. Deciding whether a
# measure is additive, semi-additive or non-additive is your job in
# star_design.md - the min/max and negative counts are there to help.
# Nothing is dropped silently: a column is either listed, reported as
# SKIPPED with the reason, or named as a text/date column.
# ---------------------------------------------------------------------------
def role_of(col):
    if col.endswith("_id"):
        return "key"
    if col in DATE_PART_COLS:
        return "date part"
    if col.startswith("is_"):
        return "flag"
    return "measure"


def check_numeric_columns(t):
    section("8. Numeric-looking columns in the fact tables (Part C)")
    rows, skipped, text_cols = [], [], []
    for fact in FACT_TABLES:
        df = t[fact]
        for col in df.columns:
            s = txt(df[col])
            nonblank = s != ""
            is_flag = col.startswith("is_")
            # Flags may be stored as 0/1 or True/False; both count as numeric (0/1).
            values = flag(df[col]) if is_flag else num(df[col])
            if not nonblank.any():
                skipped.append((fact, col, "every value is blank, so there is no min or max to report"))
                continue
            parsed_share = values[nonblank].notna().mean()
            if parsed_share == 0 and not is_flag:
                text_cols.append(f"{fact}.{col}")   # text or dates: not a numeric column
                continue
            if parsed_share < 0.9:
                bad = s[nonblank & values.isna()]
                kind = "0/1 or True/False" if is_flag else "numbers"
                skipped.append((fact, col, f"only {parsed_share * 100:.1f}% of non-blank values are "
                                           f"{kind} (e.g. {quoted(bad, 3)}); fix or explain this "
                                           f"column before classifying it"))
                continue
            unparsed = int((nonblank & values.isna()).sum())
            rows.append({"table": fact, "column": col, "role": role_of(col),
                         "non_blank": int(nonblank.sum()), "blank": int((~nonblank).sum()),
                         "min": fmt_num(values.min()), "max": fmt_num(values.max()),
                         "negatives": int((values < 0).sum()), "not_numeric": unparsed})
    print(pd.DataFrame(rows).to_string(index=False))
    for r in rows:
        detail = (f"role={r['role']}; min={r['min']}; max={r['max']}; "
                  f"{r['blank']:,} blank; {r['negatives']:,} negative"
                  + (f"; {r['not_numeric']:,} non-blank values are not numbers" if r["not_numeric"] else ""))
        record(f"numeric column {r['column']}", r["table"], "INFO", detail, show=False)

    print("\n  Skipped columns:" + ("" if skipped else " none"))
    for fact, col, why in skipped:
        record(f"numeric column {col} skipped", fact, "SKIPPED", why)

    print(f"\n  Not numeric (text or dates), so not listed: {', '.join(text_cols) or 'none'}")
    record("columns with no numeric values (text or dates)", "fact tables", "INFO",
           ", ".join(text_cols) or "none", show=False)
    print("\n  Roles: key = joins to a dimension or identifies the row; date part = describes the date;"
          "\n  flag = 0/1 marker; measure = a number you might aggregate. Classify each measure in Part C.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def save_report():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(RESULTS, columns=["check", "table", "result", "detail"]).to_csv(REPORT_FILE, index=False)


def enforced_summary():
    """The exact list of rules a PASS run has enforced (all PASS/FAIL checks)."""
    required = [f"{f}.{k}" for _, f, k, _, _ in RELATIONSHIPS if (f, k) not in ALLOWED_BLANK_FKS]
    return [
        "Row and column counts match the handout, and headers match the expected list, for all 8 tables.",
        "All 8 primary keys are non-blank, unique and plain whole numbers; dim_date.date is "
        "non-blank, unique and YYYY-MM-DD. NULL, None and N/A counted as blank.",
        "All 13 relationships: 0 orphans, 0 duplicate keys on the one side, and 0 keys that "
        "match only after trimming spaces or dropping '.0'.",
        f"0 blank keys on the {len(required)} required foreign keys: {', '.join(required)}.",
        "Blank security_id appears only on Deposit, Withdrawal and Advisory Fee rows.",
        "txn_date, fee_date and snapshot_date: 0 orphans and 0 blanks against dim_date.date, "
        "and 0 matches against dim_date.date_id.",
        "Every fee_date and snapshot_date is the 1st of a month.",
        "Snowflake links dim_client -> dim_advisor and dim_security -> dim_benchmark are clean.",
    ]


def main():
    t = load_tables()

    if not check_row_counts(t):
        save_report()
        print(f"\nERROR: required columns are missing (see above). Partial report saved to {REPORT_FILE}")
        sys.exit(1)

    check_primary_keys(t)
    ri = check_foreign_keys(t)
    check_date_join(t)
    check_grain(t)
    check_advisor_paths(t)
    check_snowflake(t, ri)
    check_numeric_columns(t)

    # Save the report BEFORE deciding pass/fail, so a failure never leaves you without it.
    save_report()

    section("SUMMARY")
    summary = pd.DataFrame(RESULTS)["result"].value_counts()
    print("  " + ", ".join(f"{k}: {v}" for k, v in summary.items()))
    print(f"  Report saved to {REPORT_FILE}")

    failures = [r for r in RESULTS if r["result"] == "FAIL"]
    if failures:
        print(f"\n  FAILED CHECKS ({len(failures)}):")
        for r in failures:
            print(f"    - [{r['table']}] {r['check']}: {r['detail']}")
        print("\n  Result: FAILED. Fix the problems above (or explain them) before building the model.")
        sys.exit(1)

    n_pass = int(summary.get("PASS", 0))
    print(f"\n  Result: PASSED. All {n_pass} PASS/FAIL checks passed. Enforced:")
    for i, line in enumerate(enforced_summary(), 1):
        print(f"    {i}. {line}")
    print("  Not enforced (reported for star_design.md only): grain candidates, advisor paths, "
          "benchmark per client, numeric-column roles.")


if __name__ == "__main__":
    main()
