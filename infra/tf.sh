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
#   ./tf.sh apply -auto-approve                          # images auto-resolved to latest
#   LIK_MCP_IMAGE=:lik-mcp-prod.app.2 LIK_UI_IMAGE=:lik-ui-prod.app.1 ./tf.sh apply   # pin images
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
# SessionToken is only present for temporary credentials (SSO / assume-role); a long-term
# IAM-user profile omits it, so default to empty rather than KeyError-ing.
AWS_SESSION_TOKEN="$(printf '%s' "$creds"     | /usr/bin/python3 -c 'import sys,json;print(json.load(sys.stdin).get("SessionToken",""))')"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
[ -n "$AWS_SESSION_TOKEN" ] && export AWS_SESSION_TOKEN || unset AWS_SESSION_TOKEN

# Only `apply` consumes the image/domain vars; resolve them (and guard) only then, so
# `plan`/`output`/`destroy` don't fail when no images exist yet. Extra args (e.g.
# -var-file, -auto-approve) are passed through after the injected vars.
if [ "${1:-}" = "apply" ]; then
    shift

    : "${UI_CUSTOM_DOMAIN_URL:=https://ui.lik.navapbc.com}"
    : "${MCP_CUSTOM_DOMAIN_URL:=https://mcp.lik.navapbc.com}"
    echo "Using UI_CUSTOM_DOMAIN_URL=$UI_CUSTOM_DOMAIN_URL"
    echo "Using MCP_CUSTOM_DOMAIN_URL=$MCP_CUSTOM_DOMAIN_URL"

    latest_image() {
        mise exec -- aws lightsail get-container-images --service-name "$1" \
            --query 'containerImages[0].image' --output text
    }

    : "${ENV_SUFFIX:=prod}"
    : "${LIK_MCP_IMAGE:=$(latest_image lik-mcp-$ENV_SUFFIX)}"
    : "${LIK_UI_IMAGE:=$(latest_image lik-ui-$ENV_SUFFIX)}"

    [ -n "$LIK_MCP_IMAGE" ] && [ "$LIK_MCP_IMAGE" != "None" ] || { echo "ERROR: LIK_MCP_IMAGE is empty" >&2; exit 1; }
    [ -n "$LIK_UI_IMAGE" ]  && [ "$LIK_UI_IMAGE" != "None" ]  || { echo "ERROR: LIK_UI_IMAGE is empty"  >&2; exit 1; }

    echo "Using LIK_MCP_IMAGE=$LIK_MCP_IMAGE"
    echo "Using LIK_UI_IMAGE=$LIK_UI_IMAGE"

    # Terraform applies variables in the order they appear in the argument list,
    # so -var-file and -var arguments in $@ will override the defaults
    exec mise exec -- terraform apply \
        -var "ui_custom_domain_url=$UI_CUSTOM_DOMAIN_URL" \
        -var "mcp_custom_domain_url=$MCP_CUSTOM_DOMAIN_URL" \
        -var "lik_mcp_image=$LIK_MCP_IMAGE" \
        -var "lik_ui_image=$LIK_UI_IMAGE" \
        "$@"
else
    exec mise exec -- terraform "$@"
fi

