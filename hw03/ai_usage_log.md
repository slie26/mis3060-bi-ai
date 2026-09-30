# HW3 AI Usage Log

## Prompt 1: Specification A (sent to Claude Cowork)

Write a Python script called `hw03/hw03_earnings.py` that builds a table of quarterly earnings data from SEC 8-K filings. Use the `requests` and `beautifulsoup4` libraries.

1. **User-Agent header.** Set the HTTP header `User-Agent: MIS3060 Villanova slie@villanova.edu` on every single request the script makes, not just the first one. The easiest way is to define the headers once and route all requests through one helper function that always includes them. Pause about 0.2 seconds between requests, because the SEC limits traffic to 10 requests per second.

2. **Find the earnings filings.** Process these five companies:

   | Company | Ticker | CIK |
   |---|---|---|
   | Apple Inc. | AAPL | 0000320193 |
   | Microsoft Corporation | MSFT | 0000789019 |
   | NVIDIA Corporation | NVDA | 0001045810 |
   | JPMorgan Chase & Co. | JPM | 0000019617 |
   | Walmart Inc. | WMT | 0000104169 |

   For each company, request `https://data.sec.gov/submissions/CIK{cik}.json` using the full 10-digit CIK with leading zeros. In the JSON, the filings are under `filings` → `recent`, stored as parallel lists (`form`, `items`, `filingDate`, `accessionNumber`, `primaryDocument`) where the same index position refers to the same filing. Loop through them by index and keep only filings where `form` equals `"8-K"` and the `items` text contains `"2.02"`. Check whether it contains the text rather than for an exact match, because the field often lists several items, like `"2.02,9.01"`.

3. **Pick four filings.** Sort the matching filings by `filingDate`, newest first, and keep the four most recent for each company (one per quarter).

4. **Find and download the press release.** For each filing, build the filing folder URL as `https://www.sec.gov/Archives/edgar/data/{CIK without leading zeros}/{accession number with dashes removed}/`. Open the filing index page in that folder, `{accession number with dashes}-index.htm`, and read its table of documents. The earnings press release is the `.htm` document whose Type is `EX-99.1` (or starts with `EX-99`). If no document has that type, fall back to any `.htm` file whose name contains `ex99` or `exhibit99`. If still nothing is found, print a warning like `WARNING: [Ticker] [filing date]: press release exhibit not found, skipping` and continue to the next filing. Never crash. Download the press release and use BeautifulSoup to strip the HTML down to plain text.

5. **Extract four fields from the text** using regular expressions:
   - **Quarterly revenue.** Companies use different labels, so try several: "revenue", "revenues", "total revenues", "net revenue", "net sales". Capture the dollar amount and its unit (million or billion) and convert it to millions, so $94.9 billion becomes 94900.
   - **Diluted EPS.** Look for phrasing like "diluted earnings per share of $1.64", "$1.64 per diluted share", or "EPS of $1.64". Store just the number.
   - **Net income.** Look for "net income of $X million/billion" and convert to millions the same way as revenue.
   - **Reporting period.** Capture phrases like "fourth quarter fiscal 2024", "second quarter of fiscal year 2025", or "third-quarter 2025".

   Press releases usually give the current quarter first and then a year-ago comparison, so take the first match after each label, not a later one.

6. **Print each row as it's processed**, in exactly this format:
   `[Ticker] | [Period] | Revenue: $X | EPS: $X | Net Income: $X`

7. **Save the results** to `hw03/earnings_history.csv` (the script will be run from the repository root) with these columns, in this order: `company`, `ticker`, `cik`, `filing_date`, `period`, `revenue_reported`, `eps_diluted`, `net_income`. After saving, print a confirmation message with the number of rows written.

8. **Handle missing data.** If a regex finds no match for a field, store the exact string `"NOT_FOUND"` in that cell. Never leave it blank and never store `None`, because a blank cell and missing data mean different things. Still save the row even if some fields are `NOT_FOUND`. Wrap each company's and each filing's processing in error handling, so that one failed download or parsing error prints a warning and the script moves on to the next one.

Save the script as hw03/hw03_earnings.py. Do not run it yet, and do not change any other files.

## Prompt 2: Specification B (sent to Claude Cowork, new conversation)

Write a Python script called `hw03/hw03_executives.py` that builds a table of executive departures and appointments from SEC 8-K filings. Use the `requests` and `beautifulsoup4` libraries.

1. **User-Agent header.** Set the HTTP header `User-Agent: MIS3060 Villanova slie@villanova.edu` on every single request the script makes, not just the first one, by routing all requests through one helper function that always includes it. Pause about 0.2 seconds between requests to stay under the SEC's limit of 10 requests per second.

2. **Find the executive-change filings.** Process these five companies:

   | Company | Ticker | CIK |
   |---|---|---|
   | Apple Inc. | AAPL | 0000320193 |
   | Microsoft Corporation | MSFT | 0000789019 |
   | NVIDIA Corporation | NVDA | 0001045810 |
   | JPMorgan Chase & Co. | JPM | 0000019617 |
   | Walmart Inc. | WMT | 0000104169 |

   For each company, request `https://data.sec.gov/submissions/CIK{cik}.json` using the full 10-digit CIK with leading zeros. The filings are under `filings` → `recent` as parallel lists (`form`, `items`, `filingDate`, `accessionNumber`, `primaryDocument`). Keep only filings where `form` equals `"8-K"`, the `items` text contains `"5.02"` (check for "contains", since the field can list several items like `"5.02,9.01"`), and `filingDate` is within the past 12 months. Calculate that window from today's date when the script runs (today minus 365 days) rather than hardcoding a date.

3. **Download and extract the events.** For each matching filing, download the main 8-K document at `https://www.sec.gov/Archives/edgar/data/{CIK without leading zeros}/{accession number with dashes removed}/{primaryDocument}` and use BeautifulSoup to strip the HTML to plain text. Focus on the Item 5.02 section: the text from "Item 5.02" up to the next "Item" heading or "SIGNATURE". From that section, extract for each event:
   - **event_type.** Use `"departure"` for wording like resigned, retired, stepped down, will depart, or will not stand for re-election. Use `"appointment"` for wording like appointed, elected, named, or promoted. Use `"both"` only when a single person is leaving one role and taking another (for example, moving from CFO to COO).
   - **person_name.** The person's full name (first and last name).
   - **title.** Their title, such as "Chief Financial Officer", "Executive Vice President", or "member of the Board of Directors".
   - **effective_date.** The date after the word "effective" (for example, "effective March 1, 2026"). If the text says "effective immediately", use the filing date.

   If a field can't be found, store the exact string `"NOT_FOUND"` rather than leaving it blank or storing `None`. If the Item 5.02 section only covers compensation or benefit plans and describes no departure or appointment, print `[Ticker] | [Date] | compensation-only filing, skipped` and move on.

4. **One row per event.** If a filing describes more than one event (for example, one executive departs and another is appointed), create a separate row for each event, each with its own name, title, event_type, and effective_date.

5. **Print each event as it's processed**, in exactly this format:
   `[Ticker] | [Date] | [Event Type] | [Name] | [Title]`

6. **Handle companies with no events.** If a company has no Item 5.02 filings in the past 12 months, print `[Ticker]: No executive events in past 12 months` and continue to the next company. This is valid data, not an error, so the script must not crash or skip the company silently.

7. **Save the results** to `hw03/executive_events.csv` (the script will be run from the repository root) with these columns, in this order: `company`, `ticker`, `cik`, `filing_date`, `event_type`, `person_name`, `title`, `effective_date`. If no events are found at all, still create the CSV with just the header row. After saving, print a confirmation message with the number of rows written. Wrap each company's and each filing's processing in error handling, so one failed download or parsing error prints a warning and the script continues.

Save the script as hw03/hw03_executives.py. Do not run it yet, and do not change any other files.

## Prompt 3: Timeline (sent to Claude Cowork, new conversation)

Write a Python script that reads `hw03/earnings_history.csv` and `hw03/executive_events.csv`. Do the following:

1. For each executive event in the events table, calculate the number of days between the executive event's `filing_date` and the nearest earnings filing date for the same company in the earnings table. Call this `days_to_nearest_earnings`.
2. Add a column `event_timing` that categorizes each executive event as: `'before earnings'` if the event came before the nearest earnings filing, `'after earnings'` if it came after, or `'same week'` if within 7 days of an earnings filing.
3. Save the combined table to `hw03/corporate_events_timeline.csv` with all columns from both source tables plus `days_to_nearest_earnings` and `event_timing`.
4. Print a summary: for each company, list any executive events and whether they occurred before or after the nearest earnings announcement.
5. Print a final count: how many events occurred before vs. after an earnings announcement across all five companies.

Save it as hw03/hw03_timeline.py. When deciding event_timing, check the 7-day 'same week' rule first, before 'before earnings' or 'after earnings'. Do not run it yet, and do not change any other files.

Note: I added the "same week first" instruction because the assignment's categories overlap. An event 3 days before earnings is both "before" and "same week", so the order of the checks decides the label.

## Extractions that required iteration

- **AAPL, NVDA, WMT (net income):** Net income was NOT_FOUND for all 12 rows on the first run. I had Cowork save Apple's plain-text press release, found that net income only appears in the flattened income statement table ("Net income $ 29,789 $ 23,434 ..."), and asked a new Cowork session: "What regex pattern would reliably extract the current-quarter net income figure from this text?" I then had the original session add that pattern as a fallback, with special handling for Walmart ("attributable to Walmart") and NVIDIA (search only after the tax line). Net income went from 8/20 to 20/20. Before/after patterns are in validation.md.
- **JPM (EPS) and WMT (period):** Not fixed. JPM EPS is NOT_FOUND in 2 rows and one value ($1.0) looks wrong; one WMT period is NOT_FOUND. Documented in validation.md.
- **Executives:** Not iterated. Known errors (a title fragment captured as a name, repeated titles, some NOT_FOUND titles) are documented in validation.md.

Other prompt used: for Part 5C, I asked Cowork to "Write Python using yfinance to get the most recent quarterly revenue and net income for MSFT," which produced hw03/hw03_yfinance_check.py.

## Something the generated script did that I didn't specify

In the timeline script, Cowork made `days_to_nearest_earnings` always a positive number (days apart) and used the separate `event_timing` column to show direction. It also renamed the earnings table's `filing_date` to `earnings_filing_date` so it wouldn't clash with the event's `filing_date`, and it read CIKs as text so their leading zeros weren't lost. These choices were correct and needed no adjustment. The renaming was necessary to keep "all columns from both source tables" without two columns having the same name.

## Other AI assistance

I also used Claude (chat) as a guide throughout the assignment: to walk through setup, help draft the specifications and analysis paragraph, interpret outputs, and look up official figures for validation.