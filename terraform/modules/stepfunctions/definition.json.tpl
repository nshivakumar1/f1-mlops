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
      "Next": "StartSageMakerPipeline",
      "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "PipelineFailed"}]
    },
    "StartSageMakerPipeline": {
      "Type": "Task",
      "Resource": "arn:aws:states:::aws-sdk:sagemaker:startPipelineExecution",
      "Parameters": {
        "PipelineName": "${project}-training-pipeline",
        "PipelineExecutionDisplayName": "auto-triggered",
        "ClientRequestToken.$": "$$.Execution.Name",
        "PipelineParameters": [
          {"Name": "InputDataUrl", "Value.$": "States.Format('s3://${s3_bucket}/processed/{}', $.session_key)"},
          {"Name": "ModelOutputUrl", "Value": "s3://${s3_bucket}/models/"}
        ]
      },
      "ResultPath": "$.pipeline_start",
      "Next": "WaitForPipeline",
      "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "PipelineFailed"}]
    },
    "WaitForPipeline": {
      "Type": "Wait",
      "Seconds": 120,
      "Next": "CheckPipelineStatus"
    },
    "CheckPipelineStatus": {
      "Type": "Task",
      "Resource": "arn:aws:states:::aws-sdk:sagemaker:describePipelineExecution",
      "Parameters": {
        "PipelineExecutionArn.$": "$.pipeline_start.PipelineExecutionArn"
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
        },
        {
          "Variable": "$.pipeline_result.PipelineExecutionStatus",
          "StringEquals": "Executing",
          "Next": "WaitForPipeline"
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
        "Message": "One or more pipeline steps failed. Check CloudWatch logs for details."
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
