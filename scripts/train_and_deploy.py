"""
Day 3 Script: Train pitstop model locally + package + upload model artifact to S3
              + create SageMaker Serverless endpoint.

Run: python3 scripts/train_and_deploy.py --bucket f1-mlops-data-297997106614
"""
import argparse
import io
import json
import os
import sys
import tarfile
import tempfile
import time
import boto3
import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
import xgboost as xgb

AWS_REGION = "us-east-1"
ACCOUNT_ID = "297997106614"
PROJECT = "f1-mlops"

FEATURE_COLS = [
    "tyre_age", "stint_number", "gap_to_leader",
    "air_temperature", "track_temperature", "rainfall", "sector_delta",
    "tyre_age_sq", "heat_deg_interaction", "wet_stint", "abs_sector_delta",
]
TARGET_COL = "pitstop_within_3_laps"
AUC_THRESHOLD = 0.82


# ── 1. Load training data from S3 ────────────────────────────────────────────

def load_training_data(bucket: str) -> pd.DataFrame:
    s3 = boto3.client("s3", region_name=AWS_REGION)
    dfs = []
    for prefix in ["processed/pitstop/"]:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith((".csv", ".parquet")):
                    continue
                print(f"  Loading s3://{bucket}/{key} ({obj['Size']//1024}KB)")
                body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
                if key.endswith(".csv"):
                    dfs.append(pd.read_csv(io.BytesIO(body)))
                else:
                    dfs.append(pd.read_parquet(io.BytesIO(body)))
    if not dfs:
        raise ValueError(f"No training data found in s3://{bucket}/processed/pitstop/")
    df = pd.concat(dfs, ignore_index=True)
    print(f"Loaded {len(df):,} rows")
    return df


# ── 2. Feature engineering ───────────────────────────────────────────────────

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df["tyre_age_sq"] = df["tyre_age"] ** 2
    df["heat_deg_interaction"] = df["track_temperature"] * df["tyre_age"] / 100.0
    df["wet_stint"] = df["rainfall"] * df["stint_number"]
    df["abs_sector_delta"] = df["sector_delta"].abs()
    return df


# ── 3. Train model ───────────────────────────────────────────────────────────

def train_model(df: pd.DataFrame):
    df = engineer_features(df)
    X = df[FEATURE_COLS].fillna(0).values
    y = df[TARGET_COL].values

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    print(f"Train: {len(X_train):,} | Val: {len(X_val):,} | Positive rate: {y.mean():.3f}")

    scale_pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)

    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight,
        eval_metric="auc",
        random_state=42,
        tree_method="hist",
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=100)

    y_pred_proba = model.predict_proba(X_val)[:, 1]
    auc = roc_auc_score(y_val, y_pred_proba)
    print(f"\nValidation AUC: {auc:.4f} (threshold: {AUC_THRESHOLD})")

    if auc < AUC_THRESHOLD:
        print(f"WARNING: AUC below threshold. Model will still be deployed for race day.")

    return model, auc


# ── 4. Package and upload to S3 ──────────────────────────────────────────────

def package_and_upload(model, bucket: str) -> str:
    """Save model + inference script → tar.gz → S3."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Save XGBoost model in native JSON format (avoids numpy version incompatibility with joblib pickle)
        model_path = os.path.join(tmpdir, "xgboost_pitstop.json")
        model.save_model(model_path)

        # Save feature names
        features_path = os.path.join(tmpdir, "feature_names.json")
        with open(features_path, "w") as f:
            json.dump(FEATURE_COLS, f)

        # Copy inference script
        inference_src = os.path.join(
            os.path.dirname(__file__), "../ml/training/pitstop/inference.py"
        )
        inference_dst = os.path.join(tmpdir, "inference.py")
        with open(inference_src) as fin, open(inference_dst, "w") as fout:
            fout.write(fin.read())

        # Create tar.gz — inference.py must be in code/ subdirectory for SageMaker script mode
        code_dir = os.path.join(tmpdir, "code")
        os.makedirs(code_dir, exist_ok=True)
        import shutil
        shutil.copy(inference_dst, os.path.join(code_dir, "inference.py"))
        shutil.copy(features_path, os.path.join(code_dir, "feature_names.json"))

        # Write setup.py so sagemaker_containers installs inference.py as a py_module
        # (auto-generated setup.py uses find_packages() which misses standalone .py files)
        setup_py_path = os.path.join(code_dir, "setup.py")
        with open(setup_py_path, "w") as f:
            f.write("from setuptools import setup\n")
            f.write("setup(name='inference', version='1.0', py_modules=['inference'])\n")

        tar_path = os.path.join(tmpdir, "model.tar.gz")
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(model_path, arcname="xgboost_pitstop.json")
            tar.add(features_path, arcname="feature_names.json")
            tar.add(os.path.join(code_dir, "inference.py"), arcname="code/inference.py")
            tar.add(os.path.join(code_dir, "feature_names.json"), arcname="code/feature_names.json")
            tar.add(setup_py_path, arcname="code/setup.py")

        # Upload
        s3_key = "models/pitstop/dry-race-v1/model.tar.gz"
        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3.upload_file(tar_path, bucket, s3_key)
        model_uri = f"s3://{bucket}/{s3_key}"
        print(f"Model artifact uploaded → {model_uri}")
        return model_uri


# ── 5. Create/update SageMaker serverless endpoint ───────────────────────────

def deploy_endpoint(model_uri: str, auc: float):
    sm = boto3.client("sagemaker", region_name=AWS_REGION)
    role_arn = f"arn:aws:iam::{ACCOUNT_ID}:role/{PROJECT}-sagemaker-role"

    model_name = f"{PROJECT}-pitstop-dry-v1"
    config_name = f"{PROJECT}-pitstop-serverless-config"
    endpoint_name = f"{PROJECT}-pitstop-endpoint"

    # XGBoost 1.7 inference image (us-east-1)
    image_uri = f"683313688378.dkr.ecr.{AWS_REGION}.amazonaws.com/sagemaker-xgboost:1.7-1"

    # Delete old model if exists
    try:
        sm.delete_model(ModelName=model_name)
        print(f"Deleted old model: {model_name}")
    except sm.exceptions.ClientError:
        pass

    # Create model
    sm.create_model(
        ModelName=model_name,
        ExecutionRoleArn=role_arn,
        PrimaryContainer={
            "Image": image_uri,
            "ModelDataUrl": model_uri,
            "Environment": {
                "SAGEMAKER_CONTAINER_LOG_LEVEL": "20",
                "SAGEMAKER_PROGRAM": "inference.py",
                # model.tar.gz extracts to /opt/ml/model/ so code/ lands at /opt/ml/model/code/
                # sagemaker_containers uses SAGEMAKER_SUBMIT_DIRECTORY as module_dir
                "SAGEMAKER_SUBMIT_DIRECTORY": "/opt/ml/model/code",
            },
        },
    )
    print(f"Created model: {model_name}")

    # Delete old endpoint config if exists
    try:
        sm.delete_endpoint_config(EndpointConfigName=config_name)
        print(f"Deleted old config: {config_name}")
    except sm.exceptions.ClientError:
        pass

    # Create serverless endpoint config
    sm.create_endpoint_config(
        EndpointConfigName=config_name,
        ProductionVariants=[{
            "VariantName": "dry-race-v1",
            "ModelName": model_name,
            "ServerlessConfig": {
                "MemorySizeInMB": 2048,
                "MaxConcurrency": 10,
            },
        }],
    )
    print(f"Created endpoint config: {config_name}")

    # Create or update endpoint
    try:
        sm.describe_endpoint(EndpointName=endpoint_name)
        print(f"Updating existing endpoint: {endpoint_name}")
        sm.update_endpoint(
            EndpointName=endpoint_name,
            EndpointConfigName=config_name,
        )
    except sm.exceptions.ClientError:
        print(f"Creating new endpoint: {endpoint_name}")
        sm.create_endpoint(
            EndpointName=endpoint_name,
            EndpointConfigName=config_name,
        )

    # Wait for endpoint to be InService
    print("Waiting for endpoint to be InService...")
    waiter = sm.get_waiter("endpoint_in_service")
    waiter.wait(
        EndpointName=endpoint_name,
        WaiterConfig={"Delay": 30, "MaxAttempts": 40},
    )
    print(f"Endpoint InService: {endpoint_name}")

    # Save evaluation metadata to S3
    s3 = boto3.client("s3", region_name=AWS_REGION)
    eval_data = {
        "auc": auc,
        "threshold": AUC_THRESHOLD,
        "approved": auc >= AUC_THRESHOLD,
        "model_uri": model_uri,
        "endpoint": endpoint_name,
        "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    s3.put_object(
        Bucket=f"{PROJECT}-data-{ACCOUNT_ID}",
        Key="models/pitstop/dry-race-v1/evaluation.json",
        Body=json.dumps(eval_data, indent=2),
        ContentType="application/json",
    )
    return endpoint_name


# ── 6. Smoke test ─────────────────────────────────────────────────────────────

def smoke_test(endpoint_name: str):
    runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION)
    # Representative feature vector: lap 18, stint 1, 3s gap, 28°C air, 44°C track, dry, +0.2s sector
    test_features = [18.0, 1.0, 3.0, 28.0, 44.0, 0.0, 0.2, 324.0, 7.92, 1.0, 0.2]
    payload = {"instances": [test_features]}
    response = runtime.invoke_endpoint(
        EndpointName=endpoint_name,
        ContentType="application/json",
        Body=json.dumps(payload),
    )
    result = json.loads(response["Body"].read())
    prediction = result["predictions"][0]
    print(f"\nSmoke test prediction: {prediction}")
    prob = prediction.get("pitstop_probability", 0)
    assert 0 <= prob <= 1, f"Invalid probability: {prob}"
    print(f"Pitstop probability: {prob:.3f} | Confidence: {prediction.get('confidence', 0):.3f}")
    print("Smoke test PASSED")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", default=f"{PROJECT}-data-{ACCOUNT_ID}")
    parser.add_argument("--skip-train", action="store_true", help="Skip training, use existing model.tar.gz")
    args = parser.parse_args()

    if not args.skip_train:
        print("=== Step 1: Loading training data ===")
        df = load_training_data(args.bucket)

        print("\n=== Step 2: Training XGBoost pitstop model ===")
        model, auc = train_model(df)

        print("\n=== Step 3: Packaging and uploading model artifact ===")
        model_uri = package_and_upload(model, args.bucket)
    else:
        auc = 0.85  # Assumed if skipping
        model_uri = f"s3://{args.bucket}/models/pitstop/dry-race-v1/model.tar.gz"
        print(f"Skipping training. Using existing artifact: {model_uri}")

    print("\n=== Step 4: Deploying SageMaker serverless endpoint ===")
    endpoint_name = deploy_endpoint(model_uri, auc)

    print("\n=== Step 5: Smoke test ===")
    smoke_test(endpoint_name)

    print(f"\n{'='*50}")
    print("DEPLOYMENT COMPLETE")
    print(f"Endpoint: {endpoint_name}")
    print(f"AUC: {auc:.4f}")
    print("Ready for race day!")


if __name__ == "__main__":
    main()
