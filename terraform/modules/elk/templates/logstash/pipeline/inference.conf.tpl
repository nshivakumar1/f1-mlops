# ── F1 Inference Logs Pipeline ─────────────────────────────────────────────────
# Sources:
#   1. HTTP port 8080 — Lambda real-time push (each driver prediction batch)
#   2. S3 input      — catches up on any missed files every 60s
# Output: Elasticsearch index f1-inference-YYYY.MM.dd

input {
  # Real-time: Lambda pushes immediately after each prediction cycle
  http {
    port  => 8080
    codec => json
    type  => "live"
    additional_codecs => { "application/json" => "json" }
  }

  # Catch-up: poll S3 for any files written directly (sessions before Lambda used HTTP)
  s3 {
    bucket       => "${s3_bucket}"
    region       => "${aws_region}"
    prefix       => "logs/inference/"
    sincedb_path => "/usr/share/logstash/data/.sincedb_inference"
    interval     => 60
    codec        => "json"
    type         => "s3_catchup"
  }
}

filter {
  # Both sources contain a "predictions" array — split into one event per driver
  if [predictions] {
    split {
      field => "predictions"
    }

    mutate {
      rename => {
        "[predictions][driver_number]"                     => "driver_number"
        "[predictions][driver_name]"                       => "driver_name"
        "[predictions][team]"                              => "team"
        "[predictions][tyre_compound]"                     => "tyre_compound"
        "[predictions][prediction][pitstop_probability]"   => "pitstop_probability"
        "[predictions][prediction][confidence]"            => "confidence"
        "[predictions][prediction][recommendation]"        => "recommendation"
      }
      remove_field => ["predictions", "errors", "@version", "headers"]
    }

    # Map tyre_age from features[0]
    ruby {
      code => "
        feats = event.get('[predictions][features]') || event.get('features')
        if feats && feats.is_a?(Array) && feats.length >= 7
          event.set('tyre_age',         feats[0])
          event.set('stint_number',     feats[1])
          event.set('gap_to_leader',    feats[2])
          event.set('air_temperature',  feats[3])
          event.set('track_temperature',feats[4])
          event.set('rainfall',         feats[5])
          event.set('sector_delta',     feats[6])
        end
        event.remove('[predictions][features]')
        event.remove('features')
      "
    }
  }

  # Ensure @timestamp is set from our payload timestamp
  if [timestamp] {
    date {
      match    => ["timestamp", "ISO8601"]
      timezone => "UTC"
    }
  }

  # Tag high-probability alerts
  if [pitstop_probability] and [pitstop_probability] >= 0.70 {
    mutate { add_tag => ["pit_alert"] }
  }
}

output {
  elasticsearch {
    hosts => ["http://elasticsearch:9200"]
    index => "f1-inference-%{+YYYY.MM.dd}"
  }
}
