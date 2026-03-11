#!/bin/bash
set -euo pipefail

STAGE="${STAGE:-test}"
echo "=== CI Build: STAGE=$STAGE ==="

case "$STAGE" in
  test)
    echo "Running full test suite..."
    python -m pytest tests/ -v --tb=short --junitxml=reports/tests.xml
    echo "Tests complete."
    ;;

  plan)
    echo "Running Terraform plan..."
    cd terraform/environments/dev
    terraform init -input=false
    terraform validate
    terraform plan -input=false -out=tfplan.binary \
      -var="account_id=${TF_VAR_account_id}" \
      -var="alert_email=${TF_VAR_alert_email:-}" \
      -var="github_owner=${TF_VAR_github_owner:-nshivakumar1}" \
      -var="github_repo=${TF_VAR_github_repo:-f1-mlops}"
    terraform show -json tfplan.binary > tfplan.json
    echo "Terraform plan complete."
    ;;

  apply)
    echo "Running Terraform apply..."
    # Copy plan binary from secondary artifact (plan_output) if present
    PLAN_SRC="${CODEBUILD_SRC_DIR_plan_output:-}"
    if [ -n "$PLAN_SRC" ] && [ -f "${PLAN_SRC}/terraform/environments/dev/tfplan.binary" ]; then
      cp "${PLAN_SRC}/terraform/environments/dev/tfplan.binary" terraform/environments/dev/tfplan.binary
    fi
    cd terraform/environments/dev
    terraform init -input=false
    terraform apply -input=false -auto-approve tfplan.binary
    terraform output -json > /tmp/tf_outputs.json
    cat /tmp/tf_outputs.json
    echo "Terraform apply complete."
    ;;

  *)
    echo "Unknown STAGE: $STAGE"
    exit 1
    ;;
esac
