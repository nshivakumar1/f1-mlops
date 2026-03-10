output "enrichment_function_arn"      { value = aws_lambda_function.enrichment.arn }
output "enrichment_function_name"     { value = aws_lambda_function.enrichment.function_name }
output "rest_handler_function_arn"    { value = aws_lambda_function.rest_handler.arn }
output "rest_handler_function_name"   { value = aws_lambda_function.rest_handler.function_name }
output "prewarm_function_arn"         { value = aws_lambda_function.prewarm.arn }
output "slack_notifier_function_arn"  { value = aws_lambda_function.slack_notifier.arn }
