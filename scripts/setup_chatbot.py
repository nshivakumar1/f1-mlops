"""
AWS Chatbot + Slack Setup Helper
---------------------------------
AWS Chatbot requires one manual OAuth step in the console.
This script handles everything else programmatically.

Steps:
  1. Run this script → it creates the SNS subscription and IAM role check
  2. Manually authorize Slack workspace in the AWS Chatbot console (one-time)
  3. Re-run with --create-channel to finalize the channel config

Usage:
  python3 scripts/setup_chatbot.py --check          # verify prerequisites
  python3 scripts/setup_chatbot.py --create-channel  # create channel config (after OAuth)
"""
import argparse
import json
import boto3
import sys

AWS_REGION = "us-east-1"
ACCOUNT_ID = "297997106614"
PROJECT = "f1-mlops"
SNS_TOPIC_ARN = f"arn:aws:sns:{AWS_REGION}:{ACCOUNT_ID}:{PROJECT}-alerts"
SLACK_CHANNEL = "#f1-race-alerts"


def check_prerequisites():
    """Verify SNS topic and IAM role exist."""
    sns = boto3.client("sns", region_name=AWS_REGION)
    iam = boto3.client("iam", region_name=AWS_REGION)

    print("=== Checking prerequisites ===")

    # Check SNS topic
    try:
        attrs = sns.get_topic_attributes(TopicArn=SNS_TOPIC_ARN)
        print(f"✅ SNS topic exists: {SNS_TOPIC_ARN}")
    except Exception as e:
        print(f"❌ SNS topic not found: {e}")
        sys.exit(1)

    # Check current subscriptions
    subs = sns.list_subscriptions_by_topic(TopicArn=SNS_TOPIC_ARN)
    print(f"   Current subscriptions: {len(subs['Subscriptions'])}")
    for sub in subs["Subscriptions"]:
        print(f"   - {sub['Protocol']}: {sub['Endpoint'][:60]}")

    # Check IAM role
    try:
        role = iam.get_role(RoleName=f"{PROJECT}-chatbot-role")
        print(f"✅ IAM role exists: {role['Role']['Arn']}")
    except iam.exceptions.NoSuchEntityException:
        print(f"⚠️  IAM role '{PROJECT}-chatbot-role' not found — creating...")
        _create_chatbot_role(iam)

    print("\n=== Manual step required ===")
    print("1. Open: https://us-east-1.console.aws.amazon.com/chatbot/home")
    print("2. Click 'Configure new client' → Slack")
    print("3. Click 'Authorize' and sign in to your Slack workspace")
    print("4. After authorization, note your Slack Workspace ID")
    print("5. Re-run: python3 scripts/setup_chatbot.py --create-channel --workspace-id <ID>")


def _create_chatbot_role(iam):
    """Create IAM role for AWS Chatbot."""
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "chatbot.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }
    role = iam.create_role(
        RoleName=f"{PROJECT}-chatbot-role",
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description="AWS Chatbot role for F1 MLOps Slack notifications",
    )
    iam.attach_role_policy(
        RoleName=f"{PROJECT}-chatbot-role",
        PolicyArn="arn:aws:iam::aws:policy/ReadOnlyAccess",
    )
    print(f"✅ Created IAM role: {role['Role']['Arn']}")
    return role["Role"]["Arn"]


def create_channel_config(workspace_id: str):
    """Create Slack channel configuration after OAuth is done."""
    chatbot = boto3.client("chatbot", region_name=AWS_REGION)
    iam = boto3.client("iam", region_name=AWS_REGION)

    try:
        role_arn = iam.get_role(RoleName=f"{PROJECT}-chatbot-role")["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        role_arn = _create_chatbot_role(iam)

    # Get Slack channel ID from workspace
    print(f"Creating channel config for {SLACK_CHANNEL} in workspace {workspace_id}...")
    print("Note: You need the channel ID (e.g. C0123ABCDEF), not the channel name.")
    print("Get it in Slack: right-click channel → View channel details → copy Channel ID")

    channel_id = input("Enter Slack channel ID for #f1-race-alerts: ").strip()

    try:
        response = chatbot.create_slack_channel_configuration(
            SlackTeamId=workspace_id,
            SlackChannelId=channel_id,
            SlackChannelName="f1-race-alerts",
            SnsTopicArns=[SNS_TOPIC_ARN],
            IamRoleArn=role_arn,
            ConfigurationName=f"{PROJECT}-slack-config",
            LoggingLevel="ERROR",
        )
        print(f"✅ Slack channel configured!")
        print(f"   Config ARN: {response['ChannelConfiguration']['ChatConfigurationArn']}")
        print(f"\nTest it: aws sns publish --topic-arn {SNS_TOPIC_ARN} \\")
        print(f"  --message 'F1 MLOps test alert 🏎️' --region {AWS_REGION}")
    except Exception as e:
        print(f"❌ Error creating channel config: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="AWS Chatbot + Slack setup helper")
    parser.add_argument("--check", action="store_true", help="Check prerequisites")
    parser.add_argument("--create-channel", action="store_true", help="Create Slack channel config")
    parser.add_argument("--workspace-id", help="Slack workspace ID (from AWS Chatbot console)")
    args = parser.parse_args()

    if args.check or (not args.create_channel):
        check_prerequisites()

    if args.create_channel:
        if not args.workspace_id:
            print("Error: --workspace-id required with --create-channel")
            sys.exit(1)
        create_channel_config(args.workspace_id)


if __name__ == "__main__":
    main()
