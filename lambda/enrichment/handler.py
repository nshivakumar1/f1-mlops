"""
Lambda Enrichment Function
- Triggered every 60s by EventBridge during live F1 sessions
- Polls OpenF1 API for all 22 drivers
- Builds 7-feature vector per driver
- Invokes SageMaker serverless endpoint for pitstop prediction
- Logs results to S3 and publishes custom CloudWatch metrics
"""
import json
import os
import time
import urllib.request
import urllib.error
import boto3
import logging
from datetime import datetime, timezone
from openf1_client import (
    build_feature_vector,
    fetch_all_session_data,
    get_latest_session,
    get_race_control,
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


def invoke_pitstop_model(features: list) -> dict:
    """Invoke SageMaker serverless endpoint with feature vector."""
    payload = {"instances": [features]}
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="application/json",
        Body=json.dumps(payload),
    )
    result = json.loads(response["Body"].read().decode())
    # Expected response: {"predictions": [{"pitstop_probability": 0.73, "confidence": 0.81}]}
    if "predictions" in result and result["predictions"]:
        return result["predictions"][0]
    return {"pitstop_probability": 0.0, "confidence": 0.0}


def publish_metrics(predictions: list):
    """Publish custom CloudWatch metrics for model drift detection."""
    if not predictions:
        return
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
    logger.info(f"Published metrics: avg_confidence={avg_confidence:.3f}, high_conf_count={high_confidence_count}")


def check_safety_car(session_key: str) -> bool:
    """Check if safety car is active from race control messages."""
    try:
        messages = get_race_control(session_key)
        for msg in reversed(messages[-10:]):
            flag = msg.get("flag", "").upper()
            message = msg.get("message", "").upper()
            if "SAFETY CAR" in message or flag in ("SC", "VSC"):
                return True
    except Exception:
        pass
    return False


def lambda_handler(event, context):
    """Main enrichment handler — polls OpenF1, predicts, logs."""
    start_time = time.time()

    # Get current session
    try:
        session = get_latest_session()
        session_key = session.get("session_key") or event.get("session_key", "latest")
    except Exception as e:
        logger.error(f"Failed to get session: {e}")
        session_key = event.get("session_key", "latest")

    logger.info(f"Processing session_key={session_key}")

    safety_car_active = check_safety_car(session_key)

    # Batch-fetch all session data in 3 API calls instead of 66
    try:
        session_data = fetch_all_session_data(session_key)
    except Exception as e:
        logger.error(f"Failed to fetch session data: {e}")
        session_data = {"stints": {}, "intervals": {}, "laps": {}, "weather": {}}
    session_data["session_key"] = session_key

    predictions = []
    errors = []

    for driver_number in ALL_DRIVER_NUMBERS:
        try:
            feature_data = build_feature_vector(driver_number, session_data)
            if not feature_data:
                continue

            prediction = invoke_pitstop_model(feature_data["features"])
            pitstop_prob = prediction.get("pitstop_probability", 0.0)

            result = {
                **feature_data,
                "prediction": prediction,
                "safety_car_active": safety_car_active,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            predictions.append(result)

            # Alert on very high probability
            if pitstop_prob > 0.85 and SNS_TOPIC_ARN:
                sns.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Subject=f"F1 High Pitstop Alert: {feature_data['driver_name']}",
                    Message=json.dumps({
                        "driver": feature_data["driver_name"],
                        "team": feature_data["team"],
                        "pitstop_probability": pitstop_prob,
                        "tyre_compound": feature_data["tyre_compound"],
                        "tyre_age": feature_data["features"][0],
                        "session_key": session_key,
                    }, indent=2),
                )

        except Exception as e:
            logger.warning(f"Driver {driver_number} failed: {e}")
            errors.append({"driver_number": driver_number, "error": str(e)})

    # Persist to S3
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
            "processing_time_ms": round((time.time() - start_time) * 1000),
        }),
        ContentType="application/json",
    )

    publish_metrics(predictions)

    # Push to Logstash for real-time Kibana dashboards (fire-and-forget)
    if LOGSTASH_ENDPOINT and predictions:
        try:
            payload = json.dumps({
                "session_key": session_key,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "predictions": predictions,
                "safety_car_active": safety_car_active,
            }).encode()
            req = urllib.request.Request(
                LOGSTASH_ENDPOINT,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception as e:
            logger.warning(f"Logstash push failed (non-critical): {e}")

    logger.info(
        f"Processed {len(predictions)} drivers, {len(errors)} errors, "
        f"{round((time.time() - start_time) * 1000)}ms"
    )

    return {
        "statusCode": 200,
        "session_key": session_key,
        "predictions_count": len(predictions),
        "errors_count": len(errors),
        "safety_car_active": safety_car_active,
        "s3_key": s3_key,
    }
