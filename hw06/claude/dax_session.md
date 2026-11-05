# Part D — Claude-assisted measure: Top 10 Client Share

## My prompt
I’m building a DAX measure in Power BI for a wealth manager (Wildcat Capital). The attached file is my model metadata from three DAX queries: INFO.VIEW.COLUMNS, INFO.VIEW.RELATIONSHIPS and INFO.VIEW.MEASURES.
Context the metadata doesn’t show:

Grain: fact_portfolio_snapshot has one row per client per month. snapshot_date is always the 1st of the month. Clients who left stop having snapshots, so not every client appears on every date.
Additivity: aum is a balance (semi-additive): it can be summed across clients for one date, but never across months. active_alpha_ytd is a year-to-date ratio.
dim_date is marked as the date table and joined to the facts on dim_date[date]. All relationships are many-to-one, single direction.
My existing measure [Ending AUM] returns the total aum at the last snapshot date in the current filter, using LASTNONBLANK ( dim_date[date], CALCULATE ( SUM ( fact_portfolio_snapshot[aum] ) ) ).
What I need: a measure named Top 10 Client Share = the share of Ending AUM held by the 10 largest clients within the current filter. “Largest” means by their AUM at that same last snapshot date. If the filter is on dim_client[client_tier] = “UHNW”, it should be the top 10 UHNW clients’ share of UHNW Ending AUM. Use TOPN over VALUES ( dim_client[client_id] ) and reuse [Ending AUM].
Please give me:

The DAX measure
A plain-English explanation of its filter context: what TOPN iterates over, how [Ending AUM] is evaluated for each client, and what happens at the grand total and in a year with only some clients
A DAX query I can run in DAX query view to test it, returning the measure by dim_date[year] and by dim_client[client_tier] for 2024

## Claude's response
1. The measure
dax
Top 10 Client Share =
VAR LastSnapshotDate =
    LASTNONBLANK ( dim_date[date], CALCULATE ( SUM ( fact_portfolio_snapshot[aum] ) ) )
VAR TotalAUM = [Ending AUM]
VAR Top10Clients =
    CALCULATETABLE (
        TOPN (
            10,
            VALUES ( dim_client[client_id] ),
            [Ending AUM], DESC,
            dim_client[client_id], ASC          -- tie-breaker: exactly 10 rows
        ),
        LastSnapshotDate                        -- rank everyone at the same date
    )
VAR Top10AUM =
    CALCULATE ( [Ending AUM], Top10Clients, LastSnapshotDate )
RETURN
    DIVIDE ( Top10AUM, TotalAUM )

Format it as 0.00%.

Why the date is pinned. If you write TOPN ( 10, VALUES ( dim_client[client_id] ), [Ending AUM] ) without pinning the date, each client’s [Ending AUM] runs its own LASTNONBLANK and finds that client’s last snapshot. A client who left in June 2024 would be ranked on their June balance. That balance could land in the numerator while it’s absent from the December denominator, which overstates the share. Pinning LastSnapshotDate makes everyone get ranked “at that same last snapshot date”, as you specified.

2. How the filter context works

LastSnapshotDate: This is evaluated in the cell’s own filter context. It’s the latest dim_date[date] where the filtered clients have any AUM, for example 2024-12-01 for year 2024. If the cell is filtered to UHNW, it’s the last date any UHNW client had AUM. It’s a one-row table that keeps its lineage to dim_date[date], so it can be used as a filter.

TotalAUM: This is [Ending AUM] in the same context. It’s the sum of AUM at that same date, so the denominator and the ranking date always agree.

What TOPN iterates over: VALUES ( dim_client[client_id] ) is every client visible through the dim_client filters, such as client_tier = "UHNW". Because the relationships are single-direction, the date filter doesn’t reduce this list. Clients who have already left are still in it.

How [Ending AUM] is evaluated for each client: For each row, context transition adds a filter of client_id = <that client>. That filter sits on top of the outer filters (tier, account type and so on) and the pinned date. Inside [Ending AUM], LASTNONBLANK now scans only that one date. The result is the client’s AUM on that date, or blank if they had no snapshot then. Blanks sort to the bottom of a DESC TOPN, so they only make the top 10 if fewer than 10 clients have AUM, and then they add nothing.

The numerator: Top10Clients replaces the filter on dim_client[client_id]. The tier filter is still in place, but it’s redundant, because the top 10 were already picked within the tier. [Ending AUM] then sums those 10 clients at the pinned date.

Ties: TOPN returns every row tied at 10th place. The client_id tie-breaker forces exactly 10.

Grand total: With no date filter, LastSnapshotDate is the latest snapshot in the whole dataset, probably October or November 2026. With no tier filter, it’s the top 10 of all clients’ share of total AUM. It is not a sum or average of the year or tier rows, and it shouldn’t be.

A year with only some clients: Only clients with a snapshot on that year’s last snapshot date count, in both the numerator and the denominator:

Clients who left during the year drop out.
Clients who hadn’t joined yet never had rows.
If 10 or fewer clients had AUM on that date, the share is 100%.
For a partial year like 2026, the “last date” is simply the latest month loaded.
3. Test query for DAX query view

DEFINE MEASURE is query-scoped, so this tests the measure without adding anything to the model.

dax
DEFINE
    MEASURE _Measures[Top 10 Client Share (test)] =
        VAR LastSnapshotDate =
            LASTNONBLANK ( dim_date[date], CALCULATE ( SUM ( fact_portfolio_snapshot[aum] ) ) )
        VAR TotalAUM = [Ending AUM]
        VAR Top10Clients =
            CALCULATETABLE (
                TOPN ( 10, VALUES ( dim_client[client_id] ),
                       [Ending AUM], DESC, dim_client[client_id], ASC ),
                LastSnapshotDate
            )
        VAR Top10AUM = CALCULATE ( [Ending AUM], Top10Clients, LastSnapshotDate )
        RETURN DIVIDE ( Top10AUM, TotalAUM )

// A) By year, with grand total row
EVALUATE
SUMMARIZECOLUMNS (
    ROLLUPADDISSUBTOTAL ( dim_date[year], "Is Total" ),
    "Ending AUM", [Ending AUM],
    "Ending Clients", [Ending Clients],
    "Top 10 Share", [Top 10 Client Share (test)]
)
ORDER BY [Is Total], dim_date[year]

// B) By client tier, 2024 only
EVALUATE
SUMMARIZECOLUMNS (
    ROLLUPADDISSUBTOTAL ( dim_client[client_tier], "Is Total" ),
    TREATAS ( { 2024 }, dim_date[year] ),
    "Ending AUM", [Ending AUM],
    "Ending Clients", [Ending Clients],
    "Top 10 Share", [Top 10 Client Share (test)]
)
ORDER BY [Is Total], dim_client[client_tier]

// C) Sanity check: the actual top 10 for 2024 and their AUM at the last 2024 snapshot
EVALUATE
VAR LastDate2024 =
    CALCULATETABLE (
        LASTNONBLANK ( dim_date[date], CALCULATE ( SUM ( fact_portfolio_snapshot[aum] ) ) ),
        dim_date[year] = 2024
    )
RETURN
    CALCULATETABLE (
        TOPN (
            10,
            ADDCOLUMNS ( VALUES ( dim_client[client_id] ), "AUM at last 2024 snapshot", [Ending AUM] ),
            [AUM at last 2024 snapshot], DESC, dim_client[client_id], ASC
        ),
        LastDate2024
    )
ORDER BY [AUM at last 2024 snapshot] DESC

## Test query results (run in Power BI DAX query view, 2026-11-05)

### Result 1 — by year
dim_date[year]	[Is Total]	[Ending AUM]	[Ending Clients]	[Top 10 Share]
2020	false	8130190789.37	1847	0.07041115316733655
2021	false	10010301949.110006	2157	0.06375446125246413
2022	false	9308159286.53	2500	0.055308650474536626
2023	false	10644971737.000006	2325	0.060379089153987445
2024	false	12729572078.859997	2325	0.06158926746579308
	true	12729572078.859997	2325	0.06158926746579308

### Result 2 — by client tier, 2024
dim_client[client_tier]	[Is Total]	[Ending AUM]	[Ending Clients]	[Top 10 Share]
HNW	false	2548521154.329999	687	0.03139674749179622
Retail	false	533452497.88999945	1394	0.018348218311311223
UHNW	false	9647598426.639997	244	0.08126426752227996
	true	12729572078.859997	2325	0.06158926746579308


### Result 3 — the actual top 10 clients at the last 2024 snapshot
dim_client[client_id]	[AUM at last 2024 snapshot]
1001	82386642.91
2361	80623907.28
1331	79236752.47
2281	79087869.65
2183	78058859.94
1245	77904633.86
1885	77750551.83
679	77316464.97
1855	77214969.9
796	74424366.68
