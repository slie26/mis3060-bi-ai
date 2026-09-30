"""
hw03_timeline.py

Combines hw03/earnings_history.csv and hw03/executive_events.csv into a single
timeline that shows when each executive event happened relative to the
nearest earnings filing for the same company.

Output: hw03/corporate_events_timeline.csv

Columns in the output:
  - every column from executive_events.csv (company, ticker, cik, filing_date,
    event_type, person_name, title, effective_date)
  - every column from earnings_history.csv for the nearest earnings filing.
    The shared key columns (company, ticker, cik) appear once, and the
    earnings filing_date is renamed to earnings_filing_date so it does not
    collide with the event's filing_date.
  - days_to_nearest_earnings: absolute number of days between the event's
    filing_date and the nearest earnings filing_date
  - event_timing: 'same week', 'before earnings', or 'after earnings'

Run from the repository root:  python hw03/hw03_timeline.py
"""

from pathlib import Path

import pandas as pd

# Resolve paths relative to this script so it works from the repo root
# (as the other hw03 scripts expect) or from inside hw03/.
HW_DIR = Path(__file__).resolve().parent
EARNINGS_CSV = HW_DIR / "earnings_history.csv"
EVENTS_CSV = HW_DIR / "executive_events.csv"
OUTPUT_CSV = HW_DIR / "corporate_events_timeline.csv"

SAME_WEEK_DAYS = 7
NOT_FOUND = "NOT_FOUND"

EVENT_COLUMNS = [
    "company", "ticker", "cik", "filing_date",
    "event_type", "person_name", "title", "effective_date",
]
EARNINGS_EXTRA_COLUMNS = [
    "earnings_filing_date", "period",
    "revenue_reported", "eps_diluted", "net_income",
]


def load_csv(path):
    """Read a CSV as strings so CIKs keep their leading zeros and
    NOT_FOUND values stay exactly as written."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def classify_timing(signed_days):
    """signed_days = event filing_date minus earnings filing_date.
    The 7-day 'same week' rule is checked first."""
    if abs(signed_days) <= SAME_WEEK_DAYS:
        return "same week"
    if signed_days < 0:
        return "before earnings"
    return "after earnings"


def find_nearest_earnings(event_date, company_earnings):
    """Return the earnings row closest in time to event_date.
    If two earnings filings are equally close, the earlier one is used."""
    gaps = (company_earnings["filing_date_dt"] - event_date).abs()
    min_gap = gaps.min()
    candidates = company_earnings[gaps == min_gap]
    return candidates.sort_values("filing_date_dt").iloc[0]


def build_timeline(earnings, events):
    earnings = earnings.copy()
    earnings["filing_date_dt"] = pd.to_datetime(earnings["filing_date"], errors="coerce")
    earnings = earnings.dropna(subset=["filing_date_dt"])

    rows = []
    for _, event in events.iterrows():
        row = {col: event[col] for col in EVENT_COLUMNS}

        event_date = pd.to_datetime(event["filing_date"], errors="coerce")
        company_earnings = earnings[earnings["cik"] == event["cik"]]

        if pd.isna(event_date) or company_earnings.empty:
            # No usable date or no earnings data for this company.
            for col in EARNINGS_EXTRA_COLUMNS:
                row[col] = NOT_FOUND
            row["days_to_nearest_earnings"] = NOT_FOUND
            row["event_timing"] = NOT_FOUND
            rows.append(row)
            continue

        nearest = find_nearest_earnings(event_date, company_earnings)
        signed_days = (event_date - nearest["filing_date_dt"]).days

        row["earnings_filing_date"] = nearest["filing_date"]
        row["period"] = nearest["period"]
        row["revenue_reported"] = nearest["revenue_reported"]
        row["eps_diluted"] = nearest["eps_diluted"]
        row["net_income"] = nearest["net_income"]
        row["days_to_nearest_earnings"] = abs(signed_days)
        row["event_timing"] = classify_timing(signed_days)
        rows.append(row)

    columns = EVENT_COLUMNS + EARNINGS_EXTRA_COLUMNS + [
        "days_to_nearest_earnings", "event_timing",
    ]
    return pd.DataFrame(rows, columns=columns)


def print_company_summary(timeline, earnings, events):
    print("\n=== Executive events vs. nearest earnings filing, by company ===")

    # Keep companies in the order they first appear across both files,
    # so a company with earnings but no events is still listed.
    companies = (
        pd.concat([earnings[["company", "ticker"]], events[["company", "ticker"]]])
        .drop_duplicates(subset="ticker")
    )

    for _, comp in companies.iterrows():
        ticker = comp["ticker"]
        print(f"\n{comp['company']} ({ticker})")
        company_rows = timeline[timeline["ticker"] == ticker]
        if company_rows.empty:
            print("  No executive events")
            continue
        company_rows = company_rows.sort_values("filing_date")
        for _, r in company_rows.iterrows():
            if r["event_timing"] == NOT_FOUND:
                timing_text = "no earnings filing to compare against"
            else:
                days = r["days_to_nearest_earnings"]
                unit = "day" if days == 1 else "days"
                timing_text = (
                    f"{r['event_timing']} "
                    f"({days} {unit} from earnings filed {r['earnings_filing_date']})"
                )
            print(
                f"  {r['filing_date']} | {r['event_type']} | "
                f"{r['person_name']} | {r['title']} -> {timing_text}"
            )


def print_final_count(timeline):
    counts = timeline["event_timing"].value_counts()
    before = counts.get("before earnings", 0)
    after = counts.get("after earnings", 0)
    same_week = counts.get("same week", 0)
    unmatched = counts.get(NOT_FOUND, 0)

    print("\n=== Final count across all companies ===")
    print(f"Before earnings: {before}")
    print(f"After earnings:  {after}")
    print(f"Same week (within {SAME_WEEK_DAYS} days, counted separately): {same_week}")
    if unmatched:
        print(f"No earnings match: {unmatched}")
    print(f"Total events:    {len(timeline)}")


def main():
    earnings = load_csv(EARNINGS_CSV)
    events = load_csv(EVENTS_CSV)

    timeline = build_timeline(earnings, events)
    timeline.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {len(timeline)} rows to {OUTPUT_CSV}")

    print_company_summary(timeline, earnings, events)
    print_final_count(timeline)


if __name__ == "__main__":
    main()
