#!/usr/bin/env bash
#
# terraform wrapper for the ik-arch prod deploy.
#
# The `lik` AWS profile authenticates via a `login_session` credential provider that the
# AWS CLI understands but Terraform's Go SDK does not — running terraform directly fails
# with "No valid credential sources found". This wrapper materializes short-lived
# credentials into the standard AWS_* env vars, then runs terraform with whatever args you
# pass. Credentials are minted fresh each invocation, so expiry is never an issue.
#
# Usage (from anywhere; it cd's into infra/):
#   ./tf.sh plan
#   ./tf.sh apply -var-file=prod.tfvars
#   ./tf.sh apply -var 'lik_mcp_image=:lik-mcp-prod.app.2' -var 'lik_ui_image=:lik-ui-prod.app.1'
#   ./tf.sh output
#   AWS_PROFILE=other ./tf.sh plan      # override the profile if needed
#
set -euo pipefail
cd "$(dirname "$0")"

: "${AWS_PROFILE:=lik}"
export AWS_PROFILE

# Resolve the profile's credentials via the CLI (invokes the login_session helper) and
# parse the JSON with the system python3 (avoids the mise/aws-cli python shadow, and the
# eval-unsafe `--format env` output).
creds="$(mise exec -- aws configure export-credentials --format process)"
AWS_ACCESS_KEY_ID="$(printf '%s' "$creds"     | /usr/bin/python3 -c 'import sys,json;print(json.load(sys.stdin)["AccessKeyId"])')"
AWS_SECRET_ACCESS_KEY="$(printf '%s' "$creds" | /usr/bin/python3 -c 'import sys,json;print(json.load(sys.stdin)["SecretAccessKey"])')"
AWS_SESSION_TOKEN="$(printf '%s' "$creds"     | /usr/bin/python3 -c 'import sys,json;print(json.load(sys.stdin)["SessionToken"])')"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

exec mise exec -- terraform "$@"
