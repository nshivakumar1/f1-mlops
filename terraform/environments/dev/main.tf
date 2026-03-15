terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  backend "s3" {
    bucket         = "f1-mlops-tfstate-297997106614"
    key            = "dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "f1-mlops-tfstate-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "f1-mlops"
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = "nshivakumar1"
    }
  }
}

module "s3" {
  source      = "../../modules/s3"
  project     = var.project
  environment = var.environment
  account_id  = var.account_id
}

module "iam" {
  source      = "../../modules/iam"
  project     = var.project
  environment = var.environment
  account_id  = var.account_id
  aws_region  = var.aws_region
  s3_bucket   = module.s3.data_bucket_arn
}

module "lambda" {
  source             = "../../modules/lambda"
  project            = var.project
  environment        = var.environment
  aws_region         = var.aws_region
  account_id         = var.account_id
  lambda_role_arn    = module.iam.lambda_role_arn
  s3_bucket          = module.s3.data_bucket_name
  sagemaker_endpoint = module.sagemaker.endpoint_name
  sns_topic_arn      = module.cloudwatch.sns_topic_arn
}

module "eventbridge" {
  source            = "../../modules/eventbridge"
  project           = var.project
  environment       = var.environment
  enrichment_lambda = module.lambda.enrichment_function_arn
  s3_bucket         = module.s3.data_bucket_name
  pipeline_role_arn = module.iam.eventbridge_role_arn
  stepfunctions_arn = module.stepfunctions.state_machine_arn
}

module "sagemaker" {
  source      = "../../modules/sagemaker"
  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region
  account_id  = var.account_id
  role_arn    = module.iam.sagemaker_role_arn
  s3_bucket   = module.s3.data_bucket_name
}

module "api_gateway" {
  source            = "../../modules/api_gateway"
  project           = var.project
  environment       = var.environment
  aws_region        = var.aws_region
  account_id        = var.account_id
  rest_handler_arn  = module.lambda.rest_handler_function_arn
  rest_handler_name = module.lambda.rest_handler_function_name
}

module "elk" {
  source      = "../../modules/elk"
  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region
  s3_bucket   = module.s3.data_bucket_name
}

module "kinesis" {
  source      = "../../modules/kinesis"
  project     = var.project
  environment = var.environment
  role_arn    = module.iam.firehose_role_arn
  s3_bucket   = module.s3.data_bucket_name
}

module "cloudwatch" {
  source             = "../../modules/cloudwatch"
  project            = var.project
  environment        = var.environment
  account_id         = var.account_id
  aws_region         = var.aws_region
  lambda_function    = module.lambda.enrichment_function_name
  sagemaker_endpoint = module.sagemaker.endpoint_name
  firehose_stream    = module.kinesis.firehose_stream_name
  stepfunctions_arn  = module.stepfunctions.state_machine_arn
  alert_email        = var.alert_email
}

module "stepfunctions" {
  source      = "../../modules/stepfunctions"
  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region
  account_id  = var.account_id
  role_arn    = module.iam.stepfunctions_role_arn
  s3_bucket   = module.s3.data_bucket_name
}

module "codepipeline" {
  source                  = "../../modules/codepipeline"
  project                 = var.project
  environment             = var.environment
  aws_region              = var.aws_region
  account_id              = var.account_id
  role_arn                = module.iam.codepipeline_role_arn
  s3_bucket               = module.s3.artifacts_bucket_name
  github_owner            = var.github_owner
  github_repo             = var.github_repo
  github_branch           = var.github_branch
  codestar_connection_arn = "arn:aws:codeconnections:us-east-1:297997106614:connection/6abde493-3ad0-4a50-8f39-44f542d93bd6"
}
