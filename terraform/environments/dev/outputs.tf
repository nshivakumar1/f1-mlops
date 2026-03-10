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

output "kibana_url" {
  description = "Self-hosted Kibana URL (ELK on EC2)"
  value       = module.elk.kibana_url
}

output "sns_topic_arn" {
  description = "SNS topic ARN for all F1 alerts"
  value       = module.cloudwatch.sns_topic_arn
}

output "stepfunctions_arn" {
  description = "Step Functions state machine ARN"
  value       = module.stepfunctions.state_machine_arn
}

output "logstash_url" {
  description = "Logstash HTTP input URL for real-time Lambda push"
  value       = module.elk.logstash_url
}

output "elk_instance_id" {
  description = "EC2 instance ID running the ELK stack"
  value       = module.elk.instance_id
}
