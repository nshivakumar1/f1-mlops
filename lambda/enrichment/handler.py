"""
Lambda Enrichment Function
- Triggered every 60s by EventBridge during live F1 sessions
- Polls OpenF1 API for all 22 drivers (5 concurrent calls)
- Builds 11-feature vector per driver
- Invokes SageMaker in a single batch call for all drivers
- Logs results to S3 and publishes custom CloudWatch metrics
- Falls back to last good predictions if current run fails
"""
import json
import os
import time
import urllib.request
import urllib.error
import boto3
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from openf1_client import (
    build_feature_vector,
    fetch_all_session_data,
    get_latest_session,
    ALL_DRIVER_NUMBERS,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET = os.environ["S3_BUCKET"]
SAGEMAKER_ENDPOINT = os.environ["SAGEMAKER_ENDPOINT"]
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
AWS_REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")
LOGSTASH_ENDPOINT = os.environ.get("LOGSTASH_ENDPOINT", "")

s3 = boto3.client("s3", region_name=AWS_REGION)
sagemaker_runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION)
cloudwatch = boto3.client("cloudwatch", region_name=AWS_REGION)
sns = boto3.client("sns", region_name=AWS_REGION)

# Module-level fallback: last successful prediction batch (survives warm invocations)
_last_good_predictions: dict = {}   # session_key → list of prediction dicts


def invoke_pitstop_model_batch(feature_vectors: list) -> list:
    """
    Single SageMaker call for all drivers at once.
    Input:  list of 11-feature lists  (up to 22)
    Output: list of prediction dicts  (same order)

    Previously: 22 sequential calls × ~100ms = ~2.2s
    Now:        1 batch call          = ~100ms
    """
    payload = {"instances": feature_vectors}
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="application/json",
        Body=json.dumps(payload),
    )
    result = json.loads(response["Body"].read().decode())
    predictions = result.get("predictions", [])
    # Pad with defaults if response is shorter than input (safety net)
    while len(predictions) < len(feature_vectors):
        predictions.append({"pitstop_probability": 0.0, "confidence": 0.0})
    return predictions


def check_safety_car(session_data: dict) -> bool:
    """Check if safety car is active from already-fetched race control messages."""
    messages = session_data.get("race_control", [])
    for msg in reversed(messages[-10:]):
        flag = msg.get("flag", "").upper()
        message = msg.get("message", "").upper()
        if "SAFETY CAR" in message or flag in ("SC", "VSC"):
            return True
    return False


def publish_alerts(alert_predictions: list):
    """Fire SNS alerts for high-probability drivers concurrently."""
    if not alert_predictions or not SNS_TOPIC_ARN:
        return

    def _publish(p):
        try:
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=f"F1 High Pitstop Alert: {p['driver_name']}",
                Message=json.dumps({
                    "driver": p["driver_name"],
                    "team": p["team"],
                    "pitstop_probability": p["prediction"].get("pitstop_probability"),
                    "tyre_compound": p["tyre_compound"],
                    "tyre_age": p["features"][0],
                    "session_key": p["session_key"],
                }, indent=2),
            )
        except Exception as e:
            logger.warning(f"SNS publish failed for {p['driver_name']}: {e}")

    with ThreadPoolExecutor(max_workers=len(alert_predictions)) as pool:
        list(pool.map(_publish, alert_predictions))


def publish_metrics_async(predictions: list):
    """Publish CloudWatch metrics in a background thread (non-blocking)."""
    if not predictions:
        return

    def _publish():
        try:
            confidences = [p["prediction"].get("confidence", 0) for p in predictions if p.get("prediction")]
            if not confidences:
                return
            avg_confidence = sum(confidences) / len(confidences)
            high_confidence_count = sum(1 for c in confidences if c > 0.85)
            cloudwatch.put_metric_data(
                Namespace="F1MLOps/Models",
                MetricData=[
                    {
                        "MetricName": "PredictionConfidence",
                        "Value": avg_confidence,
                        "Unit": "None",
                        "Timestamp": datetime.now(timezone.utc),
                    },
                    {
                        "MetricName": "HighConfidencePredictions",
                        "Value": high_confidence_count,
                        "Unit": "Count",
                        "Timestamp": datetime.now(timezone.utc),
                    },
                ],
            )
        except Exception as e:
            logger.warning(f"CloudWatch publish failed: {e}")

    ThreadPoolExecutor(max_workers=1).submit(_publish)


def push_logstash_async(payload: dict):
    """Push to Logstash in a background thread — fire and forget."""
    if not LOGSTASH_ENDPOINT:
        return

    def _push():
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                LOGSTASH_ENDPOINT,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception as e:
            logger.warning(f"Logstash push failed (non-critical): {e}")

    ThreadPoolExecutor(max_workers=1).submit(_push)


def lambda_handler(event, context):
    """Main enrichment handler — polls OpenF1, predicts, logs."""
    start_time = time.time()

    # ── 1. Resolve session key ───────────────────────────────────────────────
    try:
        session = get_latest_session()
        session_key = str(session.get("session_key") or event.get("session_key", "latest"))
    except Exception as e:
        logger.error(f"Failed to get session: {e}")
        session_key = str(event.get("session_key", "latest"))

    logger.info(f"Processing session_key={session_key}")

    # ── 2. Fetch all session data (5 concurrent API calls) ───────────────────
    try:
        session_data = fetch_all_session_data(session_key)
    except Exception as e:
        logger.error(f"Failed to fetch session data: {e}")
        # Serve stale predictions if available — don't return empty hands
        stale = _last_good_predictions.get(session_key, [])
        if stale:
            logger.warning(f"Serving {len(stale)} stale predictions from cache")
        return {
            "statusCode": 200,
            "session_key": session_key,
            "predictions_count": len(stale),
            "errors_count": 22,
            "stale": True,
        }

    session_data["session_key"] = session_key
    safety_car_active = check_safety_car(session_data)

    # ── 3. Build feature vectors for all drivers ─────────────────────────────
    driver_features = []   # (driver_number, feature_data)
    errors = []

    for driver_number in ALL_DRIVER_NUMBERS:
        try:
            feature_data = build_feature_vector(driver_number, session_data)
            if feature_data:
                driver_features.append((driver_number, feature_data))
        except Exception as e:
            logger.warning(f"Feature build failed driver={driver_number}: {e}")
            errors.append({"driver_number": driver_number, "error": str(e)})

    # ── 4. Single batch SageMaker call for all drivers ───────────────────────
    predictions = []
    if driver_features:
        try:
            feature_lists = [fd["features"] for _, fd in driver_features]
            batch_results = invoke_pitstop_model_batch(feature_lists)

            alert_queue = []
            for (driver_number, feature_data), prediction in zip(driver_features, batch_results):
                result = {
                    **feature_data,
                    "prediction": prediction,
                    "safety_car_active": safety_car_active,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                predictions.append(result)

                if prediction.get("pitstop_probability", 0) > 0.85:
                    alert_queue.append(result)

            # Fire all alerts concurrently (non-blocking relative to each other)
            if alert_queue:
                publish_alerts(alert_queue)

        except Exception as e:
            logger.error(f"SageMaker batch inference failed: {e}")
            # Fall back to last good predictions for this session
            stale = _last_good_predictions.get(session_key, [])
            if stale:
                logger.warning(f"SageMaker down — serving {len(stale)} stale predictions")
                predictions = stale
            errors.append({"batch": True, "error": str(e)})

    # ── 5. Update fallback cache ─────────────────────────────────────────────
    if predictions and not any(e.get("batch") for e in errors):
        _last_good_predictions[session_key] = predictions

    # ── 6. Persist to S3 ────────────────────────────────────────────────────
    processing_ms = round((time.time() - start_time) * 1000)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    s3_key = f"logs/inference/session_{session_key}/{ts}.json"
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=json.dumps({
            "session_key": session_key,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "predictions": predictions,
            "errors": errors,
            "safety_car_active": safety_car_active,
            "processing_time_ms": processing_ms,
        }),
        ContentType="application/json",
    )

    # ── 7. Background: CloudWatch metrics + Logstash (non-blocking) ──────────
    publish_metrics_async(predictions)
    push_logstash_async({
        "session_key": session_key,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "predictions": predictions,
        "safety_car_active": safety_car_active,
    })

    logger.info(
        f"Done: {len(predictions)} drivers · {len(errors)} errors · {processing_ms}ms"
    )

    return {
        "statusCode": 200,
        "session_key": session_key,
        "predictions_count": len(predictions),
        "errors_count": len(errors),
        "safety_car_active": safety_car_active,
        "processing_time_ms": processing_ms,
        "s3_key": s3_key,
    }
