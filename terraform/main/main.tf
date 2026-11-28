# Stack "stack-afp-main": everything that is created and destroyed repeatedly.
# The compartment, vault, key and DNS zone come from the base stack
# (terraform/base) and are looked up by name, so no values are passed between
# the stacks. The names must match terraform/modules/iam, terraform/modules/vault
# and the variable dns_zone of the base stack.

data "oci_identity_compartments" "afp" {
  compartment_id = var.tenancy_ocid
  name           = "compartment-afp-main"
  state          = "ACTIVE"

  lifecycle {
    postcondition {
      condition     = length(self.compartments) == 1
      error_message = "Compartment \"compartment-afp-main\" not found; apply the base stack first (make base-plan, make base-apply)."
    }
  }
}

locals {
  compartment_id   = data.oci_identity_compartments.afp.compartments[0].id
  compartment_name = "compartment-afp-main"
  # Also written in afp/config.py; the deploy bucket also in
  # terraform/modules/compute/afp-bootstrap.sh.
  deploy_bucket_name = "bucket-afp-deploy"
  dumps_bucket_name  = "bucket-afp-dumps"
  logs_bucket_name   = "bucket-afp-logs"
  # Each project is served at <name>.<dns_zone>.
  domains = { for p in var.projects : p.name => "${p.name}.${var.dns_zone}" }
}

data "oci_dns_zones" "afp" {
  compartment_id = local.compartment_id
  name           = var.dns_zone
  zone_type      = "PRIMARY"
  scope          = "GLOBAL"

  lifecycle {
    postcondition {
      condition     = length(self.zones) == 1
      error_message = "DNS zone \"${var.dns_zone}\" not found in compartment-afp-main; set the same dns_zone for both stacks and apply the base stack first."
    }
  }
}

data "oci_kms_vaults" "afp" {
  compartment_id = local.compartment_id

  # Older vaults of the same name may be PENDING_DELETION.
  filter {
    name   = "display_name"
    values = ["vault-afp-main"]
  }
  filter {
    name   = "state"
    values = ["ACTIVE"]
  }

  lifecycle {
    postcondition {
      condition     = length(self.vaults) == 1
      error_message = "Exactly one ACTIVE vault \"vault-afp-main\" must exist; apply the base stack first."
    }
  }
}

data "oci_kms_keys" "afp" {
  compartment_id      = local.compartment_id
  management_endpoint = data.oci_kms_vaults.afp.vaults[0].management_endpoint

  filter {
    name   = "display_name"
    values = ["key-afp-main"]
  }
  filter {
    name   = "state"
    values = ["ENABLED"]
  }

  lifecycle {
    postcondition {
      condition     = length(self.keys) == 1
      error_message = "Exactly one ENABLED key \"key-afp-main\" must exist in vault \"vault-afp-main\"; apply the base stack first."
    }
  }
}

module "secrets" {
  source         = "../modules/secrets"
  compartment_id = local.compartment_id
  vault_id       = data.oci_kms_vaults.afp.vaults[0].id
  key_id         = data.oci_kms_keys.afp.keys[0].id
  projects       = [for p in var.projects : { name = p.name, generate = p.generate }]
}

module "network" {
  source              = "../modules/network"
  compartment_id      = local.compartment_id
  vcn_cidr            = var.vcn_cidr
  public_subnet_cidr  = var.public_subnet_cidr
  vm_subnet_cidr      = var.vm_subnet_cidr
  db_subnet_cidr      = var.db_subnet_cidr
  bastion_subnet_cidr = var.bastion_subnet_cidr
  home_cidrs          = var.home_cidrs
  https_public        = var.https_public
}

module "database" {
  source                    = "../modules/database"
  tenancy_ocid              = var.tenancy_ocid
  compartment_id            = local.compartment_id
  subnet_id                 = module.network.db_subnet_id
  availability_domain_index = var.availability_domain_index
  admin_username            = var.db_admin_username
  admin_password            = module.secrets.db_admin_password
}

data "oci_identity_regions" "this" {
  filter {
    name   = "name"
    values = [var.region]
  }
}

data "oci_objectstorage_namespace" "this" {
  compartment_id = var.tenancy_ocid
}

module "storage" {
  source             = "../modules/storage"
  namespace          = data.oci_objectstorage_namespace.this.namespace
  compartment_id     = local.compartment_id
  deploy_bucket_name = local.deploy_bucket_name
  dumps_bucket_name  = local.dumps_bucket_name
  logs_bucket_name   = local.logs_bucket_name
  afp_config = {
    region    = var.region
    namespace = data.oci_objectstorage_namespace.this.namespace
    bucket    = local.deploy_bucket_name
    db = {
      host            = module.database.ip_address
      port            = module.database.port
      admin_user      = var.db_admin_username
      admin_secret_id = module.secrets.db_admin_secret_id
    }
    image_prefix_base = "${lower(data.oci_identity_regions.this.regions[0].key)}.ocir.io/${data.oci_objectstorage_namespace.this.namespace}"
    # Where afp creates OCIR repositories when it builds on the VM.
    compartment_id = local.compartment_id
    projects = [for p in var.projects : {
      name       = p.name
      domain     = local.domains[p.name]
      port       = p.port
      secret_id  = module.secrets.project_secret_ids[p.name]
      env        = p.env
      secret_ids = p.secrets
    }]
  }

  # The lifecycle policies need Object Storage's permission first.
  depends_on = [module.policies]
}

module "policies" {
  source                  = "../modules/policies"
  tenancy_ocid            = var.tenancy_ocid
  compartment_id          = local.compartment_id
  compartment_name        = local.compartment_name
  region                  = var.region
  deploy_bucket_name      = local.deploy_bucket_name
  write_only_bucket_names = [local.dumps_bucket_name, local.logs_bucket_name]
}

# The projects' container logs, sent by the VM's logging agent.
module "logging" {
  source           = "../modules/logging"
  compartment_id   = local.compartment_id
  dynamic_group_id = module.policies.dynamic_group_id
}

module "vm" {
  source                    = "../modules/compute"
  tenancy_ocid              = var.tenancy_ocid
  compartment_id            = local.compartment_id
  name                      = "main"
  subnet_id                 = module.network.vm_subnet_id
  availability_domain_index = var.vm_availability_domain_index
  shape                     = var.vm_shape
  ocpus                     = var.vm_ocpus
  memory_in_gbs             = var.vm_memory_in_gbs
  generation                = var.vm_generation
  ready_after = [
    module.policies.dynamic_group_id,
    module.policies.policy_id,
    module.storage.afp_json_id,
  ]
}

module "nlb" {
  source         = "../modules/nlb"
  compartment_id = local.compartment_id
  name           = "main"
  subnet_id      = module.network.public_subnet_id
  instance_id    = module.vm.instance_id
}

# Every project's name points at the load balancer in front of the VM it runs
# on (only "main" for now).
resource "oci_dns_rrset" "project" {
  for_each        = local.domains
  zone_name_or_id = data.oci_dns_zones.afp.zones[0].id
  domain          = each.value
  rtype           = "A"

  items {
    domain = each.value
    rtype  = "A"
    rdata  = module.nlb.public_ip
    ttl    = 300
  }
}

# Pipelines only for the projects with a repository; the others are deployed
# from the administrator's machine (make deploy).
module "devops" {
  source                 = "../modules/devops"
  tenancy_ocid           = var.tenancy_ocid
  compartment_id         = local.compartment_id
  compartment_name       = local.compartment_name
  bucket_name            = local.deploy_bucket_name
  github_token_secret_id = var.github_token_secret_id
  notification_email     = var.notification_email
  vm_instance_id         = module.vm.instance_id
  projects = [for p in var.projects : {
    name       = p.name
    repository = p.repository
  } if p.repository != null]
}

# Mails the platform's notification topic when the weekly DB dump fails.
module "alarm" {
  source           = "../modules/alarm"
  compartment_id   = local.compartment_id
  topic_id         = module.devops.topic_id
  logs_bucket_name = local.logs_bucket_name
}
