output "lambda_role_arn" { value = aws_iam_role.lambda.arn }
output "sagemaker_role_arn" { value = aws_iam_role.sagemaker.arn }
output "firehose_role_arn" { value = aws_iam_role.firehose.arn }
output "stepfunctions_role_arn" { value = aws_iam_role.stepfunctions.arn }
output "eventbridge_role_arn" { value = aws_iam_role.eventbridge.arn }
output "codepipeline_role_arn" { value = aws_iam_role.codepipeline.arn }
