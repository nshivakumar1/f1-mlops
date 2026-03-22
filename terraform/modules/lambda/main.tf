data "archive_file" "prerace_check" {
  type        = "zip"
  source_dir  = "${path.root}/../../../lambda/prerace_check"
  output_path = "${path.module}/prerace_check.zip"
}

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
  handler          = "newrelic_lambda_wrapper.handler.handler"
  runtime          = "python3.12"
  memory_size      = 512
  timeout          = 60
  role             = var.lambda_role_arn
  layers           = [var.newrelic_layer_arn]

  environment {
    variables = {
      # Application config
      S3_BUCKET          = var.s3_bucket
      SAGEMAKER_ENDPOINT = var.sagemaker_endpoint
      SNS_TOPIC_ARN      = var.sns_topic_arn
      AWS_REGION_NAME    = var.aws_region
      GROQ_SECRET_NAME   = "f1-mlops/gemini-api-key"
      # Sentry
      SENTRY_DSN         = var.sentry_dsn
      SENTRY_ENVIRONMENT = var.sentry_environment
      # New Relic APM
      NEW_RELIC_LAMBDA_HANDLER               = "handler.lambda_handler"
      NEW_RELIC_ACCOUNT_ID                   = var.newrelic_account_id
      NEW_RELIC_TRUSTED_ACCOUNT_KEY          = var.newrelic_account_id
      NEW_RELIC_LICENSE_KEY_SECRET           = "f1-mlops/newrelic-license-key"
      NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS = "true"
      # New Relic custom events (pitstop predictions)
      NEWRELIC_LICENSE_KEY_SECRET = "f1-mlops/newrelic-license-key"
      NEWRELIC_ACCOUNT_ID         = var.newrelic_account_id
    }
  }

  tracing_config { mode = "Active" }
}

# REST handler Lambda — serves API Gateway requests
resource "aws_lambda_function" "rest_handler" {
  function_name    = "${var.project}-rest-handler"
  filename         = data.archive_file.rest_handler.output_path
  source_code_hash = data.archive_file.rest_handler.output_base64sha256
  handler          = "newrelic_lambda_wrapper.handler.handler"
  runtime          = "python3.12"
  memory_size      = 256
  timeout          = 10
  role             = var.lambda_role_arn
  layers           = [var.newrelic_layer_arn]

  environment {
    variables = {
      S3_BUCKET          = var.s3_bucket
      SAGEMAKER_ENDPOINT = var.sagemaker_endpoint
      AWS_REGION_NAME    = var.aws_region
      # Sentry
      SENTRY_DSN         = var.sentry_dsn
      SENTRY_ENVIRONMENT = var.sentry_environment
      # New Relic APM
      NEW_RELIC_LAMBDA_HANDLER               = "handler.lambda_handler"
      NEW_RELIC_ACCOUNT_ID                   = var.newrelic_account_id
      NEW_RELIC_TRUSTED_ACCOUNT_KEY          = var.newrelic_account_id
      NEW_RELIC_LICENSE_KEY_SECRET           = "f1-mlops/newrelic-license-key"
      NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS = "true"
    }
  }

  tracing_config { mode = "Active" }
}

# Pre-warm Lambda — invokes SageMaker endpoint before each session
resource "aws_lambda_function" "prewarm" {
  function_name    = "${var.project}-prewarm"
  filename         = data.archive_file.prewarm.output_path
  source_code_hash = data.archive_file.prewarm.output_base64sha256
  handler          = "newrelic_lambda_wrapper.handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 30
  role             = var.lambda_role_arn
  layers           = [var.newrelic_layer_arn]

  environment {
    variables = {
      SAGEMAKER_ENDPOINT = var.sagemaker_endpoint
      AWS_REGION_NAME    = var.aws_region
      # Sentry
      SENTRY_DSN         = var.sentry_dsn
      SENTRY_ENVIRONMENT = var.sentry_environment
      # New Relic APM
      NEW_RELIC_LAMBDA_HANDLER               = "handler.lambda_handler"
      NEW_RELIC_ACCOUNT_ID                   = var.newrelic_account_id
      NEW_RELIC_TRUSTED_ACCOUNT_KEY          = var.newrelic_account_id
      NEW_RELIC_LICENSE_KEY_SECRET           = "f1-mlops/newrelic-license-key"
      NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS = "true"
    }
  }
}

# Slack notifier Lambda — sends formatted race-day Slack cards
resource "aws_lambda_function" "slack_notifier" {
  function_name    = "${var.project}-slack-notifier"
  filename         = data.archive_file.slack_notifier.output_path
  source_code_hash = data.archive_file.slack_notifier.output_base64sha256
  handler          = "newrelic_lambda_wrapper.handler.handler"
  runtime          = "python3.12"
  memory_size      = 128
  timeout          = 10
  role             = var.lambda_role_arn
  layers           = [var.newrelic_layer_arn]

  environment {
    variables = {
      SLACK_SECRET_NAME = "f1-mlops/slack-bot-token"
      AWS_REGION_NAME   = var.aws_region
      # Sentry
      SENTRY_DSN         = var.sentry_dsn
      SENTRY_ENVIRONMENT = var.sentry_environment
      # New Relic APM
      NEW_RELIC_LAMBDA_HANDLER               = "handler.lambda_handler"
      NEW_RELIC_ACCOUNT_ID                   = var.newrelic_account_id
      NEW_RELIC_TRUSTED_ACCOUNT_KEY          = var.newrelic_account_id
      NEW_RELIC_LICENSE_KEY_SECRET           = "f1-mlops/newrelic-license-key"
      NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS = "true"
    }
  }
}

# Pre-race health check Lambda — run 30 min before lights out
resource "aws_lambda_function" "prerace_check" {
  function_name    = "${var.project}-prerace-check"
  filename         = data.archive_file.prerace_check.output_path
  source_code_hash = data.archive_file.prerace_check.output_base64sha256
  handler          = "newrelic_lambda_wrapper.handler.handler"
  runtime          = "python3.12"
  memory_size      = 256
  timeout          = 60
  role             = var.lambda_role_arn
  layers           = [var.newrelic_layer_arn]

  environment {
    variables = {
      S3_BUCKET             = var.s3_bucket
      SAGEMAKER_ENDPOINT    = var.sagemaker_endpoint
      AWS_REGION_NAME       = var.aws_region
      PREWARM_FUNCTION_NAME = "${var.project}-prewarm"
      EVENTBRIDGE_RULE_NAME = "${var.project}-live-poller"
      # Sentry
      SENTRY_DSN         = var.sentry_dsn
      SENTRY_ENVIRONMENT = var.sentry_environment
      # New Relic APM
      NEW_RELIC_LAMBDA_HANDLER               = "handler.lambda_handler"
      NEW_RELIC_ACCOUNT_ID                   = var.newrelic_account_id
      NEW_RELIC_TRUSTED_ACCOUNT_KEY          = var.newrelic_account_id
      NEW_RELIC_LICENSE_KEY_SECRET           = "f1-mlops/newrelic-license-key"
      NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS = "true"
    }
  }

  tracing_config { mode = "Active" }
}

resource "aws_cloudwatch_log_group" "prerace_check" {
  name              = "/aws/lambda/${aws_lambda_function.prerace_check.function_name}"
  retention_in_days = 14
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
