output "endpoint_name" { value = "${var.project}-pitstop-endpoint" }
output "feature_group_name" { value = aws_sagemaker_feature_group.f1_features.feature_group_name }
