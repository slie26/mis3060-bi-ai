load the file data/raw/fact_transactions.csv into a pandas DataFrame.
Print the shape of the DataFrame (number of rows and number of columns). 
Print all column names along with their data types. 
Print the count of missing values for every column. 
Print descriptive statistics (count, mean, standard deviation, minimum, 25th percentile, median, 75th percentile, and maximum) for all numeric columns. 
Print the value counts and percentages for txn_type, sorted from most frequent to least frequent. 
Print the number of unique clients, unique advisors, and unique securities referenced in the file. 
Print the earliest and latest txn_date in the dataset.
Check for duplicate rows based on txn_id and print the count of duplicates found.
Print the mean, median, and skewness of the amount column. 
group the data by txn_type and print, for each group, the count plus the mean and median amount (rounded to 2 decimal places), sorted from highest mean amount to lowest. 
Compute the correlation matrix for shares, price, and amount (rounded to 2 decimal places), print it, and identify the three strongest correlations, excluding a variable's correlation with itself. 
Print the minimum, maximum, and count of negative values in the shares column, broken out by txn_type. 
Print a warning message if the shape of the data is not exactly 298,772 rows by 9 columns. 
Create and save three charts into a hw02/charts/ folder: a histogram of amount with vertical lines marking the mean and median, clearly labeled (saved as hw02/charts/hist_amount.png); a horizontal box plot of amount grouped by txn_type (saved as hw02/charts/box_amount_by_type.png); and a scatter plot with shares on the x-axis and amount on the y-axis, colored by txn_type (saved as hw02/charts/scatter_shares_amount.png).
Save a plain-text summary of items 2 through 13 to hw02/hw02_profile.txt.
Include a comment block at the top of the script identifying the script name, the dataset used, the author, and the date it was generated. 
All of the above must run together in a single Python script executed in one run - not as 17 separate scripts. 