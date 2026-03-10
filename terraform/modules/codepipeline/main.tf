resource "aws_codebuild_project" "f1" {
  name          = "${var.project}-build"
  service_role  = var.role_arn
  build_timeout = 30

  artifacts { type = "CODEPIPELINE" }

  environment {
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/standard:7.0"
    type            = "LINUX_CONTAINER"
    privileged_mode = false

    environment_variable {
      name  = "AWS_REGION"
      value = var.aws_region
    }
    environment_variable {
      name  = "TF_VAR_account_id"
      value = var.account_id
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "buildspec.yml"
  }

  logs_config {
    cloudwatch_logs {
      group_name  = "/aws/codebuild/${var.project}"
      stream_name = "build"
    }
  }
}

resource "aws_codepipeline" "f1" {
  name     = "${var.project}-pipeline"
  role_arn = var.role_arn

  artifact_store {
    location = var.s3_bucket
    type     = "S3"
  }

  stage {
    name = "Source"
    action {
      name             = "GitHub"
      category         = "Source"
      owner            = "ThirdParty"
      provider         = "GitHub"
      version          = "1"
      output_artifacts = ["source_output"]
      configuration = {
        Owner      = var.github_owner
        Repo       = var.github_repo
        Branch     = var.github_branch
        OAuthToken = "{{resolve:secretsmanager:f1-mlops/github-token}}"
      }
    }
  }

  stage {
    name = "Test"
    action {
      name            = "RunTests"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts  = ["source_output"]
      output_artifacts = ["test_output"]
      configuration = {
        ProjectName = aws_codebuild_project.f1.name
        EnvironmentVariables = jsonencode([
          { name = "STAGE", value = "test", type = "PLAINTEXT" }
        ])
      }
    }
  }

  stage {
    name = "TerraformPlan"
    action {
      name             = "TerraformPlan"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      input_artifacts  = ["source_output"]
      output_artifacts = ["plan_output"]
      configuration = {
        ProjectName = aws_codebuild_project.f1.name
        EnvironmentVariables = jsonencode([
          { name = "STAGE", value = "plan", type = "PLAINTEXT" }
        ])
      }
    }
  }

  stage {
    name = "Approve"
    action {
      name     = "ManualApproval"
      category = "Approval"
      owner    = "AWS"
      provider = "Manual"
      version  = "1"
      configuration = {
        NotificationArn = "arn:aws:sns:${var.aws_region}:${var.account_id}:${var.project}-alerts"
        CustomData      = "Review terraform plan before applying to dev environment"
      }
    }
  }

  stage {
    name = "Deploy"
    action {
      name            = "TerraformApply"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["plan_output"]
      configuration = {
        ProjectName = aws_codebuild_project.f1.name
        EnvironmentVariables = jsonencode([
          { name = "STAGE", value = "apply", type = "PLAINTEXT" }
        ])
      }
    }
  }
}

resource "aws_cloudwatch_log_group" "codebuild" {
  name              = "/aws/codebuild/${var.project}"
  retention_in_days = 14
}
