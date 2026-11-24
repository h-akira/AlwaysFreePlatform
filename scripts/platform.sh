#!/usr/bin/env bash
# Bring the VM up to the platform code on this machine, as it is (ADR 038).
#
# Usage: platform.sh
#   1. Packs the code that the VM and the DevOps build use (afp/, bin/, caddy/,
#      mysql/, scripts/) as it is on disk, committed or not, into
#      platform.tar.gz and puts it into the bucket (replacing the one there).
#   2. Runs afp-bootstrap on the VM through Run Command and waits for it: the
#      VM takes platform.tar.gz, then runs afp install and afp sync.
#   No git and no tags are involved; tags of the platform repository are only
#   for bookkeeping.
#
# Environment:
#   AFP_CONFIG_DIR  Directory holding terraform.tfvars.json (required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY=(python3 "$ROOT/scripts/rm_values.py")
# shellcheck source=SCRIPTDIR/lib.sh
source "$ROOT/scripts/lib.sh"

die() { echo "platform.sh: $*" >&2; exit 1; }
usage() { sed -n '2,/^[^#]/p' "$0" | sed '$d' >&2; exit 2; }

[[ $# -eq 0 ]] || usage

: "${AFP_CONFIG_DIR:?AFP_CONFIG_DIR is not set}"
TFVARS="$AFP_CONFIG_DIR/terraform.tfvars.json"
[[ -f "$TFVARS" ]] || die "$TFVARS not found"
REGION="$("${PY[@]}" get "$TFVARS" region)"
oci_() { oci --region "$REGION" "$@"; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
hash="$("${PY[@]}" pack-platform "$ROOT" "$tmp/platform.tar.gz")" || die "cannot pack the platform code"

load_outputs
BUCKET="$(out bucket)"
oci_ os object put -bn "$BUCKET" --name platform.tar.gz --file "$tmp/platform.tar.gz" \
    --content-type application/gzip --force > /dev/null \
  || die "cannot put platform.tar.gz into the bucket"
echo "platform.tar.gz: $hash"

exec "$ROOT/scripts/run-command.sh" send --wait "sudo -n /usr/local/sbin/afp-bootstrap"
