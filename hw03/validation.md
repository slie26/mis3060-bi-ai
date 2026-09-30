# HW3 Validation

## 5A — Known-Answer Check: Earnings

Company and quarter checked: Microsoft (MSFT), fourth quarter of fiscal year 2026

| Check | Official Source | Your CSV | Match? |
|---|---|---|---|
| MSFT Q4 FY2026 Revenue | $90.0 billion | $90,000 million | Yes |
| MSFT Q4 FY2026 EPS Diluted | $4.81 (GAAP) | $4.81 | Yes |

Source: Microsoft's Q4 FY2026 earnings press release (8-K Exhibit 99.1, July 29, 2026), https://www.sec.gov/Archives/edgar/data/0000789019/000119312526323632/msft-ex99_1.htm. Also confirmed by Redmond Magazine (July 30, 2026). Note: Microsoft also reported non-GAAP diluted EPS of $4.74, which excludes the impact of its OpenAI investment. The CSV value matches the GAAP figure, which is the standard reported number.

### Regex fix: net income (AAPL, NVDA, WMT)

Net income returned NOT_FOUND for all 12 AAPL, NVDA, and WMT rows on the first run. These companies report net income only in the income statement table, which is flattened to one line when HTML is stripped (e.g., "Net income $ 29,789 $ 23,434 $ 101,464 $ 84,544"). The original pattern only matched sentences like "net income of $X billion."

- Before: `\bnet\s+income\b[^$]{0,40}?\$\s*(\d[\d,]*(?:\.\d+)?)\s*(million|billion)\b`
- After (fallback, used when the Before pattern finds nothing): (?i)\b(?:consolidated\s+)?net\s+income(?:\s+attributable\s+to\s+(?!non-?controlling)[A-Za-z.,&' ]+?)?\s*\$?\s*(\(?\d[\d,]*(?:\.\d+)?\)?)(?=\s|$) 
- Result: net income went from 8 of 20 rows found to 20 of 20. Fix resolved the issue.

## 5B — Known-Answer Check: Executive Events

Event checked: MSFT, filed 2026-05-14, appointment, Carmine Di Sibio, member of the Board of Directors, effective 2026-05-13

| Check | News Source Confirms? | Notes |
|---|---|---|
| Person name and title | Yes | Carmine Di Sibio (former global chairman and CEO of EY) was appointed to Microsoft's board of directors and will serve on the Audit and Compensation Committees. |
| Event type (departure/appointment) | Yes | Appointment. The board was expanded to 13 members to add him, so there is no matching departure. |
| Effective date | Yes | The 8-K states the appointment was effective May 13, 2026. The CSV shows 2026-05-13, which is correct. The filing date (May 14) is one day later, and the script correctly used the effective date from the text rather than the filing date. |

Sources: Microsoft press release "Microsoft announces appointment of Carmine Di Sibio to board of directors" (PR Newswire, May 14, 2026); Microsoft 8-K Item 5.02 filed May 14, 2026, https://www.sec.gov/Archives/edgar/data/0000789019/000119312526224155/d125909d8k.htm

## 5C — Cross-Validation: Earnings via Yahoo Finance

Quarter checked: MSFT, quarter ended June 30, 2026 (fiscal Q4 2026). yfinance's most recent quarter end date is 2026-06-30, so both sources cover the same period.

| Metric | From 8-K text extraction | From yfinance | Match? |
|---|---|---|---|
| Revenue | $90,000 million | $90,007 million | Yes (within rounding) |
| Net Income | $35,800 million | $35,766 million | Yes (within rounding) |

The small differences ($7 million on revenue, $34 million on net income) come from rounding, not from an extraction error or a period mismatch. The press release sentences state revenue as "$90.0 billion" and net income as "$35.8 billion," rounded to the nearest $100 million, which the script converted to 90,000 and 35,800. yfinance reports the exact figures from the financial statements ($90,007,000,000 and $35,766,000,000), which round to the same values. Script used: `hw03/hw03_yfinance_check.py`.

## 5D — Pipeline Integrity Checks

| Check | Expected | Actual | Pass/Fail |
|---|---|---|---|
| `earnings_history.csv` row count | Up to 20 (5 companies × 4 quarters) | 20 | Pass |
| `executive_events.csv` row count | At least 0 (document actual) | 30 | Pass |
| `corporate_events_timeline.csv` created | Yes | Yes (30 rows) | Pass |
| Rows with all three fields `"NOT_FOUND"` | 0 (investigate if > 0) | 0 | Pass |

### Remaining known extraction issues
- JPM EPS is NOT_FOUND in 2 rows, and JPM second quarter 2026 EPS shows "$1.0", which looks wrong (JPM's quarterly EPS is usually around $4–5).
- WMT period is NOT_FOUND in 1 row.
- Executives: NVDA "Worldwide Field" is a title fragment, not a person's name; four WMT 2026-01-16 rows share one repeated title; the JPM 2025-12-08 row has NOT_FOUND for both name and title; several titles are NOT_FOUND.