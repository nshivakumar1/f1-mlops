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

### 21. OpenF1 Pre-populates Full Season Calendar — `get_latest_session()` Bug

- OpenF1 returns ALL sessions for the year (including future ones like Abu Dhabi in December)
- `sessions[-1]` picks the session with the latest date, which is WRONG during the actual season
- **Correct:** Filter to sessions where `date_start <= now_utc` before picking the last one
- Fixed in `openf1_client.py` `get_latest_session()` to use `datetime.utcnow()` comparison

### 22. OpenF1 `race_control` Null Fields — `.upper()` on None

- `msg.get("flag", "")` returns `None` (not `""`) when the API field is `null`
- Calling `.upper()` on `None` raises `AttributeError`
- **Correct:** Use `(msg.get("flag") or "").upper()` pattern everywhere

### 23. `aws lambda update-function-configuration --environment` Replaces ALL Env Vars

- Passing `--environment Variables={KEY=VALUE}` with only one key **wipes all other env vars**
- **Correct:** Always include all existing env vars when calling `update-function-configuration`
- For a quick race-day session override, use EventBridge target `Input` JSON instead:

  ```bash
  aws events put-targets --rule f1-mlops-live-poller --targets '[{"Id":"EnrichmentLambda","Arn":"...","Input":"{\"session_key\":\"11236\"}"}]'
  ```

### 24. Terraform `templatefile()` Interprets `%{` as Template Directive

- `elk_setup.sh.tpl` contained Elasticsearch index pattern `"f1-ec2-metrics-%{+YYYY.MM.dd}"`
- Terraform's `templatefile()` interprets `%{` as the start of a template directive (`%{if ...}`, `%{for ...}`)
- **Wrong:** `"f1-ec2-metrics-%{+YYYY.MM.dd}"` → TerraformPlan fails: `Invalid template directive`
- **Correct:** Escape with double percent: `"f1-ec2-metrics-%%{+YYYY.MM.dd}"` — `templatefile()` outputs literal `%{`
- This applies to ANY `%{` literal in `.tpl` files processed by `templatefile()`

### 25. Context Window Exhaustion — Agent Restart Loses In-Progress State

- Long debugging sessions (Logstash + race day fixes + Gemini integration) can exhaust context
- When the agent is restarted, it resumes from a summary — in-progress edits that were identified but not yet applied are lost
- **Prevention:** After identifying a fix, apply it immediately before moving on to the next investigation
- **Recovery:** Check CLAUDE.md "Pending Tasks" and git log to reconstruct what was done vs what was pending

### 26. Logstash Grok Patterns in `.tpl` Files — All `%{` Must Be Escaped

- `elk_setup.sh.tpl` line 323–327 had Logstash grok patterns: `%{DATA:request_id}`, `%{NUMBER:...}`, `%{GREEDYDATA:...}`
- These are also interpreted as Terraform template directives — same `%%{` escape required
- **Fix applied:** All grok patterns now use `%%{DATA:...}`, `%%{NUMBER:...}`, `%%{GREEDYDATA:...}`
- **Rule:** Every `%{` in any `.tpl` file must be doubled to `%%{` regardless of context

### 27. Lambda Deployment Packages — Must Build for Linux (manylinux), Not macOS

- `pip install` on macOS (arm64/x86) produces macOS-specific `.so` binaries (e.g. gRPC `cygrpc`)
- Lambda runs on Amazon Linux 2 (x86_64) — macOS binaries cause `Runtime.ImportModuleError`
- **Wrong:** `pip install -r requirements.txt -t build/` on macOS
- **Correct:** `pip install --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all: -r requirements.txt -t build/`
- Packages >50MB must be uploaded via S3, not direct ZIP (`RequestEntityTooLargeException`)
- Lambda ZIPs for enrichment are ~80MB → always use: `aws s3 cp enrichment.zip s3://BUCKET/lambda-deployments/enrichment.zip` then `--s3-bucket/--s3-key`

### 28. Gemini API — `limit: 0` Means Billing Project Issue, Not Exhausted Quota

- Free tier `limit: 0` on `gemini-2.0-flash` and `gemini-2.5-pro` means the Google Cloud project has billing enabled, disabling free-tier quotas, but paid-tier quota is also unconfigured
- Google One AI Premium subscription does NOT automatically give developer API access
- **Fix:** Either create a new GCP project without billing (free tier: 1,500 req/day), or configure paid-tier quota in Cloud Console
- **Resolution:** Switched to Groq (free, no card required) — `gsk_*` key stored in `f1-mlops/gemini-api-key` secret

### 29. AI Commentary — Groq (Llama 3.3 70B), Secret Stores Groq Key

- Model: `llama-3.3-70b-versatile` via `groq>=0.11.0` SDK
- Secret name still `f1-mlops/gemini-api-key` (not renamed to avoid Terraform changes)
- Lambda env var: `GEMINI_SECRET_NAME=f1-mlops/gemini-api-key`
- Secret format: plain string `gsk_...` (code handles both plain and `{"api_key":"..."}` JSON)
- Free tier: 14,400 req/day, 30 req/min — well within 1 req/30s race day usage

### 30. CodePipeline Does NOT Auto-Deploy Lambda Code — Manual Deploy Required

- TerraformPlan stage was failing (grok `%%{` fix only just pushed), so Lambda code from `lambda/` directory was never deployed via pipeline
- Manually deployed: `f1-mlops-enrichment` (Groq), `f1-mlops-rest-handler` (commentary field), `f1-mlops-slack-notifier` (AI label)
- After pipeline is fixed and Approve stage is clicked, Terraform will re-deploy from ZIPs — ensure `GEMINI_SECRET_NAME` env var is in `terraform/modules/lambda/main.tf`
- **Race day:** Always verify Lambda `LastModified` timestamps match expected deploy dates before enabling the poller

### 31. Vercel Deployment — `rootDirectory` Not Valid in `vercel.json`

- `vercel.json` does not accept `rootDirectory` property — schema validation fails
- **Correct:** Set Root Directory to `frontend` in Vercel dashboard → Project → Settings → General
- `vercel.json` at repo root should only contain valid properties (e.g. `framework`)

### 33. Terraform `templatefile()` — `\${VAR}` Does NOT Escape, Use `$${VAR}`

- `\${INSTANCE_ID}` in `.tpl` files is NOT an escape — Terraform still tries to interpolate it as a template variable
- **Wrong:** `instance_id: \${INSTANCE_ID}` → `vars map does not contain key "INSTANCE_ID"`
- **Correct:** `instance_id: $${INSTANCE_ID}` — `$$` is the escape, outputs literal `${INSTANCE_ID}` at runtime
- Applies to any runtime shell/Metricbeat/Logstash variable references in `.tpl` files that should not be resolved by Terraform

### 34. EC2 `user_data` 16 KB Limit — Use S3 Bootstrapper for Large Scripts

- EC2 `user_data` is limited to 16384 bytes raw; `elk_setup.sh.tpl` renders to ~22 KB
- **Wrong:** `user_data = templatefile(...)` directly → `expected length of user_data to be in the range (0 - 16384)`
- **Correct:** Add `aws_s3_object` to upload the rendered script to S3, then use a minimal ~5-line `user_data` that downloads and runs it:
  ```hcl
  resource "aws_s3_object" "elk_setup" {
    bucket  = var.s3_bucket
    key     = "scripts/elk_setup.sh"
    content = templatefile("${path.module}/templates/elk_setup.sh.tpl", { ... })
  }
  # user_data becomes: aws s3 cp s3://BUCKET/scripts/elk_setup.sh /tmp/ && bash /tmp/elk_setup.sh
  ```
- Add `depends_on = [aws_s3_object.elk_setup]` to the `aws_instance` resource

### 35. GitHub Actions `download-artifact@v4` — LCA Strips Common Path Prefix

- When uploading multiple paths, `upload-artifact@v4` calculates the Least Common Ancestor (LCA) and strips it from paths inside the artifact
- Uploading `terraform/environments/dev/tfplan.binary` + `terraform/modules/lambda/*.zip` → LCA is `terraform/`, stored internally as `environments/dev/tfplan.binary`
- `download-artifact@v4` with `path: .` extracts to `./environments/dev/tfplan.binary` — missing the `terraform/` prefix
- **Correct:** Use `path: terraform` on download to restore full `terraform/environments/dev/tfplan.binary` path

### 36. Terraform State Drift — Import Existing Resources Before Apply

- Resources created manually or in previous pipeline runs may exist in AWS but not in Terraform state
- Apply will fail with `ConflictException` or `Duplicate` errors trying to recreate them
- **Fix:** Run `terraform import <resource_address> <resource_id>` locally to bring them into state
  ```bash
  terraform import module.elk.aws_key_pair.elk f1-mlops-elk-key
  terraform import "module.api_gateway.aws_api_gateway_resource.sessions" "<api-id>/<resource-id>"
  ```
- After importing locally, push an empty commit to trigger a fresh plan (the old plan binary becomes stale after any state change)

### 37. Terraform `archive_file` Re-Zips Source-Only in CI Deploy Job — Lambda Loses Dependencies

- `data "archive_file"` in Terraform re-runs during `terraform apply` in the deploy job context, which has no pip packages installed
- Result: enrichment Lambda gets replaced with a ~9KB source-only ZIP → `No module named 'groq'` at runtime
- **Fix:** After `terraform apply`, redeploy Lambda functions from the pre-built manylinux ZIPs in the plan artifact:
  - ZIPs >50MB (enrichment ~80MB): upload to S3, then `aws lambda update-function-code --s3-bucket/--s3-key`
  - ZIPs <50MB: `aws lambda update-function-code --zip-file fileb://...`
- This step is now in `.github/workflows/ci.yml` after the `terraform apply` step
- **Race day:** If a CI run was approved while the race is live, the Lambda will be broken for ~1 min until the redeploy step finishes — watch for `No module named 'groq'` errors in CloudWatch

### 38. API Gateway `test-invoke-method` Bypasses Stage — Not a Reliable Proxy for Public URL

- `aws apigateway test-invoke-method` invokes the Lambda integration directly, bypassing the stage deployment entirely
- A route can return 200 via test-invoke but 403 `MissingAuthenticationTokenException` via the public URL if the route was never included in a stage deployment
- **Root cause:** Routes created via `terraform import` (without a full `terraform apply`) are in AWS config but not in the deployed stage snapshot
- **Fix:** Delete and recreate the method + integration with `put-method` + `put-integration`, then `create-deployment`

### 32. ELK/Kibana — RETIRED, Use Grafana for Everything

- ELK was too complex to maintain: 22KB user_data limit, Logstash config syntax, `%{` escaping, Docker boot time
- **Decision (2026-03-15):** Migrated ALL race visualizations to Grafana
- Grafana now has two datasources: CloudWatch (infra) + Infinity (F1 REST API → live race predictions)
- **Live race dashboard:** `http://<grafana-ip>:3000/d/f1-race-live` — auto-refresh 30s
- **Infra dashboard:** `http://<grafana-ip>:3000/d/f1-infra-metrics` — Lambda/SageMaker CloudWatch metrics
- ELK EC2 (`i-09b80fc03109c35a1`) is stopped — do NOT restart it unless specifically re-evaluating ELK

### 33. Grafana 12 Dashboard API — Do NOT Set `schemaVersion` or Use Wrong Auth

- **Wrong:** Creating dashboards via API with `"schemaVersion": 39` — causes panels to render "No data" silently even when CloudWatch query returns data
- **Correct:** Omit `schemaVersion` entirely when POSTing dashboards via API, or clone structure from an existing working dashboard
- **Wrong:** CloudWatch datasource `allowed_auth_providers` default (`default,keys,credentials`) blocks `ec2_iam_role` — panels show "No data" with error `"trying to use non-allowed auth method ec2_iam_role"`
- **Correct:** Add `allowed_auth_providers = default,keys,credentials,ec2_iam_role` to `/etc/grafana/grafana.ini` under `[aws]` section, then restart Grafana
- CloudWatch query format requires: `"queryMode": "Metrics"`, `"statistics": ["Average"]` (array not string), `"matchExact": true`
- EC2 basic monitoring period is 5 minutes — use `"period": "300"` not `"period": "60"`

### 34. Grafana Infinity Datasource — Install Before First Race

- Infinity plugin (`yesoreyeram-infinity-datasource`) is not bundled with Grafana — must be installed
- Already installed on current Grafana EC2 (`i-09c735935e93429d5`) — persists in `/var/lib/grafana/plugins/`
- If instance is replaced: `ssh ubuntu@<ip> "sudo grafana-cli plugins install yesoreyeram-infinity-datasource && sudo systemctl restart grafana-server"`
- Datasource UID: `cfg1tmj8jbu2oa` (created via API, persists in Grafana DB)
- If datasource needs recreation after instance replacement, re-POST the datasource config via Grafana API

---

## Architecture

```
GitHub → GitHub Actions → [Test → Plan → Approve → Deploy]
                              ↓
                        Lambda (enrichment, rest_handler, prewarm, slack_notifier)
                        SageMaker Serverless Endpoint
                        S3 (data + artifacts)
                        CloudWatch Alarms → SNS → AWS Chatbot → Slack #f1-race-alerts
                        REST API → Grafana Infinity → Live Race Dashboard
                        CloudWatch Metrics → Grafana CloudWatch → Infra Dashboard
```

### Observability (All in Grafana)

- **Live race data:** Grafana Infinity datasource → REST API (`/sessions/latest`) → pitstop probabilities, tyre age, safety car, AI commentary
- **Infra/ops:** Grafana CloudWatch datasource → Lambda duration/errors/throttles, SageMaker invocation latency
- **ELK is retired** — do not add it back

## Grafana EC2

- **Instance ID:** `i-09c735935e93429d5` (t3.micro, stop between races)
- **Login:** admin / f1mlops2026
- **Datasources:** CloudWatch (uid: `P034F075C744B399F`) + Infinity/F1 REST API (uid: `cfg1tmj8jbu2oa`)
- **Dashboards:** `f1-race-live` (Infinity), `f1-infra-metrics` (CloudWatch)
- **IAM role:** `f1-mlops-grafana-role` (CloudWatchReadOnlyAccess)
- **Security group:** `sg-07794e4eb4ba20283` (port 3000 + 22)
- **Plugins installed:** `yesoreyeram-infinity-datasource` v3.7.4
- **Note:** No Elastic IP — get fresh IP after each start with `aws ec2 describe-instances --instance-ids i-09c735935e93429d5 --region us-east-1 --query 'Reservations[0].Instances[0].PublicIpAddress' --output text`

## Key File Paths
- `buildspec.yml` — CodeBuild spec (calls `scripts/ci_build.sh`)
- `scripts/ci_build.sh` — Multi-stage build logic (test / plan / apply)
- `terraform/environments/dev/` — Root Terraform config
- `terraform/modules/lambda/main.tf` — Uses `archive_file` data sources for ZIPs
- `terraform/modules/elk/templates/elk_setup.sh.tpl` — ELK EC2 user-data
- `terraform/modules/codepipeline/main.tf` — Pipeline with conditional CodeStar connection

## Post-Race Build Plan

### AI Commentary — COMPLETE (Groq, not Gemini)
- **Secret name:** `f1-mlops/gemini-api-key` (stores Groq key `gsk_...`, not renamed to avoid Terraform changes)
- **Model:** `llama-3.3-70b-versatile` via `groq>=0.11.0`
- **Client file:** `lambda/enrichment/gemini_client.py`
- **Status:** DEPLOYED and working

### Frontend (Next.js → Vercel) — COMPLETE
- 3 pages: Live predictions, Race history, About/architecture
- Root Directory set to `frontend` in Vercel dashboard
- Polls API Gateway every 30s during race
- Displays pitstop probability per driver + AI commentary card (Groq)
- Race map: SVG-based circuit map from OpenF1 `/v1/position` data, polls every 5s

### Race Outcome Model (XGBoost)
- Separate model from pitstop predictor
- Input: current position, gap to leader, tyre strategy, historical circuit performance
- Output: win/podium probability per driver, updated each lap
- Training data: Ergast API + FastF1 historical races

---

## Race Day Checklist

> **Note:** ELK/Kibana is RETIRED. All visualizations are now in Grafana (Infinity datasource → REST API).
> ELK EC2 (`i-09b80fc03109c35a1`) is stopped and no longer part of race day workflow.

1. Start Grafana EC2: `aws ec2 start-instances --instance-ids i-09c735935e93429d5 --region us-east-1`
2. Get Grafana IP: `aws ec2 describe-instances --instance-ids i-09c735935e93429d5 --region us-east-1 --query 'Reservations[0].Instances[0].PublicIpAddress' --output text`
3. Open Grafana: `http://<grafana-ip>:3000` — admin / f1mlops2026
   - **Live race dashboard:** `/d/f1-race-live` — auto-refreshes every 30s, shows pitstop probabilities + AI commentary
   - **Infrastructure dashboard:** `/d/f1-infra-metrics` — Lambda/SageMaker CloudWatch metrics
4. Verify Lambda `GEMINI_SECRET_NAME` env var is set: `aws lambda get-function-configuration --function-name f1-mlops-enrichment --region us-east-1 --query 'Environment'`
5. Enable live poller 30 min before lights out: `aws events enable-rule --name f1-mlops-live-poller --region us-east-1`
6. Verify predictions flowing ~5 min after enabling (check S3 or Grafana `/d/f1-race-live`)
7. Disable after session: `aws events disable-rule --name f1-mlops-live-poller --region us-east-1`
8. Stop Grafana EC2: `aws ec2 stop-instances --instance-ids i-09c735935e93429d5 --region us-east-1`

## Current State (as of 2026-03-15)

- **Enrichment Lambda:** Deployed with Groq commentary (manually via S3, March 14)
- **REST handler:** Deployed with `commentary` field in response (manually, March 14)
- **Slack notifier:** Deployed with "AI Strategy Insight" label (manually, March 14)
- **Groq API key:** Stored in `f1-mlops/gemini-api-key` secret as plain string `gsk_...`
- **CodePipeline:** TerraformPlan grok `%%{` fix pushed — needs manual Approve after plan passes to sync Terraform state with manually-deployed Lambdas
- **Frontend:** Deployed on Vercel, Root Directory = `frontend`, branding = Groq/Llama 3.3
- **ELK EC2 (`i-09b80fc03109c35a1`):** STOPPED — retired, replaced by Grafana
- **Grafana EC2 (`i-09c735935e93429d5`):** Running at `98.91.186.24`
  - Datasources: CloudWatch (infra) + Infinity (F1 REST API → live race data)
  - Dashboards: `f1-race-live` (pitstop probabilities, tyre age, AI commentary) + `f1-infra-metrics`
- **SageMaker endpoint:** InService (serverless)
