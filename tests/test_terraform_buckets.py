"""Static checks of the three buckets in terraform/: which expire, and who may
write to them."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN_TF = (ROOT / "terraform" / "main" / "main.tf").read_text()
STORAGE_TF = (ROOT / "terraform" / "modules" / "storage" / "main.tf").read_text()
POLICIES_TF = (ROOT / "terraform" / "modules" / "policies" / "main.tf").read_text()


def _block(text: str, header: str) -> str:
    """The block that starts with header, up to its closing brace at column 0."""
    start = text.index(header)
    end = text.index("\n}\n", start)
    return text[start:end]


def test_dumps_and_logs_expire_after_28_days_and_deploy_does_not() -> None:
    expiring = _block(STORAGE_TF, "locals {")
    assert re.search(r"dumps\s*=\s*var\.dumps_bucket_name", expiring)
    assert re.search(r"logs\s*=\s*var\.logs_bucket_name", expiring)
    assert "deploy" not in expiring
    assert re.search(r"expire_days\s*=\s*28\b", expiring)
    policy = _block(STORAGE_TF, 'resource "oci_objectstorage_object_lifecycle_policy" "expiring"')
    assert "for_each  = local.expiring" in policy
    assert 'action      = "DELETE"' in policy
    assert 'time_unit   = "DAYS"' in policy
    assert "time_amount = local.expire_days" in policy
    # The whole bucket expires, so no name filter.
    assert "object_name_filter" not in policy


def test_afp_json_is_in_the_deploy_bucket() -> None:
    afp_json = _block(STORAGE_TF, 'resource "oci_objectstorage_object" "afp_json"')
    assert "bucket       = oci_objectstorage_bucket.deploy.name" in afp_json


def test_object_storage_may_delete_and_the_lifecycle_waits_for_it() -> None:
    policy = _block(POLICIES_TF, 'resource "oci_identity_policy" "objectstorage"')
    assert "compartment_id = var.tenancy_ocid" in policy  # the root compartment
    assert "Allow service objectstorage-${var.region} to manage object-family in compartment ${local.c}" in policy
    storage = _block(MAIN_TF, 'module "storage"')
    assert "depends_on = [module.policies]" in storage


def test_the_vm_only_creates_objects_in_dumps_and_logs() -> None:
    policies = _block(MAIN_TF, 'module "policies"')
    assert "write_only_bucket_names = [local.dumps_bucket_name, local.logs_bucket_name]" in policies
    assert "deploy_bucket_name      = local.deploy_bucket_name" in policies
    vm = _block(POLICIES_TF, 'resource "oci_identity_policy" "vm"')
    [write_only] = [line for line in vm.splitlines() if "${b}" in line]
    assert "manage objects" in write_only and "request.permission = 'OBJECT_CREATE'" in write_only


def test_devops_uses_only_the_deploy_bucket() -> None:
    devops = _block(MAIN_TF, 'module "devops"')
    assert "bucket_name            = local.deploy_bucket_name" in devops
