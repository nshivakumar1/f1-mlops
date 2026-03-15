resource "aws_api_gateway_rest_api" "f1" {
  name        = "${var.project}-api"
  description = "F1 Race Prediction REST API"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

# /predict resource
resource "aws_api_gateway_resource" "predict" {
  rest_api_id = aws_api_gateway_rest_api.f1.id
  parent_id   = aws_api_gateway_rest_api.f1.root_resource_id
  path_part   = "predict"
}

# /predict/pitstop — POST
resource "aws_api_gateway_resource" "pitstop" {
  rest_api_id = aws_api_gateway_rest_api.f1.id
  parent_id   = aws_api_gateway_resource.predict.id
  path_part   = "pitstop"
}

resource "aws_api_gateway_method" "pitstop_post" {
  rest_api_id      = aws_api_gateway_rest_api.f1.id
  resource_id      = aws_api_gateway_resource.pitstop.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "pitstop_post" {
  rest_api_id             = aws_api_gateway_rest_api.f1.id
  resource_id             = aws_api_gateway_resource.pitstop.id
  http_method             = aws_api_gateway_method.pitstop_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = "arn:aws:apigateway:${var.aws_region}:lambda:path/2015-03-31/functions/${var.rest_handler_arn}/invocations"
}

# /predict/positions/{session_key} — GET
resource "aws_api_gateway_resource" "positions" {
  rest_api_id = aws_api_gateway_rest_api.f1.id
  parent_id   = aws_api_gateway_resource.predict.id
  path_part   = "positions"
}

resource "aws_api_gateway_resource" "positions_session" {
  rest_api_id = aws_api_gateway_rest_api.f1.id
  parent_id   = aws_api_gateway_resource.positions.id
  path_part   = "{session_key}"
}

resource "aws_api_gateway_method" "positions_get" {
  rest_api_id      = aws_api_gateway_rest_api.f1.id
  resource_id      = aws_api_gateway_resource.positions_session.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = false
}

resource "aws_api_gateway_integration" "positions_get" {
  rest_api_id             = aws_api_gateway_rest_api.f1.id
  resource_id             = aws_api_gateway_resource.positions_session.id
  http_method             = aws_api_gateway_method.positions_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = "arn:aws:apigateway:${var.aws_region}:lambda:path/2015-03-31/functions/${var.rest_handler_arn}/invocations"
}

# /sessions — GET (public, no API key)
resource "aws_api_gateway_resource" "sessions" {
  rest_api_id = aws_api_gateway_rest_api.f1.id
  parent_id   = aws_api_gateway_rest_api.f1.root_resource_id
  path_part   = "sessions"
}

resource "aws_api_gateway_method" "sessions_get" {
  rest_api_id      = aws_api_gateway_rest_api.f1.id
  resource_id      = aws_api_gateway_resource.sessions.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = false
}

resource "aws_api_gateway_integration" "sessions_get" {
  rest_api_id             = aws_api_gateway_rest_api.f1.id
  resource_id             = aws_api_gateway_resource.sessions.id
  http_method             = aws_api_gateway_method.sessions_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = "arn:aws:apigateway:${var.aws_region}:lambda:path/2015-03-31/functions/${var.rest_handler_arn}/invocations"
}

# /sessions/latest — GET (public, no API key)
resource "aws_api_gateway_resource" "sessions_latest" {
  rest_api_id = aws_api_gateway_rest_api.f1.id
  parent_id   = aws_api_gateway_resource.sessions.id
  path_part   = "latest"
}

resource "aws_api_gateway_method" "sessions_latest_get" {
  rest_api_id      = aws_api_gateway_rest_api.f1.id
  resource_id      = aws_api_gateway_resource.sessions_latest.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = false
}

resource "aws_api_gateway_integration" "sessions_latest_get" {
  rest_api_id             = aws_api_gateway_rest_api.f1.id
  resource_id             = aws_api_gateway_resource.sessions_latest.id
  http_method             = aws_api_gateway_method.sessions_latest_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = "arn:aws:apigateway:${var.aws_region}:lambda:path/2015-03-31/functions/${var.rest_handler_arn}/invocations"
}

# /positions/latest — GET (live driver positions proxied from OpenF1)
resource "aws_api_gateway_resource" "positions_latest" {
  rest_api_id = aws_api_gateway_rest_api.f1.id
  parent_id   = aws_api_gateway_rest_api.f1.root_resource_id
  path_part   = "positions"
}

resource "aws_api_gateway_resource" "positions_latest_path" {
  rest_api_id = aws_api_gateway_rest_api.f1.id
  parent_id   = aws_api_gateway_resource.positions_latest.id
  path_part   = "latest"
}

resource "aws_api_gateway_method" "positions_latest_get" {
  rest_api_id      = aws_api_gateway_rest_api.f1.id
  resource_id      = aws_api_gateway_resource.positions_latest_path.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = false
}

resource "aws_api_gateway_integration" "positions_latest_get" {
  rest_api_id             = aws_api_gateway_rest_api.f1.id
  resource_id             = aws_api_gateway_resource.positions_latest_path.id
  http_method             = aws_api_gateway_method.positions_latest_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = "arn:aws:apigateway:${var.aws_region}:lambda:path/2015-03-31/functions/${var.rest_handler_arn}/invocations"
}

# /track/{circuit_key} — GET (static circuit outline from Multiviewer)
resource "aws_api_gateway_resource" "track" {
  rest_api_id = aws_api_gateway_rest_api.f1.id
  parent_id   = aws_api_gateway_rest_api.f1.root_resource_id
  path_part   = "track"
}

resource "aws_api_gateway_resource" "track_circuit" {
  rest_api_id = aws_api_gateway_rest_api.f1.id
  parent_id   = aws_api_gateway_resource.track.id
  path_part   = "{circuit_key}"
}

resource "aws_api_gateway_method" "track_get" {
  rest_api_id      = aws_api_gateway_rest_api.f1.id
  resource_id      = aws_api_gateway_resource.track_circuit.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = false
}

resource "aws_api_gateway_integration" "track_get" {
  rest_api_id             = aws_api_gateway_rest_api.f1.id
  resource_id             = aws_api_gateway_resource.track_circuit.id
  http_method             = aws_api_gateway_method.track_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = "arn:aws:apigateway:${var.aws_region}:lambda:path/2015-03-31/functions/${var.rest_handler_arn}/invocations"
}

# Deployment + stage with 5-min cache
resource "aws_api_gateway_deployment" "f1" {
  rest_api_id = aws_api_gateway_rest_api.f1.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_integration.pitstop_post,
      aws_api_gateway_integration.positions_get,
      aws_api_gateway_integration.sessions_get,
      aws_api_gateway_integration.sessions_latest_get,
      aws_api_gateway_integration.positions_latest_get,
      aws_api_gateway_integration.track_get,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.pitstop_post,
    aws_api_gateway_integration.positions_get,
    aws_api_gateway_integration.sessions_get,
    aws_api_gateway_integration.sessions_latest_get,
    aws_api_gateway_integration.positions_latest_get,
    aws_api_gateway_integration.track_get,
  ]
}

resource "aws_api_gateway_stage" "v1" {
  rest_api_id   = aws_api_gateway_rest_api.f1.id
  deployment_id = aws_api_gateway_deployment.f1.id
  stage_name    = "v1"

  cache_cluster_enabled = true
  cache_cluster_size    = "0.5"

  xray_tracing_enabled = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gw.arn
    format          = "$context.requestId $context.status $context.responseLength $context.integrationLatency"
  }
}

resource "aws_cloudwatch_log_group" "api_gw" {
  name              = "/aws/apigateway/${var.project}"
  retention_in_days = 14
}

# API Key
resource "aws_api_gateway_api_key" "f1" {
  name    = "${var.project}-api-key"
  enabled = true
}

resource "aws_api_gateway_usage_plan" "f1" {
  name = "${var.project}-usage-plan"
  api_stages {
    api_id = aws_api_gateway_rest_api.f1.id
    stage  = aws_api_gateway_stage.v1.stage_name
  }
  throttle_settings {
    rate_limit  = 100
    burst_limit = 200
  }
}

resource "aws_api_gateway_usage_plan_key" "f1" {
  key_id        = aws_api_gateway_api_key.f1.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.f1.id
}

# Lambda permission for API Gateway
resource "aws_lambda_permission" "api_gw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.rest_handler_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.f1.execution_arn}/*/*"
}
