output "sns_topic_arn" { value = aws_sns_topic.f1_alerts.arn }
output "sns_topic_name" { value = aws_sns_topic.f1_alerts.name }
output "dashboard_name" { value = aws_cloudwatch_dashboard.f1.dashboard_name }
