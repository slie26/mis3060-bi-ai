"""
hw03_executives.py

Builds a table of executive departures and appointments from SEC 8-K filings
(Item 5.02, "Departure of Directors or Certain Officers; Election of Directors;
Appointment of Certain Officers; Compensatory Arrangements of Certain Officers")
for five large companies.

For each company the script:
  1. Downloads the company's submissions JSON from data.sec.gov.
  2. Keeps 8-K filings whose items include "5.02" and that were filed in the
     past 12 months (today minus 365 days, calculated when the script runs).
  3. Downloads each filing's main 8-K document and strips it to plain text.
  4. Cuts out the Item 5.02 section (up to the next Item heading or SIGNATURE).
  5. Finds each departure / appointment event and extracts the person's name,
     title, event type, and effective date.

Each event is printed as it is found and saved to hw03/executive_events.csv
(one row per event). Run from the repository root:
    python hw03/hw03_executives.py
"""

import csv
import os
import re
import time
from datetime import date, datetime, timedelta

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

LOOKBACK_DAYS = 365
NOT_FOUND = "NOT_FOUND"
OUTPUT_CSV = os.path.join("hw03", "executive_events.csv")
CSV_COLUMNS = [
    "company",
    "ticker",
    "cik",
    "filing_date",
    "event_type",
    "person_name",
    "title",
    "effective_date",
]

SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
BOARD_TITLE = "member of the Board of Directors"


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
# Step 2: find the executive-change (Item 5.02) filings from the past 12 months
# ---------------------------------------------------------------------------

def get_executive_filings(cik, cutoff_date):
    """Return 8-K filings with Item 5.02 filed on or after cutoff_date, newest first."""
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
        item_text = items[i] if i < len(items) and items[i] else ""
        if forms[i] != "8-K" or "5.02" not in item_text:
            continue
        try:
            filed = datetime.strptime(dates[i], "%Y-%m-%d").date()
        except (ValueError, IndexError):
            continue
        if filed < cutoff_date:
            continue
        matches.append(
            {
                "filing_date": dates[i],
                "accession": accessions[i],
                "primary_document": primary_docs[i] if i < len(primary_docs) else "",
            }
        )

    # ISO dates (YYYY-MM-DD) sort correctly as strings.
    matches.sort(key=lambda f: f["filing_date"], reverse=True)
    return matches


# ---------------------------------------------------------------------------
# Step 3a: download the 8-K and isolate the Item 5.02 section
# ---------------------------------------------------------------------------

def build_document_url(cik, accession, primary_document):
    cik_no_zeros = str(int(cik))
    accession_no_dashes = accession.replace("-", "")
    return f"{SEC_ARCHIVES}/{cik_no_zeros}/{accession_no_dashes}/{primary_document}"


def html_to_text(html):
    """Strip HTML down to plain text with normalized whitespace and punctuation."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    # Hidden inline-XBRL header data is not part of the readable filing.
    for tag in soup.find_all(["ix:header"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    replacements = {
        "\xa0": " ", "​": "",
        "’": "'", "‘": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", "‑": "-",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


ITEM_502_START = re.compile(r"\bItem\s*5\.02\b\.?", re.IGNORECASE)
# The next item heading looks like "Item 9.01 Financial Statements..." (a capital
# letter follows the number). This skips in-text references like "Item 1.01 above".
NEXT_ITEM_HEADING = re.compile(r"\bItem\s*(\d{1,2}\.\d{2})\.?\s+[A-Z]", re.IGNORECASE)
SIGNATURE_HEADING = re.compile(r"SIGNATURE")  # all-caps heading only

# The standard Item 5.02 heading contains the words "Departure", "Election" and
# "Appointment", which would look like events, so it is removed from the section.
ITEM_502_HEADING = re.compile(
    r"^\s*[:.\-]?\s*Departure\s+of\s+Directors[^.]{0,220}?Officers?\s*[.;:]?"
    r"(?:\s*Compensatory\s+Arrangements\s+of\s+Certain\s+Officers\.?)?",
    re.IGNORECASE,
)


def extract_item_502_section(text):
    """Return the text of the Item 5.02 section, or None if the heading is missing."""
    start_match = ITEM_502_START.search(text)
    if not start_match:
        return None

    body = text[start_match.end():]
    end = len(body)

    for match in NEXT_ITEM_HEADING.finditer(body):
        if match.group(1) != "5.02":
            end = min(end, match.start())
            break

    sig = SIGNATURE_HEADING.search(body)
    if sig:
        end = min(end, sig.start())

    section = body[:end]
    return ITEM_502_HEADING.sub("", section, count=1).strip()


# ---------------------------------------------------------------------------
# Step 3b: sentence splitting and person-name detection
# ---------------------------------------------------------------------------

ABBREVIATIONS = [
    "Mr", "Ms", "Mrs", "Dr", "Jr", "Sr", "Inc", "Co", "Corp", "Ltd", "No",
    "St", "vs", "Messrs", "Mses", "e.g", "i.e", "U.S", "U.K", "L.P", "N.A",
]
DOT = "<DOT>"


def split_sentences(text):
    """Split text into sentences without breaking on abbreviations or initials."""
    protected = text
    for abbr in ABBREVIATIONS:
        pattern = r"\b" + re.escape(abbr) + r"\."
        protected = re.sub(pattern, lambda m: m.group(0)[:-1] + DOT, protected)
    # Middle initials such as "Kevan M. Parekh" or "J. Smith".
    protected = re.sub(r"\b([A-Z])\.(?=\s+[A-Z])", r"\1" + DOT, protected)

    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\"'])", protected)
    return [p.replace(DOT, ".").strip() for p in parts if p.strip()]


HONORIFICS = {"mr", "ms", "mrs", "dr", "messrs"}
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}

# Capitalized words that are never part of a person's name in these filings.
NON_NAME_WORDS = {
    # sentence starters / function words
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "as", "by", "for",
    "with", "from", "to", "upon", "following", "effective", "also", "additionally",
    "separately", "today", "prior", "since", "during", "before", "after", "under",
    "pursuant", "consistent", "each", "both", "neither", "there", "his", "her",
    "he", "she", "it", "its", "this", "that", "these", "those", "such", "in",
    "if", "any", "all", "no", "not", "we", "our", "their", "they", "who", "which",
    "while", "when", "where", "until", "through", "between", "among", "about",
    "further", "furthermore", "however", "accordingly", "subject", "item",
    "items", "except", "other", "new", "former", "current", "currently", "then",
    # titles and roles
    "chief", "officer", "officers", "executive", "executives", "vice",
    "president", "senior", "board", "boards", "director", "directors",
    "chairman", "chairwoman", "chair", "chairperson", "general", "counsel",
    "financial", "operating", "accounting", "technology", "technical",
    "information", "legal", "human", "resources", "people", "marketing",
    "strategy", "strategic", "operations", "principal", "corporate",
    "secretary", "treasurer", "controller", "global", "international",
    "lead", "independent", "member", "members", "committee", "committees",
    "compensation", "audit", "nominating", "governance", "risk", "management",
    "group", "deputy", "head", "advisor", "adviser", "consultant", "services",
    "retail", "commercial", "consumer", "community", "banking", "bank",
    "investment", "asset", "wealth", "hardware", "software", "engineering",
    "product", "products", "sales", "business", "division", "segment",
    "company", "company's", "companies", "registrant", "employee", "employees",
    # company names and legal words
    "apple", "microsoft", "nvidia", "jpmorgan", "chase", "walmart", "sam's",
    "club", "inc", "corporation", "corp", "co", "ltd", "llc", "plc", "n.a",
    "securities", "exchange", "commission", "act", "regulation", "section",
    "form", "report", "current", "exhibit", "exhibits", "press", "release",
    "agreement", "agreements", "letter", "offer", "plan", "plans", "stock",
    "equity", "incentive", "award", "awards", "restricted", "units",
    "performance", "annual", "meeting", "shareholders", "stockholders",
    "proxy", "statement", "fiscal", "year", "quarter", "u.s", "united",
    "states", "america", "americas", "north", "south", "east", "west", "europe",
    "asia", "china", "india", "japan",
    # dates
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday",
}

CAP_TOKEN = re.compile(r"[A-Z][A-Za-zÀ-ſ'\-]*\.?")
CAP_SEQUENCE = re.compile(
    r"[A-Z][A-Za-zÀ-ſ'\-]*\.?(?:,?\s+[A-Z][A-Za-zÀ-ſ'\-]*\.?)*"
)


def token_kind(token):
    """Classify one capitalized token."""
    bare = token.rstrip(".")
    if bare.endswith("'s"):
        bare = bare[:-2]
    low = bare.lower()
    if low in HONORIFICS:
        return "honorific"
    if low in NAME_SUFFIXES:
        return "suffix"
    if len(bare) == 1:
        return "initial"
    if low in NON_NAME_WORDS or low.rstrip("s") in NON_NAME_WORDS:
        return "stop"
    if bare.isupper():  # acronyms such as CEO, CFO, SEC, NVIDIA
        return "stop"
    return "word"


def clean_token(token):
    token = token.strip(",")
    if token.endswith("'s"):
        token = token[:-2]
    if token_kind(token) != "initial" and token_kind(token) != "suffix":
        token = token.rstrip(".")
    return token


def find_name_mentions(sentence):
    """Find person mentions in a sentence.

    Returns a list of dicts: {"start", "end", "full": "First Last" or None,
    "surname": "Last"}.
    """
    mentions = []
    for seq in CAP_SEQUENCE.finditer(sentence):
        tokens = [(m.group(0), seq.start() + m.start(), seq.start() + m.end())
                  for m in CAP_TOKEN.finditer(seq.group(0))]
        i = 0
        while i < len(tokens):
            text, start, end = tokens[i]
            kind = token_kind(text)

            if kind == "honorific":
                # "Mr. Parekh" or "Mr. Kevan Parekh"
                run = []
                j = i + 1
                while j < len(tokens) and token_kind(tokens[j][0]) in ("word", "initial", "suffix"):
                    run.append(tokens[j])
                    j += 1
                words = [t for t in run if token_kind(t[0]) == "word"]
                if words:
                    if len(words) >= 2:
                        full = " ".join(clean_token(t[0]) for t in run)
                    else:
                        full = None
                    mentions.append({
                        "start": start,
                        "end": run[-1][2],
                        "full": full,
                        "surname": clean_token(words[-1][0]),
                    })
                i = max(j, i + 1)
                continue

            if kind in ("word", "initial"):
                run = []
                j = i
                while j < len(tokens) and token_kind(tokens[j][0]) in ("word", "initial", "suffix"):
                    run.append(tokens[j])
                    j += 1
                # A name is 2-4 tokens, starts with a word or initial,
                # and its last non-suffix token is a full word (the surname).
                core = [t for t in run if token_kind(t[0]) != "suffix"]
                words = [t for t in core if token_kind(t[0]) == "word"]
                if 2 <= len(core) <= 4 and words and token_kind(core[-1][0]) == "word":
                    mentions.append({
                        "start": run[0][1],
                        "end": run[-1][2],
                        "full": " ".join(clean_token(t[0]) for t in run),
                        "surname": clean_token(core[-1][0]),
                    })
                i = max(j, i + 1)
                continue

            i += 1
    return mentions


class PersonRegistry:
    """Maps every mention (full name or 'Mr. Surname') to one canonical full name."""

    def __init__(self):
        self.by_surname = {}

    def register(self, mention):
        if mention["full"]:
            key = mention["surname"].lower()
            # Keep the first (usually most formal) full form of each person.
            self.by_surname.setdefault(key, mention["full"])

    def resolve(self, mention):
        key = mention["surname"].lower()
        if key in self.by_surname:
            return self.by_surname[key]
        return mention["full"]  # None when only "Mr. Surname" was ever seen


# ---------------------------------------------------------------------------
# Step 3c: event keywords, titles, and effective dates
# ---------------------------------------------------------------------------

# Each keyword has an event type and a direction telling where the person is:
#   "before" - the subject precedes the verb ("Jane Doe will retire")
#   "after"  - the person follows the word ("the retirement of Jane Doe")
#   "verb"   - appoint/elect/name/promote: "after" in active voice
#              ("the Board appointed Jane Doe"), "before" in passive voice
#              ("Jane Doe was appointed")
#   "noun"   - "after" when followed by "of"/"by", otherwise "before"
#              ("Mr. Doe's retirement", "his resignation")
EVENT_KEYWORDS = [
    # departures
    ("departure", "before", r"\bresign(?:s|ed|ing)?\b"),
    ("departure", "noun", r"\bresignation\b"),
    ("departure", "before", r"\bretir(?:e|es|ed|ing)\b"),
    ("departure", "noun",
     r"\bretirement\b(?!\s+(?:plans?|programs?|benefits?|savings|eligib\w*|age|"
     r"contributions?|accounts?|income|restoration|vesting|treatment|provisions?))"),
    ("departure", "before", r"\bst(?:ep|eps|epped|epping)\s+down\b"),
    ("departure", "before", r"\bdepart(?:s|ed|ing)?\b"),
    ("departure", "noun", r"\bdeparture\b"),
    ("departure", "before",
     r"\b(?:not|decided\s+not\s+to|declined\s+to)\s+(?:to\s+)?(?:stand|seek|be\s+standing|"
     r"be\s+nominated)\s+(?:for\s+)?re-?election\b"),
    ("departure", "before", r"\bleav(?:e|es|ing)\s+the\s+(?:Company|company|Board)\b"),
    ("departure", "before", r"\btransition(?:s|ed|ing)?\s+(?:out\s+of|from)\b"),
    ("departure", "before", r"\bceas(?:e|es|ed)\s+to\s+(?:serve|be)\b"),
    # appointments
    ("appointment", "verb", r"\bappoint(?:s|ed|ing)?\b"),
    ("appointment", "noun", r"\bappointment\b"),
    ("appointment", "verb",
     r"(?<!re-)(?<!re)\belect(?:s|ed|ing)?\b(?!\s+(?:to\s+(?:defer|receive|participate)|not))"),
    ("appointment", "noun", r"(?<!re-)(?<!re)\belection\b"),
    ("appointment", "verb", r"\bnam(?:e|es|ed|ing)\b(?!\s+executive\s+officers?)"),
    ("appointment", "verb", r"\bpromot(?:e|es|ed|ing)\b"),
    ("appointment", "noun", r"\bpromotion\b"),
    ("appointment", "after", r"\bsucceeded\s+by\b"),
    ("appointment", "before", r"\bsucceed(?:s|ing)?\b(?!\s+by)"),
    ("appointment", "before", r"\bwill\s+(?:join|become)\b"),
    ("appointment", "before", r"\bjoin(?:s|ed)?\s+the\s+(?:Company|Board)\b"),
    ("appointment", "before", r"(?<!continue\s)\b(?:will|to)\s+serve\s+as\b"),
    ("appointment", "before", r"\bto\s+the\s+(?:new\s+)?(?:role|position)\s+of\b"),
]
EVENT_PATTERNS = [(etype, direction, re.compile(pattern))
                  for etype, direction, pattern in EVENT_KEYWORDS]

PASSIVE_BEFORE = re.compile(
    r"\b(?:was|were|is|are|be|been|being|has\s+been|have\s+been|will\s+be)\s+(?:\w+\s+)?$",
    re.IGNORECASE,
)
# "was appointed CFO in 2019" / "has been named ... since" is background, not news.
BACKGROUND_AFTER = re.compile(r"^[^.;]{0,60}?\b(?:in|since)\s+(?:19|20)\d{2}\b")
PRONOUN = re.compile(r"\b(?:he|she|him|her|his|they|their)\b", re.IGNORECASE)
LIST_GAP = re.compile(r"^\s*(?:,\s*(?:and\s+)?|and\s+)$")
SUCCEED_BEFORE = re.compile(r"\b(?:succeed(?:s|ing)?|replac(?:e|es|ing))\s+$", re.IGNORECASE)

# --- titles ---------------------------------------------------------------
TITLE_PREFIX = r"(?:(?:Senior|Executive|Corporate|Group|Global|Deputy)\s+)*"
TITLE_CORE = (
    TITLE_PREFIX
    + r"(?:Vice\s+Chair(?:man|woman|person)?(?:\s+of\s+the\s+Board)?"
    r"|Chair(?:man|woman|person)?(?:\s+of\s+the\s+Board(?:\s+of\s+Directors)?)?"
    r"|Principal\s+(?:Executive|Financial|Accounting)\s+Officer"
    r"|Chief\s+(?:[A-Z][A-Za-z&\-]+,?\s+(?:and\s+)?){1,3}Officer"
    r"|Vice\s+President"
    r"|President"
    r"|General\s+Counsel"
    r"|Secretary"
    r"|Treasurer"
    r"|Controller"
    r"|Lead\s+Independent\s+Director)"
)
TITLE_PATTERN = re.compile(
    TITLE_CORE + r"(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+)" + TITLE_CORE + r"){0,3}"
)
BOARD_PATTERN = re.compile(
    r"\bmember\s+of\s+(?:the|its|our)\s+(?:Company's\s+)?Board(?:\s+of\s+Directors)?"
    r"|\b(?:to|from|on)\s+(?:the|its|our)\s+(?:Company's\s+|Apple's\s+|Microsoft's\s+|"
    r"NVIDIA's\s+|Walmart's\s+|JPMorgan\s+Chase's\s+)?Board(?:\s+of\s+Directors)?\b"
    r"|\b(?:as\s+)?an?\s+(?:independent\s+|non-employee\s+)?director\b"
    r"|\bas\s+(?:independent\s+|non-employee\s+)?directors\b"
    r"|\bre-?election\s+(?:to|as)\b",
)
TITLE_INTRO = re.compile(
    r"\b(?:as|to|become|becomes|named|position\s+of|role\s+of|office\s+of|roles\s+of)"
    r"\s+(?:(?:the|its|our|a|an|new|next|Company's)\s+)*$",
    re.IGNORECASE,
)

# --- effective dates ------------------------------------------------------
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
EFFECTIVE_PATTERN = re.compile(
    r"\beffective\s+(?:as\s+of\s+)?(immediately)"
    r"|\beffective\b[^.;]{0,80}?\b(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
    re.IGNORECASE,
)


def normalize_title(text):
    return re.sub(r"\s+", " ", text).strip(" ,")


def find_title(text):
    """Return the best title in a text window, preferring 'as <title>' phrasing."""
    candidates = []
    for m in TITLE_PATTERN.finditer(text):
        candidates.append((m.start(), normalize_title(m.group(0))))
    for m in BOARD_PATTERN.finditer(text):
        candidates.append((m.start(), BOARD_TITLE))
    if not candidates:
        return None
    candidates.sort()
    for start, title in candidates:
        if TITLE_INTRO.search(text[max(0, start - 40):start]):
            return title
    return candidates[0][1]


def parse_effective(match, filing_date):
    """Turn an EFFECTIVE_PATTERN match into an ISO date string."""
    if match.group(1):
        return filing_date  # "effective immediately"
    month = MONTHS[match.group(2).lower()]
    try:
        return date(int(match.group(4)), month, int(match.group(3))).isoformat()
    except ValueError:
        return NOT_FOUND


def find_effective_date(text, filing_date):
    match = EFFECTIVE_PATTERN.search(text)
    return parse_effective(match, filing_date) if match else None


# ---------------------------------------------------------------------------
# Step 3d / 4: turn a 5.02 section into one record per event
# ---------------------------------------------------------------------------

def keyword_direction(direction, sentence, kw):
    if direction == "verb":
        return "before" if PASSIVE_BEFORE.search(sentence[:kw.start()]) else "after"
    if direction == "noun":
        after = sentence[kw.end():kw.end() + 5]
        return "after" if re.match(r"\s+(?:of|by)\b", after) else "before"
    return direction


def chain_mentions(mentions, first_index, step, sentence):
    """Collect a list like 'Jane Doe, John Roe and Ann Poe' starting at one mention."""
    chosen = [mentions[first_index]]
    i = first_index
    while 0 <= i + step < len(mentions):
        a, b = (mentions[i], mentions[i + step]) if step > 0 else (mentions[i + step], mentions[i])
        if not LIST_GAP.match(sentence[a["end"]:b["start"]]):
            break
        i += step
        chosen.append(mentions[i])
    return chosen


def people_for_keyword(direction, sentence, kw, mentions):
    """Pick the mention(s) a keyword refers to, using the keyword's direction."""
    before = [i for i, m in enumerate(mentions) if m["end"] <= kw.start()]
    after = [i for i, m in enumerate(mentions)
             if m["start"] >= kw.end() and m["start"] - kw.end() <= 120]

    order = ["before", "after"] if direction == "before" else ["after", "before"]
    for side in order:
        if side == "before" and before:
            return chain_mentions(mentions, before[-1], -1, sentence)
        if side == "after" and after:
            return chain_mentions(mentions, after[0], +1, sentence)
    return []


def title_window_end(sentence, kw_end, person, mentions, registry, targets=()):
    """End the search window at the next mention of a *different* person,
    unless that person is the one being succeeded ('succeed Jane Doe as CFO')
    or is in the same list as this person ('elected Jane Doe and John Roe as directors')."""
    for m in mentions:
        if m["start"] < kw_end or m in targets:
            continue
        other = registry.resolve(m) or m["surname"]
        if other == person:
            continue
        if SUCCEED_BEFORE.search(sentence[:m["start"]]):
            continue
        return m["start"]
    return len(sentence)


def extract_events(section, filing_date):
    """Return (events, keyword_found). Each event has event_type, person_name,
    title, effective_date."""
    sentences = split_sentences(section)
    registry = PersonRegistry()
    sentence_mentions = []
    for s in sentences:
        mentions = find_name_mentions(s)
        for m in mentions:
            registry.register(m)
        sentence_mentions.append(mentions)

    people = {}      # person -> {"order", "departure": [...], "appointment": [...]}
    unnamed = {}     # event_type -> list of hits with no identifiable person
    keyword_found = False
    last_person = None

    for s_index, (sentence, mentions) in enumerate(zip(sentences, sentence_mentions)):
        for etype, raw_direction, pattern in EVENT_PATTERNS:
            for kw in pattern.finditer(sentence):
                if etype == "appointment" and BACKGROUND_AFTER.match(sentence[kw.end():]):
                    continue
                keyword_found = True
                direction = keyword_direction(raw_direction, sentence, kw)
                targets = people_for_keyword(direction, sentence, kw, mentions)

                names = []
                for m in targets:
                    resolved = registry.resolve(m)
                    names.append(resolved if resolved else "Mr./Ms. " + m["surname"])
                if not names and last_person and PRONOUN.search(sentence):
                    names = [last_person]

                hit = {"sentence": s_index, "kw_start": kw.start(), "kw_end": kw.end(),
                       "text": kw.group(0).lower(), "targets": targets}
                if not names:
                    unnamed.setdefault(etype, []).append(hit)
                for name in names:
                    record = people.setdefault(
                        name, {"order": (s_index, kw.start()), "departure": [], "appointment": []})
                    record[etype].append(hit)

        # Track the most recently mentioned person for "he"/"she" references.
        if mentions:
            last = mentions[-1]
            last_person = registry.resolve(last) or "Mr./Ms. " + last["surname"]

    events = []
    for name, record in sorted(people.items(), key=lambda kv: kv[1]["order"]):
        dep_hits = sorted(record["departure"], key=lambda h: (h["sentence"], h["kw_start"]))
        app_hits = sorted(record["appointment"], key=lambda h: (h["sentence"], h["kw_start"]))

        dep_title = first_title(dep_hits, name, sentences, sentence_mentions, registry, "departure")
        app_title = first_title(app_hits, name, sentences, sentence_mentions, registry, "appointment")

        if dep_hits and app_hits:
            event_type = "both"
            if dep_title and app_title and dep_title != app_title:
                title = f"{dep_title} -> {app_title}"
            else:
                title = app_title or dep_title
        elif dep_hits:
            event_type, title = "departure", dep_title
        else:
            event_type, title = "appointment", app_title

        all_hits = sorted(dep_hits + app_hits, key=lambda h: (h["sentence"], h["kw_start"]))
        effective = first_effective(all_hits, name, sentences, sentence_mentions,
                                    registry, filing_date)

        events.append({
            "event_type": event_type,
            "person_name": NOT_FOUND if name.startswith("Mr./Ms. ") else name,
            "title": title or NOT_FOUND,
            "effective_date": effective or NOT_FOUND,
        })

    # A keyword was found but no person could be tied to it: still record the
    # event, with NOT_FOUND for the name, so the filing is not lost.
    if not events:
        for etype, hits in unnamed.items():
            hit = hits[0]
            sentence = sentences[hit["sentence"]]
            events.append({
                "event_type": etype,
                "person_name": NOT_FOUND,
                "title": find_title(sentence[hit["kw_end"]:]) or find_title(sentence) or NOT_FOUND,
                "effective_date": find_effective_date(sentence, filing_date) or NOT_FOUND,
            })

    return events, keyword_found


def mention_span_for(name, mentions, registry):
    for m in mentions:
        if (registry.resolve(m) or "Mr./Ms. " + m["surname"]) == name:
            return m
    return None


def first_title(hits, name, sentences, sentence_mentions, registry, etype):
    """Find the title that goes with a person's departure or appointment."""
    for hit in hits:
        sentence = sentences[hit["sentence"]]
        mentions = sentence_mentions[hit["sentence"]]

        # "not stand for re-election" is always about a board seat.
        if "re-election" in hit["text"] or "reelection" in hit["text"]:
            return BOARD_TITLE

        # 1) Words after the keyword, e.g. "step down as CFO", "appointed Jane Doe as CFO".
        end = title_window_end(sentence, hit["kw_end"], name, mentions, registry, hit["targets"])
        title = find_title(sentence[hit["kw_end"]:end])
        if title:
            return title

        # 2) Appositive between the name and the keyword, e.g.
        #    "Jane Doe, Executive Vice President, will retire".
        mention = mention_span_for(name, mentions, registry)
        if mention and mention["end"] <= hit["kw_start"]:
            title = find_title(sentence[mention["end"]:hit["kw_start"]])
            if title:
                return title
    return None


def first_effective(hits, name, sentences, sentence_mentions, registry, filing_date):
    """Find the effective date for a person's event."""
    # 1) In the event sentence, after the keyword (within the person's window).
    for hit in hits:
        sentence = sentences[hit["sentence"]]
        mentions = sentence_mentions[hit["sentence"]]
        end = title_window_end(sentence, hit["kw_end"], name, mentions, registry, hit["targets"])
        found = find_effective_date(sentence[hit["kw_end"]:end], filing_date)
        if found:
            return found
    # 2) Anywhere in the event sentence ("Effective May 1, 2026, the Board appointed...").
    for hit in hits:
        found = find_effective_date(sentences[hit["sentence"]], filing_date)
        if found:
            return found
    # 3) Any other sentence that mentions the same person.
    for s_index, mentions in enumerate(sentence_mentions):
        if mention_span_for(name, mentions, registry):
            found = find_effective_date(sentences[s_index], filing_date)
            if found:
                return found
    return None


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def print_event(row):
    print(
        f"{row['ticker']} | {row['filing_date']} | {row['event_type']} | "
        f"{row['person_name']} | {row['title']}"
    )


def save_csv(rows, path):
    """Write the CSV (header only if there are no rows)."""
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
    """Process one filing and return a list of event rows (possibly empty)."""
    ticker = company["ticker"]
    cik = company["cik"]
    filing_date = filing["filing_date"]

    if not filing["primary_document"]:
        print(f"WARNING: {ticker} {filing_date}: no primary document listed, skipping")
        return []

    url = build_document_url(cik, filing["accession"], filing["primary_document"])
    text = html_to_text(sec_get(url).text)

    section = extract_item_502_section(text)
    if section is None:
        print(f"WARNING: {ticker} {filing_date}: Item 5.02 heading not found, "
              f"searching the whole document")
        section = text

    events, keyword_found = extract_events(section, filing_date)
    if not keyword_found or not events:
        print(f"{ticker} | {filing_date} | compensation-only filing, skipped")
        return []

    rows = []
    for event in events:
        row = {
            "company": company["company"],
            "ticker": ticker,
            "cik": cik,
            "filing_date": filing_date,
            **event,
        }
        print_event(row)
        rows.append(row)
    return rows


def main():
    cutoff_date = date.today() - timedelta(days=LOOKBACK_DAYS)
    print(f"Looking for 8-K Item 5.02 filings from {cutoff_date.isoformat()} "
          f"to {date.today().isoformat()}")

    rows = []
    for company in COMPANIES:
        ticker = company["ticker"]
        try:
            filings = get_executive_filings(company["cik"], cutoff_date)
        except Exception as e:
            print(f"WARNING: {ticker}: could not load filings ({e}), skipping company")
            continue

        if not filings:
            print(f"{ticker}: No executive events in past 12 months")
            continue

        for filing in filings:
            try:
                rows.extend(process_filing(company, filing))
            except Exception as e:
                print(f"WARNING: {ticker} {filing['filing_date']}: error processing "
                      f"filing ({e}), skipping")
                continue

    try:
        save_csv(rows, OUTPUT_CSV)
        print(f"Saved {len(rows)} rows to {OUTPUT_CSV}")
    except Exception as e:
        print(f"WARNING: could not save {OUTPUT_CSV} ({e})")


if __name__ == "__main__":
    main()
