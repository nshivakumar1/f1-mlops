output "s3_data_bucket" {
  value = module.s3.data_bucket_name
}

output "api_gateway_url" {
  description = "Base URL for the F1 prediction REST API"
  value       = module.api_gateway.invoke_url
}

output "sagemaker_endpoint" {
  description = "SageMaker serverless inference endpoint name"
  value       = module.sagemaker.endpoint_name
}

output "opensearch_endpoint" {
  description = "OpenSearch / Kibana endpoint"
  value       = module.opensearch.domain_endpoint
}

output "sns_topic_arn" {
  description = "SNS topic ARN for all F1 alerts"
  value       = module.cloudwatch.sns_topic_arn
}

output "stepfunctions_arn" {
  description = "Step Functions state machine ARN"
  value       = module.stepfunctions.state_machine_arn
}
