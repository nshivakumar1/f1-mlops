#!/bin/bash
set -euo pipefail
exec > /var/log/elk-setup.log 2>&1

echo "=== F1 MLOps ELK Setup $(date) ==="

# ── 1. System deps ────────────────────────────────────────────────────────────
apt-get update -y
apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release jq awscli

# ── 2. Docker (official repo) ─────────────────────────────────────────────────
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker

# ── 3. Directory layout ───────────────────────────────────────────────────────
mkdir -p /opt/elk/logstash/{pipeline,data,config}
mkdir -p /opt/elk/elasticsearch/data
chmod -R 777 /opt/elk/elasticsearch /opt/elk/logstash/data

# ── 4. docker-compose.yml ─────────────────────────────────────────────────────
cat > /opt/elk/docker-compose.yml <<'COMPOSE'
version: "3.8"

services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.12.2
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - ES_JAVA_OPTS=-Xms1g -Xmx1g
      - cluster.routing.allocation.disk.watermark.low=90%
      - cluster.routing.allocation.disk.watermark.high=95%
    volumes:
      - /opt/elk/elasticsearch/data:/usr/share/elasticsearch/data
    ports:
      - "9200:9200"
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:9200/_cluster/health | grep -qv '\"status\":\"red\"'"]
      interval: 20s
      timeout: 10s
      retries: 10
    restart: unless-stopped

  kibana:
    image: docker.elastic.co/kibana/kibana:8.12.2
    environment:
      - ELASTICSEARCH_HOSTS=http://elasticsearch:9200
      - LOGGING_QUIET=true
    ports:
      - "5601:5601"
    depends_on:
      elasticsearch:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:5601/api/status | grep -q '\"overall\"'"]
      interval: 30s
      timeout: 15s
      retries: 15
    restart: unless-stopped

  logstash:
    image: docker.elastic.co/logstash/logstash:8.12.2
    environment:
      - LS_JAVA_OPTS=-Xms512m -Xmx512m
      - AWS_DEFAULT_REGION=${aws_region}
      - PIPELINE_WORKERS=2
    volumes:
      - /opt/elk/logstash/pipeline:/usr/share/logstash/pipeline
      - /opt/elk/logstash/data:/usr/share/logstash/data
      - /opt/elk/logstash/config/logstash.yml:/usr/share/logstash/config/logstash.yml
    ports:
      - "8080:8080"
    depends_on:
      elasticsearch:
        condition: service_healthy
    restart: unless-stopped
COMPOSE

# ── 5. Logstash global config ─────────────────────────────────────────────────
cat > /opt/elk/logstash/config/logstash.yml <<'LSYML'
http.host: "0.0.0.0"
xpack.monitoring.enabled: false
pipeline.ecs_compatibility: disabled
LSYML

# ── 6. Logstash inference pipeline ───────────────────────────────────────────
cat > /opt/elk/logstash/pipeline/inference.conf <<CONF
input {
  http {
    port  => 8080
    codec => json
    type  => "live"
    additional_codecs => { "application/json" => "json" }
  }

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
  if [predictions] {
    split { field => "predictions" }

    mutate {
      rename => {
        "[predictions][driver_number]"                   => "driver_number"
        "[predictions][driver_name]"                     => "driver_name"
        "[predictions][team]"                            => "team"
        "[predictions][tyre_compound]"                   => "tyre_compound"
        "[predictions][prediction][pitstop_probability]" => "pitstop_probability"
        "[predictions][prediction][confidence]"          => "confidence"
        "[predictions][prediction][recommendation]"      => "recommendation"
      }
      remove_field => ["errors", "@version", "headers"]
    }

    ruby {
      code => "
        feats = event.get('[predictions][features]')
        if feats.is_a?(Array) && feats.length >= 7
          event.set('tyre_age',          feats[0])
          event.set('stint_number',      feats[1])
          event.set('gap_to_leader',     feats[2])
          event.set('air_temperature',   feats[3])
          event.set('track_temperature', feats[4])
          event.set('rainfall',          feats[5])
          event.set('sector_delta',      feats[6])
        end
        event.remove('[predictions][features]')
        event.remove('predictions')
      "
    }
  }

  if [timestamp] {
    date { match => ["timestamp", "ISO8601"] timezone => "UTC" }
  }

  if [pitstop_probability] {
    ruby {
      code => "
        p = event.get('pitstop_probability').to_f
        event.set('risk_band', p >= 0.70 ? 'HIGH' : (p >= 0.40 ? 'MEDIUM' : 'LOW'))
      "
    }
  }
}

output {
  elasticsearch {
    hosts => ["http://elasticsearch:9200"]
    index => "f1-inference-%%{+YYYY.MM.dd}"
  }
}
CONF

# ── 7. Logstash training pipeline ─────────────────────────────────────────────
cat > /opt/elk/logstash/pipeline/training.conf <<CONF
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
    add_field    => { "log_type" => "training" }
    remove_field => ["@version"]
  }

  if [approved] == true  { mutate { add_tag => ["model_approved"] } }
  if [approved] == false { mutate { add_tag => ["model_rejected"]  } }

  if [deployed_at] {
    date { match => ["deployed_at", "ISO8601"] timezone => "UTC" }
  }
}

output {
  elasticsearch {
    hosts => ["http://elasticsearch:9200"]
    index => "f1-training-%%{+YYYY.MM.dd}"
  }
}
CONF

# ── 8. Start ELK ──────────────────────────────────────────────────────────────
cd /opt/elk
docker compose up -d
echo "ELK stack started — waiting for services..."

# ── 9. Wait for Elasticsearch ─────────────────────────────────────────────────
for i in $(seq 1 40); do
  if curl -sf http://localhost:9200/_cluster/health | grep -qv '"status":"red"'; then
    echo "Elasticsearch ready after $((i*10))s"
    break
  fi
  echo "  waiting for ES... ($i/40)"
  sleep 10
done

# ── 10. Wait for Kibana ───────────────────────────────────────────────────────
for i in $(seq 1 30); do
  if curl -sf http://localhost:5601/api/status 2>/dev/null | grep -q '"overall"'; then
    echo "Kibana ready after $((i*10))s"
    break
  fi
  echo "  waiting for Kibana... ($i/30)"
  sleep 10
done
sleep 5  # extra buffer for API to be fully available

# ── 11. Create Elasticsearch index templates ──────────────────────────────────
curl -s -X PUT http://localhost:9200/_index_template/f1-inference \
  -H "Content-Type: application/json" -d '{
  "index_patterns": ["f1-inference-*"],
  "template": {
    "mappings": {
      "properties": {
        "@timestamp":         { "type": "date" },
        "driver_number":      { "type": "integer" },
        "driver_name":        { "type": "keyword" },
        "team":               { "type": "keyword" },
        "tyre_compound":      { "type": "keyword" },
        "recommendation":     { "type": "keyword" },
        "risk_band":          { "type": "keyword" },
        "pitstop_probability":{ "type": "float" },
        "confidence":         { "type": "float" },
        "tyre_age":           { "type": "float" },
        "stint_number":       { "type": "integer" },
        "gap_to_leader":      { "type": "float" },
        "air_temperature":    { "type": "float" },
        "track_temperature":  { "type": "float" },
        "rainfall":           { "type": "integer" },
        "sector_delta":       { "type": "float" },
        "session_key":        { "type": "long" },
        "safety_car_active":  { "type": "boolean" }
      }
    }
  }
}' && echo "  f1-inference template OK"

curl -s -X PUT http://localhost:9200/_index_template/f1-training \
  -H "Content-Type: application/json" -d '{
  "index_patterns": ["f1-training-*"],
  "template": {
    "mappings": {
      "properties": {
        "@timestamp": { "type": "date" },
        "auc":        { "type": "float" },
        "threshold":  { "type": "float" },
        "approved":   { "type": "boolean" },
        "model_uri":  { "type": "keyword" },
        "endpoint":   { "type": "keyword" }
      }
    }
  }
}' && echo "  f1-training template OK"

# ── 12. Kibana index patterns ─────────────────────────────────────────────────
KIBANA="http://localhost:5601"

create_index_pattern() {
  local id="$1" title="$2"
  curl -s -X POST "$KIBANA/api/saved_objects/index-pattern/$id" \
    -H "Content-Type: application/json" -H "kbn-xsrf: true" \
    -d "{\"attributes\":{\"title\":\"$title\",\"timeFieldName\":\"@timestamp\"}}" \
    | grep -o '"id":"[^"]*"' | head -1
}

create_index_pattern "f1-inference-star" "f1-inference-*" && echo "  index-pattern f1-inference-* OK"
create_index_pattern "f1-training-star"  "f1-training-*"  && echo "  index-pattern f1-training-* OK"

# ── 13. Kibana dashboards ─────────────────────────────────────────────────────
create_dashboard() {
  local id="$1" title="$2" desc="$3"
  curl -s -X POST "$KIBANA/api/saved_objects/dashboard/$id" \
    -H "Content-Type: application/json" -H "kbn-xsrf: true" \
    -d "{\"attributes\":{\"title\":\"$title\",\"description\":\"$desc\",\"panelsJSON\":\"[]\",\"optionsJSON\":\"{\\\"useMargins\\\":true}\",\"timeRestore\":false,\"kibanaSavedObjectMeta\":{\"searchSourceJSON\":\"{\\\"query\\\":{\\\"query\\\":\\\"\\\",\\\"language\\\":\\\"kuery\\\"},\\\"filter\\\":[]}\"}}}" \
    | grep -o '"id":"[^"]*"' | head -1
}

create_dashboard "f1-race-predictions" "F1 Race Predictions" \
  "Live pitstop probabilities per driver, tyre age, risk band" && echo "  dashboard Race Predictions OK"

create_dashboard "f1-api-health" "F1 API Health" \
  "Endpoint latency, confidence distribution, error rates" && echo "  dashboard API Health OK"

create_dashboard "f1-model-drift" "F1 Model Drift" \
  "AUC trends over training runs, confidence drift detection" && echo "  dashboard Model Drift OK"

# ── 14. Seed existing S3 data into Elasticsearch ──────────────────────────────
echo "Logstash will ingest existing S3 data in the next polling cycle (60s)."

echo "=== ELK setup complete $(date) ==="
echo "Kibana: http://$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4):5601"
echo "Logstash HTTP: http://$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4):8080"
