## 2A — Known-Answer Benchmarks

| Check | Expected | Your Script Produced | Match? | Notes |
|---|---|---|---|---|
| Dataset shape | (298772, 9) | (298772, 9) | Yes | |
| Null count — security_id | 101,597 | 101,597 | Yes | |
| Null count — amount | 0 | 0 | Yes | |
| Unique txn_type values | 6 | 6 | Yes | |
| Count of Buy transactions | 83,556 | 83,556 | Yes | |
| txn_date data type | object | str | No | Newer pandas version labels text columns as "str" instead of "object" — same underlying meaning (text, not a real date type), just a naming difference between pandas versions.|
| Earliest txn_date | 2020-01-01 | 2020-01-01| Yes | |
| Latest txn_date | 2024-12-30 | 2024-12-30 | Yes | |
| Duplicate txn_id count | 0 | 0 | Yes | |
| Mean amount | $54,075.17 | $54,075.17 | Yes | |
| Median amount | $41,220.48 | $41,220.49 | No | One-cent rounding difference, likely due to floating-point/pandas version differences — not a data quality issue.|
| Skewness of amount | 1.15 | 1.15 | Yes | |
| Correlation shares-amount | 0.65 | 0.65 | Yes | |
| Correlation price-amount | 0.64 | 0.64 | Yes | |
| Correlation shares-price | 0.00 | 0.00 | Yes | |
| Negative shares count (Buy only) | 836 | 836 |Yes | |
| Profile file created | Yes | Yes | Yes | |
| Chart files created (3) | Yes | Yes | Yes | |
## 2B — Explain the Code and Output
1. Predictions vs. actual output: Claude's predictions from Prompt 1 matched what actually printed almost exactly — the section headers, the order of output, the data types (object for txn_date/txn_type, float64 for shares/price/amount), and the general structure of each section all lined up. The only thing it couldn't predict in advance was the exact numeric values, since it hadn't run the script — but once I gave it the real output in Prompt 2, those numbers were consistent with what it described would appear.

2. Unexpected findings flagged by Claude: (1) security_id shows as float64 instead of a whole number because pandas can't keep a column as an integer type once it contains missing values — worth fixing before joining to another table. (2) The shares sign convention looks backwards: Buy transactions have negative share counts (836 of them) while Sell and Dividend are always positive, which is the opposite of the usual convention. (3) Advisory Fee's mean ($7,375) is over 8x its median ($859), a much sharper skew than any other transaction type, suggesting a handful of unusually large fee entries. (4) amount is stored as an unsigned magnitude (never negative, even for Withdrawals), so any analysis needing net cash flow would need to derive the sign from txn_type rather than read it off amount directly.

3. The 101,597 null security_id values: Yes, Claude addressed this directly. It pointed out that the 101,597 missing security_id, shares, and price values exactly equal the combined count of Deposit (35,981), Advisory Fee (35,766), and Withdrawal (29,850) transactions. Its explanation was that these are cash-only transaction types that structurally have no associated security, share count, or price — so this isn't a data quality problem, it's expected and shouldn't be imputed or treated as missing data in the traditional sense.

4. txn_date as a concern: Yes, Claude flagged this in both responses. It noted that because txn_date is stored as plain text rather than an actual date type, operations like finding the earliest/latest date only work correctly by coincidence, since Python is comparing the text alphabetically rather than chronologically. It pointed out this only produces correct results here because the format is consistently YYYY-MM-DD, and would silently break if the format ever became inconsistent. For time-series analysis, this matters because real date math — computing days between transactions, sorting chronologically in edge cases, resampling by month or year — requires an actual datetime type; running those operations on text either throws errors or produces meaningless results.

5. Comparing the charts to Claude's explanation: All three matched what was described. The histogram shows the red dashed line (mean, $54,075.17) sitting to the right of the green dashed line (median, $41,220.49), with a clear right-skewed shape — a tall bar near zero tapering into a long tail toward $250,000 — consistent with the positive skewness value (1.15) Claude explained. The box plot is horizontal as described, one box per txn_type, and visually confirms what Claude flagged about Advisory Fee: its box is compressed almost to zero with an extremely long tail of outlier points stretching out to around $150,000+, visibly different from the other five transaction types, which have much more evenly proportioned boxes. The scatter plot is colored by txn_type as described, and clearly shows the negative-share anomaly Claude called out — there are two separate triangular clusters of points split at zero shares: a smaller cluster on the left with negative share values (roughly -500 to 0) and a much denser cluster on the right with positive shares (0 to ~500). This visually confirms the 836 negative-share Buy transactions form their own distinct group rather than being scattered randomly through the data.

6. Follow-up question and answer:

Question: "Why doesn't the amount column have any negative values, even for Withdrawals?"

Answer: Claude explained that amount is recorded as a magnitude — the dollar amount involved — not a signed value showing direction of money flow. Direction is captured separately in the txn_type column instead of being encoded into the sign of amount. It pointed to the describe() output showing a minimum amount of $13.33 across all 298,772 rows as evidence: if Withdrawals or Advisory Fees were stored as negative, the overall minimum would be negative too, and it isn't. It also explained why this matters for any net-cash-flow calculation: you can't just sum amount, since that would treat every transaction as incoming money. It suggested creating a signed version of the column, flipping the sign for Withdrawal and Advisory Fee rows, so a .sum() would then reflect actual net cash movement rather than total dollar volume.

## 2C — Business Check & Cross-Validation

1. Deposit, Withdrawal, and Advisory Fee are the three types with no security attached. Deposit and Withdrawal are just cash going in or out of the account, no stock is being bought or sold. Advisory Fee is just a charge for managing the account. The other three (Buy, Sell, Dividend) all involve an actual stock: Buy and Sell are trades, and Dividend is a payout from stock the client already owns. Adding up the counts confirms this: Deposit (35,981) + Withdrawal (29,850) + Advisory Fee (35,766) = 101,597, which matches the number of missing security_id, shares, and price values exactly.

2. Having far more Buys (83,556) than Sells (59,755) over five years is a good sign for the firm. It means clients are mostly adding to their investments rather than cashing out, so their account values are likely growing over time. It also suggests the firm may be gaining new clients or new money coming in regularly.

3. If dates are stored as plain text, the computer can't subtract them to find days between transactions because you can't do math on text, so the code would crash. The dates need to be changed into a real date format first so that kind of calculation works.

4. 108 clients per advisor sounds like a lot at first, but it's actually normal for this industry. Advisors usually have support staff to help with paperwork and scheduling, so they're not handling everything alone. Many real advisors manage 50 to 150+ clients, so 108 is a reasonable number, not a red flag.

5. I can think of two reasons this could happen. First, it might just be a typo and someone accidentally entered a negative number instead of a positive one. Second, it could be intentional, like a correction to fix an earlier mistake, where instead of deleting the wrong entry, someone added a new one to cancel it out. To figure out which it actually is, I'd look closely at those 836 rows and see if each one lines up with an earlier Buy for the same client and stock around the same time. If it matches up like that, it's probably a fix. If it looks random with nothing nearby, it's probably just a typo.

### Cross-Validation
6. Script A (checking directly for "Buy") returned 83,556. Script B (counting everything, then subtracting all the other types) also returned 83,556.

7. Yes, they agree because both gave the same number, 83,556, which also matches what the assignment expected.

8. Checking it two different ways is useful because it catches mistakes one method alone might miss. If I had a typo in how "Buy" was spelled somewhere, the direct filter might miss it, but subtracting the other five types wouldn't rely on that spelling at all, so it would still catch the error. Since both methods landed on the same number here, that gives me more confidence the count is actually correct.