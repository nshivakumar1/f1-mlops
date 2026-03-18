output "firehose_stream_name" {
  value = aws_kinesis_firehose_delivery_stream.newrelic.name
}

output "metric_stream_arn" {
  value = aws_cloudwatch_metric_stream.newrelic.arn
}
