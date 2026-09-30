"""
hw03_earnings.py

Builds a table of quarterly earnings data from SEC 8-K filings (Item 2.02,
"Results of Operations and Financial Condition") for five large companies.

For each company the script:
  1. Downloads the company's submissions JSON from data.sec.gov.
  2. Keeps 8-K filings whose items include "2.02" and picks the 4 most recent.
  3. Opens each filing's index page and finds the EX-99.1 press release.
  4. Strips the press release HTML to plain text with BeautifulSoup.
  5. Extracts revenue, diluted EPS, net income, and reporting period with regex.

Results are printed row by row and saved to hw03/earnings_history.csv.
Run from the repository root:  python hw03/hw03_earnings.py
"""

import csv
import os
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HEADERS = {"User-Agent": "MIS3060 Villanova slie@villanova.edu"}
REQUEST_PAUSE_SECONDS = 0.2  # SEC allows at most 10 requests per second
REQUEST_TIMEOUT_SECONDS = 30

COMPANIES = [
    {"company": "Apple Inc.", "ticker": "AAPL", "cik": "0000320193"},
    {"company": "Microsoft Corporation", "ticker": "MSFT", "cik": "0000789019"},
    {"company": "NVIDIA Corporation", "ticker": "NVDA", "cik": "0001045810"},
    {"company": "JPMorgan Chase & Co.", "ticker": "JPM", "cik": "0000019617"},
    {"company": "Walmart Inc.", "ticker": "WMT", "cik": "0000104169"},
]

FILINGS_PER_COMPANY = 4
NOT_FOUND = "NOT_FOUND"
OUTPUT_CSV = os.path.join("hw03", "earnings_history.csv")
CSV_COLUMNS = [
    "company",
    "ticker",
    "cik",
    "filing_date",
    "period",
    "revenue_reported",
    "eps_diluted",
    "net_income",
]

SEC_BASE = "https://www.sec.gov"


# ---------------------------------------------------------------------------
# HTTP helper: every request in the script goes through this function
# ---------------------------------------------------------------------------

def sec_get(url):
    """GET a URL with the required User-Agent header, then pause briefly."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response
    finally:
        # Pause after every request (successful or not) to respect SEC limits.
        time.sleep(REQUEST_PAUSE_SECONDS)


# ---------------------------------------------------------------------------
# Step 2 & 3: find the earnings (Item 2.02) filings
# ---------------------------------------------------------------------------

def get_earnings_filings(cik):
    """Return the most recent 8-K filings with Item 2.02, newest first."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    data = sec_get(url).json()
    recent = data["filings"]["recent"]

    forms = recent.get("form", [])
    items = recent.get("items", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    matches = []
    for i in range(len(forms)):
        form = forms[i]
        item_text = items[i] if i < len(items) and items[i] else ""
        if form == "8-K" and "2.02" in item_text:
            matches.append(
                {
                    "filing_date": dates[i],
                    "accession": accessions[i],
                    "primary_document": primary_docs[i] if i < len(primary_docs) else "",
                }
            )

    # ISO dates (YYYY-MM-DD) sort correctly as strings.
    matches.sort(key=lambda f: f["filing_date"], reverse=True)
    return matches[:FILINGS_PER_COMPANY]


# ---------------------------------------------------------------------------
# Step 4: locate and download the press release exhibit
# ---------------------------------------------------------------------------

def clean_href(href):
    """Turn an index-page link into an absolute document URL.

    Inline XBRL documents are sometimes linked as /ix?doc=/Archives/...,
    so strip that viewer prefix to get the raw document.
    """
    if href.startswith("/ix?doc="):
        href = href[len("/ix?doc="):]
    return urljoin(SEC_BASE, href)


def find_press_release_url(cik, accession):
    """Read the filing index page and return the press release URL, or None."""
    cik_no_zeros = str(int(cik))
    accession_no_dashes = accession.replace("-", "")
    folder_url = f"{SEC_BASE}/Archives/edgar/data/{cik_no_zeros}/{accession_no_dashes}/"
    index_url = f"{folder_url}{accession}-index.htm"

    soup = BeautifulSoup(sec_get(index_url).text, "html.parser")

    # Collect (filename, type, url) for every document listed in the tables.
    documents = []
    for table in soup.find_all("table", class_="tableFile"):
        rows = table.find_all("tr")
        if not rows:
            continue

        # Work out which columns hold "Document" and "Type" from the header.
        header_cells = [c.get_text(strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        doc_col = header_cells.index("document") if "document" in header_cells else 2
        type_col = header_cells.index("type") if "type" in header_cells else 3

        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) <= max(doc_col, type_col):
                continue
            link = cells[doc_col].find("a")
            if link is None or not link.get("href"):
                continue
            doc_url = clean_href(link["href"])
            filename = doc_url.rsplit("/", 1)[-1]
            doc_type = cells[type_col].get_text(strip=True).upper()
            documents.append({"filename": filename, "type": doc_type, "url": doc_url})

    htm_docs = [d for d in documents if d["filename"].lower().endswith((".htm", ".html"))]

    # 1st choice: Type is exactly EX-99.1
    for doc in htm_docs:
        if doc["type"] == "EX-99.1":
            return doc["url"]

    # 2nd choice: Type starts with EX-99
    for doc in htm_docs:
        if doc["type"].startswith("EX-99"):
            return doc["url"]

    # Fallback: file name contains ex99 or exhibit99 (ignoring - _ separators)
    for doc in htm_docs:
        name = doc["filename"].lower().replace("-", "").replace("_", "")
        if "ex99" in name or "exhibit99" in name:
            return doc["url"]

    return None


def html_to_text(html):
    """Strip HTML down to plain text with normalized whitespace."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = text.replace("\xa0", " ")
    # Normalize curly quotes/dashes that can break regex matching.
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Step 5: regex extraction
# ---------------------------------------------------------------------------

# A dollar amount with a unit, e.g. "$94.9 billion" or "$94,930 million".
AMOUNT = r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*(million|billion)\b"

# Labels are listed longest first so "total revenues" wins over "revenues".
# [^$]{0,60}? allows a short phrase ("of", "was", "for the quarter was") between
# the label and the amount, and stops at the first dollar sign after the label.
REVENUE_PATTERN = re.compile(
    r"\b(?:total\s+revenues?|net\s+revenues?|net\s+sales|revenues?)\b[^$]{0,60}?" + AMOUNT,
    re.IGNORECASE,
)

NET_INCOME_PATTERN = re.compile(
    r"\bnet\s+income\b[^$]{0,40}?" + AMOUNT,
    re.IGNORECASE,
)

# Fallback for the flattened income statement table, e.g.
#   "Net income $ 29,789 $ 23,434 ..."  or
#   "Consolidated net income attributable to Walmart 4,508 ..."
# Table values are already in millions and may be negative, e.g. "(1,234)".
# Group 1 is the first number after the label (the current quarter).
NET_INCOME_TABLE_PATTERN = re.compile(
    r"(?i)\b(?:consolidated\s+)?net\s+income"
    r"(?:\s+attributable\s+to\s+(?!non-?controlling)[A-Za-z.,&' ]+?)?"
    r"\s*\$?\s*(\(?\d[\d,]*(?:\.\d+)?\)?)(?=\s|$)"
)

# NVIDIA: only search the income statement, which starts after the tax line,
# so a summary table earlier in the release is not picked up.
INCOME_STATEMENT_ANCHOR = re.compile(
    r"provision\s+for\s+income\s+taxes|income\s+tax\s+expense",
    re.IGNORECASE,
)

EPS_PATTERNS = [
    # "diluted earnings per share of $1.64" / "Diluted earnings per share was $3.65"
    re.compile(r"\bdiluted\s+earnings\s+per\s+share\b[^$]{0,40}?\$\s*(\d+\.\d+)", re.IGNORECASE),
    # "earnings per diluted share for the quarter were $1.08"
    re.compile(r"\bearnings\s+per\s+diluted\s+share\b[^$]{0,40}?\$\s*(\d+\.\d+)", re.IGNORECASE),
    # "$1.64 per diluted share"
    re.compile(r"\$\s*(\d+\.\d+)\s+per\s+diluted\s+share\b", re.IGNORECASE),
    # "EPS of $1.64" / "diluted EPS was $1.64"
    re.compile(r"\bEPS\b[^$]{0,40}?\$\s*(\d+\.\d+)", re.IGNORECASE),
]

QUARTER_WORD = r"(?:first|second|third|fourth)"
PERIOD_PATTERNS = [
    # "fourth quarter fiscal 2024", "second quarter of fiscal year 2025",
    # "third-quarter 2025", "fourth quarter and fiscal year 2025"
    re.compile(
        QUARTER_WORD
        + r"[\s-]+quarter\s+(?:of\s+)?(?:and\s+(?:full\s+)?)?(?:fiscal\s+)?(?:year\s+)?(?:of\s+)?\d{4}\b",
        re.IGNORECASE,
    ),
    # "fiscal 2025 third quarter", "2025 second-quarter"
    re.compile(
        r"(?:fiscal\s+(?:year\s+)?)?\d{4}\s+" + QUARTER_WORD + r"[\s-]+quarter\b",
        re.IGNORECASE,
    ),
]


def to_millions(amount_text, unit):
    """Convert '94.9' + 'billion' to 94900.0 (millions)."""
    value = float(amount_text.replace(",", ""))
    if unit.lower() == "billion":
        value *= 1000
    return value


def format_number(value):
    """Format a float without trailing .0 (94900.0 -> '94900', 1.5 -> '1.5')."""
    value = round(value, 2)
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def extract_amount_in_millions(pattern, text):
    """Return the first matching dollar amount converted to millions, or NOT_FOUND."""
    match = pattern.search(text)
    if not match:
        return NOT_FOUND
    return format_number(to_millions(match.group(1), match.group(2)))


def earliest_match(patterns, text):
    """Return the match that appears earliest in the text across several patterns."""
    best = None
    for pattern in patterns:
        match = pattern.search(text)
        if match and (best is None or match.start() < best.start()):
            best = match
    return best


def parse_table_number(value_text):
    """Convert a table value like '29,789' or '(1,234)' to millions (no scaling)."""
    negative = value_text.startswith("(")
    value = float(value_text.strip("()").replace(",", ""))
    return format_number(-value if negative else value)


def extract_net_income(text, ticker):
    """Net income in millions: narrative sentence first, then the income statement table."""
    # 1st attempt: "net income of $X million/billion" (works for MSFT, JPM)
    result = extract_amount_in_millions(NET_INCOME_PATTERN, text)
    if result != NOT_FOUND:
        return result

    # 2nd attempt: flattened income statement table
    search_text = text
    if ticker == "NVDA":
        anchor = INCOME_STATEMENT_ANCHOR.search(text)
        if not anchor:
            return NOT_FOUND
        search_text = text[anchor.end():]

    matches = list(NET_INCOME_TABLE_PATTERN.finditer(search_text))
    if not matches:
        return NOT_FOUND

    chosen = matches[0]
    if ticker == "WMT":
        # Prefer "Consolidated net income attributable to Walmart" over plain
        # "Consolidated net income", which includes noncontrolling interest.
        for match in matches:
            if re.search(r"attributable\s+to", match.group(0), re.IGNORECASE):
                chosen = match
                break

    return parse_table_number(chosen.group(1))


def extract_eps(text):
    match = earliest_match(EPS_PATTERNS, text)
    return match.group(1) if match else NOT_FOUND


def extract_period(text):
    match = earliest_match(PERIOD_PATTERNS, text)
    if not match:
        return NOT_FOUND
    return re.sub(r"\s+", " ", match.group(0)).strip()


def extract_fields(text, ticker):
    return {
        "period": extract_period(text),
        "revenue_reported": extract_amount_in_millions(REVENUE_PATTERN, text),
        "eps_diluted": extract_eps(text),
        "net_income": extract_net_income(text, ticker),
    }


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def dollar(value):
    """Prefix a value with $ unless it is NOT_FOUND."""
    return value if value == NOT_FOUND else f"${value}"


def print_row(row):
    print(
        f"{row['ticker']} | {row['period']} | "
        f"Revenue: {dollar(row['revenue_reported'])} | "
        f"EPS: {dollar(row['eps_diluted'])} | "
        f"Net Income: {dollar(row['net_income'])}"
    )


def save_csv(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            # Never write blanks or None: fill any missing value with NOT_FOUND.
            writer.writerow(
                {col: (row.get(col) if row.get(col) not in (None, "") else NOT_FOUND)
                 for col in CSV_COLUMNS}
            )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process_filing(company, filing):
    """Process one filing and return a result row, or None if skipped."""
    ticker = company["ticker"]
    cik = company["cik"]
    filing_date = filing["filing_date"]

    press_release_url = find_press_release_url(cik, filing["accession"])
    if press_release_url is None:
        print(f"WARNING: {ticker} {filing_date}: press release exhibit not found, skipping")
        return None

    text = html_to_text(sec_get(press_release_url).text)
    fields = extract_fields(text, ticker)

    return {
        "company": company["company"],
        "ticker": ticker,
        "cik": cik,
        "filing_date": filing_date,
        **fields,
    }


def main():
    rows = []

    for company in COMPANIES:
        ticker = company["ticker"]
        try:
            filings = get_earnings_filings(company["cik"])
        except Exception as e:
            print(f"WARNING: {ticker}: could not load filings ({e}), skipping company")
            continue

        if not filings:
            print(f"WARNING: {ticker}: no 8-K Item 2.02 filings found")
            continue

        for filing in filings:
            try:
                row = process_filing(company, filing)
            except Exception as e:
                print(f"WARNING: {ticker} {filing['filing_date']}: error processing filing ({e}), skipping")
                continue

            if row is not None:
                print_row(row)
                rows.append(row)

    try:
        save_csv(rows, OUTPUT_CSV)
        print(f"Saved {len(rows)} rows to {OUTPUT_CSV}")
    except Exception as e:
        print(f"WARNING: could not save {OUTPUT_CSV} ({e})")


if __name__ == "__main__":
    main()
