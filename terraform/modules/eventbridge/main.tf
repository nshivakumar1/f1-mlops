# Rule 1: Poll OpenF1 every 60s during live sessions (manually enabled/disabled)
resource "aws_cloudwatch_event_rule" "live_poller" {
  name                = "${var.project}-live-poller"
  description         = "Fires enrichment Lambda every 60s during live F1 sessions"
  schedule_expression = "rate(1 minute)"
  state               = "DISABLED" # Enabled manually before each session
}

resource "aws_cloudwatch_event_target" "live_poller" {
  rule      = aws_cloudwatch_event_rule.live_poller.name
  target_id = "EnrichmentLambda"
  arn       = var.enrichment_lambda
}

resource "aws_lambda_permission" "eventbridge_enrichment" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.enrichment_lambda
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.live_poller.arn
}

# Rule 2: S3 new data triggers Step Functions pipeline
resource "aws_cloudwatch_event_rule" "pipeline_trigger" {
  name        = "${var.project}-pipeline-trigger"
  description = "Triggers Step Functions when new race data lands in S3"
  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [var.s3_bucket] }
      object = { key = [{ prefix = "raw/" }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "pipeline_trigger" {
  rule      = aws_cloudwatch_event_rule.pipeline_trigger.name
  target_id = "StepFunctions"
  arn       = var.stepfunctions_arn
  role_arn  = var.pipeline_role_arn
}

# SageMaker Pipeline failure → Chatbot
resource "aws_cloudwatch_event_rule" "sagemaker_pipeline_failure" {
  name        = "${var.project}-sm-pipeline-failure"
  description = "Catch SageMaker Pipeline failures"
  event_pattern = jsonencode({
    source      = ["aws.sagemaker"]
    detail-type = ["SageMaker Model Building Pipeline Execution Status Change"]
    detail      = { currentPipelineExecutionStatus = ["Failed", "Stopped"] }
  })
}

# Glue ETL failure
resource "aws_cloudwatch_event_rule" "glue_failure" {
  name        = "${var.project}-glue-failure"
  description = "Catch Glue ETL job failures"
  event_pattern = jsonencode({
    source      = ["aws.glue"]
    detail-type = ["Glue Job State Change"]
    detail      = { state = ["FAILED"] }
  })
}

# Step Functions failure
resource "aws_cloudwatch_event_rule" "sfn_failure" {
  name        = "${var.project}-sfn-failure"
  description = "Catch Step Functions execution failures"
  event_pattern = jsonencode({
    source      = ["aws.states"]
    detail-type = ["Step Functions Execution Status Change"]
    detail      = { status = ["FAILED", "TIMED_OUT", "ABORTED"] }
  })
}
