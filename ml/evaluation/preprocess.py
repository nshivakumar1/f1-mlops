"""
SageMaker Processing Script — train/val split for pitstop model.
Called by ProcessData step in SageMaker Pipeline.
"""
import os
import pandas as pd
from sklearn.model_selection import train_test_split

INPUT_DIR = "/opt/ml/processing/input"
TRAIN_DIR = "/opt/ml/processing/train"
VAL_DIR = "/opt/ml/processing/validation"

os.makedirs(TRAIN_DIR, exist_ok=True)
os.makedirs(VAL_DIR, exist_ok=True)

dfs = []
for fname in os.listdir(INPUT_DIR):
    path = os.path.join(INPUT_DIR, fname)
    if fname.endswith(".parquet"):
        dfs.append(pd.read_parquet(path))
    elif fname.endswith(".csv"):
        dfs.append(pd.read_csv(path))

if not dfs:
    raise ValueError(f"No data in {INPUT_DIR}")

df = pd.concat(dfs, ignore_index=True)
print(f"Total rows: {len(df)}")

# Temporal split — use last 20% of sessions as validation to prevent leakage
df = df.sort_values("event_time") if "event_time" in df.columns else df
split_idx = int(len(df) * 0.8)
train_df = df.iloc[:split_idx]
val_df = df.iloc[split_idx:]

train_df.to_csv(os.path.join(TRAIN_DIR, "train.csv"), index=False)
val_df.to_csv(os.path.join(VAL_DIR, "validation.csv"), index=False)

print(f"Train: {len(train_df)} | Val: {len(val_df)}")
