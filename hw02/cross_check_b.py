import pandas as pd

df = pd.read_csv("data/raw/fact_transactions.csv")
total_rows = len(df)
other_types = df["txn_type"].isin(["Sell", "Deposit", "Withdrawal", "Dividend", "Advisory Fee"]).sum()
buy_count = total_rows - other_types
print(f"Total rows: {total_rows}")
print(f"Rows that are NOT Buy: {other_types}")
print(f"Buy count by subtraction: {buy_count}")