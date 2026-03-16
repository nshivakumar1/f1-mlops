data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "sagemaker_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "firehose_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "stepfunctions_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "eventbridge_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com", "events.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "codepipeline_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codepipeline.amazonaws.com", "codebuild.amazonaws.com"]
    }
  }
}

# Lambda role
resource "aws_iam_role" "lambda" {
  name               = "${var.project}-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_xray" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy" "lambda_custom" {
  name = "${var.project}-lambda-custom"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [var.s3_bucket, "${var.s3_bucket}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["sagemaker:InvokeEndpoint"]
        Resource = "arn:aws:sagemaker:${var.aws_region}:${var.account_id}:endpoint/*"
      },
      {
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = "arn:aws:sns:${var.aws_region}:${var.account_id}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:f1-mlops*"
      },
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData", "cloudwatch:DescribeAlarms", "cloudwatch:SetAlarmState"]
        Resource = "*"
      }
    ]
  })
}

# SageMaker role
resource "aws_iam_role" "sagemaker" {
  name               = "${var.project}-sagemaker-role"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume.json
}

resource "aws_iam_role_policy_attachment" "sagemaker_full" {
  role       = aws_iam_role.sagemaker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

resource "aws_iam_role_policy" "sagemaker_s3" {
  name = "${var.project}-sagemaker-s3"
  role = aws_iam_role.sagemaker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:*"]
      Resource = [var.s3_bucket, "${var.s3_bucket}/*"]
    }]
  })
}

# Kinesis Firehose role
resource "aws_iam_role" "firehose" {
  name               = "${var.project}-firehose-role"
  assume_role_policy = data.aws_iam_policy_document.firehose_assume.json
}

resource "aws_iam_role_policy" "firehose_custom" {
  name = "${var.project}-firehose-custom"
  role = aws_iam_role.firehose.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:AbortMultipartUpload", "s3:GetBucketLocation", "s3:GetObject", "s3:ListBucket", "s3:ListBucketMultipartUploads", "s3:PutObject"]
        Resource = [var.s3_bucket, "${var.s3_bucket}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["es:DescribeElasticsearchDomain", "es:DescribeElasticsearchDomains", "es:DescribeElasticsearchDomainConfig", "es:ESHttpPost", "es:ESHttpPut"]
        Resource = ["arn:aws:es:${var.aws_region}:${var.account_id}:domain/*"]
      }
    ]
  })
}

# Step Functions role
resource "aws_iam_role" "stepfunctions" {
  name               = "${var.project}-stepfunctions-role"
  assume_role_policy = data.aws_iam_policy_document.stepfunctions_assume.json
}

resource "aws_iam_role_policy" "stepfunctions_custom" {
  name = "${var.project}-stepfunctions-custom"
  role = aws_iam_role.stepfunctions.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["sagemaker:CreatePipelineExecution", "sagemaker:StartPipelineExecution", "sagemaker:StopPipelineExecution", "sagemaker:DescribePipelineExecution"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:*"
      },
      {
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = "arn:aws:sns:${var.aws_region}:${var.account_id}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ]
        Resource = "*"
      }
    ]
  })
}

# EventBridge Scheduler role
resource "aws_iam_role" "eventbridge" {
  name               = "${var.project}-eventbridge-role"
  assume_role_policy = data.aws_iam_policy_document.eventbridge_assume.json
}

resource "aws_iam_role_policy" "eventbridge_custom" {
  name = "${var.project}-eventbridge-custom"
  role = aws_iam_role.eventbridge.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:*"
      },
      {
        Effect   = "Allow"
        Action   = ["states:StartExecution"]
        Resource = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:*"
      }
    ]
  })
}

# CodePipeline + CodeBuild role
resource "aws_iam_role" "codepipeline" {
  name               = "${var.project}-codepipeline-role"
  assume_role_policy = data.aws_iam_policy_document.codepipeline_assume.json
}

resource "aws_iam_role_policy_attachment" "codepipeline_admin" {
  role       = aws_iam_role.codepipeline.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
