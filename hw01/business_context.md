## Question 1: Delinquent vs. Default

**Prompt:** In our loan data, there are 4 status types: Current, Paid Off, Default, and Delinquent. What's actually the difference between delinquent and default? Why would a lender want to track those as two separate things instead of just one "bad loan" category?

**Summary:** Delinquent means the borrower is late on a payment, but the lender still expects them to pay it back eventually. Default means the lender basically gives up on getting paid the normal way, so the loan goes to collections or gets written off as a loss. Lenders keep these separate because delinquent loans are still likely to be fine, but default loans are basically already a loss. 

**Follow-up question:** At what point (30, 60, or 90+ days late) does Wildcat consider a delinquent loan serious enough to reclassify as default?
