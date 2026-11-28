#!/usr/bin/env bash
# Send plan/apply jobs for terraform/ to OCI Resource Manager.
#
# Usage: stack.sh base|main plan|apply|destroy|outputs
#   base     Stack "stack-afp-base" (terraform/base): what destroy cannot remove.
#   main     Stack "stack-afp-main" (terraform/main): everything else.
#
#   plan     Upload terraform/ as it is on disk (committed or not) and the
#            variables, then run a plan job named after the hash of the code.
#   apply    Apply exactly the latest plan job, if it was made from the code
#            as it is now (same hash).
#            For the main stack, also brings the GitHub triggers of OCI DevOps
#            in line with the projects (scripts/triggers.py: those of projects
#            without a repository are deleted first, missing ones are created
#            after), then sends afp-bootstrap to the VM through Run Command
#            (without waiting), so that the VM picks up afp.json.
#   destroy  Destroy every resource of the main stack (the stack itself is kept).
#            Deletes the GitHub triggers and empties the buckets first, dumps
#            and logs included. Asks to type the stack
#            name, or needs AFP_CONFIRM_DESTROY=<name>. Refused for the base stack.
#   outputs  Print the stack's outputs as KEY=VALUE lines.
#
# Environment:
#   AFP_CONFIG_DIR  Directory holding terraform.tfvars.json (required).
#   OCI_CLI_PROFILE, OCI_CLI_AUTH, ...  Passed through to the OCI CLI.
#
# Nothing is kept locally: the stack is found by its name in the tenancy root,
# and its state is held by Resource Manager.
set -euo pipefail

TERRAFORM_VERSION="1.5.x"
JOB_MAX_WAIT_SECONDS=3600
POLL_SECONDS=15
REFRESH_SECONDS=600

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY=(python3 "$ROOT/scripts/rm_values.py")
TRIGGERS=(python3 "$ROOT/scripts/triggers.py")

die() { echo "stack.sh: $*" >&2; exit 1; }
# Print the header comment (up to the first non-comment line).
usage() { sed -n '2,/^[^#]/p' "$0" | sed '$d' >&2; exit 2; }

# Each stack runs one root module of terraform/; both share terraform/modules/.
case "${1:-}" in
  base)
    STACK_NAME="stack-afp-base"; WORKDIR="base"; MAKE_PREFIX="base-"
    # A trailing "?" marks a key that may be left out (rm_values.py variables).
    VARIABLE_KEYS="tenancy_ocid,region,dns_zone,notification_email,budget_amount?"
    ;;
  main)
    STACK_NAME="stack-afp-main"; WORKDIR="main"; MAKE_PREFIX=""
    VARIABLE_KEYS=""
    ;;
  *) usage ;;
esac
shift

# A deleted vault stays in its compartment for days; the base stack is kept.
if [[ "${1:-}" == "destroy" && "$WORKDIR" != "main" ]]; then
  die "the base stack is never destroyed by this script"
fi

: "${AFP_CONFIG_DIR:?AFP_CONFIG_DIR is not set}"
TFVARS="$AFP_CONFIG_DIR/terraform.tfvars.json"
[[ -f "$TFVARS" ]] || die "$TFVARS not found"

TENANCY="$("${PY[@]}" get "$TFVARS" tenancy_ocid)"
REGION="$("${PY[@]}" get "$TFVARS" region)"
oci_() { oci --region "$REGION" "$@"; }

# Zip terraform/ as it is on disk into $1 and print the hash of its contents
# (no git: ADR 038). The whole of terraform/ is sent so that the root module
# can reach ../modules.
pack() { "${PY[@]}" pack-terraform "$ROOT/terraform" "$1"; }

code_hash() {
  local dir hash
  dir="$(mktemp -d)"
  hash="$(pack "$dir/stack.zip")" || { rm -rf "$dir"; die "cannot pack terraform/"; }
  rm -rf "$dir"
  printf '%s\n' "$hash"
}

# Print the stack's OCID, or nothing if it does not exist. Fails on CLI errors
# (e.g. an expired session) instead of treating them as "not found".
find_stack() {
  local id
  id="$(oci_ resource-manager stack list --compartment-id "$TENANCY" \
    --display-name "$STACK_NAME" --lifecycle-state ACTIVE \
    --query 'data[0].id' --raw-output)" || die "cannot list stacks (is the OCI CLI session valid?)"
  [[ "$id" == "null" ]] || printf '%s\n' "$id"
}

# Wait for a job and print its log; fail unless it succeeded.
finish_job() {
  local job_id="$1" state
  state="$(oci_ resource-manager job get --job-id "$job_id" \
    --query 'data."lifecycle-state"' --raw-output)"
  oci_ resource-manager job get-job-logs-content --job-id "$job_id" \
    --query 'data' --raw-output || true
  [[ "$state" == "SUCCEEDED" ]] || die "job $job_id ended in $state"
}

# Session tokens expire after about an hour; keep them alive during long jobs.
refresh_session() {
  if [[ "${OCI_CLI_AUTH:-}" == "security_token" ]]; then
    oci session refresh > /dev/null 2>&1 || echo "stack.sh: warning: session refresh failed" >&2
  fi
}

run_job() {
  # $1: create-plan-job | create-apply-job | create-destroy-job; the rest is passed through.
  local kind="$1"; shift
  local job_id state waited=0 since_refresh=0
  refresh_session
  job_id="$(oci_ resource-manager job "$kind" "$@" --query 'data.id' --raw-output)"
  echo "Job $job_id started; waiting ..."
  while :; do
    state="$(oci_ resource-manager job get --job-id "$job_id" \
      --query 'data."lifecycle-state"' --raw-output)"
    case "$state" in
      SUCCEEDED|FAILED|CANCELED) break ;;
    esac
    (( waited < JOB_MAX_WAIT_SECONDS )) || die "job $job_id still $state after ${waited}s"
    sleep "$POLL_SECONDS"
    waited=$(( waited + POLL_SECONDS ))
    since_refresh=$(( since_refresh + POLL_SECONDS ))
    if (( since_refresh >= REFRESH_SECONDS )); then
      refresh_session
      since_refresh=0
    fi
  done
  finish_job "$job_id"
}

cmd_plan() {
  local sha stack_id
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  sha="$(pack "$tmp/stack.zip")" || die "cannot pack terraform/"
  "${PY[@]}" variables "$TFVARS" ${VARIABLE_KEYS:+"$VARIABLE_KEYS"} > "$tmp/variables.json"

  stack_id="$(find_stack)"
  if [[ -z "$stack_id" || "$stack_id" == "null" ]]; then
    echo "Creating stack $STACK_NAME ..."
    stack_id="$(oci_ resource-manager stack create --compartment-id "$TENANCY" \
      --display-name "$STACK_NAME" --description "AlwaysFreePlatform" \
      --terraform-version "$TERRAFORM_VERSION" \
      --freeform-tags '{"afp":"stack"}' \
      --config-source "$tmp/stack.zip" --working-directory "$WORKDIR" \
      --variables "file://$tmp/variables.json" \
      --wait-for-state ACTIVE --query 'data.id' --raw-output)"
  else
    echo "Updating stack $STACK_NAME ..."
    oci_ resource-manager stack update --stack-id "$stack_id" \
      --config-source "$tmp/stack.zip" --working-directory "$WORKDIR" \
      --variables "file://$tmp/variables.json" \
      --force --wait-for-state ACTIVE > /dev/null
  fi

  echo "Planning $sha ..."
  run_job create-plan-job --stack-id "$stack_id" --display-name "plan-$sha"
  echo "Plan of $sha succeeded. Run 'make ${MAKE_PREFIX}apply' to apply it."
}

cmd_apply() {
  local sha stack_id plan
  sha="$(code_hash)"
  stack_id="$(find_stack)"
  [[ -n "$stack_id" && "$stack_id" != "null" ]] || die "stack not found; run 'make ${MAKE_PREFIX}plan' first"

  # Latest job of the stack must be a successful plan of the code as it is now.
  plan="$(oci_ resource-manager job list --stack-id "$stack_id" \
    --sort-by TIMECREATED --sort-order DESC --limit 1 \
    --query 'data[0].[id, operation, "lifecycle-state", "display-name"] | join(`" "`, @)' \
    --raw-output)"
  read -r plan_id operation state name <<< "$plan"
  [[ "$operation" == "PLAN" && "$state" == "SUCCEEDED" ]] \
    || die "latest job is not a successful plan ($operation $state); run 'make ${MAKE_PREFIX}plan'"
  [[ "$name" == "plan-$sha" ]] \
    || die "latest plan ($name) is not of terraform/ as it is now ($sha); run 'make ${MAKE_PREFIX}plan'"

  if [[ "$WORKDIR" == "main" ]]; then
    # A trigger left on a build pipeline that is going away may block its deletion.
    stack_outputs "$stack_id" | "${TRIGGERS[@]}" prune || die "cannot delete the triggers of removed pipelines"
  fi
  echo "Applying $name ..."
  run_job create-apply-job --stack-id "$stack_id" --display-name "apply-$sha" \
    --execution-plan-strategy FROM_PLAN_JOB_ID --execution-plan-job-id "$plan_id"
  echo "Applied $sha."
  if [[ "$WORKDIR" == "main" ]]; then
    stack_outputs "$stack_id" | "${TRIGGERS[@]}" create \
      || die "the stack is applied but the triggers are not; run 'make plan' and 'make apply' again"
    # A new VM runs it by itself at boot; then this one only waits its turn.
    "$ROOT/scripts/run-command.sh" send "sudo -n /usr/local/sbin/afp-bootstrap" \
      || echo "stack.sh: warning: could not send afp-bootstrap to the VM" >&2
  fi
}

# A bucket with objects cannot be deleted. afp.json (in the deploy bucket) is
# left to Terraform.
BUCKET_OUTPUTS="bucket dumps_bucket logs_bucket"
empty_buckets() {
  local outputs key bucket
  outputs="$(stack_outputs "$1")"
  for key in $BUCKET_OUTPUTS; do
    bucket="$(printf '%s\n' "$outputs" | sed -n "s/^$key=//p")"
    if [[ -z "$bucket" ]]; then
      echo "No $key in the stack's outputs; nothing to empty."
      continue
    fi
    if ! oci_ os bucket get --bucket-name "$bucket" > /dev/null 2>&1; then
      echo "Bucket $bucket not found; nothing to empty."
      continue
    fi
    echo "Emptying bucket $bucket ..."
    oci_ os object bulk-delete --bucket-name "$bucket" --exclude afp.json --force > /dev/null \
      || die "cannot empty bucket $bucket"
  done
}

cmd_destroy() {
  local stack_id answer
  stack_id="$(find_stack)"
  [[ -n "$stack_id" && "$stack_id" != "null" ]] || die "stack not found"

  if [[ "${AFP_CONFIRM_DESTROY:-}" != "$STACK_NAME" ]]; then
    [[ -t 0 ]] || die "not a terminal; set AFP_CONFIRM_DESTROY=$STACK_NAME to confirm"
    echo "This deletes everything in the buckets too, DB dumps included."
    read -r -p "Destroy all resources of stack '$STACK_NAME'? Type the stack name: " answer
    [[ "$answer" == "$STACK_NAME" ]] || die "aborted"
  fi

  # Terraform does not know the triggers; they keep the DevOps project alive.
  stack_outputs "$stack_id" | "${TRIGGERS[@]}" delete-all || die "cannot delete the triggers"
  empty_buckets "$stack_id"
  echo "Destroying ..."
  run_job create-destroy-job --stack-id "$stack_id" --display-name "destroy-$(date -u +%Y%m%dT%H%M%SZ)" \
    --execution-plan-strategy AUTO_APPROVED
  echo "Destroyed. The stack itself is kept; 'make plan' and 'make apply' recreate everything."
}

stack_outputs() {
  oci_ resource-manager stack get-stack-tf-state --stack-id "$1" --file - \
    | "${PY[@]}" outputs
}

cmd_outputs() {
  local stack_id
  stack_id="$(find_stack)"
  [[ -n "$stack_id" && "$stack_id" != "null" ]] || die "stack not found"
  stack_outputs "$stack_id"
}

case "${1:-}" in
  plan) cmd_plan ;;
  apply) cmd_apply ;;
  destroy) cmd_destroy ;;
  outputs) cmd_outputs ;;
  *) usage ;;
esac
