## Review of 01_keys_and_grain.py
1. Blank foreign keys never cause a FAIL (01_keys_and_grain.py:399)
ok only looks at orphan_rows and dim_duplicate_keys. check_referential_integrity doesn't count blank keys as orphans, so they're only printed as a null rate. That's right for security_id on cash rows, which has its own check. It's wrong for every other key: blank client_id, advisor_id, txn_date, fee_date or snapshot_date in a fact table, or blank dim_client.advisor_id / dim_security.benchmark_id, would still give RI PASS. A fix is a list of keys that must never be blank, which then require null_key_rows == 0.

2. Blank txn_date is never checked (lines 449 and 485)

Section 4 uses match_rate_pct, which only counts non-blank rows. So "100% match on dim_date.date" still passes when some dates are blank.
Section 5 counts unreadable dates only for fact_fees and fact_portfolio_snapshot.
Together with #1, fact_transactions.txn_date can contain blanks and every check still passes.
3. Key normalisation can hide dirty keys (240)
_normalise_keys trims spaces and turns "45.0" into "45" on both sides. The data is loaded as text, so a fact value of "45.0" or " 45" is a real inconsistency in the CSV. RI would still report a 100% match, but that key may not join in Power BI if the column stays text. This was fine for the HW4 function's purpose. For a check that proves the keys are clean, it's too lenient. At minimum, count how many keys only matched after normalising.

4. The final assert is removed under python -O (645)
If the script is ever run with -O, it exits with code 0 even when there are FAILs. if failures: sys.exit(1) is reliable.

5. Section 4 compares a rounded percentage to exactly 100 (449)
pct() rounds to 4 decimals. One orphan only rounds up to 100.0 once a table has more than about 2 million rows, so this is safe at today's sizes but fragile. on_date["orphan_rows"] == 0 says what you mean and doesn't depend on table size.

Weaker spots (lower risk)
Primary key uniqueness is a text comparison (362). "45" and "45.0" count as different values, so the PK check passes. The RI duplicate check would catch this for tables that are on the one side of a relationship. The fact table PKs (txn_id, fee_id, snapshot_id) are on no one side, so nothing catches it there. The same applies to dim_date.date: 2024-01-01 and 2024-1-1 count as distinct.
Placeholder text counts as a real key. Because of keep_default_na=False, values like "NULL", "None" or "N/A" aren't treated as blank. In a PK column, one "NULL" passes as a unique non-blank key. In FK columns this is the safe way round: they show up as orphans and FAIL.
Grain results never fail the run (480). This is by design (UNIQUE / NOT UNIQUE), but:
Blank grain columns are counted and then ignored, so a candidate can be "UNIQUE" while some rows have blanks in those columns.
The closing message at line 646 implies more was enforced than really was.
Section 8 silently drops columns (591). A measure column with 10% or more non-numeric junk, or an is_ flag stored as Y/N, is skipped instead of reported. It just won't appear in Part C, and nothing tells you it's missing.
Snowflake checks (532) have the same blank-key gap as #1, because they only check orphan_rows.
Things I checked that are fine
The conditional f-string at 490-492 works as intended. String concatenation happens before the if/else.
The report is saved before any exit, including the early missing-columns exit.
Errors in the opposite direction, which can only cause false FAILs, aren't a concern here. Examples: exact-case txn_type matching, and "NULL" foreign keys counting as orphans.
The fixes that matter most for "passing when it shouldn't" are #1 and #2: make the required foreign keys and fact dates fail when blank.