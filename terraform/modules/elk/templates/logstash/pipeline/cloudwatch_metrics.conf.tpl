# ── CloudWatch Metrics → Elasticsearch ─────────────────────────────────────────
# Polls every 60s. Covers: Lambda (4 functions), SageMaker endpoint, EC2 instance.
# Index: f1-cw-metrics-YYYY.MM.dd

input {
  # ── Lambda: enrichment ──────────────────────────────────────────────────────
  cloudwatch {
    region     => "${aws_region}"
    namespace  => "AWS/Lambda"
    metrics    => ["Duration", "Errors", "Invocations", "Throttles", "ConcurrentExecutions"]
    dimensions => { "FunctionName" => "${project}-enrichment" }
    period     => 60
    statistics => ["Average", "Sum", "Maximum", "p99"]
    interval   => 60
    type       => "lambda_metrics"
    add_field  => { "function_name" => "${project}-enrichment" }
  }

  # ── Lambda: rest_handler ────────────────────────────────────────────────────
  cloudwatch {
    region     => "${aws_region}"
    namespace  => "AWS/Lambda"
    metrics    => ["Duration", "Errors", "Invocations", "Throttles"]
    dimensions => { "FunctionName" => "${project}-rest-handler" }
    period     => 60
    statistics => ["Average", "Sum", "Maximum"]
    interval   => 60
    type       => "lambda_metrics"
    add_field  => { "function_name" => "${project}-rest-handler" }
  }

  # ── Lambda: prewarm ─────────────────────────────────────────────────────────
  cloudwatch {
    region     => "${aws_region}"
    namespace  => "AWS/Lambda"
    metrics    => ["Duration", "Errors", "Invocations"]
    dimensions => { "FunctionName" => "${project}-prewarm" }
    period     => 60
    statistics => ["Average", "Sum"]
    interval   => 60
    type       => "lambda_metrics"
    add_field  => { "function_name" => "${project}-prewarm" }
  }

  # ── SageMaker: endpoint metrics ─────────────────────────────────────────────
  cloudwatch {
    region     => "${aws_region}"
    namespace  => "AWS/SageMaker"
    metrics    => ["Invocations", "InvocationLatency", "ModelLatency", "OverheadLatency", "InvocationsPerInstance"]
    dimensions => { "EndpointName" => "${project}-pitstop-endpoint" "VariantName" => "AllTraffic" }
    period     => 60
    statistics => ["Average", "Sum", "Maximum", "p99"]
    interval   => 60
    type       => "sagemaker_metrics"
    add_field  => { "service" => "sagemaker" "endpoint" => "${project}-pitstop-endpoint" }
  }

  # ── SageMaker: Serverless provisioned concurrency / cold starts ─────────────
  cloudwatch {
    region     => "${aws_region}"
    namespace  => "AWS/SageMaker"
    metrics    => ["InvocationModelErrors", "Invocation4XXErrors", "Invocation5XXErrors"]
    dimensions => { "EndpointName" => "${project}-pitstop-endpoint" "VariantName" => "AllTraffic" }
    period     => 60
    statistics => ["Sum"]
    interval   => 60
    type       => "sagemaker_metrics"
    add_field  => { "service" => "sagemaker_errors" "endpoint" => "${project}-pitstop-endpoint" }
  }

  # ── EC2: ELK instance system metrics ────────────────────────────────────────
  cloudwatch {
    region     => "${aws_region}"
    namespace  => "AWS/EC2"
    metrics    => ["CPUUtilization", "NetworkIn", "NetworkOut", "DiskReadOps", "DiskWriteOps"]
    dimensions => { "InstanceId" => "${elk_instance_id}" }
    period     => 60
    statistics => ["Average", "Maximum"]
    interval   => 60
    type       => "ec2_metrics"
    add_field  => { "service" => "ec2" "instance_id" => "${elk_instance_id}" "role" => "elk-stack" }
  }

  # ── F1MLOps custom namespace (published by enrichment Lambda) ───────────────
  cloudwatch {
    region     => "${aws_region}"
    namespace  => "F1MLOps/Models"
    metrics    => ["PredictionConfidence", "HighConfidencePredictions"]
    period     => 60
    statistics => ["Average", "Sum", "Maximum"]
    interval   => 60
    type       => "model_metrics"
    add_field  => { "service" => "f1-model" }
  }
}

filter {
  mutate {
    add_field  => { "environment" => "f1-mlops" }
    remove_field => ["@version"]
  }

  # Normalise SageMaker latency from microseconds to ms for consistent charting
  if [type] == "sagemaker_metrics" and [metric_name] in ["InvocationLatency", "ModelLatency", "OverheadLatency"] {
    ruby {
      code => "
        ['Average', 'Maximum', 'p99'].each do |stat|
          val = event.get(stat)
          event.set(\"#{stat}_ms\", val.to_f / 1000.0) if val
        end
      "
    }
  }

  # Flag Lambda errors
  if [type] == "lambda_metrics" and [metric_name] == "Errors" {
    ruby {
      code => "event.set('has_errors', event.get('Sum').to_f > 0)"
    }
  }
}

output {
  elasticsearch {
    hosts => ["http://elasticsearch:9200"]
    index => "f1-cw-metrics-%%{+YYYY.MM.dd}"
  }
}
