#!/usr/bin/env bash
# ssh into the VM (user opc) through OCI Bastion, for maintenance only.
#
# Usage: vm-ssh.sh [COMMAND ...]
#   Makes a throwaway key pair, creates a managed SSH session for it (the VM's
#   Bastion plugin puts the public key in for opc while the session lasts),
#   connects through the Bastion (ProxyCommand; the same key for both hops)
#   and deletes the session and the key on exit (ADR 041). Without COMMAND,
#   runs AFP_SSH_COMMAND if set (make ssh CMD=...), else opens a shell.
#
# Environment:
#   AFP_CONFIG_DIR   Directory holding terraform.tfvars.json (required).
#   AFP_SESSION_TTL  Session lifetime in seconds (default 3600).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY=(python3 "$ROOT/scripts/rm_values.py")
# shellcheck source=SCRIPTDIR/lib.sh
source "$ROOT/scripts/lib.sh"

die() { echo "vm-ssh.sh: $*" >&2; exit 1; }

: "${AFP_CONFIG_DIR:?AFP_CONFIG_DIR is not set}"
TFVARS="$AFP_CONFIG_DIR/terraform.tfvars.json"
[[ -f "$TFVARS" ]] || die "$TFVARS not found"
REGION="$("${PY[@]}" get "$TFVARS" region)"

SESSION_TTL="${AFP_SESSION_TTL:-3600}"
oci_() { oci --region "$REGION" "$@"; }
if [[ $# -eq 0 && -n "${AFP_SSH_COMMAND:-}" ]]; then
  set -- "$AFP_SSH_COMMAND"
fi

tmp="$(mktemp -d)"
cleanup() {
  [[ -z "$BASTION_SESSION_ID" ]] || bastion_delete_session
  rm -rf "$tmp"
}
trap cleanup EXIT

load_outputs
BASTION_ID="$(out bastion_id)"
VM_ID="$(out vm_id)"
VM_IP="$(out vm_private_ip)"

KEY="$tmp/id_ed25519"
ssh-keygen -q -t ed25519 -N "" -C "afp-vm-ssh" -f "$KEY"
bastion_create_managed_session "$BASTION_ID" session-afp-vm-ssh "$VM_ID" "$VM_IP" opc "$KEY.pub" "$SESSION_TTL"

# The VM's host key changes whenever it is recreated; the path to it is
# already authenticated by the Bastion, so a throwaway known_hosts is used.
common=(-i "$KEY" -o IdentitiesOnly=yes -o ServerAliveInterval=60 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$tmp/known_hosts")
proxy="ssh ${common[*]} -W %h:%p $(bastion_host)"
ssh "${common[@]}" -o ProxyCommand="$proxy" "opc@$VM_IP" "$@"
