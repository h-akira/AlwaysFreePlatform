variable "compartment_id" {
  type = string
}

variable "vault_id" {
  type = string
}

variable "key_id" {
  type = string
}

# Projects of the main stack, with the names of the secrets Terraform
# generates. Secrets made by hand are not here (ADR 039).
variable "projects" {
  type = list(object({
    name     = string
    generate = list(string)
  }))
}

# A deleted secret stays PENDING_DELETION in the vault, which outlives this
# stack. A suffix per stack lifetime keeps recreated names from colliding.
resource "random_id" "suffix" {
  byte_length = 4
}

# The DB system needs the password at creation, so Terraform generates it.
# It ends up in the Resource Manager state either way.
resource "random_password" "db_admin" {
  length      = 24
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
  # HeatWave requires a symbol. The provider's default symbols all count as
  # one for OCI; "~" alone does not (ADR 030).
  min_special = 1
}

resource "oci_vault_secret" "db_admin_password" {
  compartment_id = var.compartment_id
  vault_id       = var.vault_id
  key_id         = var.key_id
  secret_name    = "secret-afp-db-admin-password-${random_id.suffix.hex}"
  description    = "Administrator password of the MySQL HeatWave DB system"

  secret_content {
    content_type = "BASE64"
    content      = base64encode(random_password.db_admin.result)
  }
}

locals {
  projects = { for p in var.projects : p.name => p }
  # "<project>/<NAME>" => {project, name}
  generated = merge([for p in var.projects : {
    for n in p.generate : "${p.name}/${n}" => { project = p.name, name = n }
  }]...)
}

# Same rules as the administrator's password (ADR 030).
resource "random_password" "project_db" {
  for_each    = local.projects
  length      = 24
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
  min_special = 1
}

resource "random_password" "generated" {
  for_each    = local.generated
  length      = 32
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
  min_special = 1
}

# One suffix per project, so that a project removed and added again does not
# collide with its own name that is still pending deletion.
resource "random_id" "project" {
  for_each    = local.projects
  byte_length = 4
}

# One JSON secret per project: AFP_DB_PASSWORD and the generated secrets.
resource "oci_vault_secret" "project" {
  for_each       = local.projects
  compartment_id = var.compartment_id
  vault_id       = var.vault_id
  key_id         = var.key_id
  secret_name    = "secret-afp-${each.key}-${random_id.project[each.key].hex}"
  description    = "AlwaysFreePlatform project ${each.key}: DB password and generated secrets"

  secret_content {
    content_type = "BASE64"
    content = base64encode(jsonencode(merge(
      { AFP_DB_PASSWORD = random_password.project_db[each.key].result },
      { for k, v in local.generated : v.name => random_password.generated[k].result if v.project == each.key },
    )))
  }
}

# Per project: the JSON secret (DB password and generated secrets).
output "project_secret_ids" {
  value = { for name, _ in local.projects : name => oci_vault_secret.project[name].id }
}

output "db_admin_password" {
  value     = random_password.db_admin.result
  sensitive = true
}

output "db_admin_secret_id" {
  value = oci_vault_secret.db_admin_password.id
}
