{
  "Comment": "F1 MLOps Pipeline: S3 new data → Glue ETL → SageMaker Training → Endpoint Update",
  "StartAt": "ValidateInput",
  "States": {
    "ValidateInput": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${aws_region}:${account_id}:function:${project}-rest-handler",
        "Payload.$": "$"
      },
      "ResultPath": "$.validation",
      "Next": "StartGlueETL",
      "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "PipelineFailed"}]
    },
    "StartGlueETL": {
      "Type": "Task",
      "Resource": "arn:aws:states:::glue:startJobRun.sync",
      "Parameters": {
        "JobName": "${project}-feature-engineering",
        "Arguments": {
          "--S3_BUCKET": "${s3_bucket}",
          "--INPUT_PREFIX.$": "$.input_prefix",
          "--OUTPUT_PREFIX": "processed/"
        }
      },
      "ResultPath": "$.glue_result",
      "Next": "WaitForGlue",
      "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "PipelineFailed"}]
    },
    "WaitForGlue": {
      "Type": "Wait",
      "Seconds": 30,
      "Next": "StartSageMakerPipeline"
    },
    "StartSageMakerPipeline": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sagemaker:startPipelineExecution.sync",
      "Parameters": {
        "PipelineName": "${project}-training-pipeline",
        "PipelineExecutionDisplayName": "auto-triggered",
        "PipelineParameters": [
          {"Name": "InputDataUrl", "Value.$": "States.Format('s3://${s3_bucket}/processed/{}', $.session_key)"},
          {"Name": "ModelOutputUrl", "Value": "s3://${s3_bucket}/models/"}
        ]
      },
      "ResultPath": "$.pipeline_result",
      "Next": "CheckModelApproval",
      "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "PipelineFailed"}]
    },
    "CheckModelApproval": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.pipeline_result.PipelineExecutionStatus",
          "StringEquals": "Succeeded",
          "Next": "UpdateEndpoint"
        }
      ],
      "Default": "PipelineFailed"
    },
    "UpdateEndpoint": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${aws_region}:${account_id}:function:${project}-prewarm",
        "Payload": {
          "action": "update_endpoint",
          "model_package.$": "$.pipeline_result.PipelineExecutionArn"
        }
      },
      "ResultPath": "$.endpoint_update",
      "Next": "NotifySuccess",
      "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "PipelineFailed"}]
    },
    "NotifySuccess": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "Parameters": {
        "TopicArn": "arn:aws:sns:${aws_region}:${account_id}:${project}-alerts",
        "Subject": "F1 MLOps Pipeline Succeeded",
        "Message.$": "States.Format('Pipeline completed. Session: {}. Model updated and endpoint ready.', $.session_key)"
      },
      "Next": "PipelineSucceeded"
    },
    "PipelineSucceeded": {
      "Type": "Succeed"
    },
    "PipelineFailed": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "Parameters": {
        "TopicArn": "arn:aws:sns:${aws_region}:${account_id}:${project}-alerts",
        "Subject": "F1 MLOps Pipeline FAILED",
        "Message.$": "States.Format('Pipeline failed at state: {}. Error: {}', $$.State.Name, $.error)"
      },
      "Next": "Fail"
    },
    "Fail": {
      "Type": "Fail",
      "Error": "PipelineError",
      "Cause": "One or more pipeline steps failed"
    }
  }
}
