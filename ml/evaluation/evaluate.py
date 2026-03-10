"""
SageMaker Processing Script — model evaluation.
Loads trained model artifact, runs on validation set, writes evaluation.json.
Result used by ConditionStep to gate model registration.
"""
import os
import json
import tarfile
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

MODEL_DIR = "/opt/ml/processing/model"
VAL_DIR = "/opt/ml/processing/validation"
OUTPUT_DIR = "/opt/ml/processing/evaluation"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Extract model tarball
model_tar = os.path.join(MODEL_DIR, "model.tar.gz")
if os.path.exists(model_tar):
    with tarfile.open(model_tar) as t:
        t.extractall(MODEL_DIR)

model = joblib.load(os.path.join(MODEL_DIR, "xgboost_pitstop.pkl"))
with open(os.path.join(MODEL_DIR, "feature_names.json")) as f:
    feature_names = json.load(f)

val_dfs = []
for fname in os.listdir(VAL_DIR):
    path = os.path.join(VAL_DIR, fname)
    if fname.endswith(".csv"):
        val_dfs.append(pd.read_csv(path))
    elif fname.endswith(".parquet"):
        val_dfs.append(pd.read_parquet(path))

val_df = pd.concat(val_dfs, ignore_index=True)

# Engineer same features as training
val_df["tyre_age_sq"] = val_df["tyre_age"] ** 2
val_df["heat_deg_interaction"] = val_df["track_temperature"] * val_df["tyre_age"] / 100.0
val_df["wet_stint"] = val_df["rainfall"] * val_df["stint_number"]
val_df["abs_sector_delta"] = val_df["sector_delta"].abs()

X_val = val_df[feature_names].fillna(0).values
y_val = val_df["pitstop_within_3_laps"].values

y_pred_proba = model.predict_proba(X_val)[:, 1]
auc = roc_auc_score(y_val, y_pred_proba)
print(f"Evaluation AUC: {auc:.4f}")

evaluation = {
    "auc": auc,
    "auc_threshold": 0.82,
    "approved": auc >= 0.82,
    "n_samples": len(X_val),
    "positive_rate": float(y_val.mean()),
}

with open(os.path.join(OUTPUT_DIR, "evaluation.json"), "w") as f:
    json.dump(evaluation, f, indent=2)

print(f"Evaluation complete. Approved: {evaluation['approved']}")
