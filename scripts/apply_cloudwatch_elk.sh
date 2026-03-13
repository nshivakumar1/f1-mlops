#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# apply_cloudwatch_elk.sh
#
# Applies CloudWatch → Kibana integration to a RUNNING ELK EC2.
# Run this when the EC2 is already up and you don't want a full restart.
#
# Usage:
#   SSH_KEY=~/.ssh/your-key.pem ./scripts/apply_cloudwatch_elk.sh
#   or set ELK_IP directly:
#   ELK_IP=1.2.3.4 SSH_KEY=~/.ssh/your-key.pem ./scripts/apply_cloudwatch_elk.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

AWS_REGION="us-east-1"
PROJECT="f1-mlops"
INSTANCE_ID_ELK="i-05e4b8ddbcce9647d"

# Get ELK IP if not provided
ELK_IP="${ELK_IP:-$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID_ELK" \
  --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)}"

SSH_KEY="${SSH_KEY:-~/.ssh/id_rsa}"
SSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=no ubuntu@$ELK_IP"

echo "=== Applying CloudWatch → Kibana integration to $ELK_IP ==="

# ── 1. Get EC2 instance ID (from inside the instance) ────────────────────────
RUNNING_INSTANCE_ID=$($SSH "curl -sf http://169.254.169.254/latest/meta-data/instance-id")
echo "EC2 instance ID: $RUNNING_INSTANCE_ID"

# ── 2. Install Logstash CloudWatch plugins ────────────────────────────────────
echo "Installing Logstash plugins..."
# Find the Logstash container name (may vary)
LOGSTASH_CONTAINER=$($SSH "sudo docker ps --filter 'ancestor=docker.elastic.co/logstash/logstash:8.12.2' --format '{{.Names}}' | head -1")
echo "Logstash container: $LOGSTASH_CONTAINER"
$SSH "sudo docker exec $LOGSTASH_CONTAINER bash -c '
  bin/logstash-plugin list | grep -q logstash-input-cloudwatch_logs || \
    bin/logstash-plugin install logstash-input-cloudwatch_logs
  bin/logstash-plugin list | grep -q logstash-input-cloudwatch || \
    bin/logstash-plugin install logstash-input-cloudwatch
'"

# ── 3. Write CloudWatch Logs pipeline ────────────────────────────────────────
echo "Writing cloudwatch_logs.conf..."
$SSH "sudo tee /opt/elk/logstash/pipeline/cloudwatch_logs.conf > /dev/null" << CONF
input {
  cloudwatch_logs {
    log_group => \"/aws/lambda/${PROJECT}-enrichment\"
    region    => \"${AWS_REGION}\"
    interval  => 60
    type      => \"lambda_logs\"
    add_field => { \"function_name\" => \"${PROJECT}-enrichment\" }
  }
  cloudwatch_logs {
    log_group => \"/aws/lambda/${PROJECT}-rest-handler\"
    region    => \"${AWS_REGION}\"
    interval  => 60
    type      => \"lambda_logs\"
    add_field => { \"function_name\" => \"${PROJECT}-rest-handler\" }
  }
  cloudwatch_logs {
    log_group => \"/aws/sagemaker/Endpoints/${PROJECT}-pitstop-endpoint\"
    region    => \"${AWS_REGION}\"
    interval  => 60
    type      => \"sagemaker_logs\"
    add_field => { \"service\" => \"sagemaker\" }
  }
}
filter {
  if [type] == \"lambda_logs\" and [message] =~ /^REPORT RequestId/ {
    grok { match => { \"message\" => \"REPORT RequestId: %{DATA:request_id}\\s+Duration: %{NUMBER:duration_ms:float} ms\\s+Billed Duration: %{NUMBER:billed_duration_ms:float} ms\\s+Memory Size: %{NUMBER:memory_size_mb:integer} MB\\s+Max Memory Used: %{NUMBER:memory_used_mb:integer} MB%{GREEDYDATA:rest}\" } }
    mutate { add_tag => [\"lambda_report\"] add_field => { \"log_level\" => \"REPORT\" } }
    if [rest] =~ /Init Duration/ {
      grok { match => { \"rest\" => \"Init Duration: %{NUMBER:init_duration_ms:float} ms\" } }
      mutate { add_tag => [\"cold_start\"] }
    }
    mutate { remove_field => [\"rest\"] }
  } else if [type] == \"lambda_logs\" and [message] =~ /ERROR|WARNING/ {
    mutate { add_tag => [\"lambda_error\"] add_field => { \"log_level\" => \"ERROR\" } }
  }
  if [message] =~ /^(START|END) RequestId/ { drop {} }
  mutate { add_field => { \"environment\" => \"f1-mlops\" } remove_field => [\"@version\"] }
}
output {
  elasticsearch { hosts => [\"http://elasticsearch:9200\"] index => \"f1-lambda-logs-%{+YYYY.MM.dd}\" }
}
CONF

# ── 4. Write CloudWatch Metrics pipeline ──────────────────────────────────────
echo "Writing cloudwatch_metrics.conf..."
$SSH "sudo tee /opt/elk/logstash/pipeline/cloudwatch_metrics.conf > /dev/null" << CONF
input {
  cloudwatch {
    region => \"${AWS_REGION}\" namespace => \"AWS/Lambda\"
    metrics => [\"Duration\", \"Errors\", \"Invocations\", \"Throttles\"]
    dimensions => { \"FunctionName\" => \"${PROJECT}-enrichment\" }
    period => 60 statistics => [\"Average\", \"Sum\", \"Maximum\"] interval => 60
    type => \"lambda_metrics\" add_field => { \"function_name\" => \"${PROJECT}-enrichment\" }
  }
  cloudwatch {
    region => \"${AWS_REGION}\" namespace => \"AWS/Lambda\"
    metrics => [\"Duration\", \"Errors\", \"Invocations\"]
    dimensions => { \"FunctionName\" => \"${PROJECT}-rest-handler\" }
    period => 60 statistics => [\"Average\", \"Sum\", \"Maximum\"] interval => 60
    type => \"lambda_metrics\" add_field => { \"function_name\" => \"${PROJECT}-rest-handler\" }
  }
  cloudwatch {
    region => \"${AWS_REGION}\" namespace => \"AWS/SageMaker\"
    metrics => [\"Invocations\", \"InvocationLatency\", \"ModelLatency\", \"OverheadLatency\"]
    dimensions => { \"EndpointName\" => \"${PROJECT}-pitstop-endpoint\" \"VariantName\" => \"AllTraffic\" }
    period => 60 statistics => [\"Average\", \"Sum\", \"Maximum\"] interval => 60
    type => \"sagemaker_metrics\" add_field => { \"service\" => \"sagemaker\" }
  }
  cloudwatch {
    region => \"${AWS_REGION}\" namespace => \"AWS/EC2\"
    metrics => [\"CPUUtilization\", \"NetworkIn\", \"NetworkOut\"]
    dimensions => { \"InstanceId\" => \"${RUNNING_INSTANCE_ID}\" }
    period => 60 statistics => [\"Average\", \"Maximum\"] interval => 60
    type => \"ec2_metrics\" add_field => { \"service\" => \"ec2\" }
  }
  cloudwatch {
    region => \"${AWS_REGION}\" namespace => \"F1MLOps/Models\"
    metrics => [\"PredictionConfidence\", \"HighConfidencePredictions\"]
    period => 60 statistics => [\"Average\", \"Sum\", \"Maximum\"] interval => 60
    type => \"model_metrics\" add_field => { \"service\" => \"f1-model\" }
  }
}
filter {
  mutate { add_field => { \"environment\" => \"f1-mlops\" } remove_field => [\"@version\"] }
  if [type] == \"sagemaker_metrics\" {
    ruby { code => \"['Average','Maximum'].each{|s| v=event.get(s); event.set(\\\"#{s}_ms\\\", v.to_f/1000.0) if v}\" }
  }
}
output {
  elasticsearch { hosts => [\"http://elasticsearch:9200\"] index => \"f1-cw-metrics-%{+YYYY.MM.dd}\" }
}
CONF

$SSH "sudo chown -R 1000:1000 /opt/elk/logstash/pipeline"

# ── 5. Create Elasticsearch index templates ───────────────────────────────────
echo "Creating ES index templates..."
$SSH "curl -sf -X PUT http://localhost:9200/_index_template/f1-lambda-logs \
  -H 'Content-Type: application/json' -d '{
  \"index_patterns\":[\"f1-lambda-logs-*\"],
  \"template\":{\"mappings\":{\"properties\":{
    \"@timestamp\":{\"type\":\"date\"},\"function_name\":{\"type\":\"keyword\"},
    \"log_level\":{\"type\":\"keyword\"},\"duration_ms\":{\"type\":\"float\"},
    \"billed_duration_ms\":{\"type\":\"float\"},\"memory_size_mb\":{\"type\":\"integer\"},
    \"memory_used_mb\":{\"type\":\"integer\"},\"init_duration_ms\":{\"type\":\"float\"},
    \"message\":{\"type\":\"text\"},\"service\":{\"type\":\"keyword\"}
  }}}}' && echo 'f1-lambda-logs template OK'"

$SSH "curl -sf -X PUT http://localhost:9200/_index_template/f1-cw-metrics \
  -H 'Content-Type: application/json' -d '{
  \"index_patterns\":[\"f1-cw-metrics-*\"],
  \"template\":{\"mappings\":{\"properties\":{
    \"@timestamp\":{\"type\":\"date\"},\"function_name\":{\"type\":\"keyword\"},
    \"service\":{\"type\":\"keyword\"},\"metric_name\":{\"type\":\"keyword\"},
    \"Average\":{\"type\":\"float\"},\"Maximum\":{\"type\":\"float\"},\"Sum\":{\"type\":\"float\"},
    \"Average_ms\":{\"type\":\"float\"},\"Maximum_ms\":{\"type\":\"float\"}
  }}}}' && echo 'f1-cw-metrics template OK'"

# ── 6. Create Kibana index patterns ──────────────────────────────────────────
echo "Creating Kibana index patterns..."
for PATTERN in "f1-lambda-logs-star:f1-lambda-logs-*" "f1-cw-metrics-star:f1-cw-metrics-*"; do
  ID="${PATTERN%%:*}"
  TITLE="${PATTERN##*:}"
  $SSH "curl -sf -X POST http://localhost:5601/api/saved_objects/index-pattern/$ID \
    -H 'Content-Type: application/json' -H 'kbn-xsrf: true' \
    -d '{\"attributes\":{\"title\":\"$TITLE\",\"timeFieldName\":\"@timestamp\"}}' \
    | grep -o '\"id\":\"[^\"]*\"' | head -1 && echo ' $ID OK' || echo ' $ID (may already exist)'"
done

# ── 7. Start Metricbeat (if not running) ──────────────────────────────────────
echo "Checking Metricbeat..."
$SSH "cd /opt/elk && sudo docker compose ps metricbeat 2>/dev/null || echo 'Metricbeat not in compose — skip'"

# ── 8. Restart Logstash to pick up new pipelines ─────────────────────────────
echo "Restarting Logstash..."
$SSH "cd /opt/elk && sudo docker compose restart logstash"
echo "Waiting for Logstash to come back up (~30s)..."
sleep 30

$SSH "sudo docker logs $LOGSTASH_CONTAINER 2>&1 | tail -20"

echo ""
echo "=== Done! ==="
echo "Kibana:   http://$ELK_IP:5601"
echo "New index patterns: f1-lambda-logs-*, f1-cw-metrics-*"
echo "Data will appear in Kibana within ~2 minutes (first poll cycle)"
