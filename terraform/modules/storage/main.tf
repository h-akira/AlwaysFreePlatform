variable "namespace" {
  type = string
}

variable "compartment_id" {
  type = string
}

# afp.json (written here), platform.tar.gz (make platform), releases and each
# project's current version. Nothing in it expires.
variable "deploy_bucket_name" {
  type = string
}

# DB dumps (afp backup and afp deploy).
variable "dumps_bucket_name" {
  type = string
}

# Logs of afp runs.
variable "logs_bucket_name" {
  type = string
}

# Contents of afp.json, the VM's view of the platform (read by afp).
variable "afp_config" {
  type = any
}

locals {
  # Objects of these buckets are deleted this many days after their last
  # change (4 weekly dumps).
  expiring = {
    dumps = var.dumps_bucket_name
    logs  = var.logs_bucket_name
  }
  expire_days = 28
}

# The main stack's destroy needs every bucket empty, except for objects
# Terraform itself manages (scripts/stack.sh empties them first).
resource "oci_objectstorage_bucket" "deploy" {
  compartment_id = var.compartment_id
  namespace      = var.namespace
  name           = var.deploy_bucket_name
  access_type    = "NoPublicAccess"
  versioning     = "Disabled"
}

resource "oci_objectstorage_bucket" "expiring" {
  for_each       = local.expiring
  compartment_id = var.compartment_id
  namespace      = var.namespace
  name           = each.value
  access_type    = "NoPublicAccess"
  versioning     = "Disabled"
}

# Needs the policy that lets Object Storage delete objects (module policies);
# the main stack makes this module wait for it.
resource "oci_objectstorage_object_lifecycle_policy" "expiring" {
  for_each  = local.expiring
  namespace = var.namespace
  bucket    = oci_objectstorage_bucket.expiring[each.key].name

  # No name filter: the rule covers every object of the bucket.
  rules {
    name        = "delete-after-${local.expire_days}-days"
    action      = "DELETE"
    is_enabled  = true
    time_amount = local.expire_days
    time_unit   = "DAYS"
  }
}

resource "oci_objectstorage_object" "afp_json" {
  namespace    = var.namespace
  bucket       = oci_objectstorage_bucket.deploy.name
  object       = "afp.json"
  content      = jsonencode(var.afp_config)
  content_type = "application/json"
}

output "deploy_bucket_name" {
  value = oci_objectstorage_bucket.deploy.name
}

output "dumps_bucket_name" {
  value = oci_objectstorage_bucket.expiring["dumps"].name
}

output "logs_bucket_name" {
  value = oci_objectstorage_bucket.expiring["logs"].name
}

output "afp_json_id" {
  value = oci_objectstorage_object.afp_json.id
}
