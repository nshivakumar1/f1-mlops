# F1 Race Prediction MLOps Platform

Live pit-stop probability predictions for the 2026 Formula 1 season — deployed on AWS in time for the Chinese Grand Prix (Shanghai, March 13-15 2026).

## Architecture

```
OpenF1 API (live telemetry)
       │  every 60s
       ▼
 EventBridge Rule ──► Lambda: enrichment
 (f1-mlops-live-poller)      │
                             ├─► SageMaker Serverless Endpoint
                             │   (XGBoost pitstop model, AUC 0.8854)
                             │
                             ├─► S3: logs/inference/session_{key}/
                             │
                             └─► SNS Alert (prob > 0.85)
                                    │
                             AWS Chatbot ──► #f1-race-alerts (Slack)

 API Gateway ──► Lambda: rest_handler ──► SageMaker + S3
 POST /predict/pitstop
 GET  /predict/positions/{session_key}

 Lambda ──► Logstash HTTP (real-time) ──► Elasticsearch ──► Kibana
 S3 logs/inference/ ──► Logstash S3 input (60s poll) ┘
                       Kibana dashboards:
                      • F1 Race Predictions  • F1 API Health  • F1 Model Drift

 GitHub ──► CodePipeline ──► Terraform apply ──► AWS
```

## Prediction Model

| Model | Algorithm | Metric | Target | Status |
|-------|-----------|--------|--------|--------|
| Pitstop | XGBoost | AUC | ≥ 0.82 | ✅ 0.8854 |
| Position | Random Forest | RMSE | < 2.1 | Planned |
| Safety Car | LightGBM | F1 | ≥ 0.76 | Planned |

**7 input features**: `tyre_age`, `stint_number`, `gap_to_leader`, `air_temperature`, `track_temperature`, `rainfall`, `sector_delta`

**4 engineered features**: `tyre_age_sq`, `heat_deg_interaction`, `wet_stint`, `abs_sector_delta`

## Quick Start

### Prerequisites
- AWS CLI v2, configured with account `297997106614` (us-east-1)
- Terraform ≥ 1.14
- Python 3.9+

### 1. Bootstrap Infrastructure

```bash
# Create Terraform state bucket (one-time, already done)
aws s3 mb s3://f1-mlops-tfstate-297997106614 --region us-east-1
aws dynamodb create-table --table-name f1-mlops-tfstate-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST --region us-east-1

# Deploy infrastructure
cd terraform/environments/dev
terraform init
terraform apply -auto-approve
```

### 2. Generate Training Data & Train Model

```bash
pip install xgboost scikit-learn pandas boto3 joblib

# Generate synthetic training data (94K rows)
python3 scripts/generate_synthetic_data.py --bucket f1-mlops-data-297997106614 --n-races 50

# Seed 2024 historical data from OpenF1 API
python3 scripts/seed_historical_data.py --bucket f1-mlops-data-297997106614

# Train XGBoost model + deploy SageMaker serverless endpoint
python3 scripts/train_and_deploy.py --bucket f1-mlops-data-297997106614
```

Expected output:
```
Validation AUC: 0.8854 (threshold: 0.82)
Model artifact uploaded → s3://f1-mlops-data-297997106614/models/pitstop/dry-race-v1/model.tar.gz
Endpoint InService: f1-mlops-pitstop-endpoint
Smoke test PASSED
```

### 3. Enable Live Predictions (Before Each Session)

```bash
# Enable EventBridge poller (disabled between race weekends to save cost)
aws events enable-rule --name f1-mlops-live-poller --region us-east-1

# Pre-warm endpoint to eliminate cold start (run ~5 min before session)
aws lambda invoke --function-name f1-mlops-prewarm \
  --payload '{"action":"prewarm"}' --cli-binary-format raw-in-base64-out /dev/stdout

# After session ends
aws events disable-rule --name f1-mlops-live-poller --region us-east-1
```

### 4. Query Predictions

```bash
API_URL="https://xwmgxkj0r4.execute-api.us-east-1.amazonaws.com/v1"
API_KEY="zhMEZa785U7PuWJ4o2BIp9lEgUb00t0W25NyiFSx"

# On-demand pitstop prediction
curl -X POST "${API_URL}/predict/pitstop" \
  -H "x-api-key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"features": [20, 2, 5.0, 28.0, 44.0, 0, 0.3], "driver_number": 1, "session_key": 11245}'

# Get all driver predictions for a session
curl "${API_URL}/predict/positions/11245" -H "x-api-key: ${API_KEY}"
```

## AWS Resources

| Resource | Name | Cost/Race Weekend |
|----------|------|-------------------|
| SageMaker Serverless | `f1-mlops-pitstop-endpoint` | ~$0.40 |
| Lambda (4 functions) | `f1-mlops-*` | ~$0.01 |
| API Gateway | `f1-mlops-api` | ~$0.01 |
| ELK on EC2 | `f1-mlops-elk` (t3.medium) | ~$1.00 |
| S3 (3 buckets) | `f1-mlops-data-*` | ~$0.05 |
| Kinesis Firehose | 2 streams | ~$0.05 |
| EventBridge + SNS | Included in free tier | $0.00 |
| **Total** | | **~$1.22** |

> **Cost Control**: Destroy between race weekends with `terraform destroy`. EC2 ELK is ~$1/day — stop the instance between sessions to save cost.

## Repository Structure

```
.
├── lambda/
│   ├── enrichment/         # Live data poller: OpenF1 → SageMaker → S3/SNS
│   ├── rest_handler/       # API Gateway handler: POST /predict/pitstop
│   ├── prewarm/            # Endpoint pre-warmer (eliminates cold start)
│   └── slack_notifier/     # SNS → Slack Block Kit messages
├── ml/
│   ├── glue/               # PySpark feature engineering job
│   ├── training/
│   │   └── pitstop/        # XGBoost model + SageMaker inference script
│   └── evaluation/         # SageMaker Pipeline (5-step DAG)
├── scripts/
│   ├── train_and_deploy.py       # Local train + package + deploy to SageMaker
│   ├── generate_synthetic_data.py # Bootstrap training data (94K rows)
│   └── seed_historical_data.py   # Pull 2024 OpenF1 historical data to S3
├── terraform/
│   ├── environments/dev/   # Root module (main.tf, variables.tf)
│   └── modules/            # s3, iam, lambda, sagemaker, api_gateway,
│                           # opensearch, kinesis, cloudwatch, stepfunctions,
│                           # eventbridge, codepipeline
├── tests/
│   ├── unit/               # 20 unit tests (pytest), all passing ✅
│   └── integration/        # E2E smoke tests
└── buildspec.yml           # CodeBuild: test → terraform plan → apply
```

## SageMaker Endpoint

- **Container**: `sagemaker-xgboost:1.7-1`
- **Mode**: Serverless (zero idle cost, 2048MB, max_concurrency=10)
- **Model format**: XGBoost native JSON (version-independent)
- **Inference script**: `ml/training/pitstop/inference.py`

**Request format:**
```json
{"instances": [[tyre_age, stint_no, gap, air_temp, track_temp, rainfall, sector_delta, tyre_age_sq, heat_deg, wet_stint, abs_delta]]}
```

**Response format:**
```json
{
  "predictions": [{
    "pitstop_probability": 0.731,
    "confidence": 0.462,
    "recommendation": "PIT"
  }]
}
```

## ELK Stack Dashboards

URL: `http://<elk-public-ip>:5601` — get the IP with `terraform output kibana_url`

No auth required (dev mode). EC2 ELK runs Elasticsearch with security disabled for cost savings.

Three dashboards:
- **F1 Race Predictions** — pitstop probabilities per driver over time
- **F1 API Health** — latency percentiles, error rates, request volume
- **F1 Model Drift** — confidence distribution trends, drift alerts

## Slack Alerts

Alerts fire to `#f1-race-alerts` when `pitstop_probability > 0.85`. Setup:

1. Go to [AWS Chatbot Console](https://us-east-1.console.aws.amazon.com/chatbot/home)
2. **Configure new client** → Slack → Authorize
3. Create channel config:
   - Channel: `#f1-race-alerts`
   - SNS topic: `arn:aws:sns:us-east-1:297997106614:f1-mlops-alerts`
   - IAM role: `f1-mlops-chatbot-role`

## CI/CD Pipeline

Triggers on push to `main` branch:
1. **Test**: `pytest tests/unit/ -v` (20 tests)
2. **Plan**: `terraform plan -out=tfplan.binary`
3. **Manual approval** gate
4. **Apply**: `terraform apply tfplan.binary`

CodeStar GitHub connection requires one-time manual activation in the AWS Console.

## Chinese GP Race Weekend (March 13-15, 2026)

| Session | Key | Time (UTC) |
|---------|-----|------------|
| FP1 | 11235 | Mar 13 03:30 |
| Sprint Qualifying | 11236 | Mar 13 07:30 |
| Sprint | 11240 | Mar 14 03:00 |
| Qualifying | 11241 | Mar 14 07:00 |
| **Race** | **11245** | **Mar 15 07:00** |

**Day-of race checklist:**
- [ ] `terraform apply` — verify no drift
- [ ] Enable EventBridge: `aws events enable-rule --name f1-mlops-live-poller --region us-east-1`
- [ ] Prewarm endpoint 5 min before session
- [ ] Monitor: Kibana (`http://3.221.47.245:5601`) + `#f1-race-alerts` Slack channel
- [ ] After race: `aws events disable-rule --name f1-mlops-live-poller --region us-east-1`
- [ ] `terraform destroy` (if next race > 1 week away)

## Testing

```bash
pip install pytest moto boto3
pytest tests/unit/ -v        # 20 tests, ~3s
```

## Environment Variables

All sensitive values are in AWS Secrets Manager. Terraform manages all IAM roles and environment variable injection into Lambda.

| Secret | Description |
|--------|-------------|
| `f1-mlops/slack-bot-token` | Slack Bot Token for direct posting |

## Live Endpoints

| Service | URL | Notes |
| ------- | --- | ----- |
| REST API | `https://xwmgxkj0r4.execute-api.us-east-1.amazonaws.com/v1` | Requires `x-api-key` header |
| Kibana | `http://3.221.47.245:5601` | No auth (dev mode) |
| Logstash HTTP | `http://3.221.47.245:8080` | Lambda pushes here |
| API Key | `zhMEZa785U7PuWJ4o2BIp9lEgUb00t0W25NyiFSx` | Store securely |
