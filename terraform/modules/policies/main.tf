variable "tenancy_ocid" {
  type = string
}

variable "compartment_id" {
  type = string
}

# Name of the compartment, as written in policy statements.
variable "compartment_name" {
  type = string
}

# Region identifier (e.g. us-ashburn-1); Object Storage acts per region.
variable "region" {
  type = string
}

# afp.json, platform.tar.gz, releases and state: read and written.
variable "deploy_bucket_name" {
  type = string
}

# Dumps and logs: written only; their lifecycle policies delete them.
variable "write_only_bucket_names" {
  type = list(string)
}

# The log group the VMs' logging agent sends the projects' logs to.
variable "log_group_id" {
  type = string
}

# Every instance in the compartment acts as the platform's VM.
resource "oci_identity_dynamic_group" "vm" {
  compartment_id = var.tenancy_ocid
  name           = "dg-afp-vm"
  description    = "AlwaysFreePlatform VMs"
  matching_rule  = "ALL {instance.compartment.id = '${var.compartment_id}'}"
}

locals {
  dg = oci_identity_dynamic_group.vm.name
  c  = var.compartment_name
}

resource "oci_identity_policy" "vm" {
  compartment_id = var.compartment_id
  name           = "policy-afp-vm"
  description    = "What the AlwaysFreePlatform VMs may do"
  statements = concat(
    [
      "Allow dynamic-group ${local.dg} to read secret-bundles in compartment ${local.c}",
      "Allow dynamic-group ${local.dg} to read buckets in compartment ${local.c} where target.bucket.name = '${var.deploy_bucket_name}'",
      "Allow dynamic-group ${local.dg} to manage objects in compartment ${local.c} where target.bucket.name = '${var.deploy_bucket_name}'",
    ],
    # New objects only (names carry the UTC time): no reading, overwriting or
    # deleting. A put of 128 MiB or more is a multipart upload, which needs more.
    [for b in var.write_only_bucket_names :
      "Allow dynamic-group ${local.dg} to manage objects in compartment ${local.c} where all {target.bucket.name = '${b}', request.permission = 'OBJECT_CREATE'}"
    ],
    [
      # Pull images; afp deploy also builds on the VM and pushes, creating the
      # repositories it needs (ADR 026).
      "Allow dynamic-group ${local.dg} to manage repos in compartment ${local.c}",
      # Run Command: each instance receives only the commands sent to itself.
      "Allow dynamic-group ${local.dg} to use instance-agent-command-execution-family in compartment ${local.c} where request.instance.id = target.instance.id",
      # afp backup sends its result (afp/backup_ok) for the alarm.
      "Allow dynamic-group ${local.dg} to use metrics in compartment ${local.c} where target.metrics.namespace = 'afp'",
      # The logging agent sends the projects' container logs.
      "Allow dynamic-group ${local.dg} to use log-content in compartment ${local.c} where target.loggroup.id = '${var.log_group_id}'",
    ],
  )
}

# Lets Object Storage carry out the buckets' lifecycle policies (deleting
# objects). It must be in the root compartment.
resource "oci_identity_policy" "objectstorage" {
  compartment_id = var.tenancy_ocid
  name           = "policy-afp-objectstorage"
  description    = "Object Storage may delete the AlwaysFreePlatform objects that expire"
  statements = [
    "Allow service objectstorage-${var.region} to manage object-family in compartment ${local.c}",
  ]
}

output "dynamic_group_id" {
  value = oci_identity_dynamic_group.vm.id
}

output "policy_id" {
  value = oci_identity_policy.vm.id
}

output "objectstorage_policy_id" {
  value = oci_identity_policy.objectstorage.id
}
