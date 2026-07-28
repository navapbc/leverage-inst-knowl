#!/usr/bin/env bash
# Resolve the deployed DB connection from Terraform (the single source of truth) and print
# `export LIK_DB_*` lines for `eval`, so you can run init_db.py (or psql) against the deployed
# database WITHOUT hand-assembling LIK_DB_* variables.
#
#   eval "$(AWS_PROFILE=lik mise exec -- lik-mcp/scripts/db_env_from_terraform.sh)"      # lik-mcp DB (likdb)
#   eval "$(AWS_PROFILE=lik mise exec -- lik-mcp/scripts/db_env_from_terraform.sh ui)"   # lik-ui DB  (likuidb)
#
# Non-secret config comes from `terraform output env_config`; the password comes from SSM
# (${ssm_prefix}/shared/DB_MASTER_PASSWORD). Requires terraform state access + AWS creds — the
# same access anyone running terraform already has. Fails loudly (set -e) if any lookup fails,
# so init_db never runs against a half-resolved or default connection.
set -euo pipefail

target="${1:-mcp}"   # mcp -> master db (likdb); ui -> lik-ui db (likuidb)
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
infra="$here/../../infra"

cfg="$(terraform -chdir="$infra" output -json env_config)"
get() { printf '%s' "$cfg" | jq -er ".$1"; }

case "$target" in
  mcp) db_name="$(get db_mcp_name)" ;;
  ui)  db_name="$(get db_ui_name)" ;;
  *)   echo "usage: ${BASH_SOURCE[0]##*/} [mcp|ui]" >&2; exit 2 ;;
esac

ssm_prefix="$(get ssm_prefix)"
region="$(get region)"
# Resolve every value into a variable first: a failed `get` (missing key) aborts here under
# set -e. Doing these lookups inside the heredoc below would swallow the failure (errexit does
# not propagate from a command substitution feeding `cat`) and emit an empty export instead.
db_host="$(get db_host)"
db_port="$(get db_port)"
db_user="$(get db_user)"
password="$(aws ssm get-parameter --region "$region" --with-decryption \
  --name "$ssm_prefix/shared/DB_MASTER_PASSWORD" --query Parameter.Value --output text)"

# The master password's charset excludes single quotes and backslashes (see database.tf
# override_special), so single-quoting is safe for eval.
cat <<EOF
export LIK_DB_HOST='$db_host'
export LIK_DB_PORT='$db_port'
export LIK_DB_USER='$db_user'
export LIK_DB_NAME='$db_name'
export LIK_DB_SSLMODE='require'
export LIK_DB_PASSWORD='$password'
export SSM_PREFIX='$ssm_prefix'
EOF
