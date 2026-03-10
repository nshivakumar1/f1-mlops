"""
Slack Notifier Lambda — sends rich Block Kit race-day alerts.
Auth: Slack Bot Token (xoxb-...) stored in AWS Secrets Manager.
Triggered by SNS topic alongside AWS Chatbot.
"""
import json
import os
import urllib.request
import urllib.error
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SLACK_SECRET_NAME = os.environ.get("SLACK_SECRET_NAME", "f1-mlops/slack-bot-token")
AWS_REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")

secrets_client = boto3.client("secretsmanager", region_name=AWS_REGION)

# Team accent colours for Block Kit headers
TEAM_COLORS = {
    "McLaren":      "#FF8000",
    "Ferrari":      "#DC0000",
    "Mercedes":     "#00D2BE",
    "Red Bull":     "#3671C6",
    "Williams":     "#005AFF",
    "Aston Martin": "#006F62",
    "Alpine":       "#0093CC",
    "Haas":         "#B6BABD",
    "Racing Bulls": "#6692FF",
    "Audi":         "#BB0000",
    "Cadillac":     "#1B3D6F",
}


def get_slack_token() -> str:
    response = secrets_client.get_secret_value(SecretId=SLACK_SECRET_NAME)
    secret = json.loads(response["SecretString"])
    return secret["bot_token"]


def build_pitstop_alert_blocks(data: dict) -> list:
    """Build Slack Block Kit blocks for a high-confidence pitstop alert."""
    driver = data.get("driver", "Unknown Driver")
    team = data.get("team", "Unknown Team")
    prob = data.get("pitstop_probability", 0)
    tyre = data.get("tyre_compound", "UNK")
    tyre_age = data.get("tyre_age", 0)
    session = data.get("session_key", "")

    prob_bar = "█" * int(prob * 10) + "░" * (10 - int(prob * 10))
    prob_pct = f"{prob * 100:.1f}%"
    color = TEAM_COLORS.get(team, "#888888")

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🏁 Pitstop Alert — {driver}"}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Team:*\n{team}"},
                {"type": "mrkdwn", "text": f"*Session:*\n{session}"},
                {"type": "mrkdwn", "text": f"*Tyre:*\n{tyre} ({tyre_age} laps)"},
                {"type": "mrkdwn", "text": f"*Probability:*\n`{prob_bar}` {prob_pct}"},
            ]
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Confidence threshold: >85% | Team: _{team}_"}
            ]
        }
    ]


def post_to_slack(token: str, channel: str, blocks: list, text: str):
    """Post message to Slack using Bot Token."""
    payload = json.dumps({
        "channel": channel,
        "text": text,
        "blocks": blocks,
    }).encode()

    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        result = json.loads(resp.read().decode())
        if not result.get("ok"):
            logger.error(f"Slack API error: {result.get('error')}")
        return result


def lambda_handler(event, context):
    """Handle SNS-triggered Slack notifications."""
    try:
        token = get_slack_token()
    except Exception as e:
        logger.error(f"Failed to get Slack token: {e}")
        return {"status": "error", "message": str(e)}

    channel = "#f1-race-alerts"

    for record in event.get("Records", []):
        sns_message = record.get("Sns", {})
        subject = sns_message.get("Subject", "F1 MLOps Alert")
        message_str = sns_message.get("Message", "{}")

        try:
            message_data = json.loads(message_str)
        except json.JSONDecodeError:
            message_data = {"raw": message_str}

        # Only build rich blocks for pitstop alerts
        if "pitstop_probability" in message_data:
            blocks = build_pitstop_alert_blocks(message_data)
            text = f"Pitstop Alert: {message_data.get('driver', 'Unknown')} — {message_data.get('pitstop_probability', 0)*100:.1f}%"
        else:
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": f"⚠️ {subject}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"```{json.dumps(message_data, indent=2)[:2000]}```"}},
            ]
            text = subject

        try:
            post_to_slack(token, channel, blocks, text)
            logger.info(f"Sent Slack notification: {subject}")
        except Exception as e:
            logger.error(f"Failed to post to Slack: {e}")

    return {"status": "ok"}
