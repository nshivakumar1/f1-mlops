"""
Pre-warm Lambda — invokes SageMaker serverless endpoint 5 min before each session.
Triggered by EventBridge rule 5 minutes before session start.
Zero cost: just sends a dummy request to eliminate cold start latency.
"""
import json
import os
import boto3
import logging
import sentry_sdk
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration

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

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SAGEMAKER_ENDPOINT = os.environ["SAGEMAKER_ENDPOINT"]
AWS_REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")

sagemaker_runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION)
sagemaker = boto3.client("sagemaker", region_name=AWS_REGION)


# 11 features: tyre_age, stint_number, gap_to_leader, air_temp, track_temp, rainfall, sector_delta,
#              tyre_age_sq, heat_deg_interaction, wet_stint, abs_sector_delta
DUMMY_FEATURES = [5.0, 1.0, 2.5, 28.0, 42.0, 0.0, 0.1, 25.0, 2.1, 0.0, 0.1]


def lambda_handler(event, context):
    action = event.get("action", "prewarm")

    if action == "prewarm":
        logger.info(f"Pre-warming endpoint: {SAGEMAKER_ENDPOINT}")
        try:
            response = sagemaker_runtime.invoke_endpoint(
                EndpointName=SAGEMAKER_ENDPOINT,
                ContentType="application/json",
                Body=json.dumps({"instances": [DUMMY_FEATURES]}),
            )
            result = json.loads(response["Body"].read().decode())
            logger.info(f"Pre-warm successful: {result}")
            return {"status": "warm", "endpoint": SAGEMAKER_ENDPOINT}
        except Exception as e:
            logger.error(f"Pre-warm failed: {e}")
            return {"status": "failed", "error": str(e)}

    elif action == "update_endpoint":
        model_package_arn = event.get("model_package")
        logger.info(f"Updating endpoint with new model: {model_package_arn}")
        # Endpoint config update handled by SageMaker Pipeline ConditionStep
        return {"status": "update_triggered", "model_package": model_package_arn}

    return {"status": "unknown_action", "action": action}
