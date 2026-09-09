## Strategy 1: Zero-shot

**Prompt:** What are the most important metrics for measuring credit risk in a consumer loan portfolio?

**First 150 words of response:** The metrics that matter most for consumer loan credit risk generally fall into a few categories, and I'll flag which ones you can actually calculate from the loan-level data sitting in your 02_Data/Raw folder (credit score, DTI, loan status, income, term, rate, purpose, state — that's a solid base). Borrower-level risk indicators come first, since they predict risk before a loan ever goes bad. Credit score (FICO or similar) is the classic starting point — it's directly in your dataset and lets you segment the portfolio into risk tiers. Debt-to-income ratio is the second pillar; DTI above roughly 40-43% is where default risk climbs sharply, and you have this field too. Loan-to-income or payment-to-income ratio (monthly payment as a share of monthly income) is worth deriving from loan_amount, interest_rate, term, and annual_income — it's often a better single predictor than DTI alone because it captures the specific loan's burden rather

**Evaluation:** This answer was detailed and it did use Wildcat's actual data columns (credit score, DTI, loan amount, etc.), so it didn't feel generic. But it was hard to follow. It just listed a bunch of categories one after another without organizing them. Also, I asked what metrics matter "most," but it never actually picked a top one. It just gave a long list and treated everything as equally important.

## Strategy 2: Role-assigned

**Prompt:** You are a senior credit risk analyst at Wildcat Capital, presenting to a portfolio committee of three senior executives who have limited technical background. What are the most important metrics for measuring credit risk in a consumer loan portfolio?

**First 150 words of response:** For a portfolio committee with limited technical background, you want a small set of metrics that each answer a plain-English question, rather than a long list of ratios. I pulled up the loan-level data in your Data/Raw folder (2,340 loans) to ground this in your actual portfolio, and a handful of metrics stand out as the core story. The first tier is delinquency and default rate — the simplest and most important numbers, because they answer "how many borrowers are failing to pay us back." In your data, 248 of 2,340 loans (10.6%) are currently delinquent and 106 (4.5%) have defaulted, so roughly 15% of the book is either behind or already lost. Executives will immediately want to know how that compares to a benchmark or to last quarter, so pairing the current snapshot with a trend line matters more than the single number. The second tier is loss severity

**Evaluation:** This answer was way more organized than the zero-shot one. It ranked the metrics (first, second, third, fourth) instead of just listing them all as equal, and it told me which ones actually matter most. It also matched the audience I asked for by using plain language instead of jargon. The only weird part was at the end it randomly offered to build slides or pull more data, which I didn't ask for.

## Strategy 3: Few-shot

**Prompt:** Here's an example of the format I want your answer in:

Metric: Customer Churn Rate
What it measures: Percentage of customers who stop using a service in a given period
Why it matters: High churn signals problems with retention or satisfaction

Now, using this same format, answer: What are the most important metrics for measuring credit risk in a consumer loan portfolio?

**First 150 words of response:** Metric: Default Rate
What it measures: Percentage of loans in the portfolio where the borrower has failed to make payments per the loan terms (typically 90+ days past due or charged off)
Why it matters: Directly reflects credit losses and portfolio quality; rising default rates signal deteriorating underwriting standards or borrower financial stress
Metric: Delinquency Rate (30/60/90-day buckets)
What it measures: Percentage of loans past due by specified time thresholds, tracked in stages before default
Why it matters: Serves as an early warning system, allowing risk teams to spot deteriorating credit quality before loans reach default
Metric: Net Charge-Off Rate
What it measures: Value of loans written off as uncollectible, minus recoveries, as a percentage of total loan balances
Why it matters: Captures actual realized losses after collection efforts, giving a clearer picture of financial impact than delinquency alone
Metric: Loss Given Default (LGD)
What it measures: Percentage of the

**Evaluation:** This one matched the format I asked for really well. Each metric had a clear "what it measures" and "why it matters," which made it easy to read. But it was really long (10 metrics) and it didn't use any of Wildcat's actual data like the other two answers did, it just gave generic definitions. It also used a lot of technical terms without explaining them, so it wouldn't work for a non-technical audience. And just like the zero-shot answer, it never ranked anything, it just listed everything as equally important.

## Conclusion

Strategy 3 (few-shot) was my favorite out of the three. Giving it a format to follow made the answer so much easier to read compared to the zero-shot one, which just felt like a wall of text with no real structure. Strategy 2 was good too, it was organized and used simple language, but I still liked how clean Strategy 3 looked. Zero-shot was the hardest to get through since nothing was ranked or organized. At the end of the day, telling Claude exactly how I wanted the answer formatted made the biggest difference in how useful it actually was.
