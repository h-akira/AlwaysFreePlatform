#!/usr/bin/env bash
# Release a project's tag from the OCI DevOps build stage (ADR 026).
#
# Called by the project's build_spec.yaml (template: examples/hello). The build
# runner is x86_64 and cannot emulate arm64, so this does not build: it puts
# the tag's source and compose.afp.yaml into the bucket, and the VM builds
# them in afp deploy.
#
# Usage: devops-release.sh
#   Prints the tag (for AFP_TAG, which the deployment receives); the progress
#   goes to stderr. Fails unless the commit under build is a tag v*.
#
# Environment (set by OCI DevOps and by the build pipeline's parameters):
#   AFP_PROJECT, AFP_BUCKET        Project name and the platform's bucket.
#   OCI_PRIMARY_SOURCE_DIR         Checkout of the project's repository.
#   OCI_TRIGGER_SOURCE_BRANCH_NAME Ref that started the build, if a trigger did.
#   The OCI CLI is already authenticated as the build pipeline.
set -euo pipefail

# Same rules as afp (afp/project.py) and scripts/project.sh; the tag reaches
# the deployment command on the VM.
TAG_RE='^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$'
PROJECT_RE='^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$'

die() { echo "devops-release.sh: $*" >&2; exit 1; }
say() { echo "$*" >&2; }

: "${AFP_PROJECT:?AFP_PROJECT is not set}"
: "${AFP_BUCKET:?AFP_BUCKET is not set}"
: "${OCI_PRIMARY_SOURCE_DIR:?OCI_PRIMARY_SOURCE_DIR is not set}"
[[ "$AFP_PROJECT" =~ $PROJECT_RE ]] || die "invalid project name: $AFP_PROJECT"
src="$OCI_PRIMARY_SOURCE_DIR"

# The tag: one that points at the commit under build, else the trigger's ref.
tag="$(git -C "$src" tag --points-at HEAD --list 'v*' | head -1)"
if [[ -z "$tag" ]]; then
  ref="${OCI_TRIGGER_SOURCE_BRANCH_NAME:-}"
  [[ "$ref" == refs/tags/v* || "$ref" == v* ]] && tag="${ref#refs/tags/}"
fi
[[ -n "$tag" ]] || die "the commit under build has no tag v* (trigger ref: '${OCI_TRIGGER_SOURCE_BRANCH_NAME:-}'); nothing to release"
[[ "$tag" =~ $TAG_RE ]] || die "tag $tag cannot be a Docker tag"
[[ -f "$src/compose.afp.yaml" ]] || die "compose.afp.yaml is not at the top of the repository"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git -C "$src" archive --format=tar.gz -o "$work/source.tar.gz" HEAD

prefix="releases/$AFP_PROJECT/$tag"
say "Putting $prefix/ into bucket $AFP_BUCKET ..."
# The source first: afp deploy looks for compose.afp.yaml to start.
oci os object put -bn "$AFP_BUCKET" --name "$prefix/source.tar.gz" --file "$work/source.tar.gz" \
  --content-type application/gzip --force > /dev/null
oci os object put -bn "$AFP_BUCKET" --name "$prefix/compose.afp.yaml" --file "$src/compose.afp.yaml" \
  --content-type application/yaml --force > /dev/null
say "Released $AFP_PROJECT $tag; the VM builds it during the deployment."
printf '%s\n' "$tag"
