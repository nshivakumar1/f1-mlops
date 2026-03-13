# F1 MLOps — Claude Instructions

## Project Overview
XGBoost-based F1 pitstop prediction system deployed on AWS. Infrastructure managed by Terraform, CI/CD via AWS CodePipeline + GitHub Actions.

- **Repo:** `nshivakumar1/f1-mlops` (NOT `theinfinityloop/f1-mlops`)
- **AWS Account:** `297997106614`, region `us-east-1`
- **ELK Stack EC2:** `i-05e4b8ddbcce9647d` (t3.medium, stopped between races — IP changes on restart)

---

## Known Mistakes — Do Not Repeat

### 1. Terraform Version
- **Wrong:** `"1.14.0"` — this version does not exist
- **Correct:** `"1.9.8"` (used in both `buildspec.yml` and `.github/workflows/ci.yml`)

### 2. buildspec.yml — No Block Scalars in Commands
- **Wrong:** Using `- |` multiline block scalars in `commands:` lists — CodeBuild YAML parser rejects them
- **Correct:** Put multi-stage logic in `scripts/ci_build.sh` and call `bash scripts/ci_build.sh` from buildspec

### 3. Terraform Download in CodeBuild — Use curl Not wget
- **Wrong:** `wget -q` downloads HTML error pages silently without failing; unzip then fails on non-zip content
- **Correct:** `curl -fsSL -o /tmp/terraform.zip <url>` — fails loudly on HTTP errors

### 4. CodePipeline Deploy Stage — PrimarySource Required
- **Wrong:** Deploy stage with multiple input artifacts but no `PrimarySource` — CodeBuild can't find `buildspec.yml`
- **Correct:** Always set `PrimarySource = "source_output"` when passing multiple artifacts to a CodeBuild action

### 5. Lambda ZIP Files — Must Be in plan_output Artifact
- Lambda module uses `data "archive_file"` which creates ZIPs during `terraform plan`
- ZIPs are gitignored (`terraform/modules/lambda/*.zip`) and don't exist in fresh CodeBuild workspaces
- **Fix:** Include ZIPs in `buildspec.yml` artifacts; copy from `CODEBUILD_SRC_DIR_plan_output` before `terraform apply`
- In `scripts/ci_build.sh` apply stage, copy ZIPs before running terraform:
  ```bash
  for func in enrichment rest_handler prewarm slack_notifier; do
    if [ -f "${PLAN_SRC}/terraform/modules/lambda/${func}.zip" ]; then
      cp "${PLAN_SRC}/terraform/modules/lambda/${func}.zip" terraform/modules/lambda/${func}.zip
    fi
  done
  ```

### 6. CodeStar/CodeConnections — Use AVAILABLE Connection
- **Wrong:** Creating a new `aws_codestarconnections_connection` resource — it starts as PENDING and requires manual activation in console
- **Correct:** Pass the ARN of an existing AVAILABLE connection via `codestar_connection_arn` variable
- **Active connection ARN:** `arn:aws:codeconnections:us-east-1:297997106614:connection/6abde493-3ad0-4a50-8f39-44f542d93bd6`

### 7. GitHub Owner Tag
- **Wrong:** `theinfinityloop` anywhere in Terraform configs
- **Correct:** `nshivakumar1`

### 8. OpenSearch Module — Deleted
- `terraform/modules/opensearch/` was deleted entirely — it had an invalid `dashboard_endpoint` attribute
- The project uses ELK on EC2, not AWS OpenSearch — do not recreate this module

### 9. Logstash 8.x Config Syntax
- **Wrong:** Inline `if` syntax: `if [field] == true { mutate { ... } }`
- **Correct:** Multi-line block format:
  ```
  if [field] {
    mutate { add_tag => ["approved"] }
  } else {
    mutate { add_tag => ["rejected"] }
  }
  ```

### 10. ELK Stack Permissions
- Logstash container runs as uid 1000 — always run `chown -R 1000:1000 /opt/elk/logstash` after creating config dirs
- Template file: `terraform/modules/elk/templates/elk_setup.sh.tpl`

### 11. AWS Chatbot — Cannot Use boto3 SDK Directly
- `boto3.client('chatbot')` fails with DNS resolution error — `chatbot.us-east-1.amazonaws.com` does not resolve
- `aws chatbot` CLI commands also fail with same DNS error
- **Correct approach:** Use CloudFormation `AWS::Chatbot::SlackChannelConfiguration` resource
- **Active config ARN:** `arn:aws:chatbot::297997106614:chat-configuration/slack-channel/f1-mlops-slack-config`
- **Workspace ID:** `T0AE0EP7D27`, **Channel ID:** `C0AL3J7H0C9`

### 12. AWS Chatbot — Raw SNS Messages Not Supported
- `aws sns publish` with custom text → Chatbot logs "Event received is not supported" and silently drops it
- **Only CloudWatch Alarm state changes** (and other specific AWS service events) are forwarded to Slack
- To test Slack integration: `aws cloudwatch set-alarm-state --alarm-name <name> --state-value ALARM --state-reason "test"`

### 13. terraform fmt Must Pass Before Push
- GitHub Actions enforces `terraform fmt -check -recursive terraform/`
- Always run `terraform fmt -recursive terraform/` before committing any `.tf` file changes

### 14. OpenF1 API — 404 Means Empty Result, Not Error
- During live sessions, OpenF1 returns `{"detail":"No results found."}` with HTTP 404 for empty queries (e.g. stints before any pit stop)
- **Wrong:** Let `urllib.error.HTTPError` 404 propagate — all drivers silently return None
- **Correct:** Catch 404 in `_get()` and return `[]` — empty data handled gracefully downstream

### 15. OpenF1 Rate Limit — Batch Calls, Not Per-Driver
- OpenF1 enforces **60 requests/minute** per authenticated user
- Per-driver calls (22 drivers × 3 endpoints = 66 calls) exceed the limit → 429 Too Many Requests
- **Wrong:** Call `stints?session_key=X&driver_number=Y` for each driver separately
- **Correct:** Call `stints?session_key=X` (no driver filter) → group by `driver_number` in Python
- Reduces from 66 API calls to 3 per invocation

### 16. SageMaker Feature Mismatch — Model Expects 11, Not 7
- The XGBoost model was trained with 11 features (7 raw + 4 derived)
- Derived features: `tyre_age_sq`, `heat_deg_interaction` (track_temp × tyre_age), `wet_stint` (rainfall × stint_number), `abs_sector_delta`
- **Wrong:** Send only the 7 raw features → `Feature shape mismatch, expected: 11, got 7` (HTTP 500)
- **Correct:** Always compute and append all 4 derived features before calling `invoke_endpoint`
- Feature list in `code/feature_names.json` inside `model.tar.gz` is the source of truth

### 17. API Gateway Routes — Add to Terraform AND Deploy Immediately
- Adding a route to the Lambda handler is not enough — must also add it to `terraform/modules/api_gateway/main.tf`
- If route is needed urgently (during a race), add via AWS CLI + `aws apigateway create-deployment` first, then update Terraform
- `api_key_required = true` (the default) blocks public frontend calls with 403 "Missing Authentication Token"
- All public GET endpoints should have `api_key_required = false`

### 18. Sessions List — Filter Non-Numeric Keys
- When `get_latest_session()` fails, session_key falls back to `"latest"` (string)
- This creates `logs/inference/session_latest/` in S3 which appears in the sessions list
- **Correct:** In `handle_sessions_list()`, only include session keys where `parts[-1].isdigit()`
- Delete junk: `aws s3 rm s3://BUCKET/logs/inference/session_latest/ --recursive`

### 19. Unit Tests — Update When Function Signatures Change
- `build_feature_vector` signature changed from `(session_key, driver_number)` to `(driver_number, session_data)`
- Tests were patching `openf1_client.get_stints` etc. — those functions no longer exist in the hot path
- **Correct:** Tests now build a `MOCK_SESSION_DATA` dict and pass it directly — no mocking needed
- Always run `pytest tests/unit/ -v` locally before pushing after refactors

### 20. OpenF1 OAuth2 — Credentials Format in Secrets Manager
- Secret name: `f1-mlops/openf1-credentials`
- Format: `{"username": "email@example.com", "password": "yourpassword"}`
- Token endpoint: `POST https://api.openf1.org/token` with `grant_type=password`
- Token valid 1 hour — cached at module level in Lambda, refreshed 60s before expiry
- Register/pay at: `https://buy.stripe.com/eVqcN41BPekP0iIalBcEw02`

---

## Architecture

```
GitHub → CodePipeline → [Test → TerraformPlan → Approve → Deploy]
                              ↓
                        Lambda (enrichment, rest_handler, prewarm, slack_notifier)
                        SageMaker Serverless Endpoint
                        S3 (data + artifacts)
                        Kinesis Firehose → ELK on EC2
                        CloudWatch Alarms → SNS → AWS Chatbot → Slack #f1-race-alerts
```

## Key File Paths
- `buildspec.yml` — CodeBuild spec (calls `scripts/ci_build.sh`)
- `scripts/ci_build.sh` — Multi-stage build logic (test / plan / apply)
- `terraform/environments/dev/` — Root Terraform config
- `terraform/modules/lambda/main.tf` — Uses `archive_file` data sources for ZIPs
- `terraform/modules/elk/templates/elk_setup.sh.tpl` — ELK EC2 user-data
- `terraform/modules/codepipeline/main.tf` — Pipeline with conditional CodeStar connection

## Post-Race Build Plan

### Gemini 2.5 Pro — Race Commentary Layer
- **API key:** stored at `arn:aws:secretsmanager:us-east-1:297997106614:secret:f1-mlops/gemini-api-key-GKgHqf`
- **Secret name:** `f1-mlops/gemini-api-key`
- **Model:** `gemini-2.5-pro` (user has Google One AI Premium subscription)
- **Use:** Generate 2-sentence live race strategy commentary per lap, added to enrichment Lambda output
- **Lambda IAM:** Must add `secretsmanager:GetSecretValue` permission for `f1-mlops/gemini-api-key`
- **Python package:** `google-generativeai` — add to `lambda/enrichment/requirements.txt`

### Frontend (Next.js → Vercel)
- 3 pages: Live predictions, Race history, About/architecture
- Polls API Gateway every 30s during race
- Displays pitstop probability per driver + Gemini commentary card
- History page: predicted pitstop lap vs actual (accuracy metric)
- Build after Chinese GP when real race data is available

### Race Outcome Model (XGBoost)
- Separate model from pitstop predictor
- Input: current position, gap to leader, tyre strategy, historical circuit performance
- Output: win/podium probability per driver, updated each lap
- Training data: Ergast API + FastF1 historical races

---

## Race Day Checklist
1. Start EC2: `aws ec2 start-instances --instance-ids i-05e4b8ddbcce9647d --region us-east-1`
2. Get new IP: `aws ec2 describe-instances --instance-ids i-05e4b8ddbcce9647d --region us-east-1 --query 'Reservations[0].Instances[0].PublicIpAddress' --output text`
3. Update `logstash_url` Terraform variable with new IP
4. Enable live poller 30 min before session: `aws events enable-rule --name f1-mlops-live-poller --region us-east-1`
5. Disable after session: `aws events disable-rule --name f1-mlops-live-poller --region us-east-1`
