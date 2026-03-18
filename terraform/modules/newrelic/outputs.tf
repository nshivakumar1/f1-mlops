output "firehose_stream_name" {
  value = aws_kinesis_firehose_delivery_stream.newrelic.name
}

output "metric_stream_arn" {
  value = aws_cloudwatch_metric_stream.newrelic.arn
}

output "newrelic_integration_role_arn" {
  description = "IAM role ARN to paste into NR UI → Infrastructure → AWS → Add AWS account"
  value       = aws_iam_role.newrelic_integration.arn
}
