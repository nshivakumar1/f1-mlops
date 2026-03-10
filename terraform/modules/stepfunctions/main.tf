resource "aws_sfn_state_machine" "f1_pipeline" {
  name     = "${var.project}-pipeline"
  role_arn = var.role_arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/definition.json.tpl", {
    project    = var.project
    aws_region = var.aws_region
    account_id = var.account_id
    s3_bucket  = var.s3_bucket
  })

  tracing_configuration { enabled = true }

  logging_configuration {
    level                  = "ERROR"
    include_execution_data = true
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
  }
}

resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/states/${var.project}-pipeline"
  retention_in_days = 14
}
