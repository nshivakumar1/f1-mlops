# 🏎️ F1 MLOps

Real-time F1 Pit Stop Prediction · XGBoost on AWS · Live 2026 Season

[![CI](https://github.com/nshivakumar1/f1-mlops/actions/workflows/ci.yml/badge.svg)](https://github.com/nshivakumar1/f1-mlops/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-20%20passing-22c55e?style=flat-square&logo=pytest&logoColor=white)](tests/unit/)
[![Model AUC](https://img.shields.io/badge/XGBoost%20AUC-0.8854-3b82f6?style=flat-square&logo=scikit-learn&logoColor=white)](ml/training/pitstop/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](lambda/)
[![Terraform](https://img.shields.io/badge/Terraform-1.9.8-7B42BC?style=flat-square&logo=terraform&logoColor=white)](terraform/)
[![AWS](https://img.shields.io/badge/AWS-us--east--1-FF9900?style=flat-square&logo=amazonaws&logoColor=white)](https://aws.amazon.com)
[![Vercel](https://img.shields.io/badge/Frontend-Vercel-000000?style=flat-square&logo=vercel&logoColor=white)](https://vercel.com)
[![New Relic](https://img.shields.io/badge/Observability-New%20Relic-008C99?style=flat-square&logo=newrelic&logoColor=white)](https://newrelic.com)
[![Sentry](https://img.shields.io/badge/Errors-Sentry-362D59?style=flat-square&logo=sentry&logoColor=white)](https://sentry.io)
[![Cost](https://img.shields.io/badge/cost%2Frace%20weekend-%240.47-22c55e?style=flat-square&logo=amazonaws&logoColor=white)](#aws-resources--cost)
[![CodeRabbit](https://img.shields.io/coderabbit/prs/github/nshivakumar1/f1-mlops?utm_source=oss&utm_medium=github&utm_campaign=nshivakumar1%2Ff1-mlops&labelColor=171717&color=FF570A&link=https%3A%2F%2Fcoderabbit.ai&label=CodeRabbit)](https://coderabbit.ai)

> **Predict, with 88.5% accuracy, which F1 driver will pit — before the team even radios in.**

---

## What Is This?

Every **60 seconds** during a live race, this system:

1. 🔌 Pulls telemetry from the **OpenF1 API** (OAuth2) for all 22 drivers — stints, intervals, laps, weather, race control
2. 🧠 Engineers **11 features** per driver and scores them through an **XGBoost model** on SageMaker Serverless
3. 🏆 Computes **win probability** inline using live race state (position, gaps, tyre freshness, team strength)
4. 💬 Generates **AI strategy commentary** via Groq (Llama 3.3 70B) — two sharp broadcast-style sentences
5. 💾 Stores predictions in **S3** and serves them via **API Gateway** to the live frontend
6. 🔔 Fires **Slack alerts** (AWS Chatbot → #f1-race-alerts) when pit probability exceeds 85%
7. 📊 Streams **custom events + infra metrics** to **New Relic** dashboards in near real-time
8. 🩺 Ships **errors and traces** to **Sentry** via the NR Lambda layer

Built for the **2026 Formula 1 season** — first deployed at the Chinese GP (Shanghai, March 13–15).

---

## Architecture

```text
                        ┌──────────────────────────────────────────┐
                        │            EVERY 60 SECONDS              │
                        │   EventBridge → Lambda: enrichment       │
                        └──────────────────┬───────────────────────┘
                                           │
                   ┌───────────────────────▼───────────────────────┐
                   │          OpenF1 API  (OAuth2 auth)            │
                   │  stints · intervals · laps · weather · SC     │
                   │         3 batch calls → 22 drivers            │
                   └───────────────────────┬───────────────────────┘
                                           │
                   ┌───────────────────────▼───────────────────────┐
                   │      Lambda: enrichment  (60s timeout)        │
                   │  • 11 features/driver (7 raw + 4 engineered)  │
                   │  • Win probability (inline, no extra endpoint) │
                   │  • AI commentary  (Groq / Llama 3.3 70B)      │
                   │  • Tyre fallback cache (S3)                   │
                   └──────┬─────────────┬──────────────┬──────────┘
                          │             │              │
           ┌──────────────▼──┐  ┌───────▼──────┐  ┌───▼────────────────┐
           │   SageMaker     │  │      S3       │  │    New Relic       │
           │  Serverless     │  │ logs/infer/   │  │ F1PitstopPrediction│
           │  XGBoost 0.8854 │  │ session_{k}/  │  │  custom events     │
           └──────┬──────────┘  └───────┬───────┘  └────────────────────┘
                  │                     │
           ┌──────▼──────────┐  ┌───────▼──────────────────────────────┐
           │  prob > 0.85?   │  │         API Gateway  (REST)          │
           │  SNS → Chatbot  │  │  GET  /sessions/latest               │
           │  → Slack 🔔     │  │  GET  /predict/positions/{key}       │
           └─────────────────┘  │  GET  /positions/latest  (OpenF1)    │
                                │  GET  /track/{circuit_key}           │
                                │  GET  /sessions  · /sessions/latest  │
                                │  POST /predict/pitstop               │
                                └───────┬──────────────────────────────┘
                                        │
                   ┌────────────────────▼──────────────────────────┐
                   │       Next.js Frontend  (Vercel)              │
                   │  Live dashboard · Race history · Circuit map  │
                   │  Polls API every 30s · Map updates every 5s   │
                   └───────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────────┐
  │  CW Metric Stream → Kinesis Firehose → New Relic                     │
  │  Namespaces: AWS/Lambda · AWS/SageMaker · F1MLOps/Models · Billing   │
  └──────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────────┐
  │  GitHub → GitHub Actions  [Test → Plan → Approve → Deploy]          │
  │  • pytest 20 tests  • terraform fmt/validate  • frontend build      │
  │  • manylinux Lambda ZIPs  • production environment approval gate     │
  └──────────────────────────────────────────────────────────────────────┘
```

---

## Prediction Models

| Model | Algorithm | Metric | Status |
|:------|:----------|:------:|:------:|
| 🟢 **Pitstop** | XGBoost | AUC **0.8854** ✅ | Deployed (SageMaker Serverless) |
| 🏆 **Win Probability** | Inline scoring | Position · Gap · Tyre · Team | Live (no extra endpoint) |
| 🔵 Position Finish | Random Forest | 12 features trained | Pending deployment |
| 🟡 Safety Car | LightGBM | F1 score | Planned |

### Feature Engineering

```text
RAW (7)                          ENGINEERED (4)
──────────────────────           ──────────────────────────────────────
tyre_age          ──────────────► tyre_age²              (degradation curve)
stint_number                    ► track_temp × tyre_age  (heat deg model)
gap_to_leader                   ► rainfall × stint_number (wet strategy)
air_temperature                 ► |sector_delta|          (consistency proxy)
track_temperature
rainfall
sector_delta
```

**11 features → 1 probability score → PIT / STAY OUT**

### Win Probability Formula

Computed live each lap — no second model endpoint required:

| Signal | Weight (normal) | Weight (safety car) |
|:-------|:---------------:|:-------------------:|
| Gap ranking (position) | 40% | 55% |
| Gap to leader | 25% | 0% |
| Team strength | 20% | 20% |
| Tyre freshness | 10% | 15% |
| Pitstop stability | 5% | 10% |

---

## Live Endpoints

| Endpoint | Description |
|:---------|:------------|
| `GET /sessions/latest` | Latest predictions for all 22 drivers + win probability + AI commentary |
| `GET /sessions` | All available session keys |
| `GET /predict/positions/{session_key}` | Cached predictions for a specific session |
| `GET /positions/latest` | Live driver XY positions proxied from OpenF1 |
| `GET /track/{circuit_key}` | Circuit layout from Multiviewer (SVG coordinates) |
| `POST /predict/pitstop` | On-demand single-driver prediction |

**Base URL:** `https://xwmgxkj0r4.execute-api.us-east-1.amazonaws.com/v1`

---

## Quick Start

### Prerequisites

```bash
aws --version       # AWS CLI v2, account 297997106614 (us-east-1)
terraform -version  # ≥ 1.9.8
python3 --version   # ≥ 3.9
node --version      # ≥ 20 (frontend)
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

```text
Validation AUC: 0.8854  ✅  (threshold: 0.82)
Endpoint InService: f1-mlops-pitstop-endpoint
Smoke test PASSED
```

### 3 — Run Frontend Locally

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
npm run build      # production build + type check
```

### 4 — Query the API

```bash
API="https://xwmgxkj0r4.execute-api.us-east-1.amazonaws.com/v1"

# Latest predictions — all 22 drivers with win probability + AI commentary
curl "$API/sessions/latest" | jq '{session: .session_key, commentary: .commentary, top3: .predictions[:3]}'

# Historical session
curl "$API/predict/positions/11245" | jq '.predictions[:5]'

# On-demand prediction
curl -X POST "$API/predict/pitstop" \
  -H "x-api-key: <your-key>" \
  -H "Content-Type: application/json" \
  -d '{"features": [20, 2, 5.0, 28.0, 44.0, 0, 0.3], "driver_number": 1}'
```

---

## Repository Structure

```text
f1-mlops/
│
├── 🔬  lambda/
│   ├── enrichment/        ← live poller: OpenF1 → features → SageMaker → S3/SNS/NR
│   │   ├── handler.py     ← main Lambda (win prob, AI commentary, tyre cache)
│   │   ├── openf1_client.py
│   │   └── groq_client.py ← Llama 3.3 70B via Groq (AI commentary)
│   ├── rest_handler/      ← API Gateway: /sessions, /positions, /track, /pitstop
│   ├── prewarm/           ← SageMaker pre-warmer (eliminates cold start)
│   ├── slack_notifier/    ← SNS → Slack Block Kit alerts
│   └── prerace_check/     ← health checks for all 8 systems (run 30min pre-race)
│
├── 🧠  ml/
│   ├── training/pitstop/  ← XGBoost model + SageMaker inference script
│   ├── training/position/ ← Random Forest (12 features, trained, pending deploy)
│   └── evaluation/        ← SageMaker Pipeline DAG (5 steps)
│
├── 🖥️  frontend/           ← Next.js dashboard (deployed on Vercel)
│   └── app/
│       ├── page.tsx       ← live race predictions + circuit map
│       ├── history/       ← past session results
│       └── about/         ← architecture overview
│
├── 📊  monitoring/
│   └── newrelic_dashboard.json  ← import into NR UI to recreate dashboards
│
├── 📜  scripts/
│   ├── train_and_deploy.py
│   ├── generate_synthetic_data.py
│   └── seed_historical_data.py
│
├── 🏗️  terraform/
│   ├── environments/dev/   ← root module (all resources)
│   └── modules/            ← lambda · iam · api_gateway · sagemaker
│                              kinesis · cloudwatch · newrelic · eventbridge
│
├── 🧪  tests/
│   └── unit/               ← 20 pytest tests (all passing ✅)
│
└── .github/workflows/ci.yml  ← GitHub Actions: test → plan → approve → deploy
```

---

## AWS Resources & Cost

| Resource | Name | Cost / Race Weekend |
|:---------|:-----|--------------------:|
| SageMaker Serverless | `f1-mlops-pitstop-endpoint` | ~$0.40 |
| Lambda × 5 | `enrichment · rest-handler · prewarm · slack-notifier · prerace-check` | ~$0.01 |
| API Gateway | `f1-mlops-api` | ~$0.01 |
| Kinesis Firehose → New Relic | `f1-mlops-newrelic-metrics` | ~$0.05 |
| S3 | `f1-mlops-{data,artifacts}` | ~$0.05 |
| EventBridge + SNS + Secrets | — | $0.00 |
| **TOTAL** | | **~$0.52** |

> ELK stack and Grafana EC2 have been **retired** — replaced by New Relic (free tier covers race day usage).

---

## CI/CD Pipeline

```text
git push origin main
        │
        ▼
┌───────────────────────────────────────────────────────┐
│                  GitHub Actions                        │
│                                                        │
│  1 Test  ──────────────────────────────────────────►  │
│    • pytest 20 tests                                   │
│    • terraform fmt -check + validate                   │
│    • npm run build (frontend)                          │
│                                                        │
│  2 Plan  (main branch only) ───────────────────────►  │
│    • Two-pass manylinux Lambda ZIPs (binary + pure)    │
│    • Upload ZIPs to S3 (enrichment ~22MB with groq)    │
│    • terraform plan -out=tfplan.binary                 │
│    • Upload plan + ZIPs as artifacts                   │
│                                                        │
│  3 Deploy  (requires production env approval) ──────►  │
│    • terraform apply tfplan.binary                     │
│    • Redeploy Lambdas from S3 manylinux ZIPs           │
│      (Terraform archive_file re-zips source-only)      │
└───────────────────────────────────────────────────────┘
```

---

## Race Day Checklist 🏁

```bash
# ① 30 minutes before lights out — run pre-race health check
aws lambda invoke --function-name f1-mlops-prerace-check \
  --region us-east-1 --payload '{}' /tmp/prerace.json \
  && python3 -c "
import json
r = json.load(open('/tmp/prerace.json'))
status = 'ALL PASS ✅' if r['all_pass'] else f'FAILED: {r[\"failed_checks\"]}'
print(status)
for k, v in r['checks'].items():
    print(f'  {\"✓\" if v[\"pass\"] else \"✗\"} {k}: {v[\"detail\"]}')
"

# ② Enable live poller
aws events enable-rule --name f1-mlops-live-poller --region us-east-1

# ③ Verify predictions are flowing (~5 min after enabling)
curl https://xwmgxkj0r4.execute-api.us-east-1.amazonaws.com/v1/sessions/latest \
  | python3 -m json.tool | head -20

# ④ Monitor in New Relic
#   one.newrelic.com → Query: SELECT * FROM F1PitstopPrediction SINCE 30 minutes ago
#   Dashboard: import monitoring/newrelic_dashboard.json

# ⑤ After race — disable poller
aws events disable-rule --name f1-mlops-live-poller --region us-east-1
```

### Pre-Race Check Validates

| System | What It Checks |
|:-------|:--------------|
| SageMaker | Endpoint is `InService` |
| OpenF1 API | Returns 200 with session list |
| Groq secret | `gsk_...` key present in Secrets Manager |
| New Relic key | License key present |
| OpenF1 credentials | OAuth2 username/password present |
| EventBridge poller | Rule state (should be DISABLED pre-race) |
| S3 write | Write + delete probe object succeeds |
| Prewarm Lambda | Invocation succeeds |

---

## Observability

### New Relic (primary)

| Data Type | Source | Query |
|:----------|:-------|:------|
| Live predictions | Enrichment Lambda → Insights API | `SELECT * FROM F1PitstopPrediction SINCE 30 min ago` |
| Lambda metrics | CW Metric Stream → Firehose | `SELECT sum(aws.lambda.Invocations) FROM Metric FACET aws.lambda.FunctionName` |
| SageMaker metrics | CW Metric Stream → Firehose | `SELECT sum(aws.sagemaker.ModelLatency) FROM Metric` |
| Lambda logs + traces | NR Lambda Layer (Python 3.12) | NR APM → Lambda functions |

**Custom event fields:** `sessionKey · driverNumber · driverCode · team · pitstopProbability · confidence · tyreCompound · tyreAge · lapNumber · safetyCarActive · winProbability · aiCommentary`

**Dashboard:** Import `monitoring/newrelic_dashboard.json` into NR UI → Dashboards → Import.

### Sentry

Error tracking on all 5 Lambda functions. DSN stored in `TF_VAR_SENTRY_DSN` GitHub secret, injected at deploy time.

### Slack Alerts

`#f1-race-alerts` via **CloudWatch Alarm → SNS → AWS Chatbot** when `pitstop_probability > 0.85`.

---

## SageMaker Endpoint

```text
Container:   sagemaker-xgboost:1.7-1
Mode:        Serverless  (zero idle cost · 2048MB · max_concurrency=10)

Input:
  {"instances": [[tyre_age, stint_no, gap, air_temp, track_temp,
                  rainfall, sector_delta,
                  tyre_age_sq, heat_deg, wet_stint, abs_delta]]}

Output:
  {"predictions": [{"pitstop_probability": 0.731,
                    "confidence": 0.462,
                    "recommendation": "PIT"}]}
```

---

## 2026 Season

| Race | Circuit | Weekend | Status |
|:-----|:--------|:--------|:------:|
| 🇦🇺 R1 | Melbourne | Mar 14–16 | ✅ Live |
| 🇨🇳 R2 | Shanghai | Mar 21–23 | ✅ Live |
| 🇯🇵 R3 | **Suzuka** | **Apr 4–6** | 🟡 Next |
| 🇧🇭 R4 | Bahrain | Apr 11–13 | — |
| 🇸🇦 R5 | Jeddah | Apr 25–27 | — |
| 🇺🇸 R6 | Miami | May 2–4 | — |
| ⋮ | ⋮ | ⋮ | |

---

## Testing

```bash
pip install -r requirements.txt
pytest tests/unit/ -v
# ========================== 20 passed in 2.8s ==========================
```

Tests use `MOCK_SESSION_DATA` dicts — no API mocking required, no live AWS calls.

---

Built with obsession over a single race weekend.

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![AWS Lambda](https://img.shields.io/badge/AWS_Lambda-FF9900?style=for-the-badge&logo=awslambda&logoColor=white)
![SageMaker](https://img.shields.io/badge/SageMaker-FF9900?style=for-the-badge&logo=amazonaws&logoColor=white)
![Terraform](https://img.shields.io/badge/Terraform-7B42BC?style=for-the-badge&logo=terraform&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)
![New Relic](https://img.shields.io/badge/New_Relic-008C99?style=for-the-badge&logo=newrelic&logoColor=white)
![Sentry](https://img.shields.io/badge/Sentry-362D59?style=for-the-badge&logo=sentry&logoColor=white)
![Groq](https://img.shields.io/badge/Groq_Llama_3.3-F55036?style=for-the-badge&logo=meta&logoColor=white)
![OpenF1](https://img.shields.io/badge/OpenF1_API-e10600?style=for-the-badge)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white)
