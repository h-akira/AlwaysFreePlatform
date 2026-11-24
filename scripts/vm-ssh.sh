#!/usr/bin/env bash
# ssh into the VM (user opc) through OCI Bastion, for maintenance only.
#
# Usage: vm-ssh.sh [COMMAND ...]
#   Creates a port-forwarding session to the VM's port 22, connects through it
#   (ProxyCommand) and deletes the session on exit. Without COMMAND, runs
#   AFP_SSH_COMMAND if set (make ssh CMD=...), else opens an interactive shell.
#
# Environment:
#   AFP_CONFIG_DIR   Directory holding terraform.tfvars.json (required).
#   AFP_SSH_KEY      Optional private key for the VM (opc), whose public half is
#                    ssh_public_key in terraform.tfvars.json. Without it, ssh
#                    uses your own settings (ssh-agent, ~/.ssh/config, ...).
#   The Bastion session uses a throwaway key pair made here, like db-tunnel.sh.
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
vm_key=()
if [[ -n "${AFP_SSH_KEY:-}" ]]; then
  [[ -f "$AFP_SSH_KEY" ]] || die "AFP_SSH_KEY not found: $AFP_SSH_KEY"
  vm_key=(-i "$AFP_SSH_KEY")
fi
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
VM_IP="$(out vm_private_ip)"

# The Bastion hop needs a key only for this session.
BASTION_KEY="$tmp/bastion_ed25519"
ssh-keygen -q -t ed25519 -N "" -C "afp-vm-ssh" -f "$BASTION_KEY"
bastion_create_session "$BASTION_ID" session-afp-vm-ssh "$VM_IP" 22 "$BASTION_KEY.pub" "$SESSION_TTL"

# The VM's host key changes whenever it is recreated; the path to it is
# already authenticated by the Bastion, so a throwaway known_hosts is used.
common=(-o ServerAliveInterval=60 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$tmp/known_hosts")
proxy="ssh -i $BASTION_KEY -o IdentitiesOnly=yes ${common[*]} -W %h:%p $(bastion_host)"
ssh ${vm_key[@]+"${vm_key[@]}"} "${common[@]}" -o ProxyCommand="$proxy" "opc@$VM_IP" "$@"
