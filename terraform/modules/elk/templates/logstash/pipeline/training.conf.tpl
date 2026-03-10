# ── F1 Training / Pipeline Logs ────────────────────────────────────────────────
# Reads evaluation.json files written by the SageMaker training pipeline
# Output: Elasticsearch index f1-training-YYYY.MM.dd

input {
  s3 {
    bucket       => "${s3_bucket}"
    region       => "${aws_region}"
    prefix       => "models/"
    sincedb_path => "/usr/share/logstash/data/.sincedb_training"
    interval     => 120
    codec        => "json"
    type         => "training"
  }
}

filter {
  mutate {
    add_field  => { "log_type" => "training" }
    remove_field => ["@version", "headers"]
  }

  # Tag models that passed the AUC gate
  if [approved] {
    if [approved] == true {
      mutate { add_tag => ["model_approved"] }
    } else {
      mutate { add_tag => ["model_rejected"] }
    }
  }

  if [deployed_at] {
    date {
      match    => ["deployed_at", "ISO8601"]
      timezone => "UTC"
    }
  }
}

output {
  elasticsearch {
    hosts => ["http://elasticsearch:9200"]
    index => "f1-training-%{+YYYY.MM.dd}"
  }
}
