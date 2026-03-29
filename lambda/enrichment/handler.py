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
import threading
from concurrent.futures import ThreadPoolExecutor
import time
import urllib.request
import urllib.error
import boto3
import logging
import sentry_sdk
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration
from datetime import datetime, timezone
from openf1_client import (
    build_feature_vector,
    fetch_all_session_data,
    get_latest_session,
    ALL_DRIVER_NUMBERS,
)
from groq_client import generate_race_commentary

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN", ""),
    integrations=[AwsLambdaIntegration()],
    environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
    traces_sample_rate=1.0,
    send_default_pii=True,
    profile_session_sample_rate=1.0,
    profile_lifecycle="trace",
    release=os.environ.get("SENTRY_RELEASE", ""),
    enable_logs=True,
)

S3_BUCKET = os.environ["S3_BUCKET"]
SAGEMAKER_ENDPOINT = os.environ["SAGEMAKER_ENDPOINT"]
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
AWS_REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")
LOGSTASH_ENDPOINT = os.environ.get("LOGSTASH_ENDPOINT", "")
NEWRELIC_ACCOUNT_ID = os.environ.get("NEWRELIC_ACCOUNT_ID", "")
NEWRELIC_LICENSE_KEY_SECRET = os.environ.get("NEWRELIC_LICENSE_KEY_SECRET", "")

s3 = boto3.client("s3", region_name=AWS_REGION)
sagemaker_runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION)
cloudwatch = boto3.client("cloudwatch", region_name=AWS_REGION)
sns = boto3.client("sns", region_name=AWS_REGION)
secretsmanager = boto3.client("secretsmanager", region_name=AWS_REGION)

ALERT_PROBABILITY_THRESHOLD = 0.85

TEAM_SCORES = {
    "McLaren": 0.95, "Ferrari": 0.90, "Red Bull": 0.88, "Mercedes": 0.85,
    "Williams": 0.65, "Aston Martin": 0.70, "Alpine": 0.60, "Haas": 0.55,
    "Racing Bulls": 0.62, "Audi": 0.50, "Cadillac": 0.45,
}

# Cached NR license key — fetched once per warm container
_newrelic_license_key: str = ""


def _get_newrelic_key() -> str:
    global _newrelic_license_key
    if _newrelic_license_key:
        return _newrelic_license_key
    if not NEWRELIC_LICENSE_KEY_SECRET:
        return ""
    try:
        secret = secretsmanager.get_secret_value(SecretId=NEWRELIC_LICENSE_KEY_SECRET)
        raw = secret["SecretString"]
        # NR Lambda Extension requires JSON format {"LicenseKey": "..."}
        try:
            _newrelic_license_key = json.loads(raw)["LicenseKey"]
        except (json.JSONDecodeError, KeyError):
            _newrelic_license_key = raw  # plain string fallback
        return _newrelic_license_key
    except Exception as e:
        logger.warning(f"Failed to fetch NR license key: {e}")
        return ""

# Module-level fallback: last successful prediction batch (survives warm invocations)
_last_good_predictions: dict = {}   # session_key → list of prediction dicts

TYRE_CACHE_PREFIX = "tyre_cache"


def save_tyre_cache(session_key: str, stints_by_driver: dict):
    """Persist latest stint data to S3 so it survives OpenF1 outages."""
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=f"{TYRE_CACHE_PREFIX}/{session_key}.json",
            Body=json.dumps(stints_by_driver),
            ContentType="application/json",
        )
    except Exception as e:
        logger.warning(f"Failed to save tyre cache: {e}")


def load_tyre_cache(session_key: str) -> dict:
    """Load last known stint data from S3. Returns empty dict if not found."""
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=f"{TYRE_CACHE_PREFIX}/{session_key}.json")
        # S3 keys are strings; convert back to int for driver_number lookups
        raw = json.loads(obj["Body"].read().decode())
        return {int(k): v for k, v in raw.items()}
    except s3.exceptions.NoSuchKey:
        return {}
    except Exception as e:
        logger.warning(f"Failed to load tyre cache: {e}")
        return {}


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


def compute_win_probabilities(predictions: list, safety_car_active: bool) -> list:
    """
    Compute win probability per driver from live race state.
    Uses position (gap ranking), gap, tyre freshness, team strength, and pitstop risk.
    No second model endpoint needed — computed inline each lap.
    """
    if not predictions:
        return predictions

    # Derive current race position from gap_to_leader ranking (index 2 in features)
    sorted_preds = sorted(predictions, key=lambda p: p["features"][2])
    n = len(sorted_preds)

    raw_scores = []
    for rank, p in enumerate(sorted_preds):
        gap = p["features"][2]       # gap_to_leader
        tyre_age = p["features"][0]  # tyre_age
        team = p.get("team", "")

        position_score = (n - rank) / n                        # P1=1.0 ... last≈0
        gap_score = max(0.0, 1.0 - gap / 120.0)               # 120s = roughly 1 lap behind
        tyre_score = max(0.0, 1.0 - tyre_age / 50.0)          # fresher = better
        team_score = TEAM_SCORES.get(team, 0.50)
        pitstop_stability = 1.0 - p.get("prediction", {}).get("pitstop_probability", 0.0)

        # Under safety car, position matters more, gap matters less
        if safety_car_active:
            raw = position_score * 0.55 + team_score * 0.25 + tyre_score * 0.15 + pitstop_stability * 0.05
        else:
            raw = position_score * 0.40 + gap_score * 0.25 + team_score * 0.20 + tyre_score * 0.10 + pitstop_stability * 0.05

        raw_scores.append(raw)

    total = sum(raw_scores) or 1.0
    for p, score in zip(sorted_preds, raw_scores):
        p["win_probability"] = round(score / total, 4)

    return predictions


def check_safety_car(session_data: dict) -> bool:
    """Check if safety car is active from already-fetched race control messages.
    Sorts by date descending and returns on the first flag-bearing message found.
    """
    messages = session_data.get("race_control", [])
    for msg in sorted(messages, key=lambda m: m.get("date", ""), reverse=True):
        flag = (msg.get("flag") or "").upper()
        message = (msg.get("message") or "").upper()
        if flag in ("SC", "VSC") or "SAFETY CAR" in message:
            return True
        if flag == "GREEN" or "GREEN FLAG" in message:
            return False
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
                    "commentary": p.get("commentary", ""),
                }, indent=2),
            )
        except Exception as e:
            logger.warning(f"SNS publish failed for {p['driver_name']}: {e}")

    with ThreadPoolExecutor(max_workers=5) as pool:
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
            high_confidence_count = sum(1 for c in confidences if c > ALERT_PROBABILITY_THRESHOLD)
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

    threading.Thread(target=_publish, daemon=True).start()


def push_to_newrelic(predictions: list, session_key: str, safety_car_active: bool, commentary: str = ""):
    """Push per-driver predictions to New Relic via Metric API + Log API.

    The Insights Events API requires a separate Insights Insert Key (not the
    License/Ingest Key). Metric API and Log API both accept the License Key.

    Dashboard queries:
      SELECT latest(value) FROM Metric WHERE metricName = 'f1.pitstop.probability'
        FACET driverCode SINCE 30 minutes ago
      SELECT latest(message) FROM Log WHERE sessionKey IS NOT NULL
        SINCE 30 minutes ago
    """
    if not predictions:
        return

    license_key = _get_newrelic_key()
    if not license_key:
        return

    ts_ms = int(time.time() * 1000)   # NR Metric API requires milliseconds

    def _push():
        try:
            # ── Metric API: pitstop + win + telemetry metrics per driver ─────
            metrics = []
            for p in predictions:
                pred = p.get("prediction", {})
                attrs = {
                    "sessionKey": session_key,
                    "driverNumber": str(p.get("driver_number", "")),
                    "driverCode": p.get("driver_name", ""),
                    "team": p.get("team", ""),
                    "tyreCompound": p.get("tyre_compound", "UNKNOWN"),
                    "tyreAge": str(p["features"][0] if p.get("features") else 0),
                    "lapNumber": str(p.get("lap_number", 0)),
                    "pitsCompleted": str(p.get("pits_completed", 0)),
                    "lastPitDuration": str(p.get("last_pit_duration") or ""),
                    "lastPitLap": str(p.get("last_pit_lap") or ""),
                    "drsActive": str(p.get("drs_active", False)).lower(),
                    "speed": str(p.get("speed", 0)),
                    "throttle": str(p.get("throttle", 0)),
                    "brake": str(p.get("brake", 0)),
                    "gear": str(p.get("gear", 0)),
                    "safetyCarActive": str(safety_car_active).lower(),
                    "confidence": str(round(pred.get("confidence", 0.0), 4)),
                }
                metrics.append({
                    "name": "f1.pitstop.probability",
                    "type": "gauge",
                    "value": round(pred.get("pitstop_probability", 0.0), 4),
                    "timestamp": ts_ms,
                    "attributes": attrs,
                })
                metrics.append({
                    "name": "f1.win.probability",
                    "type": "gauge",
                    "value": round(p.get("win_probability", 0.0), 4),
                    "timestamp": ts_ms,
                    "attributes": attrs,
                })
                if p.get("speed"):
                    metrics.append({
                        "name": "f1.car.speed",
                        "type": "gauge",
                        "value": float(p.get("speed", 0)),
                        "timestamp": ts_ms,
                        "attributes": attrs,
                    })
                if p.get("throttle") is not None:
                    metrics.append({
                        "name": "f1.car.throttle",
                        "type": "gauge",
                        "value": float(p.get("throttle", 0)),
                        "timestamp": ts_ms,
                        "attributes": attrs,
                    })

            metric_payload = json.dumps([{"metrics": metrics}]).encode()
            req = urllib.request.Request(
                "https://metric-api.newrelic.com/metric/v1",
                data=metric_payload,
                headers={"Content-Type": "application/json", "Api-Key": license_key},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                nr_status = resp.status
            logger.info(f"NR: pushed {len(predictions)} drivers ({len(metrics)} metrics) → HTTP {nr_status}")

            # ── Log API: one entry per invocation with commentary ────────────
            if commentary:
                log_payload = json.dumps([{"logs": [{
                    "timestamp": ts_ms,
                    "message": commentary[:4095],
                    "sessionKey": session_key,
                    "safetyCarActive": safety_car_active,
                    "driverCount": len(predictions),
                    "source": "f1-mlops",
                }]}]).encode()
                req2 = urllib.request.Request(
                    "https://log-api.newrelic.com/log/v1",
                    data=log_payload,
                    headers={"Content-Type": "application/json", "Api-Key": license_key},
                    method="POST",
                )
                urllib.request.urlopen(req2, timeout=5)

        except Exception as e:
            logger.warning(f"New Relic push failed (non-critical): {e}")

    threading.Thread(target=_push, daemon=True).start()


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

    threading.Thread(target=_push, daemon=True).start()


def lambda_handler(event, context):
    """Main enrichment handler — polls OpenF1, predicts, logs."""
    start_time = time.time()

    # ── 1. Resolve session key ───────────────────────────────────────────────
    # Priority: env var override > event param > OpenF1 latest session
    env_session = os.environ.get("SESSION_KEY", "")
    country_name = ""
    if env_session:
        session_key = env_session
    elif event.get("session_key"):
        session_key = str(event["session_key"])
    else:
        try:
            session = get_latest_session()
            session_key = str(session.get("session_key", "latest"))
            country_name = session.get("country_name", "")
        except Exception as e:
            logger.error(f"Failed to get session: {e}")
            session_key = "latest"

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

    # ── 2b. Tyre data fallback cache ─────────────────────────────────────────
    # OpenF1 /stints returns 502/empty during heavy load (seen during Australian GP).
    # Save stints to S3 on every successful fetch; restore from cache when empty.
    if session_data["stints"]:
        save_tyre_cache(session_key, session_data["stints"])
    else:
        cached_stints = load_tyre_cache(session_key)
        if cached_stints:
            session_data["stints"] = cached_stints
            logger.warning(f"OpenF1 stints empty — restored tyre data for {len(cached_stints)} drivers from S3 cache")
        else:
            logger.warning("OpenF1 stints empty and no S3 cache found — tyre data will be UNKNOWN")

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

            for (driver_number, feature_data), prediction in zip(driver_features, batch_results):
                result = {
                    **feature_data,
                    "prediction": prediction,
                    "safety_car_active": safety_car_active,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                predictions.append(result)

        except Exception as e:
            logger.error(f"SageMaker batch inference failed: {e}")
            stale = _last_good_predictions.get(session_key, [])
            if stale:
                logger.warning(f"SageMaker down — serving {len(stale)} stale predictions")
                predictions = stale
            errors.append({"batch": True, "error": str(e)})

    # ── 5. Update fallback cache ─────────────────────────────────────────────
    if predictions and not any(e.get("batch") for e in errors):
        _last_good_predictions[session_key] = predictions

    # ── 5b. Compute win probabilities from live race state ───────────────────
    if predictions:
        predictions = compute_win_probabilities(predictions, safety_car_active)

    # ── 5c. Groq race commentary (non-blocking — failure returns "") ─────────
    commentary = generate_race_commentary(predictions, safety_car_active, session_key)
    if commentary:
        logger.info(f"Groq commentary: {commentary[:80]}...")

    # ── 5d. Fire SNS alerts with commentary attached ─────────────────────────
    if driver_features:
        alert_queue_with_commentary = [
            {**p, "commentary": commentary}
            for p in predictions
            if p.get("prediction", {}).get("pitstop_probability", 0) > ALERT_PROBABILITY_THRESHOLD
        ]
        if alert_queue_with_commentary:
            publish_alerts(alert_queue_with_commentary)

    # ── 6. Persist to S3 ────────────────────────────────────────────────────
    processing_ms = round((time.time() - start_time) * 1000)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    s3_key = f"logs/inference/session_{session_key}/{ts}.json"
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=json.dumps({
            "session_key": session_key,
            "country_name": country_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "predictions": predictions,
            "errors": errors,
            "safety_car_active": safety_car_active,
            "processing_time_ms": processing_ms,
            "commentary": commentary,
        }),
        ContentType="application/json",
    )

    # ── 7. Background: CloudWatch metrics + New Relic + Logstash (non-blocking) ─
    publish_metrics_async(predictions)
    push_to_newrelic(predictions, session_key, safety_car_active, commentary)
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
