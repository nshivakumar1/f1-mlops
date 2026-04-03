<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=e10600&height=200&section=header&text=F1%20MLOps&fontSize=72&fontColor=ffffff&fontAlignY=38&desc=Real-time%20Pit%20Stop%20Prediction%20%C2%B7%20Live%202026%20Season&descSize=18&descAlignY=58&animation=fadeIn&v=3" width="100%"/>

<a href="https://readme-typing-svg.demolab.com">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&size=22&pause=1000&color=E10600&center=true&vCenter=true&width=700&lines=Predict+pit+stops+before+the+team+radios+in.;XGBoost+%C2%B7+SageMaker+%C2%B7+AWS+Lambda+%C2%B7+OpenF1;88.5%25+accuracy+%C2%B7+%240.47+per+race+weekend;Live+since+Australian+GP+%C2%B7+3+races+and+counting." alt="Typing SVG" />
</a>

<br/><br/>

[![CI](https://github.com/nshivakumar1/f1-mlops/actions/workflows/ci.yml/badge.svg)](https://github.com/nshivakumar1/f1-mlops/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-20%20passing-22c55e?style=flat-square&logo=pytest&logoColor=white)](tests/unit/)
[![Model AUC](https://img.shields.io/badge/XGBoost%20AUC-0.8854-3b82f6?style=flat-square&logo=scikit-learn&logoColor=white)](ml/training/pitstop/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](lambda/)
[![Terraform](https://img.shields.io/badge/Terraform-1.9.8-7B42BC?style=flat-square&logo=terraform&logoColor=white)](terraform/)
[![AWS](https://img.shields.io/badge/AWS-us--east--1-FF9900?style=flat-square&logo=amazonaws&logoColor=white)](https://aws.amazon.com)
[![Vercel](https://img.shields.io/badge/Frontend-Vercel-000000?style=flat-square&logo=vercel&logoColor=white)](https://vercel.com)
[![New Relic](https://img.shields.io/badge/Observability-New%20Relic-008C99?style=flat-square&logo=newrelic&logoColor=white)](https://newrelic.com)
[![Sentry](https://img.shields.io/badge/Errors-Sentry-362D59?style=flat-square&logo=sentry&logoColor=white)](https://sentry.io)
[![Cost](https://img.shields.io/badge/cost%2Frace%20weekend-%240.47-22c55e?style=flat-square&logo=amazonaws&logoColor=white)](#-aws-cost)
[![CodeRabbit](https://img.shields.io/badge/AI%20Reviews-CodeRabbit-FF570A?style=flat-square&logo=coderabbit&logoColor=white)](https://coderabbit.ai)

<br/>

<!-- KEY STATS -->
![](https://img.shields.io/badge/Drivers%20Tracked-22-e10600?style=for-the-badge)
![](https://img.shields.io/badge/Prediction%20Accuracy-88.5%25-e10600?style=for-the-badge)
![](https://img.shields.io/badge/Update%20Interval-60s-e10600?style=for-the-badge)
![](https://img.shields.io/badge/Races%20Live-3-e10600?style=for-the-badge)
![](https://img.shields.io/badge/Cost%2FRace-$0.47-e10600?style=for-the-badge)

</div>

---

## Demo

> 📹 **Drop a screen recording here** — drag an MP4 directly into this file on GitHub.com (supports up to 10MB).
> Suggested: 30s clip of the live dashboard updating driver cards, pitstop probabilities, and AI commentary.

---

## What It Does

Every **60 seconds** during a live race, for all 22 drivers simultaneously:

| Step | What Happens |
|:-----|:-------------|
| 🔌 **Ingest** | Pulls telemetry from OpenF1 API (OAuth2) — stints, laps, intervals, weather, race control |
| 🧠 **Predict** | Engineers 11 features per driver, scores through XGBoost on SageMaker Serverless (AUC 0.8854) |
| 🏆 **Win Probability** | Computed inline — live position, gap to leader, tyre freshness, team strength |
| 💬 **AI Commentary** | Two broadcast-style sentences via Groq (Llama 3.3 70B) |
| 📡 **Serve** | Stored in S3, exposed via API Gateway REST API, displayed on Next.js frontend |
| 🔔 **Alert** | Slack notification when pit probability > 85% via AWS Chatbot |
| 📊 **Observe** | Custom events streamed to New Relic · errors captured to Sentry |

<details>
<summary>⚙️ Full Architecture Diagram</summary>

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
                   │  • Chequered flag detection + auto-disable     │
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
           │  SNS → Chatbot  │  │  GET /sessions/latest                │
           │  → Slack 🔔     │  │  GET /predict/positions/{key}        │
           └─────────────────┘  │  GET /positions/latest               │
                                │  GET /track/{circuit_key}            │
                                └───────┬──────────────────────────────┘
                                        │
                   ┌────────────────────▼──────────────────────────┐
                   │       Next.js Frontend  (Vercel)              │
                   │  Live dashboard · Race history · Circuit map  │
                   │  Polls API every 30s · Map updates every 5s   │
                   └───────────────────────────────────────────────┘

  GitHub → GitHub Actions [Test → Plan → Approve → Deploy]
  CW Metric Stream → Kinesis Firehose → New Relic
```

</details>

---

## Models

| Model | Algorithm | Metric | Status |
|:------|:----------|:------:|:------:|
| 🟢 **Pitstop** | XGBoost | AUC **0.8854** | ✅ Live — SageMaker Serverless |
| 🏆 **Win Probability** | Inline scoring | Position · Gap · Tyre · Team | ✅ Live — no extra endpoint |
| 🔵 Position Finish | Random Forest | 12 features trained | 🔜 Pending deployment |
| 🟡 Safety Car | LightGBM | — | 📋 Planned |

<details>
<summary>📐 Feature Engineering & Win Probability Formula</summary>

```
RAW (7)                          ENGINEERED (4)
──────────────────────           ──────────────────────────────────────
tyre_age          ──────────────► tyre_age²              (degradation curve)
stint_number                    ► track_temp × tyre_age  (heat deg model)
gap_to_leader                   ► rainfall × stint_number (wet strategy)
air_temperature                 ► |sector_delta|          (consistency proxy)
track_temperature
rainfall
sector_delta
                    11 features → 1 probability → PIT / STAY OUT
```

| Signal | Weight (racing) | Weight (safety car) |
|:-------|:---------------:|:-------------------:|
| Gap ranking (position) | 40% | 55% |
| Gap to leader | 25% | 0% |
| Team strength | 20% | 20% |
| Tyre freshness | 10% | 15% |
| Pitstop stability | 5% | 10% |

</details>

---

## Live API

**Base URL:** `https://xwmgxkj0r4.execute-api.us-east-1.amazonaws.com/v1`

```bash
# All 22 drivers — predictions, win probability, AI commentary
curl "$API/sessions/latest" | jq '{session: .session_key, commentary: .commentary, top3: .predictions[:3]}'
```

| Endpoint | Description |
|:---------|:------------|
| `GET /sessions/latest` | All 22 drivers — pitstop prob, win prob, AI commentary |
| `GET /predict/positions/{session_key}` | Cached predictions for a past session |
| `GET /positions/latest` | Live driver XY positions from OpenF1 |
| `GET /track/{circuit_key}` | Circuit layout (SVG coordinates) |
| `POST /predict/pitstop` | On-demand single-driver prediction |

---

## 2026 Season

<div align="center">

| # | Race | Circuit | Weekend | System | Status |
|:-:|:-----|:--------|:--------|:------:|:------:|
| R1 | 🇦🇺 Australian GP | Melbourne | Mar 14–16 | ✅ Built | ✅ Live |
| R2 | 🇨🇳 Chinese GP | Shanghai | Mar 21–23 | ✅ Built | ✅ Live |
| R3 | 🇯🇵 Japanese GP | Suzuka | Mar 28–30 | ✅ Built | ✅ Live |
| R4 | 🇧🇭 ~~Bahrain GP~~ | ~~Sakhir~~ | ~~Apr 11–13~~ | — | ❌ Cancelled |
| R5 | 🇸🇦 ~~Saudi Arabian GP~~ | ~~Jeddah~~ | ~~Apr 25–27~~ | — | ❌ Cancelled |
| R6 | 🇺🇸 **Miami GP** | **Miami** | **May 2–4** | ✅ Ready | 🟡 Next |
| R7 | 🇮🇹 Emilia Romagna GP | Imola | May 16–18 | ✅ Ready | — |
| R8 | 🇲🇨 Monaco GP | Monte Carlo | May 23–25 | ✅ Ready | — |
| R9 | 🇪🇸 Spanish GP | Barcelona | Jun 6–8 | ✅ Ready | — |
| R10 | 🇨🇦 Canadian GP | Montreal | Jun 13–15 | ✅ Ready | — |
| R11 | 🇦🇹 Austrian GP | Red Bull Ring | Jun 27–29 | ✅ Ready | — |
| R12 | 🇬🇧 British GP | Silverstone | Jul 4–6 | ✅ Ready | — |
| R13 | 🇧🇪 Belgian GP | Spa | Jul 25–27 | ✅ Ready | — |
| R14 | 🇭🇺 Hungarian GP | Budapest | Aug 1–3 | ✅ Ready | — |
| R15 | 🇳🇱 Dutch GP | Zandvoort | Aug 29–31 | ✅ Ready | — |
| R16 | 🇮🇹 Italian GP | Monza | Sep 5–7 | ✅ Ready | — |
| R17 | 🇦🇿 Azerbaijan GP | Baku | Sep 19–21 | ✅ Ready | — |
| R18 | 🇸🇬 Singapore GP | Marina Bay | Oct 3–5 | ✅ Ready | — |
| R19 | 🇺🇸 United States GP | Austin | Oct 17–19 | ✅ Ready | — |
| R20 | 🇲🇽 Mexico City GP | Mexico City | Oct 24–26 | ✅ Ready | — |
| R21 | 🇧🇷 São Paulo GP | Interlagos | Nov 7–9 | ✅ Ready | — |
| R22 | 🇺🇸 Las Vegas GP | Las Vegas | Nov 20–22 | ✅ Ready | — |
| R23 | 🇶🇦 Qatar GP | Lusail | Nov 28–30 | ✅ Ready | — |
| R24 | 🇦🇪 Abu Dhabi GP | Yas Marina | Dec 5–7 | ✅ Ready | — |

> ✅ Built = ran live · ✅ Ready = deployed, poller on standby · ❌ Cancelled

</div>

---

<details>
<summary>🚀 Quick Start</summary>

### Prerequisites

```bash
aws --version       # AWS CLI v2
terraform -version  # ≥ 1.9.8
python3 --version   # ≥ 3.9
node --version      # ≥ 20
```

### Bootstrap Infrastructure

```bash
cd terraform/environments/dev
terraform init && terraform apply -auto-approve
```

### Train & Deploy Model

```bash
pip install xgboost scikit-learn pandas boto3 joblib
python3 scripts/generate_synthetic_data.py --bucket f1-mlops-data-297997106614 --n-races 50
python3 scripts/seed_historical_data.py --bucket f1-mlops-data-297997106614
python3 scripts/train_and_deploy.py --bucket f1-mlops-data-297997106614
```

### Run Frontend Locally

```bash
cd frontend && npm install && npm run dev   # http://localhost:3000
```

</details>

<details>
<summary>🗂️ Repository Structure</summary>

```
f1-mlops/
├── 🔬 lambda/
│   ├── enrichment/        ← live poller: OpenF1 → features → SageMaker → S3/NR
│   ├── rest_handler/      ← API Gateway: /sessions · /positions · /track
│   ├── prewarm/           ← SageMaker cold-start eliminator
│   ├── slack_notifier/    ← SNS → Slack Block Kit alerts
│   └── prerace_check/     ← validates 8 systems 30 min pre-race
├── 🧠 ml/
│   ├── training/pitstop/  ← XGBoost + SageMaker inference script
│   ├── training/position/ ← Random Forest (trained, pending deploy)
│   └── evaluation/        ← SageMaker Pipeline DAG
├── 🖥️ frontend/            ← Next.js on Vercel
├── 🏗️ terraform/           ← lambda · iam · api_gateway · sagemaker · kinesis
├── 🧪 tests/unit/          ← 20 pytest tests (all passing)
└── .github/workflows/ci.yml
```

</details>

<details>
<summary>🔁 CI/CD Pipeline</summary>

```
git push origin main
        │
        ▼
  1 Test   → pytest · terraform fmt/validate · npm run build
  2 Plan   → manylinux Lambda ZIPs · terraform plan · upload artifacts
  3 Deploy → production env approval gate → terraform apply → redeploy Lambdas
```

</details>

<details>
<summary>🏁 Race Day Checklist</summary>

```bash
# ① Pre-race health check (30 min before)
aws lambda invoke --function-name f1-mlops-prerace-check \
  --region us-east-1 --payload '{}' /tmp/prerace.json \
  && python3 -c "import json; r=json.load(open('/tmp/prerace.json')); print('ALL PASS ✅' if r['all_pass'] else f'FAILED: {r[\"failed_checks\"]}')"

# ② Enable live poller
aws events enable-rule --name f1-mlops-live-poller --region us-east-1

# ③ Verify predictions flowing (~5 min later)
curl https://xwmgxkj0r4.execute-api.us-east-1.amazonaws.com/v1/sessions/latest | python3 -m json.tool | head -20

# ④ Monitor: one.newrelic.com → SELECT * FROM F1PitstopPrediction SINCE 30 minutes ago

# ⑤ After race (also auto-fires on chequered flag)
aws events disable-rule --name f1-mlops-live-poller --region us-east-1
```

</details>

<details>
<summary>💰 AWS Cost Breakdown</summary>

| Resource | Cost / Race Weekend |
|:---------|--------------------:|
| SageMaker Serverless | ~$0.40 |
| Lambda × 5 | ~$0.01 |
| API Gateway | ~$0.01 |
| Kinesis Firehose → New Relic | ~$0.05 |
| S3 | ~$0.05 |
| EventBridge + SNS + Secrets | $0.00 |
| **TOTAL** | **~$0.52** |

</details>

---

<div align="center">

### Built With

<img src="https://skillicons.dev/icons?i=python,aws,terraform,nextjs,vercel,github&theme=dark&perline=6" />

<br/><br/>

### Activity

[![Activity Graph](https://github-readme-activity-graph.vercel.app/graph?username=nshivakumar1&theme=redwhite&bg_color=0d1117&color=e10600&line=e10600&point=ffffff&area=true&hide_border=true)](https://github.com/nshivakumar1)

<br/>

*Built with obsession over a single race weekend.*

<img src="https://capsule-render.vercel.app/api?type=waving&color=e10600&height=100&section=footer" width="100%"/>

</div>
