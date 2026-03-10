"""
Session Control — Enable/disable EventBridge rules before/after F1 sessions.
Usage:
  python scripts/session_control.py --action enable   # Before session
  python scripts/session_control.py --action disable  # After session
  python scripts/session_control.py --action prewarm  # 5 min before session
"""
import argparse
import boto3
import json

RULE_NAME = "f1-mlops-live-poller"
PREWARM_FUNCTION = "f1-mlops-prewarm"
REGION = "us-east-1"

events = boto3.client("events", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)


def enable_poller():
    events.enable_rule(Name=RULE_NAME)
    print(f"Enabled EventBridge rule: {RULE_NAME}")
    print("OpenF1 polling active — Lambda fires every 60 seconds")


def disable_poller():
    events.disable_rule(Name=RULE_NAME)
    print(f"Disabled EventBridge rule: {RULE_NAME}")
    print("Polling stopped — no more Lambda invocations")


def prewarm_endpoint():
    response = lambda_client.invoke(
        FunctionName=PREWARM_FUNCTION,
        InvocationType="RequestResponse",
        Payload=json.dumps({"action": "prewarm"}),
    )
    result = json.loads(response["Payload"].read())
    print(f"Pre-warm result: {result}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["enable", "disable", "prewarm"], required=True)
    args = parser.parse_args()

    if args.action == "enable":
        prewarm_endpoint()
        enable_poller()
    elif args.action == "disable":
        disable_poller()
    elif args.action == "prewarm":
        prewarm_endpoint()
