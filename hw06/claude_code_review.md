## Review of 01_reconcile_measures.py

1. Checks that pass when they shouldn't (most important)
The Top 10 date-pinning check isn't tested. The main point of the Part D session was pinning the ranking to the last snapshot date. I computed the wrong, unpinned version (each client ranked on their own last balance). It gives exactly the same share on every slice, a difference of 0.000000. The 2023 slice has 162 departed clients, but none of them are big enough to make the top 10. So the reconciliation would pass whether or not Power BI pinned the date.
Suspect exclusion isn't tested for the HNW and UHNW tiers. The 2024-12-01 snapshot has 0 suspect rows in both tiers. All 148 suspects are Retail. Leaving the suspect filter out would still match for those two tiers.
Other paths that never run: the data has no blank active_alpha_ytd, no null aum, no blank suspect flags, no messy txn_type values, and no fact dates outside dim_date. The blank-handling helpers (is_blank, sum_or_blank, the Net Flows blank branch) only ever see clean data.
A blank on both sides counts as a match (compare:323). Three required rows pass this way: 2020 Ending AUM LY, AUM YoY % and Organic Growth Rate. That's correct, since 2020 has no prior year. But the script can't tell an expected blank from an unexpected one. The missing-row check (line 378) also counts a row with an empty value as exported. Listing every blank-on-both-sides match separately, or keeping a list of expected blanks, would close this gap.
2. Places where pandas copies Power BI instead of computing independently
The pandas step never reads Power BI's numbers, so the data side is independent. The definitions are not: the docstrings themselves say they "mirror" SAMEPERIODLASTYEAR, LASTNONBLANK and how SUMX treats blanks. Where both sides share a definition, a match can't catch a definition problem:

AUM-Weighted Alpha (lines 275-281) copies three DAX choices:
the last date is found before suspects are dropped;
the AUM of a row with a blank alpha stays in the denominator;
a blank suspect flag counts as not suspect. to_flag says outright that it does this to match DAX.
Fee Yield (line 263) is fees × 12 divided by the naive SUM of aum. That's only correct if fee months line up with snapshot months. There are 122,197 fee rows against 129,547 snapshot rows, so about 7,350 client-months have AUM but no fee. Both sides make the same choice, so the reconciliation never tests it.
Organic Growth Rate at Total (line 269) divides five years of net flows by 2023 Ending AUM. Both sides agree on 0.0308, but the number doesn't mean much.
Net Flows assumes withdrawals are stored as positive numbers. The data confirms this (the smallest withdrawal is 506.77), but the script never checks it.
What is independent: Top 10 is done differently (groupby and sort in pandas, TOPN over dim_client in DAX), so that comparison does add something.
3. Tolerances
The ratio tolerance (0.0001) is far looser than it needs to be. Power BI exports 10 decimals, and the actual ratio differences are about 4e-11, roughly a millionth of the tolerance. On a percentage, 0.0001 is 1 bp. On alpha (about 0.0145) it's about 0.7% relative, and on the Retail Top 10 share (0.018) about 0.5%. The wrong alpha formulas I tried still fail, but the closest one, keeping suspects in for 2020, only misses by 0.00061, which is 6× the tolerance. A tolerance around 1e-8, or a relative one, would be safer.
Units are inconsistent. Fee Yield is in bps but uses the same 0.0001, so it's held about 10,000× tighter than the % measures.
The currency tolerance (0.01) is fine. The worst float drift is 9e-5, on a total of $566B.
4. Latent bugs (no effect on this data; most would fail loudly, not silently)
The Total slice is cut to the dim_date range (line 140). Power BI's unfiltered SUM includes fact rows whose dates fall outside dim_date, so the two Totals would differ if any existed.
shift_back mishandles some month ends (line 159). For example, 2024-11-30 minus one month gives 2024-10-30 and drops Oct 31, while DATEADD shifts to the whole month. It's harmless here because snapshots are always on the 1st.
txn_type handling doesn't match its comment (line 127). The code also trims whitespace, which DAX does not; the comment only mentions case.
to_flag treats any value other than 1 or true as not suspect. A "2" or "Y" would differ from DAX's = 0 test.
last_snapshot_rows takes the latest date even if all its aum values are blank, while LASTNONBLANK would skip that date.
Ending Clients uses nunique(), which drops a blank client_id. DAX's DISTINCTCOUNT counts the blank.
Top 10 groups on the snapshot's client_id. DAX would put client IDs missing from dim_client together as one blank member.
The cheapest fix for section 1 is a small set of hand-built test rows that deliberately include these cases, such as a departed top-10 client, suspects in UHNW, and a blank alpha. Then the script could fail if one of these paths broke.