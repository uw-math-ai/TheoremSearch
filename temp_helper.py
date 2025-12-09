import pandas as pd

vals = pd.read_csv("validation_set.csv", header=0, index_col=0, dtype={"paper_id": str})
vals = vals[vals["body-and-summary-v1"].notnull()]
slogans = pd.read_csv("full_slogan_set.csv", header=0, index_col=0, dtype={"paper_id": str})
arr = []

for idx, row in vals.iterrows():
    print(row[1])
    indices = slogans[(slogans["theorem"] == row[1]) & (slogans["paper_id"] == row[3])].index
    # print(idx, indices[0])
    arr.append((idx, int(indices[0])))
    print(arr[idx][1])

print(arr)
"""
df = pd.DataFrame(arr, columns=["val", "full"])
df.to_csv("qrels_table_binary.csv")
"""