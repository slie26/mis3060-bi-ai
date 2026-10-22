"""
HW4 Part A - Audit the raw Wildcat Capital extract
=================================================
Run from the repo root:   python hw04/scripts/01_profile.py

What this script does
---------------------
1. Reads the 8 raw CSVs as TEXT (dtype=str, keep_default_na=False) so nothing
   is silently converted.
2. Profiles every column of every table with ONE generic function,
   profile_table(), which knows nothing about any specific table.
3. Runs data-quality checks in four groups:
      1 Column-level      - types, allowed values, ranges, key uniqueness
      2 Single-table      - duplicates, near-duplicates, columns that
                            contradict each other, existing flag columns
      3 Referential integ.- every foreign key (and fact date) must exist
                            in its dimension
      4 Cross-table       - facts that disagree with dimensions or with
                            each other (dates vs client_since, amounts
                            recomputed from other columns, fee totals, ...)
4. Tags every finding ERROR / WARN / INFO and writes:
      hw04/reports/profile_raw.csv     (one row per table x column)
      hw04/reports/dq_summary_raw.csv  (one row per finding)

The ONLY table-specific part is the CONFIG section. Every check is written
generically and reads its table/column names from CONFIG. If a column named in
CONFIG does not exist in the file, that check is skipped and logged as a
"CONFIG" finding, so a wrong guess never crashes the run - fix the name and
rerun.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 0. PATHS
# The script finds hw04/ from its own location, so it works whether you run it
# from the repo root or from inside hw04/scripts.
# ---------------------------------------------------------------------------
HW_DIR = Path(__file__).resolve().parents[1]          # .../hw04
RAW_DIR = HW_DIR / "data" / "raw"
REPORT_DIR = HW_DIR / "reports"

# ---------------------------------------------------------------------------
# 1. SMALL GENERIC HELPERS
# Plain-English building blocks used by the profile, the checks and the
# CONFIG rules. None of them mention a specific table.
# ---------------------------------------------------------------------------

# Text that *looks* like a value but means "missing". We count these
# separately from true blanks because a BI tool treats them as real text.
NULL_TOKENS = {"none", "null", "nan", "n/a", "na", "nil", "-", "--", "?", "missing", "#n/a"}
BOOL_TOKENS = {"true", "false", "t", "f", "yes", "no", "y", "n", "1", "0"}
TRUE_TOKENS = {"true", "t", "yes", "y", "1"}

# Date formats we try, in order. The first one is the "house" format.
# NOTE: 03/04/2021 is ambiguous; US month-first is tried before day-first.
DATE_FORMATS = [
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%Y/%m/%d", "%m-%d-%Y",
    "%d-%b-%Y", "%b %d, %Y", "%d %b %Y", "%Y%m%d", "%d/%m/%Y", "%m/%d/%y",
]


def blank(s: pd.Series) -> pd.Series:
    """True where the cell is empty or only spaces."""
    return s.str.strip().eq("")


def null_token(s: pd.Series) -> pd.Series:
    """True where the cell holds a word like 'None' or 'N/A'."""
    return s.str.strip().str.lower().isin(NULL_TOKENS)


def missing(s: pd.Series) -> pd.Series:
    """Blank OR a null-like word."""
    return blank(s) | null_token(s)


def num(s: pd.Series) -> pd.Series:
    """Strict numeric parse after trimming spaces. '$12' or '1,200' -> NaN."""
    return pd.to_numeric(s.str.strip(), errors="coerce")


def up(s: pd.Series) -> pd.Series:
    """Trimmed, upper-case text - used for case-insensitive comparisons."""
    return s.str.strip().str.upper()


def truthy(s: pd.Series) -> pd.Series:
    """True where the text means 'true' (True / 1 / yes ...)."""
    return s.str.strip().str.lower().isin(TRUE_TOKENS)


def canon_id(s: pd.Series) -> pd.Series:
    """Normalise an ID for a 'would it match after cleaning?' test:
    trim spaces and turn '45.0' into '45'."""
    t = s.str.strip()
    n = pd.to_numeric(t, errors="coerce")
    integral = n.notna() & np.isfinite(n) & (n % 1 == 0)
    out = t.copy()
    out[integral] = n[integral].astype("int64").astype(str)
    return out


def _parse_unique_dates(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Parse a Series of DISTINCT strings, trying each known format in turn.
    Returns (parsed datetime, format that worked) aligned with `values`."""
    stripped = values.str.strip()
    out = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    fmt = pd.Series("", index=values.index, dtype=object)
    for f in DATE_FORMATS:
        todo = out.isna() & stripped.ne("")
        if not todo.any():
            break
        p = pd.to_datetime(stripped[todo], format=f, errors="coerce")
        # only accept plausible years (also stops '99990909' overflowing)
        p = p.where((p.dt.year >= 1900) & (p.dt.year <= 2100))
        ok = p[p.notna()].astype("datetime64[ns]")
        out.loc[ok.index] = ok
        fmt.loc[ok.index] = f
    return out, fmt


def parse_dates(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Parse a whole column of text dates (fast: works on distinct values).
    Returns (datetime Series, format-used Series)."""
    uniq = pd.Series(s.unique(), dtype=object).astype(str)
    dts, fmts = _parse_unique_dates(uniq)
    parsed = s.map(dict(zip(uniq, dts))).astype("datetime64[ns]")
    return parsed, s.map(dict(zip(uniq, fmts)))


def dt(d: pd.DataFrame, col: str) -> pd.Series:
    """Shortcut used in CONFIG rules: column `col` of `d` as datetimes."""
    return parse_dates(d[col])[0]


def is_in(s: pd.Series, values) -> pd.Series:
    """Membership test that ignores case and surrounding spaces
    (' buy ' and 'BUY' both count as 'Buy')."""
    return up(s).isin([str(v).strip().upper() for v in values])


class EmptyFilter(Exception):
    """A CONFIG filter matched 0 rows - the check cannot run, so it is reported
    in the SKIPPED list instead of looking like a pass."""


def filter_mask(df: pd.DataFrame, filt: dict | None) -> pd.Series:
    """Rows where every {column: [allowed values]} matches (trimmed, case-insensitive).
    Raises EmptyFilter if a filter was given but nothing matches."""
    m = pd.Series(True, index=df.index)
    for col, vals in (filt or {}).items():
        m &= is_in(df[col], vals)
    if filt and not m.any():
        raise EmptyFilter(f"filter {filt} matched 0 rows")
    return m


# Calendar range of the extract. NOT hard-coded: main() fills it from
# dim_date's own min and max date before any check runs.
CAL: dict = {}


def unparseable(df: pd.DataFrame, cols, types: dict) -> pd.Series:
    """True where any of `cols` holds a value that is present (not blank) but
    cannot be parsed as its CONFIG type. Rules OR this into their result so a
    value like '12.5%' or '2021-13-40' is flagged instead of silently passing
    (comparisons with NaN/NaT are always False)."""
    out = pd.Series(False, index=df.index)
    for c in dict.fromkeys(cols):
        if c not in df.columns or c not in types:
            continue
        present = ~missing(df[c])
        t = types[c]
        if t in ("int", "float"):
            out |= present & num(df[c]).isna()
        elif t == "date":
            out |= present & dt(df, c).isna()
        elif t == "bool":
            out |= present & ~df[c].str.strip().str.lower().isin(BOOL_TOKENS)
    return out


def rounding_tol(*cols: pd.Series) -> float:
    """Tolerance for 'a = b - c' checks when every input was rounded: 1.5 units
    of the finest decimal place seen (e.g. 4 decimals -> 0.00015)."""
    places = 0
    for s in cols:
        dec = s.str.strip().str.extract(r"\.(\d+)$")[0].str.len()
        places = max(places, int(dec.max()) if dec.notna().any() else 0)
    return 1.5 * 10 ** (-places)


# ---------------------------------------------------------------------------
# 2. CONFIG  - the ONLY table-specific part of the script
#
# For each table:
#   file           raw file name in hw04/data/raw/
#   expected_rows  / expected_cols : counts from the assignment sheet
#   pk             primary key column
#   fks            {fk column: (parent table, parent key)}
#                  (any column named like a dimension's key is also
#                  auto-detected, so a missed FK still gets checked)
#   date_cols      fact date columns that must exist in dim_date
#   types          expected type per column: int / float / date / bool / str
#   required       columns that must never be blank (the pk is added)
#   allowed        {column: [allowed values]}  (exact, case-sensitive)
#   allowed_tokens {column: (separator, [allowed tokens])} for lists like "CFP, CFA"
#   ranges         {column: (min, max, severity)}  None = no bound on that side
#   unique         alternate keys that should also be unique
#   natural_keys   column combinations that should identify one row
#   sign_by        {numeric column: grouping column} - the sign should be
#                  consistent within each group (e.g. every Buy negative)
#   flag_cols      data-quality flag columns from the earlier partial clean
#   row_rules      [(name, function(df) -> True where WRONG, severity,
#                    [columns to show as examples], optional flag column to
#                    compare against)]
# ---------------------------------------------------------------------------

REGIONS = ["Northeast", "Mid-Atlantic", "Southeast", "Midwest", "Southwest", "West"]
SECTORS = ["Communication Services", "Consumer Discretionary", "Consumer Staples",
           "Energy", "Financials", "Healthcare", "Industrials", "Materials",
           "Real Estate", "Technology", "Utilities"]
US_STATES = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL",
             "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE",
             "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD",
             "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]

# fact_transactions.txn_type values (exact, as supplied)
TXN_TYPES = ["Buy", "Sell", "Dividend", "Deposit", "Withdrawal", "Advisory Fee"]
SECURITY_TXN = ["Buy", "Sell", "Dividend"]          # need security_id, shares, price
CASH_TXN = ["Deposit", "Withdrawal", "Advisory Fee"]  # security_id/shares/price must be blank
TRADE_TXN = ["Buy", "Sell"]
FEE_TXN = ["Advisory Fee"]
FEE_TYPES = ["Advisory", "Management", "Custodial", "Performance"]

# dim_client.age is assumed to be age at the END of the calendar (CAL["end"]).


def minority_scale(v: pd.Series) -> pd.Series:
    """For a ratio column, flag rows on the minority scale (0-1 vs 0-100).
    Example: if most return_ytd values are 0.12, a value of 12 is flagged."""
    big = v.abs() > 1
    if big.sum() <= (v.notna().sum() / 2):
        return big.fillna(False)
    return (~big & v.notna() & (v != 0))


def iqr_outlier(v: pd.Series, k: float = 3.0) -> pd.Series:
    """Scale-free extreme-value test: outside Q1 - k*IQR .. Q3 + k*IQR."""
    q1, q3 = v.quantile(0.25), v.quantile(0.75)
    iqr = q3 - q1
    return (v < q1 - k * iqr) | (v > q3 + k * iqr)


CONFIG: dict[str, dict] = {
    # ======================= DIMENSIONS =======================
    "dim_advisor": {
        "file": "dim_advisor.csv", "expected_rows": 25, "expected_cols": 7,
        "pk": "advisor_id",
        "types": {"advisor_id": "int", "years_experience": "int", "aum_target_mm": "int"},
        "required": ["first_name", "last_name", "region"],
        "allowed": {"region": REGIONS},
        # 'None' is a legitimate certification value ("no certification"), not a null
        "allowed_tokens": {"certifications": (",", ["CFA", "CFP", "CIMA", "None"])},
        "ranges": {"years_experience": (0, 50, "WARN"), "aum_target_mm": (1, 1000, "WARN")},
        "natural_keys": [["first_name", "last_name"]],
    },
    "dim_benchmark": {
        "file": "dim_benchmark.csv", "expected_rows": 8, "expected_cols": 4,
        "pk": "benchmark_id",
        "types": {"benchmark_id": "int"},
        "required": ["name", "asset_class", "ticker_proxy"],
        "unique": ["name", "ticker_proxy"],
    },
    "dim_security": {
        "file": "dim_security.csv", "expected_rows": 500, "expected_cols": 8,
        "pk": "security_id",
        "fks": {"benchmark_id": ("dim_benchmark", "benchmark_id")},
        "types": {"security_id": "int", "benchmark_id": "int", "is_etf": "bool",
                  "expense_ratio_bps": "float"},
        "required": ["ticker", "name", "asset_class", "is_etf"],
        "allowed": {"asset_class": ["Equity", "Fixed Income", "Alternative", "Cash Equivalent"],
                    "sector": SECTORS,               # blank sector is legitimate for funds
                    "is_etf": ["True", "False"]},
        "ranges": {"expense_ratio_bps": (0, 300, "WARN")},
        "unique": ["ticker"],
        "natural_keys": [["name", "asset_class"]],
        "row_rules": [
            ("ETF with no expense ratio",
             lambda d: truthy(d.is_etf) & missing(d.expense_ratio_bps), "WARN",
             ["ticker", "is_etf", "expense_ratio_bps"]),
            ("Non-ETF with an expense ratio",
             lambda d: ~truthy(d.is_etf) & ~missing(d.expense_ratio_bps), "WARN",
             ["ticker", "is_etf", "expense_ratio_bps"]),
            ("Equity with no sector",
             lambda d: up(d.asset_class).eq("EQUITY") & missing(d.sector), "WARN",
             ["ticker", "asset_class", "sector"]),
            ("Fund (non-equity) with a sector",
             lambda d: ~up(d.asset_class).eq("EQUITY") & ~missing(d.sector), "WARN",
             ["ticker", "asset_class", "sector"]),
            ("is_etf contradicts name suffix (Fund vs Inc.)",
             lambda d: (d.name.str.strip().str.endswith("Fund") & ~truthy(d.is_etf))
             | (d.name.str.strip().str.endswith("Inc.") & truthy(d.is_etf)), "WARN",
             ["name", "is_etf"]),
        ],
    },
    "dim_client": {
        "file": "dim_client.csv", "expected_rows": 2525, "expected_cols": 14,
        "pk": "client_id",
        "fks": {"advisor_id": ("dim_advisor", "advisor_id")},
        "types": {"client_id": "int", "age": "int", "zip_code": "str", "initial_aum": "float",
                  "client_since": "date", "advisor_id": "int", "is_active": "bool"},
        "required": ["first_name", "last_name", "client_since", "advisor_id", "is_active"],
        "allowed": {"state": US_STATES, "is_active": ["True", "False"]},
        "ranges": {"age": (18, 110, "WARN"), "initial_aum": (0, None, "ERROR")},
        # the same person under two client_ids
        "natural_keys": [["first_name", "last_name", "age", "zip_code"],
                         ["first_name", "last_name", "zip_code"]],
        "row_rules": [
            # zip codes read as numbers lose their leading zero (08540 -> 8540)
            ("zip_code is not 5 digits",
             lambda d: ~missing(d.zip_code) & ~d.zip_code.str.strip().str.fullmatch(r"\d{5}(-\d{4})?"),
             "WARN", ["state", "zip_code"]),
            ("client_since after the end of the calendar (dim_date max)",
             lambda d: dt(d, "client_since") > CAL["end"], "ERROR", ["client_since"]),
            # age is assumed to be "as of" the end of the extract
            ("Client under 18 when they joined (age vs client_since)",
             lambda d: (num(d.age) - (CAL["end"].year - dt(d, "client_since").dt.year)) < 18, "WARN",
             ["age", "client_since"]),
        ],
    },
    "dim_date": {
        "file": "dim_date.csv", "expected_rows": 1827, "expected_cols": 12,
        "pk": "date_id",
        "date_col": "date",            # the column facts join on
        "coverage": True,              # no missing days between dim_date's own min and max
        "unique": ["date"],
        "types": {"date_id": "int", "date": "date", "year": "int", "quarter": "int", "month": "int",
                  "week_of_year": "int", "is_month_end": "bool", "is_quarter_end": "bool",
                  "is_year_end": "bool", "is_trading_day": "bool"},
        "required": ["date"],
        "allowed": {"quarter": ["1", "2", "3", "4"],
                    "is_month_end": ["0", "1"], "is_quarter_end": ["0", "1"],
                    "is_year_end": ["0", "1"], "is_trading_day": ["0", "1"]},
        "ranges": {"month": (1, 12, "ERROR"), "week_of_year": (1, 53, "ERROR")},
        "row_rules": [
            ("year does not match date", lambda d: num(d.year) != dt(d, "date").dt.year, "ERROR", ["date", "year"]),
            ("month does not match date", lambda d: num(d.month) != dt(d, "date").dt.month, "ERROR", ["date", "month"]),
            ("quarter does not match date", lambda d: num(d.quarter) != dt(d, "date").dt.quarter,
             "ERROR", ["date", "quarter"]),
            ("month_name does not match date",
             lambda d: up(d.month_name) != dt(d, "date").dt.month_name().str.upper(), "ERROR", ["date", "month_name"]),
            # convention-free: every Monday must carry the same day_of_week value, etc.
            ("day_of_week inconsistent for the same weekday",
             lambda d: d.day_of_week.str.strip() != d.day_of_week.str.strip()
             .groupby(dt(d, "date").dt.dayofweek).transform(lambda x: x.mode().iat[0]),
             "ERROR", ["date", "day_of_week"]),
            ("week_of_year differs from ISO week (may be another convention)",
             lambda d: num(d.week_of_year) != dt(d, "date").dt.isocalendar().week.astype(float), "INFO",
             ["date", "week_of_year"]),
            ("is_month_end does not match date",
             lambda d: truthy(d.is_month_end) != dt(d, "date").dt.is_month_end, "ERROR", ["date", "is_month_end"]),
            ("is_quarter_end does not match date",
             lambda d: truthy(d.is_quarter_end) != dt(d, "date").dt.is_quarter_end, "ERROR", ["date", "is_quarter_end"]),
            ("is_year_end does not match date",
             lambda d: truthy(d.is_year_end) != dt(d, "date").dt.is_year_end, "ERROR", ["date", "is_year_end"]),
            ("Trading day on a weekend",
             lambda d: truthy(d.is_trading_day) & (dt(d, "date").dt.dayofweek >= 5), "ERROR",
             ["date", "is_trading_day"]),
            # weekday market holidays are legitimate - INFO only
            ("Weekday that is not a trading day (holiday?)",
             lambda d: ~truthy(d.is_trading_day) & (dt(d, "date").dt.dayofweek < 5), "INFO",
             ["date", "is_trading_day"]),
        ],
    },
    # ======================= FACTS =======================
    "fact_fees": {
        "file": "fact_fees.csv", "expected_rows": 122197, "expected_cols": 8,
        "pk": "fee_id",
        "fks": {"client_id": ("dim_client", "client_id"),
                "advisor_id": ("dim_advisor", "advisor_id")},
        "date_cols": ["fee_date"],
        "types": {"fee_id": "int", "client_id": "int", "advisor_id": "int", "fee_date": "date",
                  "aum_basis": "float", "bps_charged": "float", "amount": "float"},
        "required": ["client_id", "fee_date", "fee_type", "amount"],
        "allowed": {"fee_type": FEE_TYPES},
        "ranges": {"aum_basis": (0, None, "ERROR"), "bps_charged": (0, 300, "WARN"),
                   "amount": (0, None, "WARN")},
        "natural_keys": [["client_id", "fee_date", "fee_type"]],   # one charge per type per month
        "sign_by": {"amount": "fee_type"},
        "row_rules": [
            # fees are dated on the 1st of the month (month-start convention)
            ("fee_date not the 1st of the month",
             lambda d: dt(d, "fee_date").dt.day != 1, "INFO", ["fee_date"]),
        ],
    },
    "fact_portfolio_snapshot": {
        "file": "fact_portfolio_snapshot.csv", "expected_rows": 129547, "expected_cols": 13,
        "pk": "snapshot_id",
        "fks": {"client_id": ("dim_client", "client_id"),
                "advisor_id": ("dim_advisor", "advisor_id"),
                "benchmark_id": ("dim_benchmark", "benchmark_id")},
        "date_cols": ["snapshot_date"],
        "types": {"snapshot_id": "int", "client_id": "int", "advisor_id": "int", "benchmark_id": "int",
                  "snapshot_date": "date", "year": "int", "month": "int", "aum": "float",
                  "return_ytd": "float", "benchmark_return_ytd": "float", "active_alpha_ytd": "float",
                  "cash_pct": "float", "is_return_suspect": "bool"},
        "required": ["client_id", "snapshot_date", "aum"],
        "allowed": {"is_return_suspect": ["0", "1"]},
        # year bounds come from dim_date at run time (callables are resolved then)
        "ranges": {"aum": (0, None, "ERROR"), "cash_pct": (0, 1, "ERROR"),
                   "month": (1, 12, "ERROR"),
                   "year": (lambda: CAL["start"].year, lambda: CAL["end"].year, "ERROR")},
        "natural_keys": [["client_id", "snapshot_date", "account_type"]],
        "flag_cols": ["is_return_suspect"],
        "row_rules": [
            ("year does not match snapshot_date",
             lambda d: num(d.year) != dt(d, "snapshot_date").dt.year, "ERROR", ["snapshot_date", "year"]),
            ("month does not match snapshot_date",
             lambda d: num(d.month) != dt(d, "snapshot_date").dt.month, "ERROR", ["snapshot_date", "month"]),
            # snapshots are dated on the 1st of the month (month-start convention)
            ("snapshot_date not the 1st of the month",
             lambda d: dt(d, "snapshot_date").dt.day != 1, "INFO", ["snapshot_date"]),
            ("return_ytd on the minority scale (decimal vs percent)",
             lambda d: minority_scale(num(d.return_ytd)), "WARN", ["return_ytd"], "is_return_suspect"),
            ("return_ytd extreme (3x IQR)",
             lambda d: iqr_outlier(num(d.return_ytd)), "WARN", ["client_id", "snapshot_date", "return_ytd"],
             "is_return_suspect"),
            # every client tracking the same benchmark on the same date should see the same benchmark return
            ("benchmark_return_ytd differs for the same benchmark and date",
             lambda d: num(d.benchmark_return_ytd).round(6) != num(d.benchmark_return_ytd).round(6)
             .groupby([d.benchmark_id, d.snapshot_date]).transform(lambda x: x.mode().iat[0] if x.notna().any() else np.nan),
             "WARN", ["benchmark_id", "snapshot_date", "benchmark_return_ytd"]),
            ("Client's benchmark changes between snapshots",
             lambda d: d.benchmark_id.groupby(d.client_id).transform("nunique") > 1, "INFO",
             ["client_id", "benchmark_id"]),
        ],
    },
    "fact_transactions": {
        "file": "fact_transactions.csv", "expected_rows": 298772, "expected_cols": 9,
        "pk": "txn_id",
        "fks": {"client_id": ("dim_client", "client_id"),
                "advisor_id": ("dim_advisor", "advisor_id"),
                "security_id": ("dim_security", "security_id")},
        "date_cols": ["txn_date"],
        "types": {"txn_id": "int", "client_id": "int", "advisor_id": "int", "security_id": "int",
                  "txn_date": "date", "shares": "float", "price": "float", "amount": "float",
                  "is_post_departure_txn": "bool"},
        "required": ["client_id", "txn_date", "txn_type", "amount"],
        "allowed": {"txn_type": TXN_TYPES, "is_post_departure_txn": ["0", "1"]},
        "sign_by": {"amount": "txn_type", "shares": "txn_type"},
        # blanks that are legitimate by design (reported as INFO, not WARN)
        "blank_ok": {"security_id": "blank for Deposit/Withdrawal/Advisory Fee by design; the row "
                                    "rule 'Buy/Sell/Dividend with no security_id' proves trades have one"},
        "flag_cols": ["is_post_departure_txn"],
        "row_rules": [
            # A blank security_id is LEGITIMATE for Deposit / Withdrawal / Advisory Fee,
            # but a defect for Buy / Sell / Dividend - these rules separate the two.
            ("Buy/Sell/Dividend with no security_id",
             lambda d: is_in(d.txn_type, SECURITY_TXN) & missing(d.security_id), "ERROR",
             ["txn_type", "security_id"]),
            ("Buy/Sell/Dividend with no shares or price",
             lambda d: is_in(d.txn_type, SECURITY_TXN) & (missing(d.shares) | missing(d.price)), "ERROR",
             ["txn_type", "shares", "price"]),
            ("Cash txn (Deposit/Withdrawal/Fee) has security_id, shares or price",
             lambda d: is_in(d.txn_type, CASH_TXN)
             & (~missing(d.security_id) | ~missing(d.shares) | ~missing(d.price)), "WARN",
             ["txn_type", "security_id", "shares", "price"]),
            ("Price zero or negative",
             lambda d: is_in(d.txn_type, SECURITY_TXN) & (num(d.price) <= 0), "ERROR", ["txn_type", "price"]),
            ("Zero amount", lambda d: num(d.amount) == 0, "WARN", ["txn_type", "amount"]),
        ],
    },
}

# ---------------------------------------------------------------------------
# Cross-table business rules (group 4). Each entry names a generic rule type
# (implemented in section 6) plus the tables/columns it applies to.
#   flag  (optional) = existing flag column to compare the violations with
# ---------------------------------------------------------------------------
CROSS_RULES: list[dict] = [
    # --- facts must not pre-date the client relationship ---
    # fee_date / snapshot_date are month-start dates, so compare at MONTH level:
    # a client who joined on the 15th is billed for that month on the 1st.
    {"type": "not_before", "name": "Fee month before client_since month", "severity": "ERROR",
     "grain": "M", "table": "fact_fees", "date_col": "fee_date", "fk": "client_id",
     "dim": "dim_client", "dim_key": "client_id", "dim_date_col": "client_since"},
    {"type": "not_before", "name": "Snapshot month before client_since month", "severity": "ERROR",
     "grain": "M", "table": "fact_portfolio_snapshot", "date_col": "snapshot_date", "fk": "client_id",
     "dim": "dim_client", "dim_key": "client_id", "dim_date_col": "client_since"},
    {"type": "not_before", "name": "Transaction before client_since", "severity": "ERROR",
     "table": "fact_transactions", "date_col": "txn_date", "fk": "client_id",
     "dim": "dim_client", "dim_key": "client_id", "dim_date_col": "client_since"},

    # --- a fact's advisor should be the client's advisor (or be explained by a flag) ---
    {"type": "same_as_dim", "name": "Txn advisor differs from client's advisor", "severity": "WARN",
     "table": "fact_transactions", "col": "advisor_id", "fk": "client_id",
     "dim": "dim_client", "dim_key": "client_id", "dim_col": "advisor_id",
     "flag": "is_post_departure_txn"},
    {"type": "same_as_dim", "name": "Fee advisor differs from client's advisor", "severity": "WARN",
     "table": "fact_fees", "col": "advisor_id", "fk": "client_id",
     "dim": "dim_client", "dim_key": "client_id", "dim_col": "advisor_id"},
    {"type": "same_as_dim", "name": "Snapshot advisor differs from client's advisor", "severity": "WARN",
     "table": "fact_portfolio_snapshot", "col": "advisor_id", "fk": "client_id",
     "dim": "dim_client", "dim_key": "client_id", "dim_col": "advisor_id"},
    {"type": "same_as_dim", "name": "Snapshot account_type differs from client's primary_account_type",
     "severity": "INFO", "table": "fact_portfolio_snapshot", "col": "account_type", "fk": "client_id",
     "dim": "dim_client", "dim_key": "client_id", "dim_col": "primary_account_type"},

    # --- a security's benchmark should match its asset class ---
    {"type": "mapped_match", "name": "Security benchmark does not fit its asset class", "severity": "WARN",
     "table": "dim_security", "col": "asset_class", "fk": "benchmark_id",
     "dim": "dim_benchmark", "dim_key": "benchmark_id", "dim_col": "asset_class",
     "mapping": {"Equity": ["Equity", "International", "Small Cap", "Emerging"],
                 "Fixed Income": ["Fixed Income"], "Alternative": ["Multi-Asset"],
                 "Cash Equivalent": ["Cash"]}},

    # --- facts checked against dim_date / dim_client attributes ---
    {"type": "lookup_condition", "name": "Buy/Sell on a non-trading day", "severity": "WARN",
     "table": "fact_transactions", "fk": "txn_date", "dim": "dim_date", "dim_key": "date", "join": "date",
     "dim_col": "is_trading_day", "filter": {"txn_type": TRADE_TXN},
     "bad": lambda ref, d: ~truthy(ref.fillna("")) & ref.notna(), "cols": ["txn_type", "txn_date"]},
    {"type": "lookup_condition", "name": "Inactive client still billed in the final month",
     "severity": "WARN", "table": "fact_fees", "fk": "client_id", "dim": "dim_client",
     "dim_key": "client_id", "dim_col": "is_active",
     "bad": lambda ref, d: ref.notna() & ~truthy(ref.fillna("")) & (dt(d, "fee_date").dt.to_period("M") == CAL["end"].to_period("M")),
     "cols": ["client_id", "fee_date"]},
    {"type": "lookup_condition", "name": "Inactive client trading in the final month",
     "severity": "INFO", "table": "fact_transactions", "fk": "client_id", "dim": "dim_client",
     "dim_key": "client_id", "dim_col": "is_active",
     "bad": lambda ref, d: ref.notna() & ~truthy(ref.fillna("")) & (dt(d, "txn_date").dt.to_period("M") == CAL["end"].to_period("M")),
     "cols": ["client_id", "txn_date", "txn_type"]},

    # --- amounts that can be recomputed from other columns ---
    {"type": "recompute", "name": "amount != shares x price (Buy/Sell/Dividend)", "severity": "ERROR",
     "table": "fact_transactions", "target": "amount", "formula": "shares * price",
     # abs(): Buy amounts are cash out (negative) while shares x price is positive;
     # the SIGN is tested separately by sign_by, so here only the size is compared
     "filter": {"txn_type": SECURITY_TXN}, "abs": True, "abs_tol": 0.01, "rel_tol": 0.001,
     "flag": "is_post_departure_txn"},
    # the billing convention (monthly / quarterly / annual bps) is not documented, so
    # several candidate formulas are tested and the best-fitting one is reported
    {"type": "recompute", "name": "fee amount != aum_basis x bps_charged (best-fit period)",
     "severity": "ERROR", "table": "fact_fees", "target": "amount",
     "formula": ["aum_basis * bps_charged / 10000 / 12", "aum_basis * bps_charged / 10000 / 4",
                 "aum_basis * bps_charged / 10000"],
     "filter": {"fee_type": ["Advisory", "Management", "Custodial"]},
     "abs_tol": 0.01, "rel_tol": 0.005},
    {"type": "recompute", "name": "active_alpha_ytd != return_ytd - benchmark_return_ytd",
     "severity": "ERROR", "table": "fact_portfolio_snapshot", "target": "active_alpha_ytd",
     "formula": "return_ytd - benchmark_return_ytd", "abs": False, "abs_tol": "auto", "rel_tol": 0,
     "flag": "is_return_suspect"},

    # --- two fact tables describing the same money ---
    # Which fee types are debited is not documented, so both readings are tested.
    # No abs(): a debit is stored as a negative cash flow, so its sign is flipped
    # explicitly (right_sign = -1). If most groups disagree, the tables are
    # reported as not reconciling at this grain (INFO) rather than as row errors;
    # the detail also shows the comparison at coarser grains (per client, per month).
    {"type": "reconcile_totals", "name": "All fees (fact_fees) vs Advisory Fee debits (transactions)",
     "severity": "WARN", "left": "fact_fees", "left_val": "amount", "left_date": "fee_date",
     "right": "fact_transactions", "right_val": "amount", "right_date": "txn_date",
     "right_filter": {"txn_type": FEE_TXN}, "right_sign": -1,
     "keys": ["client_id"], "period": "M", "abs_tol": 0.01, "rel_tol": 0.001},
    {"type": "reconcile_totals", "name": "Advisory fees only (fact_fees) vs Advisory Fee debits",
     "severity": "WARN", "left": "fact_fees", "left_val": "amount", "left_date": "fee_date",
     "left_filter": {"fee_type": ["Advisory"]},
     "right": "fact_transactions", "right_val": "amount", "right_date": "txn_date",
     "right_filter": {"txn_type": FEE_TXN}, "right_sign": -1,
     "keys": ["client_id"], "period": "M", "abs_tol": 0.01, "rel_tol": 0.001},
    # aum_basis repeats on every fee row of a month -> take max; snapshots may be per account -> sum
    {"type": "reconcile_totals", "name": "Fee aum_basis vs snapshot aum (same client-month)",
     "severity": "WARN", "left": "fact_fees", "left_val": "aum_basis", "left_date": "fee_date",
     "left_agg": "max", "right": "fact_portfolio_snapshot", "right_val": "aum",
     "right_date": "snapshot_date", "right_agg": "sum",
     "keys": ["client_id"], "period": "M", "abs_tol": 1.0, "rel_tol": 0.05},
    {"type": "exists_in", "name": "Fee month with no portfolio snapshot", "severity": "WARN",
     "left": "fact_fees", "left_date": "fee_date",
     "right": "fact_portfolio_snapshot", "right_date": "snapshot_date",
     "keys": ["client_id"], "period": "M"},
    {"type": "exists_in", "name": "Snapshot month with no fee charged", "severity": "INFO",
     "left": "fact_portfolio_snapshot", "left_date": "snapshot_date",
     "right": "fact_fees", "right_date": "fee_date",
     "keys": ["client_id"], "period": "M"},

    # --- what do the existing flags actually mean? ---
    # Cross-tab each flag against candidate explanations. The condition that
    # matches the flag best tells you (for Part B) what the partial clean flagged,
    # and the rows it missed.
    {"type": "flag_crosstab", "name": "What explains is_post_departure_txn?", "severity": "WARN",
     "table": "fact_transactions", "flag": "is_post_departure_txn",
     "conditions": {
         "advisor_id not in dim_advisor":
             lambda T, d: ~missing(d.advisor_id) & ~canon_id(d.advisor_id).isin(canon_id(T["dim_advisor"].advisor_id)),
         "advisor differs from client's advisor":
             lambda T, d: canon_id(d.advisor_id)
             != canon_id(d.client_id.str.strip().map(_lookup(T, "dim_client", "client_id", "advisor_id")).fillna("")),
         "client is_active = False":
             lambda T, d: ~truthy(d.client_id.str.strip().map(_lookup(T, "dim_client", "client_id", "is_active")).fillna("True")),
         "after advisor's last UNflagged txn":
             lambda T, d: dt(d, "txn_date") > dt(d, "txn_date").where(~truthy(d.is_post_departure_txn))
             .groupby(d.advisor_id).transform("max"),
     }},
    {"type": "flag_crosstab", "name": "What explains is_return_suspect?", "severity": "WARN",
     "table": "fact_portfolio_snapshot", "flag": "is_return_suspect",
     "conditions": {
         "return_ytd blank": lambda T, d: missing(d.return_ytd),
         "return_ytd on minority scale": lambda T, d: minority_scale(num(d.return_ytd)),
         "return_ytd extreme (3x IQR)": lambda T, d: iqr_outlier(num(d.return_ytd)),
         "active_alpha_ytd extreme (3x IQR)": lambda T, d: iqr_outlier(num(d.active_alpha_ytd)),
         "alpha != return - benchmark":
             lambda T, d: (num(d.active_alpha_ytd) - (num(d.return_ytd) - num(d.benchmark_return_ytd))).abs()
             > rounding_tol(d.active_alpha_ytd, d.return_ytd, d.benchmark_return_ytd),
         "aum <= 0": lambda T, d: num(d.aum) <= 0,
     }},
]

# Columns whose NAME suggests a data-quality flag are also picked up
# automatically (in addition to each table's flag_cols).
FLAG_NAME_PATTERN = re.compile(r"(flag|dq_|suspect|quarantin|anomal|invalid|outlier)", re.I)

# ---------------------------------------------------------------------------
# 3. FINDINGS LOG
# Every check calls add_finding(); at the end the list becomes
# dq_summary_raw.csv.
# ---------------------------------------------------------------------------
FINDINGS: list[dict] = []
SKIPPED: list[str] = []


def add_finding(table, group, check, column, severity, n_affected, denom, detail="", examples=""):
    FINDINGS.append({
        "table": table, "check_group": group, "check": check, "column": column,
        "severity": severity, "rows_affected": int(n_affected),
        "rows_checked": int(denom),
        "pct_affected": round(100 * n_affected / denom, 3) if denom else np.nan,
        "detail": detail, "examples": examples,
    })


def skip(table, group, check, err):
    """A CONFIG name did not match the data: log it and carry on."""
    msg = f"{table}: '{check}' skipped - not found / not usable: {err}"
    SKIPPED.append(msg)
    add_finding(table, group, f"CONFIG - skipped: {check}", str(err), "INFO", 0, 0,
                "Column named in CONFIG is not in this file; fix CONFIG and rerun")


def show_examples(df, mask, cols, pk=None, k=5) -> str:
    """Up to k offending rows, as 'pk=..., col=...' text."""
    cols = [c for c in dict.fromkeys(([pk] if pk else []) + list(cols)) if c in df.columns]
    if not cols or not mask.any():
        return ""
    recs = df.loc[mask, cols].head(k).to_dict("records")
    return " | ".join(", ".join(f"{c}={v!r}" for c, v in r.items()) for r in recs)


# ---------------------------------------------------------------------------
# 4. GENERIC PROFILER
# profile_table() works on ANY DataFrame. It looks at distinct values (fast on
# 300k rows) and weights results by how often each value appears.
# ---------------------------------------------------------------------------

def _shape(values: pd.Series) -> pd.Series:
    """'AB-12 ' -> 'AA-99 '  (digits -> 9, letters -> A, everything else kept)."""
    return values.str.replace(r"[0-9]", "9", regex=True).str.replace(r"[A-Za-z]", "A", regex=True)


def profile_table(df: pd.DataFrame, table_name: str, expected_types: dict | None = None,
                  flag_cols: list | None = None) -> pd.DataFrame:
    """Return one profile row per column of `df`. The only optional inputs are
    the expected types and known flag columns - nothing table-specific."""
    expected_types = expected_types or {}
    flag_cols = set(flag_cols or [])
    n = len(df)
    rows = []
    for col in df.columns:
        vc = df[col].value_counts(dropna=False)
        uniq = pd.Series(vc.index.astype(str), dtype=object)
        cnt = pd.Series(vc.values, dtype="int64")

        is_blank = uniq.str.strip().eq("")
        is_tok = uniq.str.strip().str.lower().isin(NULL_TOKENS)
        present = ~(is_blank | is_tok)                 # real values only
        n_present = int(cnt[present].sum())

        # value shapes, e.g. 9999-99-99 vs 99/99/9999
        shapes = _shape(uniq).where(~is_blank, "<blank>")
        sc = cnt.groupby(shapes.values).sum().sort_values(ascending=False)
        top3 = "; ".join(f"{k} ({v / n:.1%})" for k, v in sc.head(3).items()) if n else ""

        # numeric parse
        nums = pd.to_numeric(uniq.str.strip(), errors="coerce")
        num_fail = int(cnt[present & nums.isna()].sum())
        num_ok = present & nums.notna()
        num_min = nums[num_ok].min() if num_ok.any() else np.nan
        num_max = nums[num_ok].max() if num_ok.any() else np.nan
        has_decimal_text = int(cnt[num_ok & uniq.str.contains(r"\.", regex=True)].sum())
        integral = bool(num_ok.any() and (nums[num_ok] % 1 == 0).all())

        # date parse (any known format) and how many formats are in use
        dts, fmts = _parse_unique_dates(uniq)
        date_fail = int(cnt[present & dts.isna()].sum())
        formats = cnt[present & dts.notna()].groupby(fmts[present & dts.notna()].values).sum()
        date_iso_fail = int(cnt[present & ~fmts.eq("%Y-%m-%d")].sum())

        # bool tokens
        low = uniq.str.strip().str.lower()
        bool_fail = int(cnt[present & ~low.isin(BOOL_TOKENS)].sum())

        # whitespace: leading/trailing or doubled inner spaces
        ws = uniq.ne(uniq.str.strip()) | uniq.str.contains(r"\s{2,}", regex=True)
        ws_count = int(cnt[ws & ~is_blank].sum())

        # infer the type the column "wants" to be
        def pct(x):
            return round(100 * x / n_present, 3) if n_present else np.nan
        if n_present and num_fail / n_present <= 0.02:
            inferred = "int" if integral and has_decimal_text == 0 else "float"
        elif n_present and date_fail / n_present <= 0.02:
            inferred = "date"
        elif n_present and bool_fail == 0:
            inferred = "bool"
        else:
            inferred = "str"
        expected = expected_types.get(col, inferred)
        fail_expected = {
            "int": int(cnt[present & (nums.isna() | (nums % 1 != 0))].sum()),
            "float": num_fail, "date": date_fail, "bool": bool_fail, "str": 0,
        }[expected]

        rows.append({
            "table": table_name, "column": col, "rows": n,
            "blank_count": int(cnt[is_blank].sum()),
            "null_token_count": int(cnt[is_tok].sum()),
            "null_tokens_seen": ", ".join(sorted(set(uniq[is_tok].str.strip()))),
            "distinct_count": int(len(uniq)),
            "distinct_pct": round(100 * len(uniq) / n, 2) if n else np.nan,
            "n_shapes": int(len(sc)),
            "top3_shapes": top3,
            "pct_fail_numeric": pct(num_fail),
            "pct_fail_date": pct(date_fail),
            "pct_not_iso_date": pct(date_iso_fail),
            "date_formats_seen": "; ".join(f"{k} ({v})" for k, v in formats.items()),
            "whitespace_count": ws_count,
            "numeric_min": num_min, "numeric_max": num_max,
            "numbers_with_decimal_point": has_decimal_text,
            "inferred_type": inferred, "expected_type": expected,
            "pct_fail_expected_type": pct(fail_expected),
            "is_flag_column": col in flag_cols or bool(FLAG_NAME_PATTERN.search(col)),
            "sample_values": " | ".join(uniq[present].head(5)),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 5. CHECK GROUPS 1-3 (generic; driven by CONFIG)
# ---------------------------------------------------------------------------

def check_structure(name, df, cfg):
    """Row and column counts vs the assignment sheet."""
    g = "0 Structure"
    exp_r, exp_c = cfg.get("expected_rows"), cfg.get("expected_cols")
    # Differences are INFO: the instructor confirmed these are the provided files,
    # so a different count is worth knowing (and documenting), not an error.
    if exp_r is not None:
        add_finding(name, g, "Row count vs assignment sheet", "", "INFO", abs(len(df) - exp_r), exp_r,
                    f"actual={len(df):,} sheet={exp_r:,}" + ("" if len(df) == exp_r else " - differs; document it"))
    if exp_c is not None:
        extra = [c for c in cfg.get("flag_cols", []) if c in df.columns]
        add_finding(name, g, "Column count vs assignment sheet", "", "INFO", abs(df.shape[1] - exp_c), exp_c,
                    f"actual={df.shape[1]} sheet={exp_c}"
                    + (f"; flag columns from the partial clean: {extra}" if extra else ""))
    # every CONFIG column should exist
    named = set(cfg.get("types", {})) | set(cfg.get("required", [])) | set(cfg.get("allowed", {})) \
        | set(cfg.get("ranges", {})) | set(cfg.get("fks", {})) | set(cfg.get("date_cols", [])) \
        | set(cfg.get("unique", [])) | ({cfg["pk"]} if cfg.get("pk") else set())
    for col in sorted(c for c in named if c not in df.columns):
        skip(name, g, "CONFIG column", col)


def check_column_level(name, df, cfg, prof):
    """Group 1: types, blanks, allowed values, ranges, key uniqueness, formats."""
    g = "1 Column"
    pk = cfg.get("pk")
    required = set(cfg.get("required", [])) | ({pk} if pk else set())
    fk_cols = set(cfg.get("fks", {}))
    p = prof.set_index("column")

    for col in df.columns:
        s, r = df[col], p.loc[col]
        n = len(s)

        # blanks: ERROR where the column is required, otherwise INFO (may be legit)
        nb = int(blank(s).sum())
        if nb:
            # required -> ERROR; a blank FK -> WARN (may be legitimate, e.g. a cash
            # deposit has no security - the row rules decide); otherwise INFO
            blank_ok = cfg.get("blank_ok", {})
            sev = "ERROR" if col in required else "INFO" if col in blank_ok \
                else "WARN" if col in fk_cols else "INFO"
            note = blank_ok.get(col) or {"ERROR": "required column",
                                         "WARN": "blank foreign key - check row rules to see if it is legitimate",
                                         "INFO": "blank may be legitimate - check context"}[sev]
            add_finding(name, g, "Blank values", col, sev, nb, n, note)
        # null-like words such as 'None'
        nt = int(null_token(s).sum())
        if nt:
            allowed_here = col in cfg.get("allowed_tokens", {}) or col in cfg.get("allowed", {})
            add_finding(name, g, "Null-like text token", col, "INFO" if allowed_here else "WARN", nt, n,
                        f"tokens: {r.null_tokens_seen}" + (" (listed as an allowed value in CONFIG)" if allowed_here else ""))
        # whitespace
        if r.whitespace_count:
            m = s.ne(s.str.strip()) | s.str.contains(r"\s{2,}", regex=True)
            add_finding(name, g, "Leading/trailing/double spaces", col, "WARN", int(m.sum()), n,
                        "breaks joins and group-bys", show_examples(df, m, [col], pk))
        # type validity vs expected (CONFIG) or inferred type
        present = ~missing(s)
        if r.pct_fail_expected_type and r.pct_fail_expected_type > 0:
            exp = r.expected_type
            if exp in ("int", "float"):
                nn = num(s)
                bad = present & (nn.isna() | ((nn % 1 != 0) if exp == "int" else False))
            elif exp == "date":
                bad = present & dt(df, col).isna()
            elif exp == "bool":
                bad = present & ~s.str.strip().str.lower().isin(BOOL_TOKENS)
            else:
                bad = pd.Series(False, index=s.index)
            sev = "ERROR" if col in cfg.get("types", {}) else "WARN"
            add_finding(name, g, f"Fails {exp} parse", col, sev, int(bad.sum()), int(present.sum()),
                        "expected type from CONFIG" if sev == "ERROR" else "minority values break the inferred type",
                        show_examples(df, bad, [col], pk))
        # integers stored as '45.0' - will not join to '45'
        if r.expected_type == "int" and r.numbers_with_decimal_point:
            m = present & s.str.contains(r"\.", regex=True) & num(s).notna()
            add_finding(name, g, "Integer stored with decimal point (e.g. 45.0)", col, "ERROR",
                        int(m.sum()), n, "text join to '45' will fail", show_examples(df, m, [col], pk))
        # mixed date formats
        if r.expected_type == "date" and r.date_formats_seen.count(";") >= 1:
            add_finding(name, g, "Mixed date formats", col, "ERROR",
                        int(round(r.pct_not_iso_date * present.sum() / 100)), int(present.sum()),
                        r.date_formats_seen)
        # mixed formats in short text codes (zip_code, state, ticker...): a
        # dominant shape covering >=90% of values plus a few odd ones out
        if r.expected_type == "str" and 1 < r.n_shapes <= 15:
            shp = _shape(s.where(present, ""))
            share = shp[present].value_counts(normalize=True)
            if len(share) > 1 and share.iat[0] >= 0.9:
                odd = present & (shp != share.index[0])
                add_finding(name, g, "Minority value shape (mixed format)", col, "WARN", int(odd.sum()),
                            int(present.sum()), f"dominant shape '{share.index[0]}' = {share.iat[0]:.1%}; "
                            f"others: {list(share.index[1:6])}", show_examples(df, odd, [col], pk))
        # mixed boolean spellings (True / 1 / yes)
        if r.expected_type == "bool":
            fams = set(s[present].str.strip().str.lower().map(
                lambda v: "word" if v in {"true", "false"} else "digit" if v in {"1", "0"}
                else "yn" if v in {"y", "n", "yes", "no"} else "letter"))
            spellings = set(s[present].str.strip())
            if len(fams) > 1 or len(spellings) > 2:
                add_finding(name, g, "Mixed boolean spellings", col, "WARN", int(present.sum()), n,
                            f"values: {sorted(spellings)}")

    # allowed values (exact match; also reports case/space variants)
    for col, allowed in cfg.get("allowed", {}).items():
        if col not in df.columns:
            continue
        s = df[col]
        bad = ~s.isin(allowed) & ~blank(s)          # blanks are reported separately above
        if bad.any():
            variants = up(s[bad]).isin([a.upper() for a in allowed]).sum()
            add_finding(name, g, "Value not in allowed list", col, "ERROR", int(bad.sum()), len(s),
                        f"{variants} are only case/space variants of an allowed value; "
                        f"distinct bad values: {sorted(s[bad].unique())[:10]}",
                        show_examples(df, bad, [col], pk))
    for col, (sep, tokens) in cfg.get("allowed_tokens", {}).items():
        if col not in df.columns:
            continue
        parts = df[col].str.split(sep)
        bad = parts.map(lambda xs: any(x.strip() not in tokens for x in xs))
        if bad.any():
            add_finding(name, g, "Token not in allowed list", col, "ERROR", int(bad.sum()), len(df),
                        f"allowed tokens: {tokens}", show_examples(df, bad, [col], pk))

    # ranges
    for col, (lo, hi, sev) in cfg.get("ranges", {}).items():
        if col not in df.columns:
            continue
        try:   # bounds may be functions of the calendar, e.g. dim_date min/max year
            lo, hi = (lo() if callable(lo) else lo), (hi() if callable(hi) else hi)
        except KeyError as e:
            skip(name, g, f"range for {col}", e)
            continue
        # unparseable values are reported by the type check; ranges test parsed values
        v = num(df[col])
        bad = v.notna() & (((v < lo) if lo is not None else False) | ((v > hi) if hi is not None else False))
        if bad.any():
            add_finding(name, g, f"Out of range [{lo}, {hi}]", col, sev, int(bad.sum()), int(v.notna().sum()),
                        f"min={v.min()} max={v.max()}", show_examples(df, bad, [col], pk))

    # primary key + alternate keys must be unique
    for col in ([pk] if pk else []) + cfg.get("unique", []):
        if col not in df.columns:
            continue
        s = df[col]
        present = ~missing(s)
        dup = present & s.duplicated(keep=False)
        sev = "ERROR" if col == pk else "WARN"
        label = "Primary key" if col == pk else "Alternate key"
        add_finding(name, g, f"{label} uniqueness", col, sev if dup.any() else "INFO", int(dup.sum()), len(s),
                    f"{s[present].duplicated().sum()} extra copies; "
                    f"{(canon_id(s)[present].duplicated(keep=False)).sum()} rows duplicate after trim/45.0->45",
                    show_examples(df, dup, [col], pk))


def detect_flag_columns(df, cfg) -> list[str]:
    """Data-quality flag columns from the earlier clean: listed in CONFIG
    (flag_cols) or named like a flag."""
    listed = [c for c in cfg.get("flag_cols", []) if c in df.columns]
    return listed + [c for c in df.columns if FLAG_NAME_PATTERN.search(c) and c not in listed]


def check_single_table(name, df, cfg):
    """Group 2: duplicates, near-duplicates, contradictory columns, flags."""
    g = "2 Single-table"
    pk = cfg.get("pk")
    n = len(df)
    non_pk = [c for c in df.columns if c != pk]

    exact = df.duplicated(keep=False)
    add_finding(name, g, "Exact duplicate rows", "(all)", "ERROR" if exact.any() else "INFO",
                int(exact.sum()), n, f"{df.duplicated().sum()} extra copies", show_examples(df, exact, non_pk[:3], pk))

    if pk in df.columns and non_pk:
        same_content = df.duplicated(subset=non_pk, keep=False) & ~exact
        add_finding(name, g, "Same content under different primary key", "(all but pk)",
                    "WARN" if same_content.any() else "INFO", int(same_content.sum()), n,
                    "may be a double-load, or legitimately identical events",
                    show_examples(df, same_content, non_pk[:4], pk))
        normed = df[non_pk].apply(lambda s: s.str.strip().str.lower().str.replace(r"\s+", " ", regex=True))
        near = normed.duplicated(keep=False) & ~df.duplicated(subset=non_pk, keep=False)
        add_finding(name, g, "Near-duplicates (differ only in case/spacing)", "(all but pk)",
                    "WARN" if near.any() else "INFO", int(near.sum()), n, "",
                    show_examples(df, near, non_pk[:4], pk))

    for keycols in cfg.get("natural_keys", []):
        if any(c not in df.columns for c in keycols):
            skip(name, g, f"natural key {keycols}", [c for c in keycols if c not in df.columns])
            continue
        k = df[keycols].apply(lambda s: s.str.strip().str.lower())
        has_all = ~df[keycols].apply(missing).any(axis=1)
        dup = has_all & k.duplicated(keep=False)
        add_finding(name, g, "Natural-key duplicates", "+".join(keycols), "WARN" if dup.any() else "INFO",
                    int(dup.sum()), int(has_all.sum()), "same business key under more than one row",
                    show_examples(df, dup, keycols, pk))

    # sign consistency inside each group (e.g. all SELL amounts positive)
    for amt, grp in cfg.get("sign_by", {}).items():
        if amt not in df.columns or grp not in df.columns:
            skip(name, g, f"sign_by {amt}/{grp}", amt if amt not in df.columns else grp)
            continue
        v = num(df[amt])
        gkey = up(df[grp])
        for gval, idx in gkey.groupby(gkey).groups.items():
            vv = v.loc[idx].dropna()
            vv = vv[vv != 0]
            if vv.empty:
                continue
            pos_share = (vv > 0).mean()
            dominant = "positive" if pos_share >= 0.5 else "negative"
            minority = vv[(vv > 0) != (dominant == "positive")]
            if len(minority):
                share = 1 - len(minority) / len(vv)
                add_finding(name, g, f"Sign inconsistent within {grp}={gval}", amt,
                            "WARN" if share >= 0.8 else "INFO", len(minority), len(vv),
                            f"{share:.1%} are {dominant}; minority may be reversals or sign errors",
                            show_examples(df, df.index.isin(minority.index), [grp, amt], pk))
        signs = v.groupby(gkey).agg(lambda x: "pos" if (x > 0).mean() >= .5 else "neg")
        add_finding(name, g, f"Dominant sign of {amt} by {grp}", amt, "INFO", 0, n, signs.to_dict().__repr__())

    # CONFIG row rules: columns in the same row that contradict each other
    for rule in cfg.get("row_rules", []):
        rname, fn, sev, cols = rule[:4]
        flag = rule[4] if len(rule) > 4 else None
        try:
            mask = pd.Series(fn(df), index=df.index).fillna(False).astype(bool)
        except (KeyError, AttributeError, EmptyFilter) as e:
            skip(name, g, rname, e)
            continue
        unp = unparseable(df, cols, cfg.get("types", {}))
        report_mask(name, g, rname, ",".join(cols), sev, mask | unp, df, cols, pk, flag, unp)

    # existing flag columns from the partial clean
    for fc in detect_flag_columns(df, cfg):
        s = df[fc].str.strip()
        ok_vals = {"0", "1", "True", "False", "true", "false", ""}
        bad = ~s.isin(ok_vals)
        if bad.any():
            add_finding(name, g, "Flag column has non-0/1 values", fc, "ERROR", int(bad.sum()), n,
                        f"values: {sorted(s[bad].unique())[:10]}")
        on = truthy(s)
        add_finding(name, g, "Existing flag column - rows flagged", fc, "INFO", int(on.sum()), n,
                    f"blank={int(blank(s).sum())}; decide in Part B whether flagged rows are defects or legit")


def report_mask(table, group, check, column, sev, mask, df, cols, pk, flag=None, unp=None):
    """Turn a True/False mask into a finding; optionally compare with an
    existing flag column so we can see what the partial clean missed."""
    detail = ""
    if unp is not None and unp.any():
        detail = f"includes {int(unp.sum())} rows where an input could not be parsed; "
    if flag and flag in df.columns:
        flagged = truthy(df[flag])
        missed = int((mask & ~flagged).sum())
        extra = int((flagged & ~mask).sum())
        detail += f"already flagged by {flag}: {int((mask & flagged).sum())}; NOT flagged: {missed}; " \
                  f"flagged but rule passes: {extra}"
    add_finding(table, group, check, column, sev if mask.any() else "INFO", int(mask.sum()), len(df),
                detail, show_examples(df, mask, cols, pk))


def ri_check(child: pd.DataFrame, fk: str, parent: pd.DataFrame, pk: str) -> dict:
    """Generic referential-integrity test on the raw text (what a join sees)."""
    s = child[fk]
    is_null = missing(s)
    keys = set(parent[pk])
    orphan = ~is_null & ~s.isin(keys)
    fixable = orphan & canon_id(s).isin(set(canon_id(parent[pk])))
    n_nonnull = int((~is_null).sum())
    return {
        "match_rate": round(100 * (n_nonnull - orphan.sum()) / n_nonnull, 3) if n_nonnull else np.nan,
        "orphan_rows": int(orphan.sum()), "distinct_orphans": int(s[orphan].nunique()),
        "null_rows": int(is_null.sum()), "null_rate": round(100 * is_null.mean(), 3) if len(s) else np.nan,
        "fixable_by_trim": int(fixable.sum()), "orphan_mask": orphan,
        "orphan_examples": sorted(s[orphan].unique())[:8],
    }


def check_referential_integrity_all(T: dict, prof_all: pd.DataFrame):
    """Group 3: every FK -> PK, plus every fact date -> dim_date."""
    g = "3 Referential integrity"
    dim_pks = {t: c["pk"] for t, c in CONFIG.items() if t.startswith("dim_") and c.get("pk")}

    # explicit FKs from CONFIG + auto-detected ones (column name == a dim's pk)
    relations = []
    for t, df in T.items():
        cfg = CONFIG[t]
        explicit = cfg.get("fks", {})
        for fk, (parent, pk) in explicit.items():
            relations.append((t, fk, parent, pk, "config"))
        for parent, pk in dim_pks.items():
            if parent != t and pk in df.columns and pk not in explicit and pk != cfg.get("pk"):
                relations.append((t, pk, parent, pk, "auto-detected"))

    for child, fk, parent, pk, how in relations:
        if parent not in T or fk not in T[child].columns or pk not in T[parent].columns:
            skip(child, g, f"FK {fk} -> {parent}.{pk}", fk if fk not in T[child].columns else pk)
            continue
        r = ri_check(T[child], fk, T[parent], pk)
        sev = "ERROR" if r["orphan_rows"] else "INFO"
        add_finding(child, g, f"FK {fk} -> {parent}.{pk}", fk, sev, r["orphan_rows"],
                    len(T[child]) - r["null_rows"],
                    f"match={r['match_rate']}%; distinct orphan keys={r['distinct_orphans']}; "
                    f"null FK rows={r['null_rows']} ({r['null_rate']}%); "
                    f"orphans that match after trim/45.0->45={r['fixable_by_trim']}; ({how})",
                    f"orphan keys: {r['orphan_examples']}")
        if r["null_rows"]:
            add_finding(child, g, f"Null FK {fk}", fk, "INFO", r["null_rows"], len(T[child]),
                        "null FK is not an orphan - decide whether it is legitimate (see row rules)")

    # dates -> dim_date
    if "dim_date" not in T:
        return
    dd = T["dim_date"]
    date_col = CONFIG["dim_date"].get("date_col")
    if date_col not in dd.columns:   # auto-detect: unique column that parses as dates
        p = prof_all[(prof_all.table == "dim_date")]
        cands = p[(p.pct_fail_date <= 1) & (p.distinct_count == len(dd))].column.tolist()
        skip("dim_date", g, "dim_date date_col", date_col)
        if not cands:
            return
        date_col = cands[0]
        add_finding("dim_date", g, "dim_date join column auto-detected", date_col, "INFO", 0, 0, "")
    dim_days = set(dt(dd, date_col).dropna().dt.normalize())
    dim_fmt = parse_dates(dd[date_col])[1].mode().iat[0]
    for t, df in T.items():
        if not t.startswith("fact_"):
            continue
        cols = list(CONFIG[t].get("date_cols", []))
        cols += [c for c in df.columns if "date" in c.lower() and c not in cols and not c.endswith("_id")]
        for c in cols:
            if c not in df.columns:
                skip(t, g, f"date {c} -> dim_date", c)
                continue
            parsed, fmts = parse_dates(df[c])
            present = ~missing(df[c])
            unparsed = present & parsed.isna()
            outside = parsed.notna() & ~parsed.dt.normalize().isin(dim_days)
            orphan = unparsed | outside
            fmt_diff = present & fmts.ne(dim_fmt) & parsed.notna()
            add_finding(t, g, f"Date {c} -> dim_date.{date_col}", c, "ERROR" if orphan.any() else "INFO",
                        int(orphan.sum()), int(present.sum()),
                        f"unparseable={int(unparsed.sum())}; outside calendar={int(outside.sum())}; "
                        f"null={int((~present).sum())}; rows in a different text format than dim_date "
                        f"({dim_fmt})={int(fmt_diff.sum())}",
                        show_examples(df, orphan, [c], CONFIG[t].get("pk")))


def check_dim_date_coverage(T):
    """dim_date must have exactly one row per calendar day in its range."""
    if "dim_date" not in T or not CONFIG["dim_date"].get("coverage") or not CAL:
        return
    dd, cfg = T["dim_date"], CONFIG["dim_date"]
    col = cfg.get("date_col")
    if col not in dd.columns:
        return
    start, end = CAL["start"].date().isoformat(), CAL["end"].date().isoformat()
    want = pd.date_range(start, end, freq="D")
    have = dt(dd, col).dropna().dt.normalize()
    gaps = want.difference(pd.DatetimeIndex(have.unique()))
    add_finding("dim_date", "1 Column", f"Calendar coverage {start}..{end}", col,
                "ERROR" if len(gaps) else "INFO", len(gaps), len(want),
                f"missing days: {[d.date().isoformat() for d in gaps[:8]]}")


# ---------------------------------------------------------------------------
# 6. GROUP 4 - CROSS-TABLE RULE TYPES (generic, parameterised by CROSS_RULES)
# Each function returns: (table, rows_affected, rows_checked, detail, examples)
# ---------------------------------------------------------------------------

def _lookup(T, dim, key, col) -> pd.Series:
    """Map key -> dim attribute (first row per trimmed key)."""
    d = T[dim].assign(_k=T[dim][key].str.strip()).drop_duplicates("_k")
    return pd.Series(d[col].values, index=d["_k"].values)


def _lookup_by_date(T, dim, key, col) -> pd.Series:
    """Map PARSED date -> dim attribute, so '2021-03-05' and '03/05/2021' both
    find the same dim_date row (a raw-text join would miss one of them)."""
    d = T[dim].assign(_k=dt(T[dim], key).dt.normalize())
    d = d[d["_k"].notna()].drop_duplicates("_k")
    return pd.Series(d[col].values, index=pd.DatetimeIndex(d["_k"]))


def _fact_dates_present_unparsed(f, col):
    return ~missing(f[col]) & dt(f, col).isna()


def rule_not_before(T, p):
    """Fact date must not be earlier than a dimension date (e.g. client_since).
    grain='M' compares calendar months (for month-start dated facts)."""
    f = T[p["table"]]
    fdate = dt(f, p["date_col"])
    since_raw = f[p["fk"]].str.strip().map(_lookup(T, p["dim"], p["dim_key"], p["dim_date_col"]))
    since = parse_dates(since_raw.fillna(""))[0]
    # present-but-unparseable dates on either side are flagged, not passed
    unp = _fact_dates_present_unparsed(f, p["date_col"]) | (since_raw.notna() & ~missing(since_raw.fillna("")) & since.isna())
    testable = fdate.notna() & since.notna()
    grain = p.get("grain")
    if grain:
        early = fdate.dt.to_period(grain) < since.dt.to_period(grain)
        gap = (since.dt.to_period(grain) - fdate.dt.to_period(grain))[testable & early].map(lambda x: x.n)
        unit = "months" if grain == "M" else grain
    else:
        early = fdate < since
        gap = (since - fdate)[testable & early].dt.days
        unit = "days"
    bad = (testable & early) | unp
    detail = (f"compared at {'month' if grain == 'M' else 'day'} level; testable={int(testable.sum())}; "
              f"{unit} early median={gap.median() if len(gap) else 0}; unparseable dates flagged={int(unp.sum())}; "
              f"clients affected={f.loc[bad, p['fk']].nunique()}")
    return p["table"], bad, int(testable.sum() + unp.sum()), detail, [p["fk"], p["date_col"]]


def rule_same_as_dim(T, p):
    f = T[p["table"]]
    ref = f[p["fk"]].str.strip().map(_lookup(T, p["dim"], p["dim_key"], p["dim_col"]))
    testable = ref.notna() & ~missing(f[p["col"]])
    # compare trimmed, case-insensitive, with 45.0 == 45
    bad = testable & (canon_id(f[p["col"]]).str.upper() != canon_id(ref.fillna("")).str.upper())
    detail = f"testable={int(testable.sum())}; clients affected={f.loc[bad, p['fk']].nunique()} " \
             f"(may be legitimate, e.g. a change over time - investigate before fixing)"
    return p["table"], bad, int(testable.sum()), detail, [p["fk"], p["col"]]


def rule_mapped_match(T, p):
    f = T[p["table"]]
    ref = up(f[p["fk"]].str.strip().map(_lookup(T, p["dim"], p["dim_key"], p["dim_col"])).fillna(""))
    mapping = {k.upper(): {v.upper() for v in vs} for k, vs in p["mapping"].items()}
    ok_sets = up(f[p["col"]]).map(mapping)
    testable = ref.ne("") & ok_sets.notna()
    bad = pd.Series([bool(t) and r not in s for t, r, s in zip(testable, ref, ok_sets)], index=f.index)
    return p["table"], bad, int(testable.sum()), f"mapping={p['mapping']}", [p["col"], p["fk"]]


def rule_recompute(T, p):
    """stored target vs a formula of other columns. `formula` may be a list of
    candidate formulas (e.g. monthly vs quarterly billing); the one that fits
    the most rows is used and the fit of every candidate is reported."""
    f = T[p["table"]]
    applies = filter_mask(f, p.get("filter"))
    formulas = p["formula"] if isinstance(p["formula"], list) else [p["formula"]]
    if p["target"] not in f.columns:
        raise KeyError(p["target"])
    stored = num(f[p["target"]])
    if p.get("abs"):
        stored = stored.abs()
    fits, best = [], None
    for formula in formulas:
        names = re.findall(r"[A-Za-z_]\w*", formula)
        absent = [c for c in names if c not in f.columns]
        if absent:
            raise KeyError(absent)
        calc = pd.DataFrame({c: num(f[c]) for c in dict.fromkeys(names)}).eval(formula)
        if p.get("abs"):
            calc = calc.abs()
        abs_tol = p.get("abs_tol", 0.01)
        if abs_tol == "auto":
            abs_tol = rounding_tol(*(f[c] for c in dict.fromkeys(names + [p["target"]])))
        tol = np.maximum(abs_tol, p.get("rel_tol", 0) * calc.abs())
        testable = applies & calc.notna() & stored.notna()
        bad = testable & ((stored - calc).abs() > tol)
        fit = 1 - bad.sum() / testable.sum() if testable.sum() else 0
        # inputs that are present but not numbers are flagged, not skipped
        unp = applies & pd.concat([~missing(f[c]) & num(f[c]).isna()
                                   for c in dict.fromkeys(names + [p["target"]])], axis=1).any(axis=1)
        bad = bad | unp
        fits.append(f"'{formula}' fits {fit:.1%}")
        if best is None or fit > best[0]:
            best = (fit, formula, calc, testable, bad, names, abs_tol)
    fit, formula, calc, testable, bad, names, abs_tol = best
    untestable = int((applies & ~testable & ~bad).sum())
    detail = (f"best formula: {formula} (tolerance {abs_tol:g}); rows where rule applies={int(applies.sum())}; "
              f"blank inputs (not testable)={untestable}; total |diff| on failures="
              f"{((stored - calc).abs()[bad]).sum():,.2f}")
    if len(formulas) > 1:
        detail += "; candidates: " + ", ".join(fits)
    return p["table"], bad, int(applies.sum() - untestable), detail, list(dict.fromkeys(names + [p["target"]]))


def rule_lookup_condition(T, p):
    """Look up a dimension attribute for each fact row (e.g. dim_date.is_trading_day
    for txn_date) and apply a condition `bad(ref_value, fact_df)`."""
    f = T[p["table"]]
    applies = filter_mask(f, p.get("filter"))
    unp = pd.Series(False, index=f.index)
    if p.get("join") == "date":     # join on parsed dates, not raw text
        lk = _lookup_by_date(T, p["dim"], p["dim_key"], p["dim_col"])
        ref = dt(f, p["fk"]).dt.normalize().map(lk)
        unp = applies & _fact_dates_present_unparsed(f, p["fk"])
    else:
        lk = _lookup(T, p["dim"], p["dim_key"], p["dim_col"])
        ref = f[p["fk"]].str.strip().map(lk)
    bad = (applies & pd.Series(p["bad"](ref, f), index=f.index).fillna(False).astype(bool)) | unp
    testable = applies & ref.notna()
    return p["table"], bad, int(testable.sum() + unp.sum()), \
        (f"{p['dim']}.{p['dim_col']} looked up via {p['fk']}"
         f"{' (parsed date join)' if p.get('join') == 'date' else ''}; rows tested={int(testable.sum())}; "
         f"unparseable keys flagged={int(unp.sum())}; no match in {p['dim']}={int((applies & ref.isna() & ~unp).sum())}"), p["cols"]


def rule_flag_crosstab(T, p):
    """Compare an existing flag with candidate explanations. Returns a dict
    (handled specially in check_cross_table)."""
    f = T[p["table"]]
    if p["flag"] not in f.columns:
        raise KeyError(p["flag"])
    flagged = truthy(f[p["flag"]])
    nf, nu = int(flagged.sum()), int((~flagged).sum())
    parts, best = [], None
    for cname, fn in p["conditions"].items():
        try:
            cond = pd.Series(fn(T, f), index=f.index).fillna(False).astype(bool)
        except (KeyError, AttributeError) as e:
            parts.append(f"[{cname}: skipped, {e}]")
            continue
        a = int((flagged & cond).sum())        # flagged and explained
        b = int((~flagged & cond).sum())       # condition true but NOT flagged
        agree = (a + (nu - b)) / len(f) if len(f) else 0
        parts.append(f"[{cname}: flagged {a}/{nf}, unflagged {b}/{nu}, agreement {agree:.2%}]")
        if best is None or agree > best[0]:
            best = (agree, cname, cond, a, b)
    return {"flagged": nf, "parts": parts, "best": best, "table": p["table"], "flag": p["flag"]}


def _period_totals(T, table, val, date, keys, period, filt, sign=1, agg="sum", count_only=False):
    """Total (or max) of `val` per key and calendar period, e.g. per client per month.
    Returns (Series, rows excluded because the date or value could not be parsed)."""
    f = T[table]
    sub = f[filter_mask(f, filt)]
    d = dt(sub, date)
    v = pd.Series(1.0, index=sub.index) if count_only else num(sub[val]) * sign
    excluded = int((d.isna() | v.isna()).sum())
    g = pd.DataFrame({k: sub[k].str.strip() for k in keys})
    g["period"] = d.dt.to_period(period).astype(str)
    g["v"] = v
    g = g[d.notna() & v.notna()]
    grouped = g.groupby(keys + ["period"])["v"]
    return (grouped.sum(min_count=1) if agg == "sum" else grouped.agg(agg)), excluded


def rule_reconcile_totals(T, p):
    """Two tables describing the same money: compare per key x period totals."""
    for t, c in ((p["left"], p["left_val"]), (p["right"], p["right_val"])):
        if c not in T[t].columns:
            raise KeyError(c)
    L, xl = _period_totals(T, p["left"], p["left_val"], p["left_date"], p["keys"], p["period"],
                           p.get("left_filter"), p.get("left_sign", 1), p.get("left_agg", "sum"))
    R, xr = _period_totals(T, p["right"], p["right_val"], p["right_date"], p["keys"], p["period"],
                           p.get("right_filter"), p.get("right_sign", 1), p.get("right_agg", "sum"))
    if L.empty or R.empty:
        raise EmptyFilter(f"no parseable rows on the {'right' if R.empty else 'left'} side")
    j = pd.concat([L.rename("left"), R.rename("right")], axis=1)
    both = j.left.notna() & j.right.notna()
    tol = np.maximum(p.get("abs_tol", 0.01), p.get("rel_tol", 0) * j.right.abs())
    mismatch = both & ((j.left - j.right).abs() > tol)
    only_l, only_r = j.left.notna() & j.right.isna(), j.right.notna() & j.left.isna()
    ex = j[mismatch].head(4).round(2).reset_index().to_dict("records")
    detail = (f"unit = {'+'.join(p['keys'])} x {p['period']} period; groups={len(j)}; both sides={int(both.sum())}; "
              f"mismatched={int(mismatch.sum())}; only in {p['left']}={int(only_l.sum())}; "
              f"only in {p['right']}={int(only_r.sum())}; left total={j.left.sum():,.2f}; "
              f"right total (sign x{p.get('right_sign', 1)})={j.right.sum():,.2f}; "
              f"unparseable rows excluded: left={xl}, right={xr}")
    # same comparison at coarser grains - helps show WHERE the tables agree
    if p.get("left_agg", "sum") == "sum" and p.get("right_agg", "sum") == "sum":
        for label, lvl in (("per client, all periods", p["keys"]), ("per period, all clients", ["period"])):
            jj = j.fillna(0).groupby(level=lvl).sum()
            tt = np.maximum(p.get("abs_tol", 0.01), p.get("rel_tol", 0) * jj.right.abs())
            detail += f"; {label}: {int(((jj.left - jj.right).abs() > tt).sum())}/{len(jj)} differ"
    return p["left"], int(mismatch.sum()), int(both.sum()), detail, str(ex)


def rule_exists_in(T, p):
    """Every key x period in `left` should also appear in `right`."""
    L, xl = _period_totals(T, p["left"], None, p["left_date"], p["keys"], p["period"], p.get("left_filter"), count_only=True)
    R, xr = _period_totals(T, p["right"], None, p["right_date"], p["keys"], p["period"], p.get("right_filter"), count_only=True)
    missing_idx = L.index.difference(R.index)
    return p["left"], len(missing_idx), len(L), \
        (f"unit = {'+'.join(p['keys'])} x {p['period']} period; "
         f"unparseable dates excluded: left={xl}, right={xr}"), str(list(missing_idx[:5]))


RULE_FUNCS = {"not_before": rule_not_before, "same_as_dim": rule_same_as_dim,
              "mapped_match": rule_mapped_match, "recompute": rule_recompute,
              "lookup_condition": rule_lookup_condition, "flag_crosstab": rule_flag_crosstab,
              "reconcile_totals": rule_reconcile_totals, "exists_in": rule_exists_in}


def check_cross_table(T):
    g = "4 Cross-table"
    for p in CROSS_RULES:
        tables = [p.get(k) for k in ("table", "dim", "left", "right") if p.get(k)]
        home = p.get("table") or p.get("left")
        if any(t not in T for t in tables):
            skip(home, g, p["name"], [t for t in tables if t not in T])
            continue
        try:
            result = RULE_FUNCS[p["type"]](T, p)
        except (KeyError, AttributeError, EmptyFilter) as e:
            skip(home, g, p["name"], e)
            continue

        if isinstance(result, dict):            # flag cross-tab
            df, n = T[result["table"]], len(T[result["table"]])
            add_finding(result["table"], g, p["name"], result["flag"], "INFO", result["flagged"], n,
                        " ".join(result["parts"]))
            if result["best"]:
                agree, cname, cond, a, b = result["best"]
                if b:   # best explanation is true on rows the flag did not catch
                    add_finding(result["table"], g, f"Rows matching '{cname}' but {result['flag']}=0",
                                result["flag"], p["severity"], b, n,
                                f"'{cname}' is the best match for the flag ({agree:.2%} agreement)",
                                show_examples(df, cond & ~truthy(df[result["flag"]]), [result["flag"]],
                                              CONFIG[result["table"]].get("pk")))
            continue

        table, bad, denom, detail, ex = result
        if isinstance(bad, pd.Series):          # row-level rule -> mask
            df = T[table]
            flag = p.get("flag")
            if flag and flag in df.columns:     # how much of this is already flagged?
                fl = truthy(df[flag])
                detail += (f"; already flagged by {flag}: {int((bad & fl).sum())}; "
                           f"NOT flagged: {int((bad & ~fl).sum())}")
            add_finding(table, g, p["name"], ",".join(ex), p["severity"] if bad.any() else "INFO",
                        int(bad.sum()), denom, detail, show_examples(df, bad, ex, CONFIG[table].get("pk")))
        else:                                   # aggregate rule -> counts
            sev, name = (p["severity"] if bad else "INFO"), p["name"]
            # most groups disagree -> the tables are not at the same grain,
            # which is a structural fact (INFO), not thousands of row errors
            if p["type"] == "reconcile_totals" and denom and bad / denom > p.get("grain_threshold", 0.5):
                sev = "INFO"
                name += f" - tables don't reconcile at {' x '.join(p['keys'])} x month (grain mismatch)"
            add_finding(table, g, name, "", sev, bad, denom, detail, ex)


# ---------------------------------------------------------------------------
# 7. MAIN - load, profile, check, save, print summary
# ---------------------------------------------------------------------------

def load_tables() -> dict[str, pd.DataFrame]:
    """Read every configured file as text. A missing file is an ERROR finding."""
    T = {}
    for name, cfg in CONFIG.items():
        path = RAW_DIR / cfg["file"]
        if not path.exists():
            add_finding(name, "0 Structure", "File missing", "", "ERROR", 0, 0, str(path))
            print(f"  !! missing file: {path}")
            continue
        T[name] = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        print(f"  loaded {cfg['file']:<30} {len(T[name]):>8,} rows  {T[name].shape[1]:>2} cols")
    return T


def main():
    pd.set_option("display.width", 160)
    print(f"\nRaw folder: {RAW_DIR}")
    T = load_tables()
    if not T:
        sys.exit("No raw files found - check hw04/data/raw/")

    # calendar range from dim_date's own min/max (used by year ranges, the
    # "final month" rules and the coverage check) - nothing is hard-coded
    if "dim_date" in T and CONFIG["dim_date"].get("date_col") in T["dim_date"].columns:
        cal = dt(T["dim_date"], CONFIG["dim_date"]["date_col"]).dropna()
        if len(cal):
            CAL.update(start=cal.min().normalize(), end=cal.max().normalize())
            add_finding("dim_date", "0 Structure", "Calendar range (from dim_date)", CONFIG["dim_date"]["date_col"],
                        "INFO", 0, len(T["dim_date"]), f"{CAL['start'].date()} .. {CAL['end'].date()}")
            print(f"  calendar from dim_date: {CAL['start'].date()} .. {CAL['end'].date()}")

    # profile every table with the same generic function
    profiles = [profile_table(df, name, CONFIG[name].get("types"), CONFIG[name].get("flag_cols"))
                for name, df in T.items()]
    prof_all = pd.concat(profiles, ignore_index=True)

    # groups 0-2 run table by table
    for name, df in T.items():
        cfg = CONFIG[name]
        check_structure(name, df, cfg)
        check_column_level(name, df, cfg, prof_all[prof_all.table == name])
        check_single_table(name, df, cfg)
    check_dim_date_coverage(T)
    # groups 3-4 need several tables at once
    check_referential_integrity_all(T, prof_all)
    check_cross_table(T)

    # save
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(FINDINGS)
    sev_order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    summary = summary.sort_values(["table", "check_group", "severity"],
                                  key=lambda s: s.map(sev_order) if s.name == "severity" else s)
    prof_all.to_csv(REPORT_DIR / "profile_raw.csv", index=False)
    summary.to_csv(REPORT_DIR / "dq_summary_raw.csv", index=False)

    # ---- screen summary ----
    print("\nROW COUNTS vs ASSIGNMENT SHEET (~ = differs; INFO only)")
    for name, cfg in CONFIG.items():
        actual = len(T[name]) if name in T else 0
        ok = "   " if actual == cfg.get("expected_rows") else "~  "
        print(f"  {ok}{name:<26} actual {actual:>8,}   expected {cfg.get('expected_rows', 0):>8,}")

    real = summary[~summary.check.str.startswith("CONFIG")]
    print("\nFINDINGS BY TABLE (ERROR / WARN / INFO)")
    pivot = real.pivot_table(index="table", columns="severity", values="check", aggfunc="count", fill_value=0)
    print(pivot.reindex(columns=["ERROR", "WARN", "INFO"], fill_value=0).to_string())

    flags = prof_all[prof_all.is_flag_column]
    if len(flags):
        print("\nEXISTING FLAG COLUMNS (from the partial clean)")
        for _, r in flags.iterrows():
            print(f"  {r.table}.{r.column}: shapes {r.top3_shapes}")

    print("\nTOP ERRORS (by rows affected)")
    top = real[real.severity == "ERROR"].sort_values("rows_affected", ascending=False).head(15)
    for _, r in top.iterrows():
        print(f"  [{r.check_group[:1]}] {r.table}.{r.column}: {r.check} - {r.rows_affected:,} rows")

    if SKIPPED:
        print(f"\n{len(SKIPPED)} CHECK(S) SKIPPED - a CONFIG name does not match the file headers:")
        for s in SKIPPED:
            print("  -", s)
        print("  Actual headers:")
        for name, df in T.items():
            print(f"    {name}: {list(df.columns)}")

    print(f"\nSaved {REPORT_DIR / 'profile_raw.csv'}  ({len(prof_all)} rows)")
    print(f"Saved {REPORT_DIR / 'dq_summary_raw.csv'}  ({len(summary)} findings)\n")


if __name__ == "__main__":
    main()
