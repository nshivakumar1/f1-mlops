data "archive_file" "enrichment" {
  type        = "zip"
  source_dir  = "${path.root}/../../../lambda/enrichment"
  output_path = "${path.module}/enrichment.zip"
}

data "archive_file" "rest_handler" {
  type        = "zip"
  source_dir  = "${path.root}/../../../lambda/rest_handler"
  output_path = "${path.module}/rest_handler.zip"
}

data "archive_file" "prewarm" {
  type        = "zip"
  source_dir  = "${path.root}/../../../lambda/prewarm"
  output_path = "${path.module}/prewarm.zip"
}

data "archive_file" "slack_notifier" {
  type        = "zip"
  source_dir  = "${path.root}/../../../lambda/slack_notifier"
  output_path = "${path.module}/slack_notifier.zip"
}

# Enrichment Lambda — polls OpenF1, builds feature vector, invokes SageMaker
resource "aws_lambda_function" "enrichment" {
  function_name    = "${var.project}-enrichment"
  filename         = data.archive_file.enrichment.output_path
  source_code_hash = data.archive_file.enrichment.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  memory_size      = 512
  timeout          = 30
  role             = var.lambda_role_arn

  environment {
    variables = {
      S3_BUCKET          = var.s3_bucket
      SAGEMAKER_ENDPOINT = var.sagemaker_endpoint
      SNS_TOPIC_ARN      = var.sns_topic_arn
      AWS_REGION_NAME    = var.aws_region
      LOGSTASH_ENDPOINT  = var.logstash_url
    }
  }

  tracing_config { mode = "Active" }
}

# REST handler Lambda — serves API Gateway requests
resource "aws_lambda_function" "rest_handler" {
  function_name    = "${var.project}-rest-handler"
  filename         = data.archive_file.rest_handler.output_path
  source_code_hash = data.archive_file.rest_handler.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  memory_size      = 256
  timeout          = 10
  role             = var.lambda_role_arn

  environment {
    variables = {
      S3_BUCKET          = var.s3_bucket
      SAGEMAKER_ENDPOINT = var.sagemaker_endpoint
      AWS_REGION_NAME    = var.aws_region
    }
  }

  tracing_config { mode = "Active" }
}

# Pre-warm Lambda — invokes SageMaker endpoint before each session
resource "aws_lambda_function" "prewarm" {
  function_name    = "${var.project}-prewarm"
  filename         = data.archive_file.prewarm.output_path
  source_code_hash = data.archive_file.prewarm.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 30
  role             = var.lambda_role_arn

  environment {
    variables = {
      SAGEMAKER_ENDPOINT = var.sagemaker_endpoint
      AWS_REGION_NAME    = var.aws_region
    }
  }
}

# Slack notifier Lambda — sends formatted race-day Slack cards
resource "aws_lambda_function" "slack_notifier" {
  function_name    = "${var.project}-slack-notifier"
  filename         = data.archive_file.slack_notifier.output_path
  source_code_hash = data.archive_file.slack_notifier.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 10
  role             = var.lambda_role_arn

  environment {
    variables = {
      SLACK_SECRET_NAME = "f1-mlops/slack-bot-token"
      AWS_REGION_NAME   = var.aws_region
    }
  }
}

# Allow SNS to invoke slack_notifier
resource "aws_lambda_permission" "sns_slack" {
  statement_id  = "AllowSNSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.slack_notifier.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = var.sns_topic_arn
}

# CloudWatch Log Groups
resource "aws_cloudwatch_log_group" "enrichment" {
  name              = "/aws/lambda/${aws_lambda_function.enrichment.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "rest_handler" {
  name              = "/aws/lambda/${aws_lambda_function.rest_handler.function_name}"
  retention_in_days = 14
}
