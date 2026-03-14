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
chown -R 1000:1000 /opt/elk/logstash

# ── 4. docker-compose.yml ─────────────────────────────────────────────────────
cat > /opt/elk/docker-compose.yml <<'COMPOSE'
version: "3.8"

services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.12.2
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - ES_JAVA_OPTS=-Xms2g -Xmx2g
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
    # Install CloudWatch plugins before startup (cached after first boot)
    command: >
      bash -c "
        bin/logstash-plugin list | grep -q logstash-input-cloudwatch_logs ||
          bin/logstash-plugin install logstash-input-cloudwatch_logs;
        bin/logstash-plugin list | grep -q logstash-input-cloudwatch ||
          bin/logstash-plugin install logstash-input-cloudwatch;
        /usr/local/bin/docker-entrypoint
      "
    environment:
      - LS_JAVA_OPTS=-Xms1g -Xmx1g
      - AWS_DEFAULT_REGION=${aws_region}
      - PIPELINE_WORKERS=4
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

  metricbeat:
    image: docker.elastic.co/beats/metricbeat:8.12.2
    user: root
    command: metricbeat -e -system.hostfs=/hostfs --strict.perms=false
    environment:
      - ELASTICSEARCH_HOST=http://elasticsearch:9200
    volumes:
      - /proc:/hostfs/proc:ro
      - /sys/fs/cgroup:/hostfs/sys/fs/cgroup:ro
      - /:/hostfs:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /opt/elk/metricbeat.yml:/usr/share/metricbeat/metricbeat.yml:ro
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

  if [approved] {
    mutate { add_tag => ["model_approved"] }
  } else {
    mutate { add_tag => ["model_rejected"] }
  }

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

# ── 7b. Metricbeat config ─────────────────────────────────────────────────────
INSTANCE_ID=$(curl -sf http://169.254.169.254/latest/meta-data/instance-id)

cat > /opt/elk/metricbeat.yml <<MBCFG
metricbeat.config.modules:
  path: /usr/share/metricbeat/modules.d/*.yml
  reload.enabled: false

metricbeat.modules:
  - module: system
    period: 30s
    metricsets:
      - cpu
      - memory
      - network
      - diskio
      - load
      - filesystem
    cpu.metrics: [percentages, normalized_percentages]
    filesystem.ignore_types: [tmpfs, devtmpfs, devfs, iso9660, overlay, aufs, squashfs]

  - module: docker
    period: 30s
    hosts: ["unix:///var/run/docker.sock"]
    metricsets:
      - container
      - cpu
      - memory
      - network

processors:
  - add_host_metadata:
      when.not.contains.tags: forwarded
  - add_fields:
      target: ''
      fields:
        service: ec2-elk
        environment: f1-mlops
        instance_id: \${INSTANCE_ID}

output.elasticsearch:
  hosts: ["\${ELASTICSEARCH_HOST}"]
  index: "f1-ec2-metrics-%%{+YYYY.MM.dd}"

setup.template:
  name: f1-ec2-metrics
  pattern: "f1-ec2-metrics-*"
  overwrite: true

setup.kibana:
  host: "http://kibana:5601"

logging.level: warning
MBCFG

# ── 7c. CloudWatch Logs pipeline ─────────────────────────────────────────────
mkdir -p /opt/elk/logstash/pipeline
chown -R 1000:1000 /opt/elk/logstash

cat > /opt/elk/logstash/pipeline/cloudwatch_logs.conf <<CONF
input {
  cloudwatch_logs {
    log_group    => "/aws/lambda/${project}-enrichment"
    region       => "${aws_region}"
    interval     => 60
    type         => "lambda_logs"
    add_field    => { "function_name" => "${project}-enrichment" }
  }
  cloudwatch_logs {
    log_group    => "/aws/lambda/${project}-rest-handler"
    region       => "${aws_region}"
    interval     => 60
    type         => "lambda_logs"
    add_field    => { "function_name" => "${project}-rest-handler" }
  }
  cloudwatch_logs {
    log_group    => "/aws/sagemaker/Endpoints/${project}-pitstop-endpoint"
    region       => "${aws_region}"
    interval     => 60
    type         => "sagemaker_logs"
    add_field    => { "service" => "sagemaker" }
  }
}

filter {
  if [type] == "lambda_logs" and [message] =~ /^REPORT RequestId/ {
    grok {
      match => { "message" => "REPORT RequestId: %%{DATA:request_id}\\s+Duration: %%{NUMBER:duration_ms:float} ms\\s+Billed Duration: %%{NUMBER:billed_duration_ms:float} ms\\s+Memory Size: %%{NUMBER:memory_size_mb:integer} MB\\s+Max Memory Used: %%{NUMBER:memory_used_mb:integer} MB%%{GREEDYDATA:rest}" }
    }
    mutate { add_tag => ["lambda_report"] add_field => { "log_level" => "REPORT" } }
    if [rest] =~ /Init Duration/ {
      grok { match => { "rest" => "Init Duration: %%{NUMBER:init_duration_ms:float} ms" } }
      mutate { add_tag => ["cold_start"] }
    }
    mutate { remove_field => ["rest"] }
  } else if [type] == "lambda_logs" and [message] =~ /\\[?(ERROR|WARNING)/ {
    mutate { add_tag => ["lambda_error"] add_field => { "log_level" => "ERROR" } }
  }
  if [message] =~ /^(START|END) RequestId/ { drop {} }
  mutate { add_field => { "environment" => "f1-mlops" } remove_field => ["@version"] }
}

output {
  elasticsearch {
    hosts => ["http://elasticsearch:9200"]
    index => "f1-lambda-logs-%%{+YYYY.MM.dd}"
  }
}
CONF

# ── 7d. CloudWatch Metrics pipeline ──────────────────────────────────────────
cat > /opt/elk/logstash/pipeline/cloudwatch_metrics.conf <<CONF
input {
  cloudwatch {
    region     => "${aws_region}"
    namespace  => "AWS/Lambda"
    metrics    => ["Duration", "Errors", "Invocations", "Throttles"]
    dimensions => { "FunctionName" => "${project}-enrichment" }
    period     => 60
    statistics => ["Average", "Sum", "Maximum"]
    interval   => 60
    type       => "lambda_metrics"
    add_field  => { "function_name" => "${project}-enrichment" }
  }
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
  cloudwatch {
    region     => "${aws_region}"
    namespace  => "AWS/SageMaker"
    metrics    => ["Invocations", "InvocationLatency", "ModelLatency", "OverheadLatency"]
    dimensions => { "EndpointName" => "${project}-pitstop-endpoint" "VariantName" => "AllTraffic" }
    period     => 60
    statistics => ["Average", "Sum", "Maximum"]
    interval   => 60
    type       => "sagemaker_metrics"
    add_field  => { "service" => "sagemaker" }
  }
  cloudwatch {
    region     => "${aws_region}"
    namespace  => "AWS/EC2"
    metrics    => ["CPUUtilization", "NetworkIn", "NetworkOut"]
    dimensions => { "InstanceId" => "$INSTANCE_ID" }
    period     => 60
    statistics => ["Average", "Maximum"]
    interval   => 60
    type       => "ec2_metrics"
    add_field  => { "service" => "ec2" }
  }
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
  mutate { add_field => { "environment" => "f1-mlops" } remove_field => ["@version"] }
  if [type] == "sagemaker_metrics" {
    ruby { code => "['Average','Maximum'].each{|s| v=event.get(s); event.set(\"#{s}_ms\", v.to_f/1000.0) if v}" }
  }
}

output {
  elasticsearch {
    hosts => ["http://elasticsearch:9200"]
    index => "f1-cw-metrics-%%{+YYYY.MM.dd}"
  }
}
CONF

chown -R 1000:1000 /opt/elk/logstash

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

curl -s -X PUT http://localhost:9200/_index_template/f1-lambda-logs \
  -H "Content-Type: application/json" -d '{
  "index_patterns": ["f1-lambda-logs-*"],
  "template": {
    "mappings": {
      "properties": {
        "@timestamp":        { "type": "date" },
        "function_name":     { "type": "keyword" },
        "log_level":         { "type": "keyword" },
        "request_id":        { "type": "keyword" },
        "duration_ms":       { "type": "float" },
        "billed_duration_ms":{ "type": "float" },
        "memory_size_mb":    { "type": "integer" },
        "memory_used_mb":    { "type": "integer" },
        "init_duration_ms":  { "type": "float" },
        "model_latency_ms":  { "type": "float" },
        "message":           { "type": "text" },
        "service":           { "type": "keyword" },
        "environment":       { "type": "keyword" }
      }
    }
  }
}' && echo "  f1-lambda-logs template OK"

curl -s -X PUT http://localhost:9200/_index_template/f1-cw-metrics \
  -H "Content-Type: application/json" -d '{
  "index_patterns": ["f1-cw-metrics-*"],
  "template": {
    "mappings": {
      "properties": {
        "@timestamp":    { "type": "date" },
        "function_name": { "type": "keyword" },
        "service":       { "type": "keyword" },
        "metric_name":   { "type": "keyword" },
        "namespace":     { "type": "keyword" },
        "Average":       { "type": "float" },
        "Maximum":       { "type": "float" },
        "Sum":           { "type": "float" },
        "Average_ms":    { "type": "float" },
        "Maximum_ms":    { "type": "float" },
        "environment":   { "type": "keyword" }
      }
    }
  }
}' && echo "  f1-cw-metrics template OK"

curl -s -X PUT http://localhost:9200/_index_template/f1-ec2-metrics \
  -H "Content-Type: application/json" -d '{
  "index_patterns": ["f1-ec2-metrics-*"],
  "template": {
    "mappings": {
      "properties": {
        "@timestamp":  { "type": "date" },
        "service":     { "type": "keyword" },
        "environment": { "type": "keyword" }
      }
    }
  }
}' && echo "  f1-ec2-metrics template OK"

# ── 12. Kibana index patterns ─────────────────────────────────────────────────
KIBANA="http://localhost:5601"

create_index_pattern() {
  local id="$1" title="$2"
  curl -s -X POST "$KIBANA/api/saved_objects/index-pattern/$id" \
    -H "Content-Type: application/json" -H "kbn-xsrf: true" \
    -d "{\"attributes\":{\"title\":\"$title\",\"timeFieldName\":\"@timestamp\"}}" \
    | grep -o '"id":"[^"]*"' | head -1
}

create_index_pattern "f1-inference-star"   "f1-inference-*"   && echo "  index-pattern f1-inference-* OK"
create_index_pattern "f1-training-star"    "f1-training-*"    && echo "  index-pattern f1-training-* OK"
create_index_pattern "f1-lambda-logs-star" "f1-lambda-logs-*" && echo "  index-pattern f1-lambda-logs-* OK"
create_index_pattern "f1-cw-metrics-star"  "f1-cw-metrics-*"  && echo "  index-pattern f1-cw-metrics-* OK"
create_index_pattern "f1-ec2-metrics-star" "f1-ec2-metrics-*" && echo "  index-pattern f1-ec2-metrics-* OK"

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
