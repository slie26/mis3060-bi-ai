"""
HW03 - yfinance cross-check for MSFT's most recent quarter.

Pulls the most recent quarterly Total Revenue and Net Income for Microsoft
(MSFT) from yfinance and prints the quarter end date, so the figures can be
compared against the quarter ended June 30, 2026.

Requires: pip install yfinance pandas
"""

import pandas as pd
import yfinance as yf

TICKER = "MSFT"
EXPECTED_QUARTER_END = pd.Timestamp("2026-06-30")

REVENUE_ROWS = ["Total Revenue", "Operating Revenue"]
NET_INCOME_ROWS = ["Net Income", "Net Income Common Stockholders"]


def pick_row(statement: pd.DataFrame, candidates: list[str]) -> tuple[str, pd.Series]:
    """Return the first matching row label and its values from the statement."""
    for label in candidates:
        if label in statement.index:
            return label, statement.loc[label]
    raise KeyError(f"None of these rows were found: {candidates}")


def main() -> None:
    stock = yf.Ticker(TICKER)
    stmt = stock.quarterly_income_stmt

    if stmt is None or stmt.empty:
        raise SystemExit(f"yfinance returned no quarterly income statement for {TICKER}.")

    # Columns are quarter end dates; sort so the newest quarter is first.
    stmt = stmt.reindex(sorted(stmt.columns, reverse=True), axis=1)

    rev_label, revenue_row = pick_row(stmt, REVENUE_ROWS)
    ni_label, net_income_row = pick_row(stmt, NET_INCOME_ROWS)

    # Most recent quarter that has both values reported.
    both = pd.DataFrame({"revenue": revenue_row, "net_income": net_income_row}).dropna()
    if both.empty:
        raise SystemExit("No quarter has both revenue and net income reported.")

    quarter_end = pd.Timestamp(both.index[0])
    revenue = float(both.iloc[0]["revenue"])
    net_income = float(both.iloc[0]["net_income"])

    print(f"Ticker:              {TICKER}")
    print(f"Quarter end date:    {quarter_end:%Y-%m-%d}")
    if quarter_end.normalize() == EXPECTED_QUARTER_END:
        print("Quarter check:       MATCH (quarter ended June 30, 2026)")
    else:
        print(f"Quarter check:       DIFFERENT - expected {EXPECTED_QUARTER_END:%Y-%m-%d}")
    print()
    print(f"Revenue ({rev_label})")
    print(f"  Exact:             ${revenue:,.0f}")
    print(f"  In millions:       ${revenue / 1_000_000:,.2f}M")
    print()
    print(f"Net income ({ni_label})")
    print(f"  Exact:             ${net_income:,.0f}")
    print(f"  In millions:       ${net_income / 1_000_000:,.2f}M")


if __name__ == "__main__":
    main()
