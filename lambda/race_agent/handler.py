"""
F1 Race Day AI Agent — autonomous monitoring and remediation.

Triggered by:
  1. CloudWatch Alarm SNS notifications (alarm state changes)
  2. Manual invocation: {"action": "diagnose"} or {"action": "health_check"}

Uses Claude claude-sonnet-4-6 to:
  - Analyse CloudWatch logs and metrics
  - Diagnose the root cause of failures
  - Execute targeted remediations (session key fix, Lambda redeploy, alarm reset)
  - Post a structured Slack report via SNS

Architecture:
  SNS (alarm) → Lambda (this) → Claude → remediation actions → SNS (Slack report)
"""
import json
import os
import boto3
import logging
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

AWS_REGION       = os.environ.get("AWS_REGION_NAME", "us-east-1")
S3_BUCKET        = os.environ["S3_BUCKET"]
SNS_TOPIC_ARN    = os.environ.get("SNS_TOPIC_ARN", "")
ANTHROPIC_SECRET = os.environ.get("ANTHROPIC_SECRET_NAME", "f1-mlops/anthropic-api-key")
ENRICHMENT_FN    = os.environ.get("ENRICHMENT_FUNCTION", "f1-mlops-enrichment")
REST_HANDLER_FN  = os.environ.get("REST_HANDLER_FUNCTION", "f1-mlops-rest-handler")
API_URL          = os.environ.get("API_URL", "https://xwmgxkj0r4.execute-api.us-east-1.amazonaws.com/v1")

logs    = boto3.client("logs",       region_name=AWS_REGION)
cw      = boto3.client("cloudwatch", region_name=AWS_REGION)
s3      = boto3.client("s3",         region_name=AWS_REGION)
sns     = boto3.client("sns",        region_name=AWS_REGION)
lmb     = boto3.client("lambda",     region_name=AWS_REGION)
sm      = boto3.client("secretsmanager", region_name=AWS_REGION)
events  = boto3.client("events",     region_name=AWS_REGION)
apigw   = boto3.client("apigateway", region_name=AWS_REGION)


# ── Anthropic client ─────────────────────────────────────────────────────────

def _get_anthropic_key() -> str:
    secret = sm.get_secret_value(SecretId=ANTHROPIC_SECRET)["SecretString"]
    try:
        return json.loads(secret)["api_key"]
    except (json.JSONDecodeError, KeyError):
        return secret.strip()


def call_claude(system: str, messages: list, max_tokens: int = 1024) -> str:
    """Call Claude claude-sonnet-4-6 via direct HTTPS (no SDK needed in Lambda)."""
    api_key = _get_anthropic_key()
    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode())
    return result["content"][0]["text"]


# ── Diagnostic data collectors ────────────────────────────────────────────────

def get_recent_lambda_errors(function_name: str, minutes: int = 10) -> list[str]:
    """Pull ERROR lines from Lambda CloudWatch logs in the last N minutes."""
    log_group = f"/aws/lambda/{function_name}"
    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - minutes * 60 * 1000
    try:
        streams = logs.describe_log_streams(
            logGroupName=log_group,
            orderBy="LastEventTime",
            descending=True,
            limit=3,
        )["logStreams"]
        errors = []
        for stream in streams:
            events_resp = logs.get_log_events(
                logGroupName=log_group,
                logStreamName=stream["logStreamName"],
                startTime=start_ms,
                endTime=end_ms,
                limit=100,
            )
            for e in events_resp["events"]:
                msg = e.get("message", "")
                if any(kw in msg for kw in ["ERROR", "Exception", "Traceback", "Task timed out"]):
                    errors.append(msg[:400])
        return errors[-20:]  # last 20 error lines
    except Exception as e:
        logger.warning(f"Could not fetch logs for {function_name}: {e}")
        return []


def get_alarm_states() -> list[dict]:
    """Return all F1 MLOps alarms and their current states."""
    resp = cw.describe_alarms(AlarmNamePrefix="f1-mlops")
    return [
        {
            "name": a["AlarmName"],
            "state": a["StateValue"],
            "reason": a["StateReason"][:200],
        }
        for a in resp.get("MetricAlarms", [])
    ]


def get_latest_s3_prediction() -> dict:
    """Return metadata from the most recent prediction file in S3."""
    try:
        result = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix="logs/inference/")
        objects = result.get("Contents", [])
        if not objects:
            return {"error": "No prediction files found"}
        latest = sorted(objects, key=lambda x: x["LastModified"], reverse=True)[0]
        age_s  = (datetime.now(timezone.utc) - latest["LastModified"]).total_seconds()
        obj    = s3.get_object(Bucket=S3_BUCKET, Key=latest["Key"])
        data   = json.loads(obj["Body"].read().decode())
        unknown_count = sum(
            1 for p in data.get("predictions", [])
            if p.get("tyre_compound", "") == "UNKNOWN"
        )
        return {
            "key": latest["Key"],
            "age_seconds": round(age_s),
            "session_key": data.get("session_key"),
            "country_name": data.get("country_name", ""),
            "prediction_count": len(data.get("predictions", [])),
            "unknown_tyre_count": unknown_count,
            "processing_time_ms": data.get("processing_time_ms"),
            "commentary_present": bool(data.get("commentary")),
        }
    except Exception as e:
        return {"error": str(e)}


def check_api_health() -> dict:
    """GET /sessions/latest and report status code + data freshness."""
    try:
        req = urllib.request.Request(
            f"{API_URL}/sessions/latest",
            headers={"User-Agent": "f1-mlops-agent/1.0"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            pred_time = data.get("prediction_time", "")
            if pred_time:
                age_s = (datetime.now(timezone.utc) - datetime.fromisoformat(pred_time)).total_seconds()
            else:
                age_s = -1
            return {
                "status": resp.status,
                "session_key": data.get("session_key"),
                "prediction_age_seconds": round(age_s),
                "driver_count": len(data.get("predictions", [])),
                "commentary_present": bool(data.get("commentary")),
            }
    except urllib.error.HTTPError as e:
        return {"status": e.code, "error": str(e)}
    except Exception as e:
        return {"status": 0, "error": str(e)}


def get_eventbridge_poller_state() -> str:
    try:
        resp = events.describe_rule(Name="f1-mlops-live-poller")
        return resp.get("State", "UNKNOWN")
    except Exception:
        return "UNKNOWN"


# ── Remediation actions ───────────────────────────────────────────────────────

REMEDIATIONS = {
    "reset_alarm": "Reset a CloudWatch alarm to OK state.",
    "restart_poller": "Enable the EventBridge poller rule if it is disabled.",
    "invoke_enrichment": "Manually trigger the enrichment Lambda once.",
    "fix_api_stage": "Force a new API Gateway deployment to fix 403 errors.",
}


def remediate(action: str, params: dict = {}) -> str:
    """Execute a remediation and return a human-readable result."""
    try:
        if action == "reset_alarm":
            alarm_name = params.get("alarm_name", "")
            cw.set_alarm_state(
                AlarmName=alarm_name,
                StateValue="OK",
                StateReason="Auto-reset by F1 race day AI agent",
            )
            return f"✅ Alarm `{alarm_name}` reset to OK."

        elif action == "restart_poller":
            events.enable_rule(Name="f1-mlops-live-poller")
            return "✅ EventBridge poller re-enabled."

        elif action == "invoke_enrichment":
            resp = lmb.invoke(
                FunctionName=ENRICHMENT_FN,
                InvocationType="Event",  # async
                Payload=json.dumps({}),
            )
            return f"✅ Enrichment Lambda invoked asynchronously (status {resp['StatusCode']})."

        elif action == "fix_api_stage":
            api_id = "xwmgxkj0r4"
            # Get all integrations to build the redeployment trigger
            deployment = apigw.create_deployment(
                restApiId=api_id,
                stageName="v1",
                description="Auto-redeployment by F1 race day AI agent",
            )
            dep_id = deployment["id"]
            apigw.update_stage(
                restApiId=api_id,
                stageName="v1",
                patchOperations=[{"op": "replace", "path": "/deploymentId", "value": dep_id}],
            )
            return f"✅ API Gateway stage redeployed (deployment `{dep_id}`)."

        else:
            return f"⚠️ Unknown remediation action: `{action}`"
    except Exception as e:
        return f"❌ Remediation `{action}` failed: {e}"


# ── Agent loop ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an autonomous F1 race day operations agent for an MLOps system that predicts pitstops using XGBoost + AWS SageMaker.

Your job during a live race:
1. Diagnose issues from the diagnostic data provided
2. Select remediation actions from the available list
3. Report clearly what was wrong and what you fixed

Available remediation actions (respond with JSON array):
- {"action": "reset_alarm", "params": {"alarm_name": "<name>"}}
- {"action": "restart_poller", "params": {}}
- {"action": "invoke_enrichment", "params": {}}
- {"action": "fix_api_stage", "params": {}}

Known issues and their fixes:
- Prediction file age >120s AND poller is DISABLED → restart_poller
- Prediction file age >120s AND poller is ENABLED → invoke_enrichment (Lambda likely errored)
- API returns 403 or status!=200 → fix_api_stage
- CloudWatch alarms stuck in ALARM state with normal operation → reset_alarm
- tyre compound UNKNOWN for all drivers → OpenF1 overloaded, no action needed (cache will restore)

Respond ONLY with a JSON object:
{
  "diagnosis": "1-2 sentence diagnosis",
  "severity": "ok|warning|critical",
  "actions": [<list of remediation action objects, or empty array if no action needed>],
  "summary": "1-2 sentence plain English summary for Slack"
}"""


def run_agent(trigger: str = "manual") -> dict:
    """Collect diagnostics, call Claude, execute remediations, return report."""
    logger.info(f"Agent triggered: {trigger}")

    # Collect all diagnostic data
    diag = {
        "trigger": trigger,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alarms": get_alarm_states(),
        "latest_prediction": get_latest_s3_prediction(),
        "api_health": check_api_health(),
        "poller_state": get_eventbridge_poller_state(),
        "enrichment_errors": get_recent_lambda_errors(ENRICHMENT_FN, minutes=15),
        "rest_handler_errors": get_recent_lambda_errors(REST_HANDLER_FN, minutes=15),
    }

    logger.info(f"Diagnostics: {json.dumps(diag, default=str)[:1000]}")

    # Ask Claude to diagnose and prescribe remediations
    try:
        response_text = call_claude(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Diagnostic data:\n{json.dumps(diag, indent=2, default=str)}"}],
            max_tokens=512,
        )
        agent_decision = json.loads(response_text)
    except Exception as e:
        logger.error(f"Claude call failed: {e}")
        agent_decision = {
            "diagnosis": "Agent unable to call Claude — manual review required.",
            "severity": "warning",
            "actions": [],
            "summary": f"Agent call failed: {e}",
        }

    # Execute each prescribed remediation
    remediation_results = []
    for action_obj in agent_decision.get("actions", []):
        action = action_obj.get("action", "")
        params = action_obj.get("params", {})
        result = remediate(action, params)
        remediation_results.append(result)
        logger.info(f"Remediation result: {result}")

    # Build Slack report
    severity_emoji = {"ok": "✅", "warning": "⚠️", "critical": "🔴"}.get(agent_decision.get("severity", "ok"), "ℹ️")
    slack_msg = (
        f"{severity_emoji} *F1 Race Agent Report*\n"
        f"*Trigger:* {trigger}\n"
        f"*Diagnosis:* {agent_decision.get('diagnosis', '')}\n"
        f"*Actions taken:* {chr(10).join(remediation_results) if remediation_results else 'None'}\n"
        f"*Summary:* {agent_decision.get('summary', '')}"
    )

    # Post to Slack via SNS
    if SNS_TOPIC_ARN:
        try:
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=f"F1 Agent [{agent_decision.get('severity','ok').upper()}]: {agent_decision.get('diagnosis','')[:60]}",
                Message=slack_msg,
            )
        except Exception as e:
            logger.warning(f"SNS publish failed: {e}")

    return {
        "trigger": trigger,
        "severity": agent_decision.get("severity"),
        "diagnosis": agent_decision.get("diagnosis"),
        "actions_taken": remediation_results,
        "summary": agent_decision.get("summary"),
        "diagnostics": diag,
    }


# ── Lambda entry point ────────────────────────────────────────────────────────

def lambda_handler(event, context):
    # CloudWatch Alarm via SNS
    if "Records" in event:
        for record in event["Records"]:
            if record.get("EventSource") == "aws:sns":
                msg = json.loads(record["Sns"]["Message"])
                alarm_name = msg.get("AlarmName", "unknown")
                new_state  = msg.get("NewStateValue", "")
                # Only act on ALARM transitions, not OK
                if new_state == "ALARM":
                    trigger = f"alarm:{alarm_name}"
                    return run_agent(trigger)
        return {"statusCode": 200, "body": "No ALARM transitions — nothing to do"}

    # Manual invocation
    action = event.get("action", "diagnose")
    if action in ("diagnose", "health_check"):
        return run_agent(trigger="manual")

    return {"statusCode": 400, "body": f"Unknown action: {action}"}
