output "endpoint_name" { value = aws_sagemaker_endpoint.pitstop.name }
output "endpoint_arn"  { value = aws_sagemaker_endpoint.pitstop.arn }
output "feature_group_name" { value = aws_sagemaker_feature_group.f1_features.feature_group_name }
