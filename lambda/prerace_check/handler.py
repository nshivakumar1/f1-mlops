import json
import os
import urllib.request
import urllib.error
import boto3
import logging
import sentry_sdk
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration
from datetime import datetime, timezone

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

S3_BUCKET = os.environ["S3_BUCKET"]
SAGEMAKER_ENDPOINT = os.environ["SAGEMAKER_ENDPOINT"]
AWS_REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")
PREWARM_FUNCTION_NAME = os.environ.get("PREWARM_FUNCTION_NAME", "f1-mlops-prewarm")

sagemaker_client = boto3.client("sagemaker", region_name=AWS_REGION)
secrets_client = boto3.client("secretsmanager", region_name=AWS_REGION)
events_client = boto3.client("events", region_name=AWS_REGION)
s3_client = boto3.client("s3", region_name=AWS_REGION)
lambda_client = boto3.client("lambda", region_name=AWS_REGION)


def _check(name: str, fn) -> dict:
    """Run a single check function, catch all exceptions, return structured result."""
    try:
        detail = fn()
        result = {"pass": True, "detail": detail}
    except Exception as e:
        result = {"pass": False, "detail": str(e)}
    logger.info(f"check={name} pass={result['pass']} detail={result['detail']}")
    return result


def check_sagemaker() -> str:
    resp = sagemaker_client.describe_endpoint(EndpointName=SAGEMAKER_ENDPOINT)
    status = resp["EndpointStatus"]
    if status != "InService":
        raise RuntimeError(f"endpoint status is {status}")
    return "InService"


def check_openf1_api() -> str:
    url = "https://api.openf1.org/v1/sessions?year=2026"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}")
        sessions = json.loads(resp.read().decode())
    if not sessions:
        raise RuntimeError("empty session list returned")
    return f"200 OK — {len(sessions)} sessions found"


def check_groq_secret() -> str:
    resp = secrets_client.get_secret_value(SecretId="f1-mlops/gemini-api-key")
    secret = resp["SecretString"]
    # Secret is stored as plain string gsk_... or JSON {"api_key": "gsk_..."}
    if secret.strip().startswith("{"):
        parsed = json.loads(secret)
        key = parsed.get("api_key", "")
    else:
        key = secret.strip()
    if not key.startswith("gsk_"):
        raise RuntimeError("secret does not start with gsk_")
    return f"gsk_... found"


def check_newrelic_key() -> str:
    resp = secrets_client.get_secret_value(SecretId="f1-mlops/newrelic-license-key")
    secret = resp["SecretString"].strip()
    if not secret:
        raise RuntimeError("secret value is empty")
    return "key present"


def check_openf1_credentials() -> str:
    resp = secrets_client.get_secret_value(SecretId="f1-mlops/openf1-credentials")
    creds = json.loads(resp["SecretString"])
    missing = [k for k in ("username", "password") if not creds.get(k)]
    if missing:
        raise RuntimeError(f"missing keys: {missing}")
    return "username/password present"


def check_eventbridge_poller() -> str:
    resp = events_client.describe_rule(Name="f1-mlops-live-poller")
    state = resp["State"]
    if state == "DISABLED":
        return "DISABLED — enable before race"
    return state


def check_s3_write() -> str:
    key = "prerace_check/probe.txt"
    s3_client.put_object(Bucket=S3_BUCKET, Key=key, Body=b"ok")
    s3_client.delete_object(Bucket=S3_BUCKET, Key=key)
    return "write/delete OK"


def check_prewarm() -> str:
    resp = lambda_client.invoke(
        FunctionName=PREWARM_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps({"action": "prewarm"}).encode(),
    )
    status_code = resp["StatusCode"]
    if status_code != 200:
        raise RuntimeError(f"invoke returned status {status_code}")
    # Check for function error (unhandled exception inside the invoked Lambda)
    if resp.get("FunctionError"):
        payload = json.loads(resp["Payload"].read().decode())
        raise RuntimeError(f"function error: {payload.get('errorMessage', 'unknown')}")
    return "invoked OK"


def lambda_handler(event, context):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    checks = {
        "sagemaker":           _check("sagemaker", check_sagemaker),
        "openf1_api":          _check("openf1_api", check_openf1_api),
        "groq_secret":         _check("groq_secret", check_groq_secret),
        "newrelic_key":        _check("newrelic_key", check_newrelic_key),
        "openf1_credentials":  _check("openf1_credentials", check_openf1_credentials),
        "eventbridge_poller":  _check("eventbridge_poller", check_eventbridge_poller),
        "s3_write":            _check("s3_write", check_s3_write),
        "prewarm":             _check("prewarm", check_prewarm),
    }

    # eventbridge_poller being DISABLED is expected pre-race — exclude from all_pass
    all_pass = all(
        v["pass"] for k, v in checks.items() if k != "eventbridge_poller"
    )

    failed_checks = [k for k, v in checks.items() if not v["pass"]]

    report = {
        "all_pass": all_pass,
        "checks": checks,
        "failed_checks": failed_checks,
        "timestamp": timestamp,
    }

    # Persist report to S3 for audit trail
    s3_key = f"prerace_check/{timestamp}.json"
    try:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(report, indent=2).encode(),
            ContentType="application/json",
        )
        logger.info(f"Report saved to s3://{S3_BUCKET}/{s3_key}")
    except Exception as e:
        # Don't fail the whole Lambda if the save fails — report is still returned
        logger.error(f"Failed to save report to S3: {e}")

    logger.info(f"Pre-race check complete: all_pass={all_pass} failed={failed_checks}")
    return report
