# F1 MLOps — Claude Instructions

## Project Overview
XGBoost-based F1 pitstop prediction system deployed on AWS. Infrastructure managed by Terraform, CI/CD via AWS CodePipeline + GitHub Actions.

- **Repo:** `nshivakumar1/f1-mlops` (NOT `theinfinityloop/f1-mlops`)
- **AWS Account:** `297997106614`, region `us-east-1`
- **ELK Stack EC2:** RETIRED — do not use

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
- ZIPs are gitignored (`terraform/modules/lambda/*.zip`) and don't exist in fresh CI workspaces
- **Fix (GitHub Actions):** Build all ZIPs in the plan job, include in artifact upload, download in deploy job
- **Current Lambda functions:** `enrichment`, `rest_handler`, `prewarm`, `slack_notifier`, `prerace_check`
- The build loop and artifact list in `.github/workflows/ci.yml` **must include ALL Lambda function names**
- If a new Lambda is added to Terraform, add its name to both the build loop and the artifact `path:` list

### 6. CodeStar/CodeConnections — Use AVAILABLE Connection
- **Wrong:** Creating a new `aws_codestarconnections_connection` resource — it starts as PENDING and requires manual activation in console
- **Correct:** Pass the ARN of an existing AVAILABLE connection via `codestar_connection_arn` variable
- **Active connection ARN:** `arn:aws:codeconnections:us-east-1:297997106614:connection/6abde493-3ad0-4a50-8f39-44f542d93bd6`

### 7. GitHub Owner Tag
- **Wrong:** `theinfinityloop` anywhere in Terraform configs
- **Correct:** `nshivakumar1`

### 8. OpenSearch Module — Deleted
- `terraform/modules/opensearch/` was deleted entirely — it had an invalid `dashboard_endpoint` attribute
- The project does NOT use AWS OpenSearch or ELK — do not recreate either module
- Observability is in New Relic (see #39)

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

- Long debugging sessions (New Relic + race day fixes + Lambda + Terraform) can exhaust context
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

### 32. Terraform `templatefile()` — `\${VAR}` Does NOT Escape, Use `$${VAR}`

- `\${INSTANCE_ID}` in `.tpl` files is NOT an escape — Terraform still tries to interpolate it as a template variable
- **Wrong:** `instance_id: \${INSTANCE_ID}` → `vars map does not contain key "INSTANCE_ID"`
- **Correct:** `instance_id: $${INSTANCE_ID}` — `$$` is the escape, outputs literal `${INSTANCE_ID}` at runtime
- Applies to any runtime shell/Metricbeat/Logstash variable references in `.tpl` files that should not be resolved by Terraform

### 33. EC2 `user_data` 16 KB Limit — Use S3 Bootstrapper for Large Scripts

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

### 34. GitHub Actions `download-artifact@v4` — LCA Strips Common Path Prefix

- When uploading multiple paths, `upload-artifact@v4` calculates the Least Common Ancestor (LCA) and strips it from paths inside the artifact
- Uploading `terraform/environments/dev/tfplan.binary` + `terraform/modules/lambda/*.zip` → LCA is `terraform/`, stored internally as `environments/dev/tfplan.binary`
- `download-artifact@v4` with `path: .` extracts to `./environments/dev/tfplan.binary` — missing the `terraform/` prefix
- **Correct:** Use `path: terraform` on download to restore full `terraform/environments/dev/tfplan.binary` path

### 35. Terraform State Drift — Import Existing Resources Before Apply

- Resources created manually or in previous pipeline runs may exist in AWS but not in Terraform state
- Apply will fail with `ConflictException` or `Duplicate` errors trying to recreate them
- **Fix:** Run `terraform import <resource_address> <resource_id>` locally to bring them into state
  ```bash
  terraform import module.elk.aws_key_pair.elk f1-mlops-elk-key
  terraform import "module.api_gateway.aws_api_gateway_resource.sessions" "<api-id>/<resource-id>"
  ```
- After importing locally, push an empty commit to trigger a fresh plan (the old plan binary becomes stale after any state change)

### 36. Terraform `archive_file` Re-Zips Source-Only in CI Deploy Job — Lambda Loses Dependencies

- `data "archive_file"` in Terraform re-runs during `terraform apply` in the deploy job context, which has no pip packages installed
- Result: enrichment Lambda gets replaced with a ~9KB source-only ZIP → `No module named 'groq'` at runtime
- **Fix:** After `terraform apply`, redeploy Lambda functions from the pre-built manylinux ZIPs in the plan artifact:
  - ZIPs >50MB (enrichment ~80MB): upload to S3, then `aws lambda update-function-code --s3-bucket/--s3-key`
  - ZIPs <50MB: `aws lambda update-function-code --zip-file fileb://...`
- This step is now in `.github/workflows/ci.yml` after the `terraform apply` step
- **Race day:** If a CI run was approved while the race is live, the Lambda will be broken for ~1 min until the redeploy step finishes — watch for `No module named 'groq'` errors in CloudWatch

### 37. API Gateway `test-invoke-method` Bypasses Stage — Not a Reliable Proxy for Public URL

- `aws apigateway test-invoke-method` invokes the Lambda integration directly, bypassing the stage deployment entirely
- A route can return 200 via test-invoke but 403 `MissingAuthenticationTokenException` via the public URL if the route was never included in a stage deployment
- **Root cause:** Routes created via `terraform import` (without a full `terraform apply`) are in AWS config but not in the deployed stage snapshot
- **Fix:** Delete and recreate the method + integration with `put-method` + `put-integration`, then `create-deployment`

### 38. New Lambda Functions — Must Be Added to CI Build Loop AND Artifact List

- When a new Lambda function is added to Terraform, it **must** also be added to **three places** in `.github/workflows/ci.yml`:
  1. The build loop in the `plan` job: `for func in enrichment rest_handler prewarm slack_notifier prerace_check ...`
  2. The artifact `path:` list in `Upload plan artifacts` step
  3. The redeploy loop in the `deploy` job
- **Failure mode:** Terraform apply succeeds but Lambda gets a ~5KB source-only ZIP (no pip deps) — `No module named '...'` at runtime
- **Current Lambda list:** `enrichment`, `rest_handler`, `prewarm`, `slack_notifier`, `prerace_check`

### 39. Grafana RETIRED — Do Not Recreate, Use New Relic

- Grafana EC2 (`i-09c735935e93429d5`) is STOPPED and retired as of 2026-03-19
- **All observability is now in New Relic** (account ID `7941720`)
- Live race data: `F1PitstopPrediction` custom events with `pitstopProbability`, `winProbability`, `aiCommentary`
- Infra metrics: CloudWatch Metric Streams → Kinesis Firehose → NR (Lambda, SageMaker, Billing)
- Do NOT recreate Grafana datasources, dashboards, or EC2 unless explicitly re-evaluating the observability stack

### 40. Win Probability — Computed Inline, No Second SageMaker Endpoint

- Win probability is computed in the enrichment Lambda (`compute_win_probabilities()`) after each pitstop batch
- Uses live race state: gap ranking (40%), gap to leader (25%), team strength (20%), tyre freshness (10%), pitstop stability (5%)
- Under safety car: position weight increases to 55%, gap weight drops to 0% (gaps reset under SC)
- **No second SageMaker endpoint** — the Random Forest position model (`ml/training/position/`) is trained but not deployed
- `win_probability` is returned in `/sessions/latest` and `/predict/positions/{session_key}` responses
- `winProbability` is also sent as a field in New Relic `F1PitstopPrediction` custom events

### 42. AI Commentary Module — File is `groq_client.py`, Not `gemini_client.py`

- `lambda/enrichment/gemini_client.py` was renamed to `groq_client.py` (2026-03-23)
- Terraform env var for enrichment Lambda: `GROQ_SECRET_NAME = "f1-mlops/gemini-api-key"`
- `groq_client.py` reads `GROQ_SECRET_NAME` from env (fallback: `f1-mlops/gemini-api-key`)
- Secret name in AWS is still `f1-mlops/gemini-api-key` — do NOT rename it (see #29)

### 43. Prediction Dict Structure — `pitstop_probability` Is Nested

- Top-level prediction dict keys: `driver_number`, `driver_name`, `team`, `features` (list[11]), `tyre_compound`, `win_probability`, `prediction` (nested dict)
- **Wrong:** `p.get("pitstop_probability")` → always returns `None`
- **Correct:** `p.get("prediction", {}).get("pitstop_probability", 0)`
- `tyre_age` is at `p["features"][0]`, not `p.get("tyre_age")`

### 44. Sentry Error Tracking — Integrated but Opt-In

- `sentry-sdk>=2.0.0` in all 5 Lambda `requirements.txt`; `sentry_sdk.init()` at module level in each handler
- Controlled by `SENTRY_DSN` env var — empty string disables Sentry silently (safe to deploy without it)
- Set via `TF_VAR_sentry_dsn=https://...@....ingest.sentry.io/...` or `terraform.tfvars`
- `SENTRY_ENVIRONMENT` defaults to Terraform `var.environment`

### 41. Pre-Race Health Check — Run Before Every Race

- Lambda: `f1-mlops-prerace-check` — invoke manually 30 min before lights out
- Checks: SageMaker InService, OpenF1 API, Groq secret, NR license key, OpenF1 credentials, EventBridge poller state, S3 write, prewarm invoke
- `all_pass` excludes EventBridge poller (expected DISABLED pre-race)
- Report saved to `s3://{bucket}/prerace_check/{timestamp}.json`
- EventBridge rule `f1-mlops-prerace-check` exists (cron Sundays 12:30 UTC) but is **DISABLED by default** — update cron per race calendar or invoke manually

---

## Architecture

```
GitHub → GitHub Actions → [Test → Plan → Approve → Deploy]
                              ↓
                        Lambda (enrichment, rest_handler, prewarm, slack_notifier, prerace_check)
                        SageMaker Serverless Endpoint (pitstop XGBoost)
                        S3 (data + artifacts)
                        CloudWatch Alarms → SNS → AWS Chatbot → Slack #f1-race-alerts
                        CloudWatch Metric Stream → Kinesis Firehose → New Relic
                        REST API → New Relic Infinity → Live Race Dashboard
```

### Observability (New Relic)

- **Live race predictions:** Enrichment Lambda POSTs `F1PitstopPrediction` custom events to NR after each batch
  - Fields: `pitstopProbability`, `winProbability`, `tyreCompound`, `tyreAge`, `lapNumber`, `safetyCarActive`, `aiCommentary`
- **AWS infra metrics:** CloudWatch Metric Streams → Kinesis Firehose → NR (Lambda, SageMaker, F1MLOps/Models, Billing)
- **Lambda APM:** New Relic Lambda Layer (`arn:aws:lambda:us-east-1:451483290750:layer:NewRelicPython312:17`) on all 5 Lambdas
- **Alerts:** NR email alerts configured (NR UI → Alerts → Notification channels)
- **Slack:** AWS Chatbot handles CloudWatch Alarm → #f1-race-alerts (independent of NR)
- **Grafana:** RETIRED — replaced by New Relic
- **ELK:** RETIRED — do not add back

### New Relic Setup

- **NR Account ID:** `7941720`
- **License key secret:** `f1-mlops/newrelic-license-key`
- **NR AWS integration role:** `arn:aws:iam::297997106614:role/f1-mlops-newrelic-integration` (register in NR UI → Infrastructure → AWS)
- **Custom events query:** `SELECT * FROM F1PitstopPrediction SINCE 1 hour ago`
- **Lambda layer ARN:** `arn:aws:lambda:us-east-1:451483290750:layer:NewRelicPython312:17`

## Frontend Development

```bash
cd frontend
npm install
npm run dev        # Start dev server at http://localhost:3000
npm run build      # Production build (verifies types + generates static pages)
npm run start      # Serve production build locally
```

- Root Directory in Vercel dashboard is set to `frontend` — do NOT add `rootDirectory` to `vercel.json`
- API base URL (`NEXT_PUBLIC_API_URL`) must point to the API Gateway stage URL for live data
- `/history` page is server-rendered (dynamic) — API is called at request time, not build time

## Python Lambda Tests

```bash
pytest tests/unit/ -v           # Run all unit tests
pytest tests/unit/test_enrichment.py -v  # Single test file
```

- Tests use `MOCK_SESSION_DATA` dict — no API mocking needed (see Known Mistake #19)
- Always run before pushing after any Lambda code changes

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

### Race Outcome / Win Probability — COMPLETE (inline, no model endpoint)
- Win probability computed inline in enrichment Lambda each lap — see Known Mistake #41
- Position model (`ml/training/position/`) retrained with 12 features (added `current_position`, `gap_to_leader`, `lap_fraction`, `safety_car_active`) and inference script created — ready for SageMaker deployment if more accuracy is needed later

---

## Race Day Checklist

> **Note:** Grafana is RETIRED. Observability is now in New Relic.
> ELK EC2 (`i-09b80fc03109c35a1`) and Grafana EC2 (`i-09c735935e93429d5`) are both STOPPED — do not restart.

1. **30 min before race:** Run pre-race health check:
   ```bash
   aws lambda invoke --function-name f1-mlops-prerace-check \
     --region us-east-1 --payload '{}' /tmp/prerace.json \
     && python3 -c "import json; r=json.load(open('/tmp/prerace.json')); print('ALL PASS' if r['all_pass'] else f'FAILED: {r[\"failed_checks\"]}')"
   ```
   Fix any failed checks before proceeding. Report also saved to `s3://{bucket}/prerace_check/{timestamp}.json`.

2. **Enable live poller:**
   ```bash
   aws events enable-rule --name f1-mlops-live-poller --region us-east-1
   ```

3. **Verify predictions flowing** (~5 min after enabling):
   ```bash
   curl https://xwmgxkj0r4.execute-api.us-east-1.amazonaws.com/v1/sessions/latest | python3 -m json.tool | head -30
   ```

4. **Monitor in New Relic:** `one.newrelic.com` → Query: `SELECT * FROM F1PitstopPrediction SINCE 30 minutes ago ORDER BY timestamp DESC`
   - `pitstopProbability` + `winProbability` per driver
   - `aiCommentary` (Groq Llama 3.3 70B)
   - `safetyCarActive` flag

5. **After race:** Disable poller:
   ```bash
   aws events disable-rule --name f1-mlops-live-poller --region us-east-1
   ```

## Current State (as of 2026-03-23)

- **Enrichment Lambda:** Groq commentary (`groq_client.py`) + `win_probability` computed inline (position/gap/tyre/team scoring)
- **Sentry:** Integrated across all 5 Lambdas — activate by setting `TF_VAR_sentry_dsn` before `terraform apply`
- **REST handler:** `/sessions/latest` and `/predict/positions/{session_key}` return `win_probability` per driver
- **Pre-race check Lambda:** `f1-mlops-prerace-check` — validates 8 systems before race start
- **Slack notifier:** AWS Chatbot → #f1-race-alerts (CloudWatch Alarms only — NR alerts go to email)
- **Groq API key:** `f1-mlops/gemini-api-key` (plain string `gsk_...`)
- **New Relic:** License key in `f1-mlops/newrelic-license-key`; account ID `7941720`; Lambda layer on all 5 functions
- **Frontend:** Deployed on Vercel, Root Directory = `frontend`; displays pitstop + win probability
- **ELK EC2 (`i-09b80fc03109c35a1`):** STOPPED — retired
- **Grafana EC2 (`i-09c735935e93429d5`):** STOPPED — retired (replaced by New Relic)
- **SageMaker endpoint:** InService (serverless, pitstop XGBoost only)
- **Position model:** Trained (12 features incl. live position/gap/lap_fraction) but not deployed as SageMaker endpoint — win probability is computed inline instead
