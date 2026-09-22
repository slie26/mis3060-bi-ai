import pandas as pd

df = pd.read_csv("data/raw/fact_transactions.csv")
buy_count = (df["txn_type"] == "Buy").sum()
print(f"Direct count of Buy transactions: {buy_count}")