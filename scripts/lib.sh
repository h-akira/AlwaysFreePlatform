# shellcheck shell=bash
# Shared by db-tunnel.sh and vm-ssh.sh (sourced, not run).
# The caller sets ROOT and REGION, defines die() and oci_(), and deletes any
# Bastion session on exit:
#   trap '[[ -z "$BASTION_SESSION_ID" ]] || bastion_delete_session' EXIT

# Main stack outputs as KEY=VALUE lines (bash 3.2: no associative arrays).
STACK_OUTPUTS=""
load_outputs() {
  STACK_OUTPUTS="$("$ROOT/scripts/stack.sh" main outputs)" || die "cannot read the stack outputs"
}

# Print one output loaded by load_outputs.
out() {
  local value
  value="$(printf '%s\n' "$STACK_OUTPUTS" | sed -n "s/^$1=//p")"
  [[ -n "$value" ]] || die "stack output $1 is missing; run 'make apply' first"
  printf '%s' "$value"
}

BASTION_SESSION_ID=""

# Create a port-forwarding session and wait until it is ACTIVE.
# Usage: bastion_create_session BASTION_ID NAME TARGET_IP TARGET_PORT PUBLIC_KEY_FILE TTL
bastion_create_session() {
  local bastion_id="$1" name="$2" ip="$3" port="$4" public_key="$5" ttl="$6"
  echo "Creating a Bastion session to ${ip}:${port} (TTL ${ttl}s) ..." >&2
  BASTION_SESSION_ID="$(oci_ bastion session create-port-forwarding \
    --bastion-id "$bastion_id" --display-name "$name" \
    --target-private-ip "$ip" --target-port "$port" \
    --ssh-public-key-file "$public_key" --key-type PUB --session-ttl "$ttl" \
    --query 'data.id' --raw-output)" || die "cannot create a Bastion session"
  bastion_wait_active
}

# Create a managed SSH session to an instance (its Bastion plugin puts the
# session's public key in for USER) and wait until it is ACTIVE.
# Usage: bastion_create_managed_session BASTION_ID NAME INSTANCE_ID TARGET_IP USER PUBLIC_KEY_FILE TTL
bastion_create_managed_session() {
  local bastion_id="$1" name="$2" instance_id="$3" ip="$4" user="$5" public_key="$6" ttl="$7"
  echo "Creating a Bastion managed SSH session to ${user}@${ip} (TTL ${ttl}s) ..." >&2
  BASTION_SESSION_ID="$(oci_ bastion session create-managed-ssh \
    --bastion-id "$bastion_id" --display-name "$name" \
    --target-resource-id "$instance_id" --target-private-ip "$ip" --target-port 22 \
    --target-os-username "$user" \
    --ssh-public-key-file "$public_key" --key-type PUB --session-ttl "$ttl" \
    --query 'data.id' --raw-output)" || die "cannot create a Bastion session"
  bastion_wait_active
}

bastion_wait_active() {
  local state=""
  for _ in $(seq 60); do
    state="$(oci_ bastion session get --session-id "$BASTION_SESSION_ID" \
      --query 'data."lifecycle-state"' --raw-output)"
    if [[ "$state" == "ACTIVE" ]]; then
      # Right after ACTIVE the Bastion still rejects the key for a few seconds.
      sleep "${BASTION_KEY_WAIT_SECONDS:-15}"
      return 0
    fi
    [[ "$state" == "CREATING" ]] || die "session $BASTION_SESSION_ID is $state"
    sleep 5
  done
  die "session $BASTION_SESSION_ID did not become ACTIVE"
}

bastion_delete_session() {
  oci_ bastion session delete --session-id "$BASTION_SESSION_ID" --force > /dev/null 2>&1 || true
}

# ssh destination of the session, e.g. for -L or ProxyCommand.
bastion_host() {
  printf '%s@host.bastion.%s.oci.oraclecloud.com' "$BASTION_SESSION_ID" "$REGION"
}
