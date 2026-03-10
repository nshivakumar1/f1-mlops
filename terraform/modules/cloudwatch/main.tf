# SNS Topic — all F1 alerts converge here
resource "aws_sns_topic" "f1_alerts" {
  name = "${var.project}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.f1_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Alarm 1: Lambda error rate > 2% in 5 min (P2)
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.project}-lambda-error-rate"
  alarm_description   = "Lambda error rate > 2% in 5 min window"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = var.lambda_function }
  alarm_actions       = [aws_sns_topic.f1_alerts.arn]
  ok_actions          = [aws_sns_topic.f1_alerts.arn]
}

# Alarm 2: SageMaker cold start latency > 3s (P3)
resource "aws_cloudwatch_metric_alarm" "sagemaker_latency" {
  alarm_name          = "${var.project}-sagemaker-cold-start"
  alarm_description   = "SageMaker serverless cold start > 3000ms"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ModelLatency"
  namespace           = "AWS/SageMaker"
  period              = 60
  statistic           = "p99"
  threshold           = 3000
  treat_missing_data  = "notBreaching"
  dimensions          = { EndpointName = var.sagemaker_endpoint, VariantName = "dry-race-v1" }
  alarm_actions       = [aws_sns_topic.f1_alerts.arn]
}

# Alarm 3: Firehose delivery failure (P2)
resource "aws_cloudwatch_metric_alarm" "firehose_failure" {
  alarm_name          = "${var.project}-firehose-failure"
  alarm_description   = "Kinesis Firehose delivery failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "DeliveryToOpenSearch.Success"
  namespace           = "AWS/Firehose"
  period              = 300
  statistic           = "Average"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions          = { DeliveryStreamName = var.firehose_stream }
  alarm_actions       = [aws_sns_topic.f1_alerts.arn]
}

# Alarm 4: Prediction confidence mean < 0.65 (P1 — triggers retrain)
resource "aws_cloudwatch_metric_alarm" "model_drift" {
  alarm_name          = "${var.project}-model-drift"
  alarm_description   = "Pitstop prediction confidence < 0.65 — retrain needed"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 10
  metric_name         = "PredictionConfidence"
  namespace           = "F1MLOps/Models"
  period              = 60
  statistic           = "Average"
  threshold           = 0.65
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.f1_alerts.arn, var.stepfunctions_arn]
}

# Alarm 5: Billing threshold $10 (CRITICAL)
resource "aws_cloudwatch_metric_alarm" "billing" {
  alarm_name          = "${var.project}-billing-cap"
  alarm_description   = "AWS spend exceeds $10 — CRITICAL cost control"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "EstimatedCharges"
  namespace           = "AWS/Billing"
  period              = 86400
  statistic           = "Maximum"
  threshold           = 10
  treat_missing_data  = "notBreaching"
  dimensions          = { Currency = "USD" }
  alarm_actions       = [aws_sns_topic.f1_alerts.arn]
}

# CloudWatch Dashboard
resource "aws_cloudwatch_dashboard" "f1" {
  dashboard_name = "${var.project}-overview"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          title  = "Lambda Invocations & Errors"
          period = 60
          stat   = "Sum"
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", var.lambda_function],
            ["AWS/Lambda", "Errors", "FunctionName", var.lambda_function]
          ]
        }
      },
      {
        type = "metric"
        properties = {
          title  = "SageMaker Latency (p99)"
          period = 60
          stat   = "p99"
          metrics = [
            ["AWS/SageMaker", "ModelLatency", "EndpointName", var.sagemaker_endpoint, "VariantName", "dry-race-v1"]
          ]
        }
      },
      {
        type = "metric"
        properties = {
          title  = "Prediction Confidence (Rolling)"
          period = 60
          stat   = "Average"
          metrics = [
            ["F1MLOps/Models", "PredictionConfidence"]
          ]
        }
      },
      {
        type = "metric"
        properties = {
          title  = "AWS Estimated Charges"
          period = 86400
          stat   = "Maximum"
          metrics = [
            ["AWS/Billing", "EstimatedCharges", "Currency", "USD"]
          ]
        }
      }
    ]
  })
}
