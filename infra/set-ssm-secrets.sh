#!/usr/bin/env bash
#
# Bulk-set SSM SecureString parameters from a NAME=value file, keeping every value off the
# command line (fed via file://) so secrets never hit shell history / `ps` and special
# characters can't break quoting.
#
# File format (one per line):
#   /ik-arch/prod/lik-ui/LIK_UI_SESSION_SECRET=abc123
#   # comment and blank lines are skipped
#   /ik-arch/prod/lik-ui/LIK_UI_GITHUB_CLIENT_SECRET=GOCSPX-...
# The value is everything after the FIRST '=' (so '=' inside a secret is fine). A line whose
# value still contains the '…' placeholder is skipped.
#
# Usage:
#   ./set-ssm-secrets.sh <secrets-file>          # bulk (see runbook step 3)
#   printf '%s\n' '/ik-arch/prod/lik-ui/LIK_UI_LIKMCP_CLIENT_SECRET=GOCSPX-xxx' > /tmp/s.env
#   ./set-ssm-secrets.sh /tmp/s.env              # single-secret update, then rm /tmp/s.env
#
# Region defaults to us-east-1; override with AWS_REGION. Profile defaults to lik.
#
set -uo pipefail

SF="${1:-}"
if [ -z "$SF" ] || [ ! -f "$SF" ]; then
  echo "usage: $0 <secrets-file>   (NAME=value lines; # and blank lines skipped)" >&2
  exit 2
fi

: "${AWS_PROFILE:=lik}"
: "${AWS_REGION:=us-east-1}"
export AWS_PROFILE

set_count=0 skip_count=0
while IFS='=' read -r name value; do
  case "$name" in ''|\#*) continue ;; esac                  # skip blank / comment lines
  if printf %s "$value" | grep -q '…'; then                 # skip un-filled placeholders
    echo "skip (still placeholder): $name"; skip_count=$((skip_count+1)); continue
  fi
  f=$(mktemp)
  printf %s "$value" > "$f"                                 # exact value, no trailing newline
  if mise exec -- aws ssm put-parameter --region "$AWS_REGION" \
       --type SecureString --overwrite --name "$name" --value "file://$f" >/dev/null; then
    echo "set: $name"; set_count=$((set_count+1))
  else
    echo "FAILED: $name" >&2
  fi
  rm -f "$f"
done < "$SF"

echo "done — $set_count set, $skip_count skipped. Redeploy to pick up changes: ./tf.sh apply"
