
<div align="center">

```
███████╗ ██╗     ███╗   ███╗██╗      ██████╗ ██████╗ ███████╗
██╔════╝ ██║     ████╗ ████║██║     ██╔═══██╗██╔══██╗██╔════╝
█████╗   ██║     ██╔████╔██║██║     ██║   ██║██████╔╝███████╗
██╔══╝   ██║     ██║╚██╔╝██║██║     ██║   ██║██╔═══╝ ╚════██║
██║      ███████╗██║ ╚═╝ ██║███████╗╚██████╔╝██║     ███████║
╚═╝      ╚══════╝╚═╝     ╚═╝╚══════╝ ╚═════╝ ╚═╝     ╚══════╝
```

### 🏎️ Real-time F1 Pit Stop Prediction · XGBoost · AWS · Live 2026

[![CI](https://github.com/nshivakumar1/f1-mlops/actions/workflows/ci.yml/badge.svg)](https://github.com/nshivakumar1/f1-mlops/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-20%20passing-brightgreen?style=flat-square&logo=pytest)](tests/unit/)
[![Model AUC](https://img.shields.io/badge/Model%20AUC-0.8854-blue?style=flat-square&logo=scikit-learn)](ml/training/pitstop/)
[![Terraform](https://img.shields.io/badge/Terraform-1.9.8-7B42BC?style=flat-square&logo=terraform)](terraform/)
[![AWS](https://img.shields.io/badge/AWS-us--east--1-FF9900?style=flat-square&logo=amazonaws)](https://aws.amazon.com)
[![Cost](https://img.shields.io/badge/cost%2Frace%20weekend-%241.22-success?style=flat-square)](README.md#aws-resources)
[![CodeRabbit](https://img.shields.io/coderabbit/prs/github/nshivakumar1/f1-mlops?utm_source=oss&utm_medium=github&utm_campaign=nshivakumar1%2Ff1-mlops&labelColor=171717&color=FF570A&link=https%3A%2F%2Fcoderabbit.ai&label=CodeRabbit+Reviews)](https://coderabbit.ai)

</div>

---

## What Is This?

> **Predict, with 88.5% accuracy, which F1 driver will pit — before the team even radios in.**

Every 60 seconds during a live race, this system:
1. Pulls telemetry from the **OpenF1 API** for all 22 drivers
2. Engineers 11 features and scores them through an **XGBoost model** on SageMaker
3. Stores predictions in **S3** and serves them via **API Gateway**
4. Fires **Slack alerts** when pit probability exceeds 85%
5. Streams everything to **Kibana dashboards** in real time

Built for the **2026 Formula 1 season** — first deployed for the Chinese Grand Prix (Shanghai, March 13–15 2026).

---

## Architecture

```
                        ┌─────────────────────────────────────────┐
                        │           EVERY 60 SECONDS              │
                        └──────────────────┬──────────────────────┘
                                           │
                   ┌───────────────────────▼───────────────────────┐
                   │          OpenF1 API  (oauth2 auth)            │
                   │  stints · intervals · laps · weather · SC     │
                   └───────────────────────┬───────────────────────┘
                                           │  3 batch calls → 22 drivers
                   ┌───────────────────────▼───────────────────────┐
                   │      Lambda: enrichment  (60s timeout)        │
                   │  feature engineering · 11 features/driver     │
                   └────────┬──────────────┬────────────┬──────────┘
                            │              │            │
               ┌────────────▼───┐  ┌───────▼──────┐  ┌▼──────────────────┐
               │    SageMaker   │  │      S3       │  │   Kinesis/HTTP    │
               │   Serverless   │  │  logs/infer.. │  │  → Logstash       │
               │ XGBoost AUC    │  │  session_{k}/ │  │  → Elasticsearch  │
               │   0.8854  🎯   │  └───────┬───────┘  │  → Kibana  📊     │
               └────────┬───────┘          │           └───────────────────┘
                        │                  │
               ┌────────▼───────┐  ┌───────▼───────────────────────────────┐
               │  prob > 0.85?  │  │          API Gateway (REST)            │
               │  SNS → Chatbot │  │  GET  /sessions/latest                 │
               │  → Slack 🔔    │  │  GET  /predict/positions/{session_key} │
               └────────────────┘  │  POST /predict/pitstop                 │
                                   └───────────────────────────────────────┘
                                                    ▲
                                                    │
                                   ┌────────────────┴───────────────────────┐
                                   │        Next.js Frontend (Vercel)        │
                                   │    Live Dashboard · Race History        │
                                   └────────────────────────────────────────┘

  ┌────────────────────────────────────────────────────────────────────────┐
  │   GitHub ──► CodePipeline ──► [Test → TerraformPlan → Approve → Apply] │
  └────────────────────────────────────────────────────────────────────────┘
```

---

## Prediction Model

<div align="center">

| Model | Algorithm | Metric | Target | Status |
|:------|:----------|:------:|:------:|:------:|
| 🟢 **Pitstop** | XGBoost | AUC | ≥ 0.82 | **0.8854** ✅ |
| 🔵 Position Finish | Random Forest | RMSE | < 2.1 | Planned |
| 🟡 Safety Car | LightGBM | F1 | ≥ 0.76 | Planned |

</div>

### Feature Engineering

```
RAW (7)                          ENGINEERED (4)
──────────────────────           ───────────────────────────────────────
tyre_age          ──────────────► tyre_age²          (degradation curve)
stint_number                    ► track_temp × tyre_age  (heat deg model)
gap_to_leader                   ► rainfall × stint_number  (wet strategy)
air_temperature                 ► |sector_delta|      (consistency proxy)
track_temperature
rainfall
sector_delta
```

**Total: 11 features → 1 probability score → PIT / STAY OUT**

---

## Live Endpoints

| Service | URL | Auth |
|:--------|:----|:-----|
| REST API | `https://xwmgxkj0r4.execute-api.us-east-1.amazonaws.com/v1` | `x-api-key` (POST only) |
| Kibana | `http://<elk-ip>:5601` | None (dev mode) |
| Logstash | `http://<elk-ip>:8080` | None |

> ELK EC2 IP changes on restart — run `terraform output kibana_url` to get the current address.

---

## Quick Start

### Prerequisites

```bash
# Required
aws --version          # AWS CLI v2, configured for account 297997106614 (us-east-1)
terraform -version     # ≥ 1.9.8
python3 --version      # ≥ 3.9
```

### 1 — Bootstrap Infrastructure

```bash
cd terraform/environments/dev
terraform init
terraform apply -auto-approve
```

### 2 — Train & Deploy Model

```bash
pip install xgboost scikit-learn pandas boto3 joblib

# Generate 94K rows of synthetic training data
python3 scripts/generate_synthetic_data.py --bucket f1-mlops-data-297997106614 --n-races 50

# Seed 2024 historical data from OpenF1
python3 scripts/seed_historical_data.py --bucket f1-mlops-data-297997106614

# Train + deploy SageMaker serverless endpoint
python3 scripts/train_and_deploy.py --bucket f1-mlops-data-297997106614
```

Expected output:
```
Validation AUC: 0.8854  ✅  (threshold: 0.82)
Model artifact → s3://f1-mlops-data-297997106614/models/pitstop/dry-race-v1/model.tar.gz
Endpoint InService: f1-mlops-pitstop-endpoint
Smoke test PASSED
```

### 3 — Go Live (Before Each Session)

```bash
# Start ELK stack (stopped between races to save cost)
aws ec2 start-instances --instance-ids i-05e4b8ddbcce9647d --region us-east-1

# Enable 60s poller
aws events enable-rule --name f1-mlops-live-poller --region us-east-1

# Pre-warm SageMaker (eliminates cold-start latency)
aws events enable-rule --name f1-mlops-prewarm-rule --region us-east-1

# Set up Kibana dashboards (after EC2 boot)
python3 scripts/setup_kibana_dashboards.py --host http://<elk-ip>:5601
```

### 4 — Query the API

```bash
API_URL="https://xwmgxkj0r4.execute-api.us-east-1.amazonaws.com/v1"

# Latest predictions for all 22 drivers
curl "${API_URL}/sessions/latest" | jq '.predictions[:5]'

# Historical session
curl "${API_URL}/predict/positions/11245" | jq '.predictions[:5]'

# On-demand prediction (requires API key)
curl -X POST "${API_URL}/predict/pitstop" \
  -H "x-api-key: <your-key>" \
  -H "Content-Type: application/json" \
  -d '{"features": [20, 2, 5.0, 28.0, 44.0, 0, 0.3], "driver_number": 1}'
```

---

## Repository Structure

```
f1-mlops/
│
├── 🔬  lambda/
│   ├── enrichment/       ← live poller: OpenF1 → feature eng → SageMaker → S3/SNS
│   ├── rest_handler/     ← API Gateway handler (pitstop, positions, sessions)
│   ├── prewarm/          ← endpoint pre-warmer (eliminates cold start)
│   └── slack_notifier/   ← SNS → Slack Block Kit messages
│
├── 🧠  ml/
│   ├── glue/             ← PySpark feature engineering job
│   ├── training/pitstop/ ← XGBoost model + SageMaker inference script
│   └── evaluation/       ← SageMaker Pipeline DAG (5 steps)
│
├── 🖥️  frontend/          ← Next.js dashboard (deployed on Vercel)
│   └── app/
│       ├── page.tsx      ← live race predictions
│       └── history/      ← past session results
│
├── 📜  scripts/
│   ├── train_and_deploy.py          ← local train + SageMaker deploy
│   ├── generate_synthetic_data.py   ← 94K row bootstrap dataset
│   ├── seed_historical_data.py      ← 2024 OpenF1 historical pull
│   └── setup_kibana_dashboards.py   ← push 9 vizs + 3 dashboards to Kibana
│
├── 🏗️  terraform/
│   ├── environments/dev/  ← root module
│   └── modules/           ← s3, iam, lambda, sagemaker, api_gateway,
│                             kinesis, cloudwatch, eventbridge, codepipeline, elk
│
├── 🧪  tests/
│   ├── unit/              ← 20 pytest tests (all passing ✅)
│   └── integration/       ← E2E smoke tests
│
├── buildspec.yml          ← CodeBuild: calls ci_build.sh
└── scripts/ci_build.sh    ← test → terraform plan → terraform apply
```

---

## AWS Resources & Cost

<div align="center">

| Resource | Name | Cost / Race Weekend |
|:---------|:-----|--------------------:|
| SageMaker Serverless | `f1-mlops-pitstop-endpoint` | ~$0.40 |
| Lambda × 4 | `f1-mlops-{enrichment,rest,prewarm,slack}` | ~$0.01 |
| API Gateway | `f1-mlops-api` | ~$0.01 |
| ELK on EC2 (t3.medium) | `f1-mlops-elk` | ~$1.00 |
| S3 × 3 buckets | `f1-mlops-{data,artifacts,logs}-*` | ~$0.05 |
| Kinesis Firehose | 2 streams | ~$0.05 |
| EventBridge + SNS | — | $0.00 |
| **TOTAL** | | **~$1.52** |

</div>

> **Cost tip:** Stop the ELK EC2 between races (`aws ec2 stop-instances ...`). Destroy everything between race weekends with `terraform destroy` if the next race is > 1 week away.

---

## CI/CD Pipeline

```
git push origin main
        │
        ▼
┌───────────────────────────────────────────────────┐
│                  AWS CodePipeline                  │
│                                                   │
│  ①Source  →  ②Test  →  ③Plan  →  ④Approve  →  ⑤Apply  │
│                  │          │                     │
│               pytest    terraform              terraform │
│               20 tests    plan -out           apply     │
│                           tfplan.binary                 │
└───────────────────────────────────────────────────┘
        │
        ▼ (also triggered on PR)
┌───────────────────────────────────────────────────┐
│               GitHub Actions (CI)                 │
│  • pytest tests/unit/ -v                         │
│  • terraform fmt -check                          │
│  • terraform validate                            │
└───────────────────────────────────────────────────┘
```

---

## Race Day Checklist 🏁

```bash
# ① Start ELK EC2
aws ec2 start-instances --instance-ids i-05e4b8ddbcce9647d --region us-east-1

# ② Get new IP (changes on restart)
aws ec2 describe-instances --instance-ids i-05e4b8ddbcce9647d \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text

# ③ Update logstash_url var, re-apply Terraform if needed
# ④ Enable live poller (30 min before lights out)
aws events enable-rule --name f1-mlops-live-poller    --region us-east-1
aws events enable-rule --name f1-mlops-prewarm-rule   --region us-east-1

# ⑤ Push Kibana dashboards
python3 scripts/setup_kibana_dashboards.py --host http://<IP>:5601

# ⑥ Watch the race 🍿
#    Kibana: http://<IP>:5601
#    Slack:  #f1-race-alerts

# ⑦ After session — shut it all down
aws events disable-rule --name f1-mlops-live-poller   --region us-east-1
aws events disable-rule --name f1-mlops-prewarm-rule  --region us-east-1
aws ec2 stop-instances  --instance-ids i-05e4b8ddbcce9647d --region us-east-1
```

---

## Kibana Dashboards

Three dashboards auto-provisioned via `scripts/setup_kibana_dashboards.py`:

| Dashboard | Visualizations |
|:----------|:---------------|
| **F1 Live Race Predictions** | Pitstop probability bar · Risk band donut · Tyre compound donut · Prob timeline · Driver strategy table |
| **API Health & Model Performance** | Avg confidence metric · Tyre age histogram · Gap-to-leader chart · Confidence drift timeline |
| **Tyre Strategy Analysis** | Compound breakdown · Tyre age distribution · Heat degradation index |

---

## SageMaker Endpoint

```
Container:   sagemaker-xgboost:1.7-1
Mode:        Serverless  (zero idle cost · 2048MB · max_concurrency=10)
Format:      XGBoost native JSON

Request:
  {"instances": [[tyre_age, stint_no, gap, air_temp, track_temp,
                  rainfall, sector_delta,
                  tyre_age_sq, heat_deg, wet_stint, abs_delta]]}

Response:
  {"predictions": [{"pitstop_probability": 0.731,
                    "confidence": 0.462,
                    "recommendation": "PIT"}]}
```

---

## Slack Alerts

Fires to **#f1-race-alerts** when `pitstop_probability > 0.85`:

```
🚨 F1 PIT ALERT — Max Verstappen (RBR)
   Pitstop Probability: 92%  |  Confidence: 78%
   Tyre: HARD L28  |  Gap: +3.1s  |  Sector Δ: +0.8s
   Session: 11245
```

Powered by **CloudWatch Alarm → SNS → AWS Chatbot → Slack** (boto3/CLI SDK doesn't work for Chatbot — see CLAUDE.md #11).

---

## Testing

```bash
pip install pytest moto boto3
pytest tests/unit/ -v
# ========================== 20 passed in 2.8s ==========================
```

---

## 2026 Season

| Race | Circuit | Weekend |
|:-----|:--------|:--------|
| 🇦🇺 R1 | Melbourne | Mar 14–16 |
| 🇨🇳 **R2** | **Shanghai** | **Mar 21–23** |
| 🇯🇵 R3 | Suzuka | Apr 4–6 |
| 🇧🇭 R4 | Bahrain | Apr 11–13 |
| 🇸🇦 R5 | Jeddah | Apr 25–27 |
| ⋮ | ⋮ | ⋮ |

> First live deployment: **Chinese GP, March 2026** — all 22 drivers tracked from FP1 through race day.

---

<div align="center">

**Built with obsession over a single race weekend.**

`XGBoost` · `SageMaker Serverless` · `AWS Lambda` · `API Gateway` · `Terraform` · `Next.js` · `Kibana` · `OpenF1`

</div>
