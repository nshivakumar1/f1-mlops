# ── CloudWatch Logs → Elasticsearch ────────────────────────────────────────────
# Pulls logs from all 4 Lambda functions + SageMaker endpoint every 60s.
# Parses Lambda REPORT lines for duration/memory, tags ERROR lines separately.

input {
  # ── Lambda: enrichment ──────────────────────────────────────────────────────
  cloudwatch_logs {
    log_group    => "/aws/lambda/${project}-enrichment"
    region       => "${aws_region}"
    interval     => 60
    type         => "lambda_logs"
    add_field    => { "function_name" => "${project}-enrichment" }
  }

  # ── Lambda: rest_handler ────────────────────────────────────────────────────
  cloudwatch_logs {
    log_group    => "/aws/lambda/${project}-rest-handler"
    region       => "${aws_region}"
    interval     => 60
    type         => "lambda_logs"
    add_field    => { "function_name" => "${project}-rest-handler" }
  }

  # ── Lambda: prewarm ─────────────────────────────────────────────────────────
  cloudwatch_logs {
    log_group    => "/aws/lambda/${project}-prewarm"
    region       => "${aws_region}"
    interval     => 60
    type         => "lambda_logs"
    add_field    => { "function_name" => "${project}-prewarm" }
  }

  # ── Lambda: slack_notifier ──────────────────────────────────────────────────
  cloudwatch_logs {
    log_group    => "/aws/lambda/${project}-slack-notifier"
    region       => "${aws_region}"
    interval     => 60
    type         => "lambda_logs"
    add_field    => { "function_name" => "${project}-slack-notifier" }
  }

  # ── SageMaker endpoint logs ──────────────────────────────────────────────────
  cloudwatch_logs {
    log_group    => "/aws/sagemaker/Endpoints/${project}-pitstop-endpoint"
    region       => "${aws_region}"
    interval     => 60
    type         => "sagemaker_logs"
    add_field    => { "service" => "sagemaker" }
  }
}

filter {
  # ── Lambda REPORT lines ──────────────────────────────────────────────────────
  # Format: REPORT RequestId: xxx Duration: 1234.56 ms  Billed Duration: 1235 ms
  #         Memory Size: 256 MB  Max Memory Used: 89 MB  Init Duration: 432.1 ms
  if [type] == "lambda_logs" and [message] =~ /^REPORT RequestId/ {
    grok {
      match => {
        "message" => "REPORT RequestId: %{DATA:request_id}\s+Duration: %{NUMBER:duration_ms:float} ms\s+Billed Duration: %{NUMBER:billed_duration_ms:float} ms\s+Memory Size: %{NUMBER:memory_size_mb:integer} MB\s+Max Memory Used: %{NUMBER:memory_used_mb:integer} MB%{GREEDYDATA:rest}"
      }
    }
    mutate {
      add_tag    => ["lambda_report"]
      add_field  => { "log_level" => "REPORT" }
    }
    # Parse Init Duration if present (cold start)
    if [rest] =~ /Init Duration/ {
      grok {
        match => { "rest" => "Init Duration: %{NUMBER:init_duration_ms:float} ms" }
      }
      mutate { add_tag => ["cold_start"] }
    }
    mutate { remove_field => ["rest"] }
  }

  # ── Lambda ERROR/WARNING lines ───────────────────────────────────────────────
  else if [type] == "lambda_logs" and [message] =~ /^\[?(ERROR|WARNING|CRITICAL)/ {
    grok {
      match => { "message" => "\[?%{LOGLEVEL:log_level}\]?\s+%{GREEDYDATA:error_message}" }
    }
    mutate { add_tag => ["lambda_error"] }
  }

  # ── Lambda INFO/DEBUG (structured JSON logs) ─────────────────────────────────
  else if [type] == "lambda_logs" and [message] =~ /^\{/ {
    json {
      source => "message"
      target => "parsed"
    }
    mutate {
      add_field => { "log_level" => "INFO" }
      add_tag   => ["structured_log"]
    }
  }

  # ── SageMaker: extract invocation latency from logs ──────────────────────────
  else if [type] == "sagemaker_logs" {
    if [message] =~ /ModelLatency/ {
      grok {
        match => { "message" => "ModelLatency:%{NUMBER:model_latency_us:float}" }
      }
      mutate {
        # Convert microseconds to milliseconds
        add_field => { "log_level" => "METRIC" }
        add_tag   => ["sagemaker_latency"]
      }
      ruby {
        code => "event.set('model_latency_ms', event.get('model_latency_us').to_f / 1000.0)"
      }
    }
  }

  # ── Drop Lambda START/END lines (low value, high volume) ────────────────────
  if [message] =~ /^(START|END) RequestId/ {
    drop {}
  }

  mutate {
    add_field  => { "environment" => "f1-mlops" }
    remove_field => ["@version", "cloudwatch_logs", "log_group", "log_stream"]
  }
}

output {
  elasticsearch {
    hosts => ["http://elasticsearch:9200"]
    index => "f1-lambda-logs-%%{+YYYY.MM.dd}"
  }
}
